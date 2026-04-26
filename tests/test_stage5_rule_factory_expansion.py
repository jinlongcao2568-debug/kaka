from __future__ import annotations

import json
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
from shared.contracts_runtime import StageBundle
from shared.pipeline import run_internal_chain
from stage5_rules_evidence.service import Stage5Service


def load_rule_catalog() -> dict[str, object]:
    return json.loads((ROOT / "contracts/rules/rule_catalog.json").read_text(encoding="utf-8"))


def stage4_bundle_with_inputs(extra_inputs: dict[str, object]) -> StageBundle:
    stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
    return StageBundle(
        stage=4,
        records=dict(stage4.records),
        handoff=dict(stage4.handoff),
        trace_rules=list(stage4.trace_rules),
        inputs={**stage4.inputs, **extra_inputs},
    )


class Stage5RuleFactoryExpansionTests(unittest.TestCase):
    def test_catalog_registers_stage5_factory_metadata(self) -> None:
        catalog = load_rule_catalog()
        factory = catalog["stage5_rule_factory"]
        bindings = factory["rule_bindings"]

        self.assertEqual(catalog["version"], "0.1.7")
        self.assertEqual(factory["state"], "INTERNAL_READY")
        self.assertEqual(factory["runtime_entrypoint"], "RuleEvidenceEngine")
        self.assertEqual(factory["runtime_components"], ["RuleRunner", "EvidenceBuilder", "GateEvaluator"])
        self.assertEqual(factory["selection_policy"]["stage"], 5)
        self.assertEqual(factory["selection_policy"]["default_selection_limit"], 3)
        for rule_code in ("PROC-001", "PROC-002", "DOC-001", "PM-002"):
            binding = bindings[rule_code]
            self.assertTrue(binding["enabled"])
            self.assertEqual(binding["version"], "stage5-factory-v1")
            self.assertTrue(binding["dependency_fields"])
            self.assertTrue(binding["dependency_evidence"])
            self.assertTrue(binding["golden_case_refs"])
        self.assertFalse(bindings["GOV-004"]["enabled"])
        self.assertTrue(factory["golden_cases"])

    def test_catalog_aware_selection_execution_trace_and_coverage(self) -> None:
        stage5 = Stage5Service().run(run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"])

        selection_trace = stage5.inputs["stage5_rule_selection_trace"]
        execution_trace = stage5.inputs["stage5_rule_execution_trace"]
        coverage = stage5.inputs["stage5_rule_coverage_summary"]
        readback = stage5.inputs["stage5_rule_readback_summary"]

        self.assertEqual(stage5.inputs["stage5_rule_codes"], ["PROC-001", "PROC-002", "DOC-001"])
        self.assertEqual(
            [entry["rule_code"] for entry in execution_trace],
            ["PROC-001", "PROC-002", "DOC-001"],
        )
        selected = [entry for entry in selection_trace if entry["selected"]]
        self.assertEqual([entry["reason"] for entry in selected], ["selected_catalog_priority"] * 3)
        win_trace = next(entry for entry in selection_trace if entry["rule_code"] == "WIN-001")
        self.assertEqual(win_trace["reason"], "skipped_by_priority_limit")
        disabled_trace = next(entry for entry in selection_trace if entry["rule_code"] == "GOV-004")
        self.assertEqual(disabled_trace["reason"], "catalog_disabled")

        for entry in execution_trace:
            self.assertEqual(
                set(
                    [
                        "rule_code",
                        "rule_name",
                        "version",
                        "selected_reason",
                        "upstream_objects",
                        "dependency_fields",
                        "dependency_evidence",
                        "evidence_refs",
                        "confidence",
                        "rule_gate_status",
                        "rule_hit_state",
                        "blocking_reasons",
                    ]
                ).issubset(entry),
                True,
            )
            self.assertEqual(entry["rule_gate_status"], "PASS")
            self.assertEqual(entry["rule_hit_state"], "CONFIRMED")
            self.assertEqual(entry["evidence_refs"], [stage5.record("evidence").get("evidence_id")])
            self.assertGreaterEqual(entry["confidence"], 0.6)
            self.assertTrue(entry["golden_case_refs"])

        self.assertEqual(coverage["selected_count"], 3)
        self.assertGreater(coverage["skipped_count"], 0)
        self.assertGreaterEqual(coverage["disabled_count"], 1)
        self.assertGreater(coverage["unsupported_count"], 0)
        self.assertEqual(coverage["pass_count"], 3)
        self.assertEqual(coverage["review_count"], 0)
        self.assertEqual(coverage["block_count"], 0)
        self.assertEqual(readback["rule_gate_decision_id"], stage5.record("rule_gate_decision").get("gate_id"))
        self.assertEqual(readback["evidence_gate_decision_id"], stage5.record("evidence_gate_decision").get("gate_id"))
        self.assertTrue(readback["golden_case_refs"])

    def test_requested_116a_active_conflict_rule_degrades_to_review_with_evidence_binding(self) -> None:
        active_conflict_readback = {
            "readback_state": "READBACK_READY",
            "replayable": True,
            "fail_closed": False,
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
            "missing_required_fields": [],
            "active_conflict_run_id": "PMAC-RUN-001",
            "overlap_judgement": "OVERLAP_RISK",
            "review_required": True,
        }
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["PM-002"],
                "stage5_supported_upstream_objects": [
                    "project_manager",
                    "focus_bidder_verification_profile",
                ],
                "project_manager_active_conflict_readback": active_conflict_readback,
            }
        )

        stage5 = Stage5Service().run(stage4)
        execution_trace = stage5.inputs["stage5_rule_execution_trace"]
        pm_trace = execution_trace[0]

        self.assertEqual(stage5.inputs["stage5_rule_codes"], ["PM-002"])
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "PASS")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertEqual(stage5.record("review_request").get("target_object_type"), "rule_hit")
        self.assertEqual(pm_trace["rule_code"], "PM-002")
        self.assertEqual(pm_trace["selected_reason"], "selected_requested_rule")
        self.assertIn("PMAC-RUN-001", pm_trace["dependency_evidence"])
        self.assertTrue(any("active conflict requires manual review" in reason for reason in pm_trace["blocking_reasons"]))
        self.assertTrue(pm_trace["review_request_target_selected"])
        self.assertNotIn("project_fact", stage5.records)

    def test_missing_dependency_fails_closed_without_bypassing_gates(self) -> None:
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["PM-002"],
                "stage5_supported_upstream_objects": [
                    "project_manager",
                    "focus_bidder_verification_profile",
                ],
            }
        )

        stage5 = Stage5Service().run(stage4)
        pm_selection = next(
            entry for entry in stage5.inputs["stage5_rule_selection_trace"] if entry["rule_code"] == "PM-002"
        )
        pm_execution = stage5.inputs["stage5_rule_execution_trace"][0]

        self.assertEqual(pm_selection["reason"], "selected_requested_fail_closed")
        self.assertIn(
            "project_manager_active_conflict_readback.active_conflict_run_id",
            pm_selection["missing_dependency_fields"],
        )
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "PASS")
        self.assertIn("review_request", stage5.records)
        self.assertTrue(any("missing dependency fields" in reason for reason in pm_execution["blocking_reasons"]))
        self.assertGreaterEqual(stage5.inputs["stage5_rule_coverage_summary"]["missing_dependency_count"], 1)

    def test_version_conflict_fails_closed_to_review(self) -> None:
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["PROC-001"],
                "stage5_rule_version_pins": {"PROC-001": "stage5-factory-v0"},
            }
        )

        stage5 = Stage5Service().run(stage4)
        proc_trace = stage5.inputs["stage5_rule_execution_trace"][0]
        coverage = stage5.inputs["stage5_rule_coverage_summary"]

        self.assertEqual(proc_trace["rule_code"], "PROC-001")
        self.assertEqual(proc_trace["selected_reason"], "selected_requested_fail_closed")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertTrue(any("version conflict expected" in reason for reason in proc_trace["blocking_reasons"]))
        self.assertGreaterEqual(coverage["version_conflict_count"], 1)


if __name__ == "__main__":
    unittest.main()
