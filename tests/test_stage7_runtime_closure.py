from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from helpers import load_fixture, run_internal_chain_to_stage7
from shared.context_packet import ContextPacket
from shared.contract_loader import load_contract
from shared.provider_adapter_config import PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY
from shared.policy_executor import PolicyExecutor
from shared.state_packet import PolicyDecision, StatePacket


class TestStage7RuntimeClosure(unittest.TestCase):
    def test_stage7_provider_adapter_readiness_is_shared_sandbox_readback(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        provider_summary = stage7.inputs[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]
        workbench = stage7.inputs["crm_quote_workbench"]
        package = stage7.inputs["leadpack_delivery_package"]

        self.assertEqual(provider_summary["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertEqual(provider_summary["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(provider_summary["provider_circuit_breaker_state"], "CLOSED")
        self.assertTrue(provider_summary["provider_reliability_summary"]["health_check_visible"])
        self.assertTrue(provider_summary["provider_reliability_summary"]["circuit_breaker_visible"])
        self.assertFalse(provider_summary["provider_reliability_summary"]["live_fallback_allowed"])
        self.assertFalse(provider_summary["real_provider_call_enabled"])
        self.assertEqual(workbench[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY], provider_summary)
        self.assertEqual(package[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY], provider_summary)
        self.assertEqual(workbench["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(package["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(workbench["provider_circuit_breaker_state"], "CLOSED")
        self.assertEqual(package["provider_circuit_breaker_state"], "CLOSED")
        self.assertFalse(workbench["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertFalse(package["provider_adapter_readiness"]["real_provider_call_enabled"])

    def test_stage7_runtime_consumes_buyer_fit_scorecard(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        trace = stage7.inputs["stage7_resolution_trace"]["buyer_fit_scorecard"]

        self.assertEqual(trace["buyer_fit_scorecard_id"], "general_buyer_fit_v1")
        self.assertEqual(trace["challenger_buyer_fit_scorecard_id"], "challenger_buyer_fit_v1")
        self.assertIn("base_fit_score", trace["buyer_fit_derivation_trace"])
        self.assertIn("project_fact.sale_gate_status", trace["buyer_fit_derivation_trace"]["component_sources"].values())
        self.assertEqual(stage7.record("buyer_fit").get("fit_score"), trace["buyer_fit_scorecard_score"])
        self.assertEqual(
            stage7.record("challenger_buyer_fit").get("fit_score"),
            trace["challenger_buyer_fit_scorecard_score"],
        )

    def test_stage7_value_scores_use_catalog_derivation_and_scorecard_input(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        value_trace = stage7.inputs["stage7_resolution_trace"]["value_derivation"]["value_derivation_trace"]

        self.assertEqual(
            value_trace["buyer_fit_score_source"],
            "buyer_fit_scorecard_policy_replay",
        )
        self.assertTrue(value_trace["buyer_fit_replayed"])
        self.assertFalse(value_trace["missing_formal_sources"])
        self.assertEqual(
            stage7.record("saleable_opportunity").get("opportunity_value_score_optional"),
            stage7.inputs["stage7_resolution_trace"]["formal_sink_projection"]["opportunity_value_score_optional"],
        )
        self.assertIn("PROJECT-VALUE-001", value_trace["model_ids"])
        self.assertIn("LEAD-VALUE-001", value_trace["model_ids"])
        self.assertIn("OPPORTUNITY-VALUE-001", value_trace["model_ids"])
        self.assertEqual(
            value_trace["component_sources_used"]["coverage_sellable_state"],
            "project_fact.coverage_sellable_state",
        )
        self.assertEqual(
            value_trace["component_sources_used"]["delivery_risk_state"],
            "project_fact.delivery_risk_state",
        )
        self.assertIn(
            "window_status=MISSED -> lead_score max 54",
            value_trace["model_gating_rules"]["LEAD-VALUE-001"],
        )
        self.assertEqual(
            stage7.record("saleable_opportunity").get("major_value_points"),
            stage7.inputs["stage7_resolution_trace"]["value_derivation"]["opportunity_value_reason_tags"],
        )
        self.assertIn(
            "lead_value_reason_tag_policy_id",
            stage7.inputs["stage7_resolution_trace"]["value_derivation"],
        )

    def test_stage7_value_scoring_marks_missing_stage6_state_sources_via_contract_fallback(self) -> None:
        context = ContextPacket.from_records(
            capability_mode="stage7_sales",
            stage=7,
            project_id="PROJ-TEST",
            records={
                "project_fact": {
                    "sale_gate_status": "OPEN",
                    "rule_gate_status": "PASS",
                    "evidence_gate_status": "PASS",
                    "delivery_risk_state": None,
                    "coverage_sellable_state": None,
                    "competitor_quality_grade": "B",
                },
                "legal_action_recommendation": {
                    "window_status": "ACTIONABLE",
                },
                "challenger_candidate_profile": {
                    "challenge_actionability_score": 78,
                },
                "report_record": {
                    "report_status": "ISSUED",
                },
            },
            inputs={
                "external_use_grade": "E3_CLIENT_VISIBLE",
            },
        )
        state = StatePacket(capability_mode="stage7_sales")
        state.add_decision(
            PolicyDecision(
                policy_key="window_value",
                decision_state="ALLOW",
                outputs={
                    "window_urgency_score": 82,
                    "window_status": "ACTIONABLE",
                },
                reasons=[],
                trace={},
            )
        )
        state.add_decision(
            PolicyDecision(
                policy_key="price_normalization",
                decision_state="ALLOW",
                outputs={
                    "price_signal_score": 61,
                },
                reasons=[],
                trace={},
            )
        )
        state.add_decision(
            PolicyDecision(
                policy_key="competitor_confidence",
                decision_state="ALLOW",
                outputs={
                    "competitor_confidence_score": 76,
                    "competitor_confidence_band": "MEDIUM",
                    "competitor_quality_grade": "B",
                },
                reasons=[],
                trace={},
            )
        )
        state.add_decision(
            PolicyDecision(
                policy_key="buyer_fit_scorecard",
                decision_state="ALLOW",
                outputs={
                    "buyer_fit_scorecard_score": 88,
                    "buyer_fit_derivation_trace": {
                        "source": "seeded_test_decision",
                    },
                },
                reasons=[],
                trace={},
            )
        )

        decision = PolicyExecutor().execute("value_scoring", context, state)
        trace = decision.outputs["value_derivation_trace"]

        self.assertEqual(decision.decision_state, "REVIEW")
        self.assertIn("coverage_sellable_state", trace["missing_formal_sources"])
        self.assertIn("delivery_risk_state", trace["missing_formal_sources"])
        self.assertEqual(
            trace["component_sources_used"]["coverage_sellable_state"],
            "derivationPolicy.sourceFallbacks.coverage_sellable_state",
        )
        self.assertEqual(
            trace["component_sources_used"]["delivery_risk_state"],
            "derivationPolicy.sourceFallbacks.delivery_risk_state",
        )
        self.assertEqual(trace["gating_inputs"]["coverage_sellable_state"], "RESTRICTED")
        self.assertEqual(trace["gating_inputs"]["delivery_risk_state"], "REVIEW")

    def test_stage7_expected_bands_and_reason_are_policy_outputs(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "current_action_deadline_at_optional": "2026-04-20T00:00:00Z",
                "why_recommended": "free text must not win",
            }
        )

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        opportunity = stage7.record("saleable_opportunity")
        offer = stage7.record("offer_recommendation")
        policy_trace = stage7.inputs["stage7_resolution_trace"]["opportunity_policy"]

        self.assertNotEqual(opportunity.get("expected_close_days_band"), "UNKNOWN")
        self.assertNotEqual(opportunity.get("expected_delivery_cost_band"), "UNKNOWN")
        self.assertEqual(opportunity.get("expected_close_days_band"), policy_trace["expected_close_days_band"])
        self.assertEqual(opportunity.get("expected_delivery_cost_band"), policy_trace["expected_delivery_cost_band"])
        self.assertNotEqual(offer.get("why_recommended"), "free text must not win")
        self.assertEqual(offer.get("why_recommended"), policy_trace["why_recommended"])
        self.assertEqual(policy_trace["why_recommended_template_id"], "WHY-RECOMMENDED-001")
        self.assertEqual(policy_trace["why_recommended_rule_outputs"]["policy"], "OPPORTUNITY-BAND-001")

    def test_stage7_value_contracts_declare_formal_source_contracts(self) -> None:
        buyer_fit_catalog = load_contract("contracts/sales/buyer_fit_scorecard.json")
        value_catalog = load_contract("contracts/sales/lead_value_scoring_catalog.json")
        opportunity_policy = load_contract("contracts/sales/opportunity_policy_catalog.json")

        buyer_source = buyer_fit_catalog["formalSourceContract"]
        self.assertEqual(buyer_source["contractId"], "STAGE7-BUYER-FIT-SOURCE-CONTRACT-001")
        self.assertEqual(buyer_source["missingFormalSourceDecisionState"], "REVIEW")
        self.assertIn("inputs.buyer_fit_score", buyer_source["forbiddenSubstitutes"])
        self.assertIn(
            "base_fit_score",
            buyer_source["scorecards"]["general_buyer_fit_v1"]["requiredDerivationRefs"],
        )
        self.assertIn(
            "general_buyer_fit_v1.score",
            buyer_source["scorecards"]["challenger_buyer_fit_v1"]["requiredDerivationRefs"],
        )

        value_source = value_catalog["derivationPolicy"]["sourceContracts"]
        self.assertEqual(value_source["contractId"], "STAGE7-VALUE-SOURCE-CONTRACT-001")
        self.assertTrue(value_source["opportunityValueScore"]["buyerFitReplayRequired"])
        self.assertEqual(
            value_source["opportunityValueScore"]["buyerFitSource"],
            "buyer_fit_scorecard.general_buyer_fit_v1.score",
        )
        self.assertIn(
            "PROJECT-VALUE-001.project_value_score",
            value_source["leadValueScore"]["authoritativeInputs"]["project_value_score"],
        )
        self.assertIn(
            "service_local_buyer_fit_seed",
            value_source["opportunityValueScore"]["forbiddenSubstitutes"],
        )

        band_source = opportunity_policy["expectedBandPolicies"][0]["sourceContract"]
        self.assertEqual(band_source["contractId"], "STAGE7-EXPECTED-BAND-SOURCE-CONTRACT-001")
        self.assertIn("window_status", band_source["requiredRuntimeInputs"])
        self.assertEqual(
            band_source["outputProjection"]["saleable_opportunity.expected_close_days_band"],
            "close_days_rules.expected_close_days_band",
        )
        self.assertIn("inputs.why_recommended", band_source["forbiddenSubstitutes"])

    def test_stage7_reason_tags_and_reason_summary_ignore_direct_input_override(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "buyer_fit_reason_tags": ["OVERRIDE"],
                "challenger_buyer_fit_reason_tags": ["OVERRIDE2"],
                "major_value_points": ["OVERRIDE3"],
                "lead_reason_summary": "OVERRIDE4",
            }
        )

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        buyer_fit = stage7.record("buyer_fit")
        challenger_buyer_fit = stage7.record("challenger_buyer_fit")
        sales_lead = stage7.record("sales_lead")
        opportunity = stage7.record("saleable_opportunity")
        buyer_trace = stage7.inputs["stage7_resolution_trace"]["buyer_fit_scorecard"]
        value_trace = stage7.inputs["stage7_resolution_trace"]["value_derivation"]

        self.assertNotEqual(buyer_fit.get("fit_reason_tags"), ["OVERRIDE"])
        self.assertNotEqual(challenger_buyer_fit.get("fit_reason_tags"), ["OVERRIDE2"])
        self.assertNotEqual(opportunity.get("major_value_points"), ["OVERRIDE3"])
        self.assertNotEqual(sales_lead.get("lead_reason_summary"), "OVERRIDE4")
        self.assertEqual(buyer_fit.get("fit_reason_tags"), buyer_trace["buyer_fit_reason_tags"])
        self.assertEqual(
            challenger_buyer_fit.get("fit_reason_tags"),
            buyer_trace["challenger_buyer_fit_reason_tags"],
        )
        self.assertEqual(opportunity.get("major_value_points"), value_trace["opportunity_value_reason_tags"])
        self.assertEqual(
            sales_lead.get("lead_reason_summary"),
            ";".join(value_trace["lead_value_reason_tags"]),
        )

    def test_stage7_actor_seed_provenance_prefers_h06_formal_seed(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        actor_trace = stage7.inputs["stage7_resolution_trace"]["actor_seed_provenance"]

        self.assertEqual(actor_trace["legal_action_actor_org_name"]["source"], "H06_FORMAL_SEED")
        self.assertEqual(actor_trace["procurement_decision_actor_org_name"]["source"], "H06_FORMAL_SEED")
        self.assertEqual(
            stage7.record("legal_action_actor_profile").get("actor_org_name"),
            actor_trace["legal_action_actor_org_name"]["value"],
        )
        self.assertEqual(
            stage7.record("procurement_decision_actor_profile").get("actor_org_name"),
            actor_trace["procurement_decision_actor_org_name"]["value"],
        )

    def test_stage7_blocks_when_h06_authoritative_fields_are_overridden(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_block.json"))
        payload.update(
            {
                "sale_gate_status": "OPEN",
                "competitor_quality_grade": "A",
            }
        )

        with self.assertRaisesRegex(ValueError, "must-not-recompute conflicts"):
            run_internal_chain_to_stage7(payload)

    def test_stage7_blocks_when_any_single_h06_authoritative_field_is_overridden(self) -> None:
        for field_name, override_value in {
            "sale_gate_status": "OPEN",
            "competitor_quality_grade": "A",
        }.items():
            payload = copy.deepcopy(load_fixture("internal_chain_block.json"))
            payload.update({field_name: override_value})

            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, "must-not-recompute conflicts"):
                    run_internal_chain_to_stage7(payload)

    def test_stage7_ignores_raw_sale_flags_and_uses_h06_constraints(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["flags"] = {
            **payload["flags"],
            "sale_blocked": True,
            "sale_review": True,
            "offer_review": True,
        }

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]

        self.assertEqual(stage7.record("sales_lead").get("lead_status"), "QUALIFIED")
        self.assertEqual(stage7.record("saleable_opportunity").get("saleability_status"), "QUALIFIED")
        self.assertEqual(stage7.record("offer_recommendation").get("offer_recommendation_state"), "APPROVED")

    def test_stage7_review_request_h06_carrier_constrains_sales_objects(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_block.json"))["stage7"]
        constraints = stage7.inputs["stage7_resolution_trace"]["review_gate_report_constraints"]

        self.assertEqual(constraints["linked_review_request_id_optional"], "RR-PROJ-002")
        self.assertEqual(constraints["missing_condition_family_optional"], "MISSING_EVIDENCE")
        self.assertEqual(stage7.record("sales_lead").get("lead_status"), "REVIEW")
        self.assertNotEqual(stage7.record("saleable_opportunity").get("saleability_status"), "QUALIFIED")
        self.assertIn(
            "missing_condition_family=MISSING_EVIDENCE",
            stage7.record("saleable_opportunity").get("blocking_reasons"),
        )

    def test_stage7_price_candidate_resolution_prefers_highest_priority_source(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["price_source_set_optional"] = [
            {
                "source_type": "MANUAL_INPUT",
                "amount": 3000000,
                "currency": "CNY",
                "tax_basis_optional": "EX_TAX",
                "unit_basis_optional": "TOTAL_AMOUNT",
                "lot_id_optional": "LOT-01",
                "package_id_optional": "PKG-01",
                "recency_days_optional": 1,
            },
            {
                "source_type": "BID_PRICE",
                "amount": 8720000,
                "currency": "CNY",
                "tax_basis_optional": "INCL_TAX",
                "tax_rate_optional": 0.09,
                "unit_basis_optional": "TOTAL_AMOUNT",
                "lot_id_optional": "LOT-01",
                "package_id_optional": "PKG-01",
                "recency_days_optional": 15,
            },
            {
                "source_type": "BID_PRICE",
                "amount": 8720000,
                "currency": "CNY",
                "tax_basis_optional": "INCL_TAX",
                "tax_rate_optional": 0.09,
                "unit_basis_optional": "TOTAL_AMOUNT",
                "lot_id_optional": "LOT-01",
                "package_id_optional": "PKG-01",
                "recency_days_optional": 15,
            },
            {
                "source_type": "HISTORICAL_REFERENCE",
                "amount": 1000,
                "currency": "CNY",
                "tax_basis_optional": "EX_TAX",
                "unit_basis_optional": "PER_ITEM",
                "quantity_optional": 6000,
                "lot_id_optional": "LOT-02",
                "package_id_optional": "PKG-02",
                "recency_days_optional": 420,
            },
        ]
        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        price_trace = stage7.inputs["stage7_resolution_trace"]["price_resolution"]

        self.assertEqual(price_trace["policy_id"], "price_candidate_merge_v2")
        self.assertEqual(price_trace["selected_source_type"], "BID_PRICE")
        self.assertEqual(price_trace["price_candidate_count"], 4)
        self.assertEqual(price_trace["price_candidate_deduped_count"], 3)
        self.assertEqual(price_trace["price_source_priority_applied"][0], "BID_PRICE")
        self.assertEqual(stage7.handoff.get("normalized_price_amount_optional"), 8000000)
        self.assertEqual(price_trace["normalized_currency"], "CNY")
        self.assertEqual(price_trace["normalized_tax_basis"], "EX_TAX")
        self.assertEqual(price_trace["normalized_unit_basis"], "TOTAL_AMOUNT")
        self.assertEqual(price_trace["selected_scope_key"], "LOT-01|PKG-01")
        self.assertEqual(price_trace["price_band"], "HIGH")
        self.assertEqual(price_trace["recommended_quote_band"], "HIGH")
        self.assertEqual(
            price_trace["quote_band_authority_ref"],
            "contracts/sales/price_normalization_catalog.json#authorityContract",
        )
        self.assertIn("SCOPE_MISMATCH", price_trace["review_flags"])
        self.assertEqual(price_trace["selected_candidate_trace"]["freshness_score"], 100)

    def test_stage7_quote_band_uses_price_normalization_authority(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["price_source_set_optional"] = [
            {
                "source_type": "BID_PRICE",
                "amount": 500000,
                "currency": "CNY",
                "tax_basis_optional": "EX_TAX",
                "unit_basis_optional": "TOTAL_AMOUNT",
                "lot_id_optional": "LOT-LOW",
                "package_id_optional": "PKG-LOW",
                "recency_days_optional": 5,
            }
        ]

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        price_trace = stage7.inputs["stage7_resolution_trace"]["price_resolution"]

        self.assertEqual(price_trace["price_band"], "LOW")
        self.assertEqual(price_trace["recommended_quote_band"], "LOW")
        self.assertEqual(stage7.record("offer_recommendation").get("recommended_quote_band"), "LOW")
        self.assertEqual(stage7.record("saleable_opportunity").get("expected_contract_value_band"), "LOW")

    def test_stage7_direct_price_overrides_do_not_bypass_price_authority(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "normalized_price_amount_optional": 99_000_000,
                "price_conflict_gate_status_optional": "BLOCK",
                "price_band_optional": "VERY_HIGH",
                "recommended_quote_band": "CUSTOM",
                "price_source_set_optional": [
                    {
                        "source_type": "BID_PRICE",
                        "amount": 500000,
                        "currency": "CNY",
                        "tax_basis_optional": "EX_TAX",
                        "unit_basis_optional": "TOTAL_AMOUNT",
                        "lot_id_optional": "LOT-LOW",
                        "package_id_optional": "PKG-LOW",
                        "recency_days_optional": 5,
                    }
                ],
            }
        )

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        price_trace = stage7.inputs["stage7_resolution_trace"]["price_resolution"]

        self.assertEqual(stage7.handoff.get("normalized_price_amount_optional"), 500000)
        self.assertEqual(stage7.handoff.get("price_conflict_gate_status_optional"), "PASS")
        self.assertEqual(price_trace["price_band"], "LOW")
        self.assertEqual(price_trace["recommended_quote_band"], "LOW")
        self.assertEqual(stage7.record("offer_recommendation").get("recommended_quote_band"), "LOW")
        self.assertEqual(stage7.record("saleable_opportunity").get("expected_contract_value_band"), "LOW")

    def test_stage7_price_resolution_marks_stale_reference_only(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["price_source_set_optional"] = [
            {
                "source_type": "HISTORICAL_REFERENCE",
                "amount": 1_000_000,
                "currency": "CNY",
                "tax_basis_optional": "EX_TAX",
                "unit_basis_optional": "TOTAL_AMOUNT",
                "lot_id_optional": "LOT-OLD",
                "package_id_optional": "PKG-OLD",
                "recency_days_optional": 500,
            },
            {
                "source_type": "HISTORICAL_REFERENCE",
                "amount": 1_200_000,
                "currency": "CNY",
                "tax_basis_optional": "EX_TAX",
                "unit_basis_optional": "TOTAL_AMOUNT",
                "lot_id_optional": "LOT-OLD",
                "package_id_optional": "PKG-OLD",
                "recency_days_optional": 420,
            },
        ]

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        price_trace = stage7.inputs["stage7_resolution_trace"]["price_resolution"]

        self.assertEqual(price_trace["selected_source_type"], "HISTORICAL_REFERENCE")
        self.assertEqual(price_trace["selected_scope_key"], "LOT-OLD|PKG-OLD")
        self.assertEqual(price_trace["selected_candidate_trace"]["freshness_score"], 35)
        self.assertIn("STALE_REFERENCE", price_trace["review_flags"])
        self.assertIn("STALE_REFERENCE_ONLY", price_trace["review_flags"])
        self.assertEqual(stage7.handoff.get("price_conflict_gate_status_optional"), "REVIEW")

    def test_stage7_resolution_policy_asset_exists(self) -> None:
        policy = load_contract("contracts/sales/stage7_resolution_policy.json")
        actor_policy_ids = {entry["policyId"] for entry in policy["actorSeedPolicies"]}

        self.assertIn("legal_action_actor_seed_resolution_v1", actor_policy_ids)
        self.assertIn("procurement_decision_actor_seed_resolution_v1", actor_policy_ids)
        self.assertEqual(policy["priceCandidateResolution"]["policyId"], "price_candidate_merge_v2")
        self.assertEqual(policy["multiCompetitorResolution"]["policyId"], "stage7_multi_competitor_resolution_v1")

    def test_stage7_emits_multi_competitor_collection_and_projects_h07_refs(self) -> None:
        baseline_stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        baseline_winner = baseline_stage7.record("multi_competitor_collection").get("candidate_list")[0]
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["multi_competitor_candidate_pool"] = [
            {
                "candidate_id": "cand-dup",
                "challenger_profile_id": baseline_winner["challenger_profile_id"],
                "challenger_bidder_id": baseline_winner["challenger_bidder_id"],
                "candidate_position_label": baseline_winner["candidate_position_label"],
                "confidence_score_optional": baseline_winner["confidence_score_optional"],
                "challenge_actionability_score": baseline_winner["challenge_actionability_score"],
                "execution_readiness_score": baseline_winner["execution_readiness_score"],
                "alias_names_optional": ["示例竞争者A"],
            },
            {
                "candidate_id": "cand-second",
                "challenger_profile_id": "CHALT-PROJ-001-02",
                "challenger_bidder_id": "BID-PROJ-001-03",
                "candidate_position_label": "SECOND_CANDIDATE",
                "confidence_score_optional": 58,
                "challenge_actionability_score": 62,
                "execution_readiness_score": 57,
                "ranking_reason_tags_optional": ["SECONDARY_POOL_INPUT"],
            },
            {
                "candidate_id": "cand-low",
                "challenger_profile_id": "CHALT-PROJ-001-03",
                "challenger_bidder_id": "BID-PROJ-001-04",
                "candidate_position_label": "THIRD_CANDIDATE",
                "confidence_score_optional": 40,
                "challenge_actionability_score": 54,
                "execution_readiness_score": 49,
            },
        ]

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        collection = stage7.record("multi_competitor_collection")
        trace = stage7.inputs["stage7_resolution_trace"]["multi_competitor_collection"]

        self.assertEqual(collection.get("winning_challenger_profile_id"), stage7.record("saleable_opportunity").get("challenger_profile_id"))
        self.assertGreaterEqual(len(collection.get("candidate_list")), 3)
        self.assertEqual(collection.get("top_n_candidate_ids")[0], collection.get("winning_candidate_id"))
        self.assertEqual(
            stage7.handoff.get("multi_competitor_collection_id_optional"),
            collection.get("multi_competitor_collection_id"),
        )
        self.assertEqual(
            stage7.handoff.get("winning_challenger_profile_id_optional"),
            collection.get("winning_challenger_profile_id"),
        )
        self.assertEqual(trace["policy_id"], "stage7_multi_competitor_resolution_v1")
        self.assertEqual(trace["ranking_policy_id"], "COMP-RANK-001")
        self.assertEqual(trace["cutoff_policy_id"], "COMP-CUTOFF-001")
        self.assertEqual(trace["top_n_limit"], 3)
        self.assertEqual(trace["deduped_candidate_count"], len(collection.get("candidate_list")))
        self.assertEqual(trace["alias_deduped_count"], 1)
        self.assertIn("cand-low", trace["candidate_only_candidate_ids"])
        self.assertEqual(trace["selection_trace"]["authoritative_ranking_policy_id"], "COMP-RANK-001")
        self.assertEqual(trace["selection_trace"]["authoritative_cutoff_policy_id"], "COMP-CUTOFF-001")
        self.assertIn("CONFIDENCE_SCORE_LT_55", trace["selection_trace"]["candidate_only_reason_tags"])
        low_candidate = next(item for item in collection.get("candidate_list") if item["candidate_id"] == "cand-low")
        self.assertIn("CONFIDENCE_SCORE_LT_55", low_candidate["ranking_reason_tags_optional"])

    def test_stage7_multi_competitor_collection_keeps_selection_trace(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        collection = stage7.record("multi_competitor_collection")
        trace = stage7.inputs["stage7_resolution_trace"]["multi_competitor_collection"]

        self.assertEqual(trace["multi_competitor_collection_id"], collection.get("multi_competitor_collection_id"))
        self.assertEqual(trace["winning_candidate_id"], collection.get("winning_candidate_id"))
        self.assertIn("ranking_score desc", collection.get("selection_trace")["sort_basis"])
        self.assertEqual(collection.get("selection_trace")["selection_policy_id"], "stage7_multi_competitor_resolution_v1")
        self.assertIn(
            "winner_selection=highest_ranked_non_candidate_only_else_rank_1",
            collection.get("selection_trace")["winner_selection_basis"],
        )

    def test_stage7_outputs_typed_persistence_refs_for_repository_readback(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        collection = stage7.record("multi_competitor_collection")

        self.assertEqual(
            stage7.inputs["buyer_fit_id"],
            stage7.record("buyer_fit").get("buyer_fit_id"),
        )
        self.assertEqual(
            stage7.inputs["offer_recommendation_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertEqual(
            stage7.inputs["legal_action_actor_id"],
            stage7.record("legal_action_actor_profile").get("actor_id"),
        )
        self.assertEqual(
            stage7.inputs["procurement_decision_actor_id"],
            stage7.record("procurement_decision_actor_profile").get("actor_id"),
        )
        self.assertEqual(
            stage7.inputs["multi_competitor_collection_id_optional"],
            collection.get("multi_competitor_collection_id"),
        )
        self.assertEqual(
            stage7.inputs["winning_competitor_candidate_id_optional"],
            collection.get("winning_candidate_id"),
        )
        self.assertEqual(
            stage7.inputs["winning_challenger_profile_id_optional"],
            collection.get("winning_challenger_profile_id"),
        )

    def test_stage7_crm_quote_prerequisite_readiness_carrier_is_internal_non_live(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        carrier = stage7.inputs["crm_quote_prerequisite_readiness"]
        workbench = stage7.inputs["crm_quote_workbench"]

        self.assertEqual(carrier["crm_prerequisite_state"], "RESERVED_NOT_LIVE")
        self.assertEqual(carrier["quote_prerequisite_state"], "RESERVED_NOT_LIVE")
        self.assertEqual(carrier["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertTrue(carrier["readiness_only"])
        self.assertTrue(carrier["prerequisite_only"])
        self.assertFalse(carrier["crm_runtime_enabled"])
        self.assertFalse(carrier["external_quote_enabled"])
        self.assertFalse(carrier["external_delivery_enabled"])
        self.assertEqual(stage7.handoff["crm_quote_prerequisite_readiness_optional"], carrier)
        self.assertEqual(
            stage7.inputs["stage7_resolution_trace"]["crm_quote_prerequisite_readiness"],
            carrier,
        )

        source_refs = carrier["source_object_refs"]
        self.assertEqual(
            source_refs["sales_lead"]["object_id"],
            stage7.record("sales_lead").get("lead_id"),
        )
        self.assertEqual(
            source_refs["saleable_opportunity"]["object_id"],
            stage7.record("saleable_opportunity").get("opportunity_id"),
        )
        self.assertEqual(
            source_refs["offer_recommendation"]["object_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertTrue(source_refs["stage7_resolution_trace"]["opportunity_policy_present"])
        self.assertTrue(source_refs["stage7_resolution_trace"]["price_resolution_present"])
        self.assertIn("crm_runtime_enabled=false", carrier["blocked_reasons"])
        self.assertIn("external_quote_enabled=false", carrier["blocked_reasons"])
        self.assertIn("external_delivery_enabled=false", carrier["blocked_reasons"])
        self.assertIn("customer_facing_quote_not_generated", carrier["blocked_reasons"])
        self.assertIn("client_report_release", carrier["required_approvals"])
        self.assertIn("external_action_release", carrier["required_approvals"])

        audit_summary = carrier["audit_readiness_summary"]
        self.assertFalse(audit_summary["crm_runtime_audit_ready"])
        self.assertFalse(audit_summary["external_quote_audit_ready"])
        self.assertFalse(audit_summary["external_delivery_audit_ready"])
        self.assertEqual(audit_summary["missing_audit_refs"], carrier["required_audit_refs"])

        operator_summary = carrier["operator_readback_summary"]
        self.assertTrue(operator_summary["readback_ready"])
        self.assertFalse(operator_summary["operator_can_enable_crm_runtime"])
        self.assertFalse(operator_summary["operator_can_generate_external_quote"])
        self.assertFalse(operator_summary["operator_can_deliver_external"])

        self.assertEqual(
            workbench["opportunity_id"],
            stage7.record("saleable_opportunity").get("opportunity_id"),
        )
        self.assertTrue(workbench["crm_action_id"].startswith("CRMACT-"))
        self.assertTrue(workbench["quote_draft_id"].startswith("QDRAFT-"))
        self.assertEqual(workbench["owner_action_state"], "DRAFT")
        self.assertEqual(workbench["approval_state"], "NOT_REQUIRED")
        self.assertEqual(workbench["audit_state"], "MISSING")
        self.assertEqual(workbench["vendor_adapter_state"]["state"], "READY")
        self.assertEqual(workbench["quote_surface_state"], "DRAFT")
        self.assertEqual(workbench["dry_run_state"], "INTERNAL_DRY_RUN_CARRIER_ONLY")
        self.assertEqual(workbench["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertFalse(workbench["live_execution_enabled"])
        self.assertFalse(workbench["real_external_quote_sent"])
        self.assertFalse(workbench["real_crm_receipt_generated"])
        self.assertFalse(workbench["customer_visible_quote_generated"])
        self.assertFalse(workbench["customer_visible_delivery_package_generated"])
        self.assertIn("real_crm_receipt_not_generated", workbench["blocked_reasons"])
        self.assertIn("customer_facing_quote_not_generated", workbench["blocked_reasons"])
        self.assertEqual(stage7.handoff["crm_quote_workbench_optional"], workbench)
        self.assertEqual(stage7.handoff["crm_action_id_optional"], workbench["crm_action_id"])
        self.assertEqual(stage7.handoff["quote_draft_id_optional"], workbench["quote_draft_id"])
        self.assertEqual(
            stage7.inputs["stage7_resolution_trace"]["crm_quote_workbench"],
            workbench,
        )
        self.assertEqual(
            stage7.inputs["crm_quote_workbench_readiness_summary"]["quote_draft_id"],
            workbench["quote_draft_id"],
        )

    def test_stage7_crm_quote_workbench_explains_approval_audit_and_vendor_blocks(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "approval_state": "PENDING",
                "audit_trail_present": False,
                "crm_vendor_id_optional": "CRM-UNKNOWN-VENDOR",
                "external_quote_enabled": True,
                "crm_runtime_enabled": True,
                "live_execution_enabled": True,
            }
        )

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        workbench = stage7.inputs["crm_quote_workbench"]

        self.assertEqual(workbench["owner_action_state"], "BLOCKED")
        self.assertEqual(workbench["approval_state"], "PENDING")
        self.assertEqual(workbench["audit_state"], "MISSING")
        self.assertEqual(workbench["vendor_adapter_state"]["state"], "BLOCKED")
        self.assertEqual(workbench["vendor_adapter_state"]["resolved_from"], "EXPLICIT_UNKNOWN_VENDOR")
        self.assertEqual(workbench["quote_surface_state"], "BLOCKED")
        self.assertFalse(workbench["live_execution_enabled"])
        self.assertFalse(workbench["real_external_quote_sent"])
        self.assertIn("approval_state=PENDING", workbench["blocked_reasons"])
        self.assertIn("audit_ref_missing", workbench["blocked_reasons"])
        self.assertIn("crm_vendor_not_in_registry", workbench["blocked_reasons"])
        self.assertIn("external_quote_request_blocked", workbench["blocked_reasons"])
        self.assertIn("live_crm_request_blocked", workbench["blocked_reasons"])
        self.assertIn("live_execution_requested_but_blocked", workbench["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
