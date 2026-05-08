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

        self.assertEqual(
            contract["status"],
            "P5_STAGE16_STABILITY_COVERAGE_AND_REVIEW_RULES_FIRST_CUT_IMPLEMENTED",
        )
        batches = {item["batch_id"]: item for item in contract["batches"]}
        self.assertEqual(batches["B0_EXPERIENCE_LIBRARY_MAPPING_BASELINE"]["status"], "FIRST_CUT_IMPLEMENTED")
        self.assertEqual(batches["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["status"], "FIRST_CUT_IMPLEMENTED")

        baseline = contract["runtime_mapping_baseline"]
        self.assertEqual(baseline["status"], "FIRST_CUT_IMPLEMENTED")
        self.assertFalse(baseline["customer_visible"])
        self.assertFalse(baseline["no_formal_schema_or_rule_code_added"])
        self.assertTrue(baseline["no_formal_schema_or_migration_added"])
        self.assertTrue(baseline["stage5_review_rule_codes_added"])
        self.assertTrue(baseline["no_uncontrolled_external_fetch_or_release_enabled"])
        self.assertTrue(baseline["controlled_b7_real_sample_fetch_runner_enabled"])

        entries = {item["capability_id"]: item for item in baseline["entries"]}
        for capability_id in (
            "B1_LEGAL_SYSTEM_CLASSIFIER",
            "B2_PRE_NOTICE_OPPORTUNITY_POLICY_RULES",
            "B3_AI_INTELLIGENCE_PROJECT_ARCHIVE",
            "B4_DOCUMENT_COMPLETENESS_VERSION_LINEAGE",
            "B5_MAINLINE_RISK_AND_BID_DECISION",
            "B6_PUBLIC_VERIFICATION_DUAL_GATES_REPORT",
            "B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES",
            "B8_PRICE_PERFORMANCE_LOW_BID_RISK",
            "B9_BID_DOCUMENT_INTERNAL_QA",
            "B10_REMEDY_PERFORMANCE_SETTLEMENT",
        ):
            self.assertIn(capability_id, entries)
            self.assertEqual(entries[capability_id]["implementation_state"], "FIRST_CUT_IMPLEMENTED")
            self.assertTrue(entries[capability_id]["runtime_entrypoints"])
            self.assertTrue(entries[capability_id]["data_carriers"])
            self.assertTrue(entries[capability_id]["minimum_validation_commands"])

        self.assertIn("src/storage/evaluation_corpus.py", entries["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["runtime_entrypoints"])
        self.assertIn("src/storage/evaluation_real_sample_execution.py", entries["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["runtime_entrypoints"])
        self.assertIn("evaluation_seed_coverage_audit_manifest", entries["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["data_carriers"])
        self.assertIn("evaluation_real_project_sample_execution_manifest", entries["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["data_carriers"])
        self.assertIn("coverage_quality_summary", entries["B7_REVIEW_CORPUS_AND_GOLDEN_SAMPLES"]["data_carriers"])
        self.assertIn("file_analysis_review_summary", entries["B6_PUBLIC_VERIFICATION_DUAL_GATES_REPORT"]["data_carriers"])
        self.assertIn("document_quality_state", entries["B4_DOCUMENT_COMPLETENESS_VERSION_LINEAGE"]["data_carriers"])
        self.assertIn("TAILORED-REVIEW-001", entries["B5_MAINLINE_RISK_AND_BID_DECISION"]["data_carriers"])
        self.assertIn("price_performance_risk_profile", entries["B8_PRICE_PERFORMANCE_LOW_BID_RISK"]["data_carriers"])
        self.assertIn("PRICE-REVIEW-001", entries["B8_PRICE_PERFORMANCE_LOW_BID_RISK"]["data_carriers"])
        self.assertIn("bid_document_internal_qa_profile", entries["B9_BID_DOCUMENT_INTERNAL_QA"]["data_carriers"])
        self.assertIn("src/stage3_parsing/bid_document_qa.py", entries["B9_BID_DOCUMENT_INTERNAL_QA"]["runtime_entrypoints"])
        self.assertIn("remedy_performance_settlement_profile", entries["B10_REMEDY_PERFORMANCE_SETTLEMENT"]["data_carriers"])
        self.assertIn("qualification_legality_risk_hits", entries["B10_REMEDY_PERFORMANCE_SETTLEMENT"]["data_carriers"])
        self.assertIn("REMEDY-REVIEW-001", entries["B10_REMEDY_PERFORMANCE_SETTLEMENT"]["data_carriers"])
        self.assertIn("src/stage3_parsing/remedy_performance.py", entries["B10_REMEDY_PERFORMANCE_SETTLEMENT"]["runtime_entrypoints"])
        self.assertNotIn("B8_PRICE_PERFORMANCE_LOW_BID_RISK", baseline["deferred_boundaries"])
        self.assertNotIn("B9_BID_DOCUMENT_INTERNAL_QA", baseline["deferred_boundaries"])
        self.assertNotIn("B10_REMEDY_PERFORMANCE_SETTLEMENT", baseline["deferred_boundaries"])
        self.assertIn("git diff --check", baseline["global_minimum_validation_commands"])


def _load_contract() -> dict:
    return yaml.safe_load(
        (ROOT / "control" / "stage16_file_analysis_task_contract.yaml").read_text(encoding="utf-8")
    )


if __name__ == "__main__":
    unittest.main()
