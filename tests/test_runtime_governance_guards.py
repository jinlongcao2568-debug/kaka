from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from shared.pipeline import run_internal_chain


class TestRuntimeGovernanceGuards(unittest.TestCase):
    def test_stage8_high_restriction_field_requires_runtime_review(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "person_name_optional": "张三",
                "approval_state": "PENDING",
            }
        )

        result = run_internal_chain(payload)
        stage8 = result["stage8"]

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "REVIEW_REQUIRED")
        self.assertTrue(stage8.record("contact_target").get("requires_manual_review"))
        self.assertEqual(stage8.inputs.get("governance_decision_state"), "REVIEW")
        self.assertIn(
            "contact_target.person_name",
            stage8.inputs.get("governance_additions", {}).get("contact_target", {}).get("field_policy", {}).get("review_fields", []),
        )

    def test_stage8_delivery_matrix_blocks_outreach_plan_on_leadpack_surface(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["requested_delivery_surface"] = "LEADPACK_DELIVERABLE"

        result = run_internal_chain(payload)
        stage8 = result["stage8"]

        self.assertEqual(stage8.record("outreach_plan").get("plan_status"), "BLOCKED")
        self.assertEqual(stage8.inputs.get("governance_decision_state"), "BLOCK")
        self.assertEqual(
            stage8.inputs.get("governance_additions", {}).get("outreach_plan", {}).get("delivery_matrix", {}).get("projection_policies", {}).get("LEADPACK_DELIVERABLE"),
            "BLOCK",
        )

    def test_stage9_delivery_matrix_blocks_direct_leadpack_objects(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["requested_delivery_surface"] = "LEADPACK_DELIVERABLE"

        result = run_internal_chain(payload)
        stage9 = result["stage9"]

        self.assertEqual(stage9.record("order_record").get("order_status"), "ON_HOLD")
        self.assertEqual(stage9.record("delivery_record").get("delivery_status"), "RELEASE_BLOCKED")
        self.assertEqual(stage9.inputs.get("governance_decision_state"), "BLOCK")
        self.assertEqual(
            stage9.inputs.get("governance_additions", {}).get("order_record", {}).get("delivery_matrix", {}).get("projection_policies", {}).get("LEADPACK_DELIVERABLE"),
            "BLOCK",
        )

    def test_stage9_release_gate_is_runtime_consumed(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["release_level"] = "DEV_ALLOWED"

        result = run_internal_chain(payload)
        stage9 = result["stage9"]

        self.assertEqual(stage9.inputs.get("governance_decision_state"), "REVIEW")
        gate_results = stage9.inputs.get("governance_additions", {}).get("order_record", {}).get("release_gates", {}).get("gate_results", [])
        self.assertTrue(any(item.get("gate_id") == "internal_review_release" and item.get("decision_state") == "REVIEW" for item in gate_results))

    def test_stage9_governance_trace_covers_all_runtime_assets(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        governance_trace = stage9.inputs.get("governance_trace", [])
        guarded_objects = {entry.get("object_type") for entry in governance_trace}

        self.assertEqual(
            guarded_objects,
            {
                "order_record",
                "payment_record",
                "delivery_record",
                "opportunity_outcome_event",
                "governance_feedback_event",
            },
        )
        for entry in governance_trace:
            self.assertIn("field_policy", entry)
            self.assertIn("delivery_matrix", entry)
            self.assertIn("release_gates", entry)

    def test_stage9_payment_delivery_refund_live_execution_remains_blocked(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"refund_state": "REQUESTED"})

        stage9 = run_internal_chain(payload)["stage9"]

        for record_name in (
            "order_record",
            "payment_record",
            "delivery_record",
            "opportunity_outcome_event",
            "governance_feedback_event",
        ):
            metadata = stage9.record(record_name).get("governed_metadata", {})
            self.assertEqual(stage9.record(record_name).get("governed_execution_mode"), "INTERNAL_GOVERNED")
            self.assertFalse(metadata.get("live_execution_enabled"))
            self.assertTrue(metadata.get("projection_only"))

        self.assertEqual(stage9.record("payment_record").get("paid_at_optional"), "NOT_PAID")
        self.assertEqual(stage9.record("payment_record").get("refund_state"), "REQUESTED")
        self.assertNotEqual(stage9.record("payment_record").get("refund_state"), "COMPLETED")
        self.assertEqual(stage9.record("delivery_record").get("delivered_at_optional"), "NOT_DELIVERED")
        self.assertNotEqual(stage9.record("delivery_record").get("delivery_status"), "DELIVERED")


if __name__ == "__main__":
    unittest.main()
