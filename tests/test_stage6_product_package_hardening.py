from __future__ import annotations

import copy
import sys
import tempfile
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
from shared.contracts_runtime import StageBundle
from shared.pipeline import run_internal_chain
from stage6_fact_review.fact_aggregator import STAGE6_PRODUCT_PACKAGE_READINESS_KEY
from stage6_fact_review.service import Stage6Service
from stage5_rules_evidence.service import Stage5Service
from storage import persist_stage_bundle, reset_default_storage
from storage.repository_boundary import hydrate_stage_bundle
from storage.repositories import WorkItemRepository
from test_stage5_rule_factory_expansion import _real_public_stage4_verification


class TestStage6ProductPackageHardening(unittest.TestCase):
    def _carrier(self, stage6: StageBundle) -> dict[str, object]:
        carrier = stage6.inputs.get(STAGE6_PRODUCT_PACKAGE_READINESS_KEY)
        self.assertIsInstance(carrier, dict)
        return carrier

    def _rerun_stage6_with_stage5_inputs(self, overrides: dict[str, object]) -> StageBundle:
        stage5 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage5"]
        return Stage6Service().run(
            StageBundle(
                stage=5,
                records=dict(stage5.records),
                handoff=dict(stage5.handoff),
                trace_rules=list(stage5.trace_rules),
                inputs={**stage5.inputs, **overrides},
            )
        )

    def test_happy_path_emits_internal_product_package_readiness_carrier(self) -> None:
        stage6 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage6"]
        carrier = self._carrier(stage6)

        self.assertEqual(stage6.handoff.get(STAGE6_PRODUCT_PACKAGE_READINESS_KEY), carrier)
        self.assertEqual(
            stage6.inputs.get("stage6_review_report_trace", {}).get("product_package_readiness"),
            carrier,
        )
        self.assertEqual(carrier["product_package_readiness"], "INTERNAL_READY")
        self.assertEqual(carrier["objection_viability"], "VIABLE")
        self.assertEqual(carrier["evidence_strength"], "MEDIUM")
        self.assertEqual(carrier["sellable_signal"], "SELLABLE_INTERNAL")
        self.assertEqual(carrier["customer_delivery_eligibility"], "NOT_ELIGIBLE")
        self.assertEqual(carrier["delivery_readiness"], "INTERNAL_READY_CUSTOMER_GATED")
        self.assertEqual(carrier["objection_pack_readiness"], "INTERNAL_READY")
        self.assertEqual(carrier["sales_readiness"], "INTERNAL_READY_NO_EXECUTION_TRIGGERED")
        self.assertEqual(carrier["external_visibility_status"], "INTERNAL_ONLY_EXTERNAL_PLATFORM_BLOCKED")

        constraints = carrier["customer_delivery_constraints"]
        self.assertEqual(
            {
                "evidence_gate_ready": True,
                "public_visibility_ready": False,
                "review_state_ready": True,
                "field_allowlist_masking_ready": True,
                "delivery_governance_ready": False,
                "minimum_release_ready": False,
                "approval_ready": False,
                "stage9_writeback_ready": False,
            },
            constraints,
        )
        self.assertIn(
            "external_use_grade=E2_REVIEW_READY_below_E3_CLIENT_VISIBLE",
            carrier["downgrade_reasons"],
        )
        self.assertIn(
            "minimum_release_level=INTERNAL_OPERABLE_below_LEADPACK_DELIVERABLE",
            carrier["downgrade_reasons"],
        )
        self.assertIn("stage9_writeback_before_delivery_missing", carrier["downgrade_reasons"])
        self.assertEqual(carrier["block_reasons"], [])

        refs = carrier["source_object_refs"]
        self.assertEqual(refs["project_fact_id"], stage6.record("project_fact").get("project_fact_id"))
        self.assertEqual(refs["report_record_id"], stage6.record("report_record").get("report_id"))
        self.assertEqual(
            refs["review_queue_profile_id"],
            stage6.record("review_queue_profile").get("queue_profile_id"),
        )
        self.assertEqual(refs["evidence_id"], "EVD-PROJ-001")
        self.assertEqual(refs["rule_gate_decision_id"], "RGATE-PROJ-001")
        self.assertEqual(refs["evidence_gate_decision_id"], "EGATE-PROJ-001")

        audit = carrier["audit_readback_summary"]
        self.assertTrue(audit["replayable"])
        self.assertTrue(audit["no_customer_visible_material_generated"])
        self.assertTrue(audit["no_external_release_enabled"])
        self.assertTrue(audit["no_stage7_stage8_stage9_execution_triggered"])
        self.assertFalse(audit["formal_facts_mutated_by_carrier"])

    def test_review_and_block_paths_downgrade_or_block_package_readiness(self) -> None:
        stage6 = run_internal_chain(load_fixture("internal_chain_block.json"))["stage6"]
        carrier = self._carrier(stage6)

        self.assertEqual(carrier["product_package_readiness"], "BLOCKED")
        self.assertEqual(carrier["customer_delivery_eligibility"], "NOT_ELIGIBLE")
        self.assertEqual(carrier["objection_viability"], "BLOCKED")
        self.assertEqual(carrier["sellable_signal"], "BLOCKED")
        self.assertIn("report_status=REVOKED_not_ISSUED", carrier["block_reasons"])
        self.assertIn("rule_gate_status=REVIEW", carrier["downgrade_reasons"])
        self.assertIn("evidence_gate_status=REVIEW", carrier["downgrade_reasons"])
        self.assertIn("linked_review_request_id_present", carrier["downgrade_reasons"])
        self.assertIn(
            "governed_supplement_unavailable_for_review_request",
            carrier["downgrade_reasons"],
        )

    def test_customer_delivery_requires_evidence_visibility_review_masking_and_governance(self) -> None:
        stage6 = self._rerun_stage6_with_stage5_inputs(
            {
                "external_use_grade": "E3_CLIENT_VISIBLE",
                "minimum_release_level": "LEADPACK_DELIVERABLE",
                "approval_state": "APPROVED",
                "stage9_outcome_governance_writeback_recorded": True,
            }
        )
        carrier = self._carrier(stage6)

        self.assertEqual(carrier["product_package_readiness"], "INTERNAL_READY")
        self.assertEqual(carrier["customer_delivery_eligibility"], "ELIGIBLE_GATED_NOT_PUBLISHED")
        self.assertTrue(all(carrier["customer_delivery_constraints"].values()))
        self.assertEqual(carrier["delivery_governance"]["decision_state"], "ALLOW")
        self.assertEqual(carrier["delivery_governance"]["governance_reasons"], [])
        projected = carrier["delivery_governance"]["field_policy_masking"]["projected_fields"]
        self.assertIn(
            {"field": "project_fact.rule_hit_summary", "mask_rule": "SUMMARY_ONLY"},
            projected["LEADPACK_DELIVERABLE"],
        )
        visibility_trace = carrier["external_visibility_trace"]
        self.assertFalse(visibility_trace["external_platform_allowed"])
        self.assertFalse(visibility_trace["external_software_release_enabled"])
        self.assertFalse(visibility_trace["leadpack_publication_generated"])

    def test_semantic_review_is_reflected_as_product_downgrade_reason(self) -> None:
        stage6 = self._rerun_stage6_with_stage5_inputs(
            {
                "real_competitor_count": 0,
                "challenge_actionability_score": 70,
            }
        )
        carrier = self._carrier(stage6)

        self.assertEqual(stage6.inputs.get("semantic_decision_state"), "REVIEW")
        self.assertEqual(carrier["product_package_readiness"], "REVIEW_REQUIRED")
        self.assertIn("semantic_decision_state=REVIEW", carrier["downgrade_reasons"])

    def test_persist_hydrate_and_work_item_readback_replay_product_carrier(self) -> None:
        reset_default_storage()
        stage6 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage6"]
        carrier = self._carrier(stage6)
        persist_stage_bundle(stage6)

        hydrated = hydrate_stage_bundle(
            "stage6",
            {"project_id": stage6.record("project_fact").get("project_id")},
        )
        self.assertIsNotNone(hydrated)
        hydrated_carrier = self._carrier(hydrated)
        self.assertEqual(hydrated_carrier, carrier)
        self.assertEqual(hydrated.handoff.get(STAGE6_PRODUCT_PACKAGE_READINESS_KEY), carrier)
        self.assertEqual(
            hydrated.inputs.get("stage6_review_report_trace", {}).get("product_package_readiness"),
            carrier,
        )

        work_items = WorkItemRepository().list(stage_scope=6)
        self.assertEqual(len(work_items), 1)
        self.assertEqual(
            work_items[0].governed_context.get(STAGE6_PRODUCT_PACKAGE_READINESS_KEY),
            carrier,
        )

    def test_stage9_feedback_inputs_do_not_pollute_stage6_formal_facts_or_refs(self) -> None:
        base_payload = load_fixture("internal_chain_happy.json")
        feedback_payload = copy.deepcopy(base_payload)
        feedback_payload.update(
            {
                "outcome_family": "FALSE_POSITIVE",
                "outcome_reason_tags": ["FACT_CONFLICT"],
                "governance_feedback_event_id": "GOV-FEEDBACK-RAW",
                "feedback_reason": "stage9_feedback_should_not_rewrite_stage6_fact",
                "is_false_positive": True,
            }
        )

        base_stage6 = run_internal_chain(base_payload)["stage6"]
        feedback_stage6 = run_internal_chain(feedback_payload)["stage6"]
        base_carrier = self._carrier(base_stage6)
        feedback_carrier = self._carrier(feedback_stage6)

        self.assertEqual(
            feedback_stage6.record("project_fact").data,
            base_stage6.record("project_fact").data,
        )
        self.assertEqual(
            feedback_carrier["source_object_refs"],
            base_carrier["source_object_refs"],
        )
        forbidden_feedback_fields = {
            "outcome_family",
            "outcome_reason_tags",
            "governance_feedback_event_id",
            "feedback_reason",
            "is_false_positive",
        }
        self.assertTrue(
            forbidden_feedback_fields.isdisjoint(feedback_stage6.record("project_fact").data)
        )
        self.assertTrue(forbidden_feedback_fields.isdisjoint(feedback_carrier["source_object_refs"]))
        self.assertEqual(
            feedback_carrier["audit_readback_summary"]["stage9_feedback_writeback_policy"],
            "trace_only_not_stage6_formal_fact_input",
        )

    def test_real_public_rule_evidence_readback_enters_stage6_product_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            verification = _real_public_stage4_verification(tmp_dir=tmp_dir)
            base_stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
            stage5 = Stage5Service().run_public_verification_readback(
                base_stage4,
                verification,
                requested_rule_codes=["DOC-001"],
            )
            stage6 = Stage6Service().run_real_public_rule_evidence_readback(stage5)

        carrier = self._carrier(stage6)
        source_refs = carrier["source_object_refs"]
        self.assertEqual(carrier["product_package_readiness"], "INTERNAL_READY")
        self.assertEqual(
            source_refs["stage4_public_verification_run_id_optional"],
            verification["verification_run_id"],
        )
        self.assertEqual(source_refs["source_snapshot_id_optional"], verification["source_snapshot_id"])
        self.assertEqual(source_refs["input_parse_run_id_optional"], verification["input_parse_run_id"])
        self.assertIn(
            verification["verification_run_id"],
            source_refs["stage4_public_verification_refs_optional"],
        )

        summary = stage6.inputs[Stage6Service.REAL_PUBLIC_STAGE6_READBACK_KEY]
        self.assertEqual(summary, stage6.handoff[Stage6Service.REAL_PUBLIC_STAGE6_READBACK_KEY])
        self.assertEqual(summary["readback_state"], "READBACK_READY")
        self.assertEqual(summary["real_public_product_package_chain_state"], "INTERNAL_READY")
        self.assertEqual(summary["stage5_rule_gate_status"], "PASS")
        self.assertEqual(summary["stage5_evidence_gate_status"], "PASS")
        self.assertEqual(summary["source_refs"]["verification_run_id"], verification["verification_run_id"])
        self.assertEqual(summary["source_refs"]["source_snapshot_id"], verification["source_snapshot_id"])
        self.assertEqual(summary["fail_closed_reasons"], [])
        self.assertFalse(summary["customer_visible_material_generated"])
        self.assertFalse(summary["external_release_enabled"])
        self.assertFalse(summary["stage7_stage8_stage9_execution_triggered"])
        self.assertFalse(summary["legal_conclusion_generated"])
        closure = stage6.inputs["stage6_review_report_trace"]["stage16_b6_closure_profile"]
        self.assertEqual(closure["closure_state"], "INTERNAL_READY")
        self.assertEqual(closure["public_evidence_readback_state"], "INTERNAL_READY")
        self.assertEqual(closure["dual_gate_chain_state"], "INTERNAL_READY")
        self.assertEqual(closure["stage6_report_state"], "INTERNAL_READY")
        self.assertEqual(closure["review_queue_state"], "INTERNAL_READY")
        self.assertEqual(closure["closure_reasons"], [])
        self.assertFalse(closure["customer_visible"])
        self.assertFalse(closure["legal_conclusion_generated"])
        self.assertFalse(closure["external_release_enabled"])
        self.assertNotIn("sales_lead", stage6.records)
        self.assertNotIn("customer_material", stage6.inputs)

    def test_real_public_rule_evidence_review_fails_closed_before_product_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            verification = _real_public_stage4_verification(
                tmp_dir=tmp_dir,
                profile_id="BEIJING-PLATFORM-HOME",
                target_type="contract_public_info",
                identifier="CONTRACT-PUBLIC-STAGE6-141",
                target_identifier="",
            )
            base_stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
            stage5 = Stage5Service().run_public_verification_readback(
                base_stage4,
                verification,
                requested_rule_codes=["DOC-001"],
            )
            stage6 = Stage6Service().run_real_public_rule_evidence_readback(stage5)

        carrier = self._carrier(stage6)
        summary = stage6.inputs[Stage6Service.REAL_PUBLIC_STAGE6_READBACK_KEY]
        self.assertEqual(verification["verification_result"], "REVIEW_REQUIRED")
        self.assertEqual(carrier["product_package_readiness"], "REVIEW_REQUIRED")
        self.assertEqual(summary["readback_state"], "REVIEW_REQUIRED")
        self.assertEqual(summary["real_public_product_package_chain_state"], "REVIEW_REQUIRED")
        self.assertIn("evidence_gate_status=REVIEW", summary["fail_closed_reasons"])
        self.assertIn("rule_gate_status=REVIEW", summary["fail_closed_reasons"])
        self.assertFalse(summary["customer_visible_material_generated"])
        self.assertFalse(summary["external_release_enabled"])
        self.assertFalse(summary["stage7_stage8_stage9_execution_triggered"])
        self.assertNotIn("customer_material", stage6.inputs)


if __name__ == "__main__":
    unittest.main()
