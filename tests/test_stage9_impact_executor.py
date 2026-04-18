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

from helpers import load_fixture
from shared.pipeline import run_internal_chain
from stage9_delivery.impact_executor import ImpactExecutor


class TestStage9ImpactExecutor(unittest.TestCase):
    def test_m6_contact_failed_projects_only_formal_targets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"response_status": "WRONG_ROLE"})

        stage9 = run_internal_chain(payload)["stage9"]
        impact = stage9.inputs["impact_mutations"]
        contract_only = stage9.inputs["impact_projected_contracts"]

        self.assertEqual(stage9.inputs["impact_executor_state"], "INTERNAL_V0_ACTIVE")
        self.assertEqual(set(stage9.inputs["impact_formal_targets"]), {"project_fact", "saleable_opportunity", "contact_target", "review_queue_profile"})
        self.assertEqual(set(stage9.inputs["impact_targets_projected"]), {"contact_target", "saleable_opportunity"})
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})
        self.assertEqual(impact["contact_target"]["field_patches"]["contact_target_status"], "INVALID")
        self.assertTrue(impact["contact_target"]["field_patches"]["contact_conflict_flag"])
        self.assertEqual(impact["saleable_opportunity"]["field_patches"]["saleability_status"], "RESTRICTED")
        self.assertEqual(contract_only["sales_lead"]["field_patches"]["lead_status"], "REVIEW")
        self.assertEqual(contract_only["report_record"]["field_patches"]["report_status"], "REVIEW_REQUIRED")

    def test_m6_window_missed_reprioritizes_review_queue(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "CONNECTED",
                "outcome_family": "WINDOW_MISSED",
                "outcome_reason_tags": ["WINDOW_EXPIRED"],
                "window_missed_state": "MISSED",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        impact = stage9.inputs["impact_mutations"]

        self.assertIn("project_fact", impact)
        self.assertIn("review_queue_profile", impact)
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})
        self.assertEqual(stage9.inputs["impact_targets_advisory"], ["buyer_fit"])
        self.assertEqual(impact["review_queue_profile"]["field_patches"]["review_queue_bucket"], "CRITICAL_WINDOW")
        self.assertEqual(impact["review_queue_profile"]["field_patches"]["window_risk_level"], "CRITICAL")
        self.assertEqual(impact["project_fact"]["field_patches"]["sale_gate_status"], "HOLD")
        self.assertEqual(
            stage9.inputs["impact_projected_contracts"]["sales_lead"]["field_patches"]["lead_status"],
            "REVIEW",
        )
        self.assertEqual(
            stage9.inputs["impact_advisories"]["buyer_fit"]["field_patches"]["fit_refresh_reason"],
            "WINDOW_MISSED",
        )

    def test_m6_governance_targets_remain_additive(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"response_status": "NO_RESPONSE", "crm_owner_state": "UNASSIGNED"})

        stage9 = run_internal_chain(payload)["stage9"]
        projected = stage9.inputs["impact_targets_projected"]
        impact = stage9.inputs["impact_mutations"]

        self.assertEqual(set(projected), {"contact_target", "saleable_opportunity"})
        self.assertEqual(impact["contact_target"]["field_patches"]["contact_target_status"], "REVIEW_REQUIRED")
        self.assertEqual(impact["saleable_opportunity"]["field_patches"]["saleability_status"], "RESTRICTED")
        self.assertIn("IMPACT-CONTACT-FAILED-OPPORTUNITY-001", impact["saleable_opportunity"]["applied_rule_ids"])
        self.assertIn("IMPACT-APPROVAL-MISSING-OPPORTUNITY-001", impact["saleable_opportunity"]["applied_rule_ids"])
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})

    def test_writeback_contract_formalizes_target_semantics(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "refund_state": "COMPLETED",
                "outcome_family": "DELIVERY_ABANDONED",
                "outcome_reason_tags": ["REFUND_COMPLETED"],
                "trigger_type": "EXCEPTION_TRIGGERED",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        contracts = stage9.inputs["writeback_target_contracts"]
        semantics = stage9.inputs["writeback_contract_semantics"]

        self.assertEqual(stage9.inputs["writeback_contract_state"], "FORMAL_CONTRACT_ACTIVE")
        self.assertTrue(semantics["outcome_targets_authoritative"])
        self.assertTrue(semantics["governance_targets_additive_only"])
        self.assertTrue(semantics["payment_exception_targets_additive_only"])
        self.assertTrue(semantics["delivery_exception_targets_additive_only"])
        self.assertTrue(semantics["silent_override_outcome_targets_forbidden"])
        self.assertEqual(
            stage9.inputs["writeback_persistence_targets"],
            ["delivery_record", "governance_feedback_event"],
        )
        self.assertEqual(
            stage9.inputs["writeback_projected_targets"],
            ["project_fact", "sales_lead", "report_record", "saleable_opportunity"],
        )
        self.assertEqual(
            stage9.inputs["resolved_effective_writeback_targets"],
            [
                "delivery_record",
                "project_fact",
                "governance_feedback_event",
                "sales_lead",
                "report_record",
                "controlled_exception_record",
                "release_gates",
                "saleable_opportunity",
            ],
        )
        self.assertEqual(
            stage9.inputs["writeback_advisory_targets"],
            [],
        )
        self.assertEqual(
            stage9.inputs["writeback_trace_only_targets"],
            ["controlled_exception_record", "release_gates"],
        )
        self.assertEqual(
            contracts["delivery_record"]["mutation_semantics"],
            "PERSISTED_STAGE9_RECORD",
        )
        self.assertEqual(
            contracts["project_fact"]["mutation_semantics"],
            "PROJECTED_MUTATION_ONLY",
        )
        self.assertEqual(
            contracts["controlled_exception_record"]["mutation_semantics"],
            "TRACE_ONLY_CONTRACT",
        )
        self.assertEqual(
            contracts["sales_lead"]["mutation_semantics"],
            "PROJECTED_MUTATION_ONLY",
        )
        self.assertEqual(
            contracts["report_record"]["persistence_semantics"],
            "NOT_PERSISTED_IN_STAGE9_RUNTIME",
        )
        self.assertEqual(
            contracts["governance_feedback_event"]["resolved_from_sources"],
            ["outcome_taxonomy"],
        )

    def test_writeback_source_contracts_and_target_sources_are_exposed(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "refund_state": "COMPLETED",
                "outcome_family": "DELIVERY_ABANDONED",
                "outcome_reason_tags": ["REFUND_COMPLETED"],
                "trigger_type": "EXCEPTION_TRIGGERED",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        source_contracts = stage9.inputs["writeback_source_contracts"]
        target_sources = stage9.inputs["writeback_target_sources"]
        contracts = stage9.inputs["writeback_target_contracts"]

        self.assertEqual(
            source_contracts["outcome_taxonomy"]["merge_semantics"],
            "AUTHORITATIVE_BASE",
        )
        self.assertEqual(
            source_contracts["governance_taxonomy"]["merge_semantics"],
            "ADDITIVE_ONLY",
        )
        self.assertEqual(
            source_contracts["payment_exception"]["persisted_stage9_record_target"],
            "payment_record",
        )
        self.assertEqual(
            source_contracts["delivery_exception"]["persisted_stage9_record_target"],
            "delivery_record",
        )
        self.assertEqual(
            source_contracts["upstream_feedback_loop"]["merge_semantics"],
            "PROJECTED_FEEDBACK_ONLY",
        )
        self.assertEqual(
            source_contracts["upstream_feedback_loop"]["target_semantics"],
            "PROJECTED_CONTRACT_ONLY + TRACE_ONLY_ADVISORY",
        )
        self.assertEqual(
            target_sources["project_fact"],
            ["outcome_taxonomy", "payment_exception"],
        )
        self.assertEqual(
            target_sources["sales_lead"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            target_sources["report_record"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            target_sources["delivery_record"],
            ["outcome_taxonomy", "delivery_exception"],
        )
        self.assertEqual(
            contracts["delivery_record"]["resolved_from_sources"],
            ["outcome_taxonomy", "delivery_exception"],
        )
        self.assertEqual(
            contracts["saleable_opportunity"]["resolved_from_sources"],
            ["payment_exception"],
        )
        self.assertEqual(
            target_sources["governance_feedback_event"],
            ["outcome_taxonomy"],
        )
        self.assertEqual(
            source_contracts["outcome_taxonomy"]["authoritative_feedback_contract_ref"],
            "contracts/sales/opportunity_policy_catalog.json#policies.opportunity_outcome_writeback_v1",
        )

    def test_false_positive_forms_projected_and_advisory_feedback_targets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "outcome_family": "FALSE_POSITIVE",
                "outcome_reason_tags": ["FACT_CONFLICT"],
                "is_false_positive": True,
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        self.assertEqual(
            stage9.inputs["upstream_feedback_projected_targets"],
            ["sales_lead", "report_record"],
        )
        self.assertEqual(
            set(stage9.inputs["upstream_feedback_advisory_targets"]),
            {"buyer_fit", "challenger_candidate_profile"},
        )
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})
        self.assertEqual(set(stage9.inputs["impact_targets_advisory"]), {"buyer_fit", "challenger_candidate_profile"})
        self.assertEqual(
            stage9.inputs["impact_projected_contracts"]["sales_lead"]["field_patches"]["lead_status"],
            "DISQUALIFIED",
        )
        self.assertEqual(
            stage9.inputs["impact_advisories"]["challenger_candidate_profile"]["field_patches"]["profile_refresh_reason"],
            "FALSE_POSITIVE",
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["challenger_candidate_profile"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            stage9.inputs["outcome_writeback_targets"],
            ["project_fact"],
        )

    def test_partial_payment_keeps_precise_exception_family_and_additive_targets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"payment_status": "PARTIALLY_PAID"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "PARTIAL_PAYMENT",
        )
        self.assertEqual(stage9.record("opportunity_outcome_event").get("outcome_family"), "LOST")
        self.assertEqual(
            stage9.record("opportunity_outcome_event").get("outcome_reason_tags"),
            ["PAYMENT_FAILED"],
        )
        self.assertEqual(
            stage9.inputs["payment_exception_writeback_targets_optional"],
            ["saleable_opportunity", "project_fact"],
        )
        self.assertEqual(
            stage9.inputs["governance_writeback_targets_optional"],
            ["delivery_record", "release_gates"],
        )
        self.assertEqual(
            stage9.inputs["effective_writeback_targets"],
            [
                "project_fact",
                "saleable_opportunity",
                "delivery_record",
                "release_gates",
            ],
        )
        self.assertNotIn("buyer_fit", stage9.inputs["effective_writeback_targets"])
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["project_fact"],
            ["outcome_taxonomy", "payment_exception"],
        )

    def test_refund_requested_keeps_precise_family_and_coarse_signed_reason(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"refund_state": "REQUESTED"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "REFUND_REQUESTED",
        )
        self.assertEqual(
            stage9.record("opportunity_outcome_event").get("outcome_family"),
            "DELIVERY_ABANDONED",
        )
        self.assertEqual(
            stage9.record("opportunity_outcome_event").get("outcome_reason_tags"),
            ["SIGNED"],
        )
        self.assertEqual(
            stage9.inputs["payment_exception_writeback_targets_optional"],
            ["delivery_record", "saleable_opportunity"],
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["sales_lead"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["governance_feedback_event"],
            ["outcome_taxonomy"],
        )

    def test_payer_mismatch_keeps_outcome_and_governance_semantics_separate(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"payer_mismatch_state": "CONFIRMED"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.inputs["outcome_writeback_targets"],
            ["order_record", "payment_record"],
        )
        self.assertEqual(
            stage9.inputs["governance_writeback_targets_optional"],
            ["delivery_record", "release_gates"],
        )
        self.assertEqual(
            stage9.inputs["payment_exception_writeback_targets_optional"],
            ["order_record", "delivery_record"],
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["payment_record"],
            ["outcome_taxonomy"],
        )
        self.assertEqual(
            set(stage9.inputs["impact_targets_projected_contract_only"]),
            {"sales_lead", "report_record"},
        )

    def test_writeback_contract_rejects_disallowed_additive_source(self) -> None:
        executor = ImpactExecutor()

        with self.assertRaisesRegex(
            ValueError,
            "does not allow additive source governance_taxonomy",
        ):
            executor.resolve_effective_targets(
                outcome_targets=["contact_target"],
                upstream_feedback_targets=[],
                governance_targets=["saleable_opportunity"],
                payment_exception_targets=[],
                delivery_exception_targets=[],
            )


if __name__ == "__main__":
    unittest.main()
