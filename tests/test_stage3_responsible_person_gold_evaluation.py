from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage3_parsing.responsible_person_identity import (  # noqa: E402
    assess_responsible_person_name,
)
from storage.stage3_responsible_person_gold_evaluation import (  # noqa: E402
    build_stage3_responsible_person_gold_evaluation,
)


GOLDEN_SET = ROOT / "contracts" / "evaluation" / "stage3_responsible_person_golden_set.json"


class Stage3ResponsiblePersonGoldEvaluationTests(unittest.TestCase):
    def test_repository_golden_set_passes_per_field_precision_recall_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = build_stage3_responsible_person_gold_evaluation(
                golden_set_json=GOLDEN_SET,
                output_root=tmp_dir,
                created_at="2026-07-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertTrue(result["evaluation_passed"])
            self.assertEqual(result["summary"]["case_count"], 5)
            self.assertEqual(result["summary"]["regression_error_count"], 0)
            self.assertFalse(result["summary"]["external_second_review_complete"])
            for metric in result["summary"]["field_metrics"].values():
                self.assertEqual(metric["precision"], 1.0)
                self.assertEqual(metric["recall"], 1.0)
                self.assertEqual(metric["threshold_state"], "PASSED")
            output_root = Path(tmp_dir)
            self.assertTrue(
                (output_root / "stage3-responsible-person-golden-evaluation.json").exists()
            )
            self.assertTrue((output_root / "regression-error-samples.json").exists())
            self.assertTrue((output_root / "summary.md").exists())

    def test_metric_failure_is_written_as_machine_readable_regression_error(self) -> None:
        contract = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
        contract["cases"][0]["expected"]["responsible_person"].append("不存在的人名")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            broken_contract = root / "broken-golden.json"
            broken_contract.write_text(
                json.dumps(contract, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = build_stage3_responsible_person_gold_evaluation(
                golden_set_json=broken_contract,
                output_root=root / "out",
                created_at="2026-07-20T00:00:00+08:00",
            )

            self.assertFalse(result["evaluation_passed"])
            self.assertIn(
                "responsible_person",
                result["summary"]["failed_metric_fields"],
            )
            errors = json.loads(
                (root / "out" / "regression-error-samples.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertGreater(errors["summary"]["error_sample_count"], 0)
            self.assertEqual(errors["items"][0]["field_name"], "responsible_person")

    def test_rejected_and_low_confidence_identity_both_fail_closed_to_review(self) -> None:
        rejected = assess_responsible_person_name("达到", confidence=0.95)
        low_confidence = assess_responsible_person_name("张建明", confidence=0.62)

        self.assertFalse(rejected.accepted)
        self.assertTrue(rejected.review_required)
        self.assertEqual(rejected.quality_state, "REJECTED_NON_PERSON_TOKEN")
        self.assertTrue(low_confidence.accepted)
        self.assertTrue(low_confidence.review_required)


if __name__ == "__main__":
    unittest.main()
