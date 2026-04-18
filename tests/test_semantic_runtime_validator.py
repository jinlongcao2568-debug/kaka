from __future__ import annotations

import copy
import unittest

from helpers import load_fixture
from shared.contracts_runtime import ContractStore, StageBundle
from shared.pipeline import run_internal_chain
from stage1_tasking.service import Stage1Service
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from stage7_sales.service import Stage7Service


class TestSemanticRuntimeValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ContractStore.default()

    def _stage_bundles_to_stage7(self) -> dict[str, StageBundle]:
        payload = load_fixture("internal_chain_happy.json")
        stage1 = Stage1Service().run(payload)
        stage2 = Stage2Service().run(stage1)
        stage3 = Stage3Service().run(stage2)
        stage4 = Stage4Service().run(stage3)
        stage5 = Stage5Service().run(stage4)
        stage6 = Stage6Service().run(stage5)
        stage7 = Stage7Service().run(stage6)
        return {
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "stage4": stage4,
            "stage5": stage5,
            "stage6": stage6,
            "stage7": stage7,
        }

    def test_h01_to_h07_handoff_runtime_checks_allow_happy_path(self) -> None:
        bundles = self._stage_bundles_to_stage7()
        stage_map = {
            2: bundles["stage1"],
            3: bundles["stage2"],
            4: bundles["stage3"],
            5: bundles["stage4"],
            6: bundles["stage5"],
            7: bundles["stage6"],
            8: bundles["stage7"],
        }
        for consumer_stage, producer_bundle in stage_map.items():
            result = self.store.evaluate_handoff_consumer(
                producer_bundle=producer_bundle,
                consumer_stage=consumer_stage,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.decision_state, "ALLOW", result.semantic_scope)

    def test_handoff_runtime_blocks_missing_required_or_critical_inputs(self) -> None:
        bundles = self._stage_bundles_to_stage7()

        broken_h01 = StageBundle(
            stage=1,
            records={key: value for key, value in bundles["stage1"].records.items() if key != "task_execution_context"},
            handoff={key: value for key, value in bundles["stage1"].handoff.items() if key != "review_lane"},
            trace_rules=list(bundles["stage1"].trace_rules),
            inputs={key: value for key, value in bundles["stage1"].inputs.items() if key != "review_lane"},
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=broken_h01, consumer_stage=2).decision_state,
            "BLOCK",
        )

        broken_h02 = StageBundle(
            stage=2,
            records={key: value for key, value in bundles["stage2"].records.items() if key != "fixation_bundle"},
            handoff={key: value for key, value in bundles["stage2"].handoff.items() if key != "fixation_bundle_id"},
            trace_rules=list(bundles["stage2"].trace_rules),
            inputs={key: value for key, value in bundles["stage2"].inputs.items() if key != "fixation_bundle_id"},
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=broken_h02, consumer_stage=3).decision_state,
            "BLOCK",
        )

        broken_h03 = StageBundle(
            stage=3,
            records={key: value for key, value in bundles["stage3"].records.items() if key != "project_base"},
            handoff=dict(bundles["stage3"].handoff),
            trace_rules=list(bundles["stage3"].trace_rules),
            inputs=dict(bundles["stage3"].inputs),
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=broken_h03, consumer_stage=4).decision_state,
            "BLOCK",
        )

        broken_h04 = StageBundle(
            stage=4,
            records={key: value for key, value in bundles["stage4"].records.items() if key != "evidence_grade_profile"},
            handoff=dict(bundles["stage4"].handoff),
            trace_rules=list(bundles["stage4"].trace_rules),
            inputs=dict(bundles["stage4"].inputs),
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=broken_h04, consumer_stage=5).decision_state,
            "BLOCK",
        )

        broken_h05 = StageBundle(
            stage=5,
            records={key: value for key, value in bundles["stage5"].records.items() if key != "rule_gate_decision"},
            handoff={key: value for key, value in bundles["stage5"].handoff.items() if key != "coverage_sellable_state"},
            trace_rules=list(bundles["stage5"].trace_rules),
            inputs={key: value for key, value in bundles["stage5"].inputs.items() if key != "coverage_sellable_state"},
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=broken_h05, consumer_stage=6).decision_state,
            "BLOCK",
        )

    def test_h01_must_not_recompute_source_route_fields(self) -> None:
        bundles = self._stage_bundles_to_stage7()
        h01_conflict = StageBundle(
            stage=1,
            records=dict(bundles["stage1"].records),
            handoff=dict(bundles["stage1"].handoff),
            trace_rules=list(bundles["stage1"].trace_rules),
            inputs={**bundles["stage1"].inputs, "default_route": "DETAIL_DIRECT"},
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=h01_conflict, consumer_stage=2).decision_state,
            "BLOCK",
        )

    def test_h03_stage4_must_not_recompute_stage3_truth_fields(self) -> None:
        bundles = self._stage_bundles_to_stage7()
        project_base = bundles["stage3"].record("project_base")
        canonical_handoff = {
            **bundles["stage3"].handoff,
            "project_root_id": project_base.get("project_root_id"),
            "notice_version_id": project_base.get("notice_version_id"),
            "candidate_order_mode": project_base.get("candidate_order_mode"),
        }
        h03_conflict = StageBundle(
            stage=3,
            records=dict(bundles["stage3"].records),
            handoff=canonical_handoff,
            trace_rules=list(bundles["stage3"].trace_rules),
            inputs={**bundles["stage3"].inputs, "project_root_id": "ROOT-RECOMPUTED"},
        )
        validation = self.store.evaluate_handoff_consumer(
            producer_bundle=h03_conflict,
            consumer_stage=4,
        )
        self.assertEqual(validation.decision_state, "BLOCK")
        self.assertIn("must-not-recompute", validation.reasons[0])

    def test_stage3_unresolved_lineage_forces_stage4_review_path(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["flags"] = {"missing_source": True}

        stage1 = Stage1Service().run(payload)
        stage2 = Stage2Service().run(stage1)
        stage3 = Stage3Service().run(stage2)
        stage4 = Stage4Service().run(stage3)

        lineage = stage3.record("field_lineage_record")
        self.assertEqual(lineage.get("lineage_status"), "UNVERIFIED")
        self.assertEqual(lineage.get("conflict_state"), "UNRESOLVED")
        self.assertEqual(lineage.get("review_path_optional"), "STAGE3_REVIEW_REQUIRED")
        self.assertEqual(lineage.get("unresolved_reason_optional"), "missing_source_slice_or_normalization_rule")
        self.assertEqual(stage3.record("project_base").get("stage3_review_path_ref_optional"), "STAGE3_REVIEW_REQUIRED")
        self.assertEqual(stage4.record("public_attack_surface").get("verification_state"), "REVIEW")
        self.assertNotEqual(stage4.record("public_attack_surface").get("verification_state"), "PASS")

    def test_stage3_prefers_stage2_handoff_authority_over_input_override(self) -> None:
        stage1 = Stage1Service().run(load_fixture("internal_chain_happy.json"))
        stage2 = Stage2Service().run(stage1)
        conflicted_stage2 = StageBundle(
            stage=2,
            records=dict(stage2.records),
            handoff=dict(stage2.handoff),
            trace_rules=list(stage2.trace_rules),
            inputs={
                **stage2.inputs,
                "source_registry_id": "SRC-REG-PROC-CITY-PDF",
                "route_policy_id": "ROUTE-PROC-CITY-OVERRIDE",
                "route_decision_state": "REVIEW",
                "winning_version_resolution_rule_id": "VERSION-OVERRIDE",
                "clock_resolution_rule_id": "CLOCK-OVERRIDE",
            },
        )
        stage3 = Stage3Service().run(conflicted_stage2)

        self.assertEqual(stage3.inputs.get("source_registry_id"), stage2.handoff.get("source_registry_id"))
        self.assertEqual(stage3.inputs.get("route_policy_id"), stage2.handoff.get("route_policy_id"))
        self.assertEqual(stage3.inputs.get("route_decision_state"), stage2.handoff.get("route_decision_state"))
        self.assertEqual(
            stage3.inputs.get("winning_version_resolution_rule_id"),
            stage2.handoff.get("winning_version_resolution_rule_id"),
        )
        self.assertEqual(
            stage3.inputs.get("clock_resolution_rule_id"),
            stage2.handoff.get("clock_resolution_rule_id"),
        )
        self.assertEqual(stage3.handoff.get("source_registry_id"), stage2.handoff.get("source_registry_id"))
        self.assertEqual(stage3.handoff.get("route_policy_id"), stage2.handoff.get("route_policy_id"))

    def test_h06_and_h07_must_not_recompute_conflicts_block(self) -> None:
        bundles = self._stage_bundles_to_stage7()

        h06_conflict = StageBundle(
            stage=6,
            records=dict(bundles["stage6"].records),
            handoff=dict(bundles["stage6"].handoff),
            trace_rules=list(bundles["stage6"].trace_rules),
            inputs={**bundles["stage6"].inputs, "window_status": "MISSED"},
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=h06_conflict, consumer_stage=7).decision_state,
            "BLOCK",
        )

        h07_conflict = StageBundle(
            stage=7,
            records=dict(bundles["stage7"].records),
            handoff=dict(bundles["stage7"].handoff),
            trace_rules=list(bundles["stage7"].trace_rules),
            inputs={**bundles["stage7"].inputs, "opportunity_id": "OPP-WRONG"},
        )
        self.assertEqual(
            self.store.evaluate_handoff_consumer(producer_bundle=h07_conflict, consumer_stage=8).decision_state,
            "BLOCK",
        )

    def test_stage8_third_party_source_cannot_bypass_formal_merge_review(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "source_vendor_role": "THIRD_PARTY_SUPPORT_SOURCE",
                "source_vendor_id_optional": "SOURCE-TIANYANCHA",
                "public_contact_source": "TIANYANCHA",
                "channel_family": "ORG_EMAIL",
                "contact_channel": "EMAIL",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        collection = stage8.inputs.get("contact_candidate_collection_snapshot", {})
        trace = stage8.inputs.get("contact_selection_trace_snapshot", {})

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "REVIEW_REQUIRED")
        self.assertTrue(stage8.record("contact_target").get("requires_manual_review"))
        self.assertEqual(collection.get("source_merge_review_required_count"), 1)
        self.assertEqual(trace.get("source_merge_review_required_count"), 1)
        self.assertEqual(collection.get("candidate_list", [])[0].get("formal_merge_state"), "REVIEW_REQUIRED_SINGLE_THIRD_PARTY")

    def test_stage6_to_stage9_semantic_rules_block_key_contradictions(self) -> None:
        project_fact = self.store.evaluate_object_semantics(
            stage=6,
            object_type="project_fact",
            payload={
                "project_fact_id": "FACT-1",
                "project_id": "P-1",
                "sale_gate_status": "OPEN",
                "rule_gate_status": "PASS",
                "evidence_gate_status": "REVIEW",
                "rule_hit_summary": ["RH-1"],
                "clue_summary": ["CLUE"],
                "risk_summary": ["RISK"],
                "coverage_sellable_state": "SELLABLE",
                "delivery_risk_state": "ALLOW",
                "manual_override_status": "NONE",
                "real_competitor_count": 1,
                "serviceable_competitor_count": 1,
                "competitor_quality_grade": "B",
            },
            semantic_context={},
        )
        self.assertEqual(project_fact.decision_state, "BLOCK")

        opportunity = self.store.evaluate_object_semantics(
            stage=7,
            object_type="saleable_opportunity",
            payload={
                "opportunity_id": "OPP-1",
                "project_id": "P-1",
                "recommended_sku": "SKU-A",
                "buyer_fit_id": "BF-1",
                "challenger_profile_id": "CH-1",
                "opportunity_grade": "A",
                "saleability_status": "QUALIFIED",
                "major_value_points": ["A"],
                "blocking_reasons": [],
                "expected_close_days_band": "UNKNOWN",
                "expected_contract_value_band": "UNKNOWN",
                "expected_delivery_cost_band": "UNKNOWN",
                "crm_owner_state": "ASSIGNED",
            },
            semantic_context={
                "project_fact_present": True,
                "challenger_profile_present": True,
                "sale_gate_status": "REVIEW",
                "report_status": "READY",
            },
        )
        self.assertEqual(opportunity.decision_state, "BLOCK")

        sales_lead = self.store.evaluate_object_semantics(
            stage=7,
            object_type="sales_lead",
            payload={
                "lead_id": "LEAD-1",
                "project_id": "P-1",
                "lead_reason_summary": "test",
                "lead_score": 88,
                "lead_status": "QUALIFIED",
                "generated_at": "2026-04-15T00:00:00Z",
            },
            semantic_context={
                "sale_gate_status": "OPEN",
                "report_status": "READY",
            },
        )
        self.assertEqual(sales_lead.decision_state, "BLOCK")

        offer = self.store.evaluate_object_semantics(
            stage=7,
            object_type="offer_recommendation",
            payload={
                "offer_recommendation_id": "OFFER-1",
                "project_id": "P-1",
                "offer_recommendation_state": "APPROVED",
                "sku_code": "SKU-A",
                "recommended_delivery_form": "OBJECTION_DRAFT",
                "recommended_quote_band": "HIGH",
                "why_recommended": "test",
                "prerequisites": ["report_status=READY"],
            },
            semantic_context={
                "saleability_status": "BLOCKED",
                "report_status": "READY",
            },
        )
        self.assertEqual(offer.decision_state, "BLOCK")

        contact = self.store.evaluate_object_semantics(
            stage=8,
            object_type="contact_target",
            payload={
                "contact_target_id": "CT-1",
                "opportunity_id": "OPP-1",
                "project_id": "P-1",
                "saleability_status": "QUALIFIED",
                "org_name": "ORG",
                "org_type": "ENTERPRISE",
                "person_name_optional": "张三",
                "role_cluster": "PROCUREMENT_DECISION",
                "public_contact_source": "PUBLIC_SITE",
                "source_family": "PROCUREMENT_NOTICE",
                "source_auditability_state": "AUDITABLE",
                "source_vendor_id_optional": "SOURCE-OFFICIAL-WEBSITE",
                "source_vendor_type_optional": "SOURCE_VENDOR",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_target_status": "ELIGIBLE",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "OPTED_OUT",
                "quiet_hours_policy_state": "ALLOW",
                "auto_contact_allowed": True,
                "source_audit_ref": "AUDIT-1",
                "query_trace_id": "TRACE-1",
                "vendor_response_ref_optional": "RESP-1",
                "fallback_vendor_id_optional": "FB-1",
                "requires_manual_review": False,
                "primary_contact_flag": True,
                "contact_priority_score": 80,
                "contact_priority_reason_tags": ["ROLE_PROCUREMENT_DECISION_ACTOR"],
                "contact_candidate_rank": 1,
                "contact_selection_reason": "role=PROCUREMENT_DECISION_ACTOR;channel=ORG_EMAIL",
                "contact_conflict_flag": False,
                "contact_conflict_reason": "single candidate",
                "blocking_reasons": [],
                "last_evaluated_at": "2026-04-15T00:00:00Z",
            },
            semantic_context={"upstream_saleability_status": "QUALIFIED"},
        )
        self.assertEqual(contact.decision_state, "BLOCK")

        outcome = self.store.evaluate_object_semantics(
            stage=9,
            object_type="opportunity_outcome_event",
            payload={
                "outcome_event_id": "OUT-1",
                "project_id": "P-1",
                "opportunity_id": "OPP-1",
                "outcome_family": "WON",
                "outcome_reason_tags": ["SIGNED"],
                "is_false_positive": False,
                "window_missed_state": "NOT_MISSED",
                "contact_failure_state": "OTHER",
                "payer_mismatch_state": "NO_MISMATCH",
                "feedback_reason": "SIGNED",
                "trigger_type": "OTHER",
                "action_taken": "manual review",
                "writeback_targets": ["project_fact"],
                "governance_feedback_triggered_optional": False,
                "written_back_at": "2026-04-15T00:00:00Z",
                "written_back_at_optional": "2026-04-15T00:00:00Z",
                "governed_execution_mode": "INTERNAL_GOVERNED",
                "permission_decision_state": "ALLOW",
                "governance_decision_state": "BLOCK",
                "semantic_decision_state": "ALLOW",
                "governed_metadata": {
                    "live_execution_enabled": False,
                    "skeleton_only": True,
                },
            },
            semantic_context={
                "delivery_status": "RELEASE_BLOCKED",
                "plan_status": "APPROVED",
                "feedback_reason": "SIGNED",
                "governance_decision_state": "BLOCK",
            },
        )
        self.assertEqual(outcome.decision_state, "BLOCK")

    def test_stage9_semantic_rules_cover_h08_optional_and_refund_closure(self) -> None:
        order = self.store.evaluate_object_semantics(
            stage=9,
            object_type="order_record",
            payload={
                "order_id": "ORDER-1",
                "project_id": "P-1",
                "opportunity_id": "OPP-1",
                "touch_record_id": "TOUCH-1",
                "response_status": "CONNECTED",
                "saleability_status": "QUALIFIED",
                "crm_owner_state": "ASSIGNED",
                "commercial_status": "DRAFT",
                "order_status": "DRAFT",
                "approval_state": "APPROVED",
                "archival_status": "NOT_ARCHIVED",
                "amount_band": "LOW",
                "plan_status": "APPROVED",
                "touch_record_state": "CANCELLED",
                "governed_execution_mode": "INTERNAL_GOVERNED",
                "permission_decision_state": "ALLOW",
                "governance_decision_state": "ALLOW",
                "semantic_decision_state": "ALLOW",
                "governed_metadata": {"live_execution_enabled": False},
                "created_at": "2026-04-15T00:00:00Z",
            },
            semantic_context={
                "saleability_status": "QUALIFIED",
                "crm_owner_state": "ASSIGNED",
                "plan_status": "APPROVED",
                "touch_record_state": "CANCELLED",
                "feedback_reason": "CONNECTED",
                "governance_decision_state": "ALLOW",
            },
        )
        self.assertEqual(order.decision_state, "BLOCK")

        payment = self.store.evaluate_object_semantics(
            stage=9,
            object_type="payment_record",
            payload={
                "payment_id": "PAY-1",
                "project_id": "P-1",
                "order_id": "ORDER-1",
                "payment_status": "REFUNDED",
                "payment_proof_state": "UPLOADED",
                "payer_match_state": "MATCHED",
                "amount_match_state": "MATCHED",
                "amount_band": "LOW",
                "payment_exception_family_optional": "REFUND_COMPLETED",
                "payment_exception_reason_optional": "REFUND_COMPLETED",
                "payment_exception_reason_tags_optional": ["REFUND_COMPLETED"],
                "amount_mismatch_state_optional": "NO_MISMATCH",
                "refund_state": "COMPLETED",
                "paid_at_optional": "2026-04-15T00:00:00Z",
                "written_back_at_optional": "2026-04-15T00:00:00Z",
                "governed_execution_mode": "INTERNAL_GOVERNED",
                "permission_decision_state": "ALLOW",
                "governance_decision_state": "REVIEW",
                "semantic_decision_state": "ALLOW",
                "governed_metadata": {"live_execution_enabled": False},
            },
            semantic_context={"payer_mismatch_state": "NO_MISMATCH", "feedback_reason": "REFUND_COMPLETED"},
        )
        self.assertEqual(payment.decision_state, "BLOCK")


if __name__ == "__main__":
    unittest.main()
