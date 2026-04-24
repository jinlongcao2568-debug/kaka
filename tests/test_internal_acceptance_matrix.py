from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from shared.pipeline import run_internal_chain


MATRIX_PATH = ROOT / "fixtures" / "internal_acceptance_matrix.json"
REFUND_REDLINE_FIXTURE_PATH = ROOT / "fixtures" / "internal_acceptance_stage9_refund_redline.json"
REQUIRED_TAXONOMY = {
    "happy",
    "blocked",
    "review_hold",
    "reject",
    "reselect",
    "quiet_hours",
    "approval",
    "source_conflict",
    "writeback",
}


def load_matrix() -> dict[str, Any]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def scenario_by_id(matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {scenario["scenario_id"]: scenario for scenario in matrix["scenarios"]}


def build_payload(scenario: dict[str, Any]) -> dict[str, Any]:
    fixture_name = Path(scenario["fixture_ref"]).name
    payload = copy.deepcopy(load_fixture(fixture_name))
    payload.update(scenario.get("payload_overrides", {}))
    return payload


def assert_subset(testcase: unittest.TestCase, expected: dict[str, Any], actual: dict[str, Any]) -> None:
    for key, value in expected.items():
        testcase.assertEqual(actual.get(key), value, key)


class TestInternalAcceptanceMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = load_matrix()
        self.scenarios = scenario_by_id(self.matrix)

    def test_matrix_schema_required_fields_and_offline_policy(self) -> None:
        required_top_level = {
            "metadata",
            "required_scenario_taxonomy",
            "redlines",
            "failure_taxonomy",
            "operator_readback_contract",
            "scenarios",
        }
        self.assertTrue(required_top_level.issubset(self.matrix.keys()))
        self.assertEqual(self.matrix["metadata"]["source_data_class"], "sanitized_offline")
        self.assertFalse(self.matrix["metadata"]["external_live_execution"])
        self.assertEqual(self.matrix["metadata"]["external_release"], "BLOCKED")

        required_scenario_fields = set(self.matrix["operator_readback_contract"]["required_fields"])
        for scenario in self.matrix["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertTrue(required_scenario_fields.issubset(scenario.keys()))
                self.assertEqual(scenario["audit_summary"]["source_data_class"], "sanitized_offline")
                self.assertFalse(scenario["audit_summary"]["external_live_execution"])

    def test_fixture_refs_exist_for_matrix_entries(self) -> None:
        for scenario in self.matrix["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                fixture_ref = scenario["fixture_ref"]
                self.assertIsInstance(fixture_ref, str)
                self.assertTrue((ROOT / fixture_ref).exists(), fixture_ref)
                self.assertTrue(fixture_ref.startswith("fixtures/"))

    def test_scenario_taxonomy_complete(self) -> None:
        declared = set(self.matrix["required_scenario_taxonomy"])
        observed = {scenario["taxonomy"] for scenario in self.matrix["scenarios"]}
        self.assertEqual(declared, REQUIRED_TAXONOMY)
        self.assertTrue(REQUIRED_TAXONOMY.issubset(observed))

    def test_replayable_scenarios_execute_against_runtime(self) -> None:
        replayable = [
            scenario
            for scenario in self.matrix["scenarios"]
            if scenario["replay_status"] == "replayable"
        ]
        self.assertGreaterEqual(len(replayable), len(REQUIRED_TAXONOMY))

        for scenario in replayable:
            with self.subTest(scenario=scenario["scenario_id"]):
                payload = build_payload(scenario)
                for flag_name in scenario.get("input_expectations", {}).get("flags", []):
                    self.assertTrue(payload.get("flags", {}).get(flag_name), flag_name)

                result = run_internal_chain(payload)
                stage7 = result["stage7"]
                stage8 = result["stage8"]
                stage9 = result["stage9"]
                contact_target = stage8.record("contact_target")
                outreach_plan = stage8.record("outreach_plan")
                touch_record = stage8.record("touch_record")
                order_record = stage9.record("order_record")
                payment_record = stage9.record("payment_record")
                delivery_record = stage9.record("delivery_record")
                governance_feedback = stage9.record("governance_feedback_event")

                expected = scenario["expected"]
                assert_subset(
                    self,
                    expected["stage7"],
                    {
                        "saleability_status": stage7.record("saleable_opportunity").get("saleability_status"),
                        "sale_gate_status": stage7.handoff.get("sale_gate_status"),
                    },
                )
                assert_subset(
                    self,
                    expected["stage8"],
                    {
                        "contact_target_status": contact_target.get("contact_target_status"),
                        "requires_manual_review": contact_target.get("requires_manual_review"),
                        "plan_status": outreach_plan.get("plan_status"),
                        "touch_record_state": touch_record.get("touch_record_state"),
                        "execution_compliance_decision": outreach_plan.get("governed_metadata", {}).get(
                            "execution_compliance_decision"
                        ),
                        "next_step_optional": touch_record.get("next_step_optional"),
                        "feedback_reason": touch_record.get("feedback_reason"),
                        "projection_mode": outreach_plan.get("projection_mode"),
                        "requested_delivery_surface": outreach_plan.get("requested_delivery_surface"),
                    },
                )
                assert_subset(
                    self,
                    expected["stage9"],
                    {
                        "commercial_status": order_record.get("commercial_status"),
                        "order_status": order_record.get("order_status"),
                        "payment_status": payment_record.get("payment_status"),
                        "delivery_status": delivery_record.get("delivery_status"),
                        "trigger_type": governance_feedback.get("trigger_type"),
                        "payment_exception_family_optional": payment_record.get(
                            "payment_exception_family_optional"
                        ),
                        "refund_state": payment_record.get("refund_state"),
                        "governed_execution_mode": order_record.get("governed_execution_mode"),
                        "live_execution_enabled": order_record.get("governed_metadata", {}).get(
                            "live_execution_enabled"
                        ),
                    },
                )
                self.assertEqual(
                    stage9.inputs.get("effective_writeback_targets"),
                    expected["writeback"]["effective_writeback_targets"],
                )
                if "stage8_touch_writeback_targets" in expected["writeback"]:
                    self.assertEqual(
                        touch_record.get("writeback_targets"),
                        expected["writeback"]["stage8_touch_writeback_targets"],
                    )

    def test_happy_and_blocked_named_samples_are_replayable(self) -> None:
        for scenario_id in ("happy", "blocked"):
            scenario = self.scenarios[scenario_id]
            with self.subTest(scenario=scenario_id):
                self.assertEqual(scenario["replay_status"], "replayable")
                self.assertEqual(scenario["operator_replay"]["entrypoint"], "run_internal_chain")
                result = run_internal_chain(build_payload(scenario))
                self.assertIn("stage9", result)
                self.assertEqual(
                    result["stage9"].record("order_record").get("governed_execution_mode"),
                    "INTERNAL_GOVERNED",
                )

    def test_refund_redline_dedicated_fixture_replays_through_full_chain(self) -> None:
        scenario = self.scenarios["refund-live-redline"]
        self.assertTrue(REFUND_REDLINE_FIXTURE_PATH.exists())

        fixture = json.loads(REFUND_REDLINE_FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(fixture["source_data_class"], "sanitized_offline")
        self.assertFalse(fixture["external_live_execution"])
        self.assertEqual(fixture["payment_exception_family_optional"], "REFUND_REQUESTED")
        self.assertEqual(fixture["refund_state"], "REQUESTED")

        self.assertEqual(scenario["replay_status"], "replayable")
        self.assertEqual(scenario["replay_mode"], "runtime_replay")
        self.assertEqual(scenario["fixture_ref"], "fixtures/internal_acceptance_stage9_refund_redline.json")
        self.assertEqual(scenario["operator_replay"]["entrypoint"], "run_internal_chain")
        self.assertEqual(scenario["readback"]["execution_state"], "executed_offline")
        self.assertNotIn("blocked_reason", scenario)

        result = run_internal_chain(build_payload(scenario))
        stage9 = result["stage9"]
        self.assertIn("POLICY:emit_decision:payment_exception", stage9.trace_rules)

        for record_name in (
            "order_record",
            "payment_record",
            "delivery_record",
            "opportunity_outcome_event",
            "governance_feedback_event",
        ):
            with self.subTest(record=record_name):
                record = stage9.record(record_name)
                metadata = record.get("governed_metadata", {})
                self.assertEqual(record.get("governed_execution_mode"), "INTERNAL_GOVERNED")
                self.assertFalse(metadata.get("live_execution_enabled"))
                self.assertTrue(metadata.get("projection_only"))
                self.assertTrue(metadata.get("skeleton_only"))

        payment_record = stage9.record("payment_record")
        delivery_record = stage9.record("delivery_record")
        governance_feedback = stage9.record("governance_feedback_event")
        outcome_event = stage9.record("opportunity_outcome_event")

        self.assertEqual(payment_record.get("payment_status"), "REFUND_PENDING")
        self.assertEqual(payment_record.get("payment_exception_family_optional"), "REFUND_REQUESTED")
        self.assertEqual(payment_record.get("refund_state"), "REQUESTED")
        self.assertEqual(payment_record.get("paid_at_optional"), "NOT_PAID")
        self.assertNotEqual(payment_record.get("payment_status"), "REFUNDED")
        self.assertNotEqual(payment_record.get("refund_state"), "COMPLETED")
        self.assertEqual(delivery_record.get("delivery_status"), "NOT_READY")
        self.assertEqual(delivery_record.get("delivered_at_optional"), "NOT_DELIVERED")
        self.assertNotEqual(delivery_record.get("delivery_status"), "DELIVERED")
        self.assertEqual(governance_feedback.get("trigger_type"), "EXCEPTION_TRIGGERED")
        self.assertEqual(outcome_event.get("outcome_family"), "DELIVERY_ABANDONED")
        self.assertEqual(outcome_event.get("outcome_reason_tags"), ["SIGNED"])

        self.assertEqual(self.matrix["metadata"]["external_release"], "BLOCKED")
        self.assertEqual(self.matrix["metadata"]["stage8_real_execution"], "BLOCKED")
        self.assertEqual(self.matrix["metadata"]["stage9_live_payment_delivery_refund"], "BLOCKED")
        self.assertFalse(self.matrix["redlines"]["external_release"]["live_execution_allowed"])
        self.assertFalse(self.matrix["redlines"]["stage8_real_execution"]["live_execution_allowed"])
        self.assertFalse(self.matrix["redlines"]["stage9_live_payment_execution"]["live_execution_allowed"])
        self.assertFalse(self.matrix["redlines"]["stage9_live_delivery_execution"]["live_execution_allowed"])
        self.assertFalse(self.matrix["redlines"]["stage9_live_refund_execution"]["live_execution_allowed"])

    def test_planned_only_scenarios_are_not_live_or_executed(self) -> None:
        planned = [
            scenario
            for scenario in self.matrix["scenarios"]
            if scenario["replay_mode"] == "planned_trace_only"
        ]
        for scenario in planned:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertIn(scenario["replay_status"], {"planned_trace_only", "blocked_by_missing_fixture"})
                self.assertEqual(scenario["operator_replay"]["entrypoint"], "not_executed")
                self.assertEqual(scenario["readback"]["execution_state"], "not_executed")
                self.assertFalse(scenario["audit_summary"]["external_live_execution"])
                self.assertFalse(scenario["expected"]["stage9"]["live_execution_enabled"])
        self.assertFalse(
            any(
                scenario["scenario_id"] == "refund-live-redline"
                and scenario["replay_status"] == "blocked_by_missing_fixture"
                for scenario in self.matrix["scenarios"]
            )
        )

    def test_failure_taxonomy_is_readable_and_referenced(self) -> None:
        taxonomy = {entry["failure_id"]: entry for entry in self.matrix["failure_taxonomy"]}
        self.assertIn("missing_fixture", taxonomy)
        for failure_id, entry in taxonomy.items():
            with self.subTest(failure_id=failure_id):
                for field_name in ("label", "category", "operator_readback", "blocking_scope"):
                    self.assertIsInstance(entry[field_name], str)
                    self.assertTrue(entry[field_name].strip())

        referenced = {
            failure_id
            for scenario in self.matrix["scenarios"]
            for failure_id in scenario["failure_taxonomy_refs"]
        }
        self.assertTrue(referenced.issubset(taxonomy.keys()))

    def test_operator_replay_readback_and_audit_summary_have_stable_structure(self) -> None:
        required_summary = set(self.matrix["operator_readback_contract"]["summary_required_fields"])
        required_audit = set(self.matrix["operator_readback_contract"]["audit_summary_required_fields"])
        for scenario in self.matrix["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertTrue({"entrypoint", "readback_scope", "operator_action"}.issubset(scenario["operator_replay"]))
                self.assertTrue(required_summary.issubset(scenario["readback"]["summary"].keys()))
                self.assertTrue(required_audit.issubset(scenario["audit_summary"].keys()))

    def test_stage8_real_execution_remains_blocked(self) -> None:
        redline = self.matrix["redlines"]["stage8_real_execution"]
        self.assertEqual(redline["status"], "BLOCKED")
        self.assertFalse(redline["live_execution_allowed"])

        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        outreach_plan = stage8.record("outreach_plan")
        self.assertEqual(outreach_plan.get("requested_delivery_surface"), "INTERNAL_OPERATIONS")
        self.assertEqual(outreach_plan.get("projection_mode"), redline["allowed_mode"])
        permission_trace = outreach_plan.get("governed_metadata", {}).get("permission_trace", [])
        stage8_execution = [
            entry for entry in permission_trace if entry.get("capability_family") == "stage8_execution"
        ]
        self.assertTrue(stage8_execution)
        self.assertEqual(stage8_execution[0].get("capability_mode"), "DRY_RUN")

    def test_stage9_payment_delivery_refund_live_remains_blocked(self) -> None:
        for redline_id in (
            "stage9_live_payment_execution",
            "stage9_live_delivery_execution",
            "stage9_live_refund_execution",
        ):
            with self.subTest(redline=redline_id):
                redline = self.matrix["redlines"][redline_id]
                self.assertEqual(redline["status"], "BLOCKED")
                self.assertFalse(redline["live_execution_allowed"])

        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        for record_name in ("order_record", "payment_record", "delivery_record"):
            with self.subTest(record=record_name):
                record = stage9.record(record_name)
                self.assertEqual(record.get("governed_execution_mode"), "INTERNAL_GOVERNED")
                self.assertFalse(record.get("governed_metadata", {}).get("live_execution_enabled"))
                self.assertTrue(record.get("governed_metadata", {}).get("projection_only"))

    def test_external_release_still_blocked(self) -> None:
        redline = self.matrix["redlines"]["external_release"]
        self.assertEqual(redline["status"], "BLOCKED")
        self.assertFalse(redline["live_execution_allowed"])

        repo_status = read_text("control/repo_status.md")
        self.assertIn("External software release remains blocked", repo_status)
        self.assertIn(
            "Stage 9 real payment/delivery/refund remains governed / approval-gated / blocked by default",
            repo_status,
        )


if __name__ == "__main__":
    unittest.main()
