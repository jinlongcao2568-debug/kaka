from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))


class TestStage16FileAnalysisTaskContract(unittest.TestCase):
    def test_b0_mapping_and_b7_corpus_prep_are_machine_readable(self) -> None:
        contract = _load_contract()

        self.assertEqual(contract["status"], "P1_STAGE16_B0_MAPPING_AND_B7_CORPUS_PREP_FIRST_CUT")
        batches = {item["batch_id"]: item for item in contract["batches"]}
        self.assertEqual(batches["B0_EXPERIENCE_LIBRARY_MAPPING_BASELINE"]["status"], "FIRST_CUT_IMPLEMENTED")
        self.assertEqual(batches["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["status"], "FIRST_CUT_IMPLEMENTED")

        baseline = contract["runtime_mapping_baseline"]
        self.assertEqual(baseline["status"], "FIRST_CUT_IMPLEMENTED")
        self.assertFalse(baseline["customer_visible"])
        self.assertTrue(baseline["no_formal_schema_or_rule_code_added"])
        self.assertTrue(baseline["no_external_fetch_or_release_enabled"])

        entries = {item["capability_id"]: item for item in baseline["entries"]}
        for capability_id in (
            "B1_LEGAL_SYSTEM_CLASSIFIER",
            "B2_PRE_NOTICE_OPPORTUNITY_POLICY_RULES",
            "B3_AI_INTELLIGENCE_PROJECT_ARCHIVE",
            "B4_DOCUMENT_COMPLETENESS_VERSION_LINEAGE",
            "B5_MAINLINE_RISK_AND_BID_DECISION",
            "B6_PUBLIC_VERIFICATION_DUAL_GATES_REPORT",
            "B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES",
        ):
            self.assertIn(capability_id, entries)
            self.assertEqual(entries[capability_id]["implementation_state"], "FIRST_CUT_IMPLEMENTED")
            self.assertTrue(entries[capability_id]["runtime_entrypoints"])
            self.assertTrue(entries[capability_id]["data_carriers"])
            self.assertTrue(entries[capability_id]["minimum_validation_commands"])

        self.assertIn("src/storage/evaluation_corpus.py", entries["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["runtime_entrypoints"])
        self.assertIn("evaluation_seed_coverage_audit_manifest", entries["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["data_carriers"])
        self.assertIn("B8_PRICE_PERFORMANCE_LOW_BID_RISK", baseline["deferred_boundaries"])
        self.assertIn("B9_BID_DOCUMENT_INTERNAL_QA", baseline["deferred_boundaries"])
        self.assertIn("B10_REMEDY_PERFORMANCE_SETTLEMENT", baseline["deferred_boundaries"])
        self.assertIn("git diff --check", baseline["global_minimum_validation_commands"])


def _load_contract() -> dict:
    return yaml.safe_load(
        (ROOT / "control" / "stage16_file_analysis_task_contract.yaml").read_text(encoding="utf-8")
    )


if __name__ == "__main__":
    unittest.main()
