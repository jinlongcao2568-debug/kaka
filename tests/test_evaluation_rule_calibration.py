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

from storage.evaluation_rule_calibration import (  # noqa: E402
    FILE_REVIEW_RULE_CODE,
    TAILORED_REVIEW_RULE_CODE,
    build_evaluation_rule_calibration_manifest,
)


class TestEvaluationRuleCalibration(unittest.TestCase):
    def test_file_review_calibration_passes_complete_attachments_without_quality_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "execution.json"
            _write_execution_manifest(
                path,
                [
                    _execution_item(
                        target_id="REAL-OK",
                        document_counts={"COMPLETE_WITH_ATTACHMENTS": 1},
                        version_counts={"NO_SUPPLEMENT_DETECTED": 1},
                    )
                ],
            )

            result = build_evaluation_rule_calibration_manifest(
                real_sample_execution_manifest_json=path,
                target_backend="json-file",
            )

            self.assertTrue(result["safe_to_execute"])
            item = result["manifest"]["items"][0]
            self.assertEqual(item["file_review_rule_code"], FILE_REVIEW_RULE_CODE)
            self.assertEqual(item["expected_file_review_state"], "PASS")
            self.assertEqual(result["summary"]["file_review_expected_counts"], {"PASS": 1, "REVIEW_REQUIRED": 0})
            self.assertFalse(result["manifest"]["safety"]["stage5_rule_execution_enabled"])

    def test_file_review_calibration_reviews_missing_ocr_unknown_and_version_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "execution.json"
            _write_execution_manifest(
                path,
                [
                    _execution_item(
                        target_id="REAL-REVIEW",
                        state="CAPTURE_PARTIAL_REVIEW",
                        document_counts={"ATTACHMENTS_NOT_CAPTURED_REVIEW": 1},
                        version_counts={"CLARIFICATION_OR_ADDENDUM_PRESENT": 1},
                        ocr_required=2,
                        attachment_missing=1,
                        version_review=1,
                        unknown_count=1,
                        quality_reasons=["unknown_attachment_format"],
                    )
                ],
            )

            result = build_evaluation_rule_calibration_manifest(
                real_sample_execution_manifest_json=path,
                target_backend="json-file",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["expected_file_review_state"], "REVIEW_REQUIRED")
            self.assertIn("target_execution_state=CAPTURE_PARTIAL_REVIEW", item["expected_file_review_reasons"])
            self.assertIn("ocr_required_or_engine_unavailable", item["expected_file_review_reasons"])
            self.assertEqual(result["summary"]["ocr_blocked_count"], 2)
            self.assertEqual(result["summary"]["attachment_missing_count"], 1)
            self.assertEqual(result["summary"]["clarification_version_review_count"], 1)
            self.assertEqual(result["summary"]["unknown_format_count"], 1)
            self.assertEqual(result["summary"]["file_review_expected_counts"], {"PASS": 0, "REVIEW_REQUIRED": 1})

    def test_detail_only_without_declared_attachment_requirement_does_not_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "execution.json"
            _write_execution_manifest(
                path,
                [
                    _execution_item(
                        target_id="REAL-DETAIL-ONLY",
                        document_counts={"DETAIL_ONLY_NO_ATTACHMENTS": 1},
                        version_counts={"NO_SUPPLEMENT_DETECTED": 1},
                    )
                ],
            )

            result = build_evaluation_rule_calibration_manifest(
                real_sample_execution_manifest_json=path,
                target_backend="json-file",
            )

            self.assertEqual(result["manifest"]["items"][0]["expected_file_review_state"], "PASS")

    def test_missing_execution_manifest_fails_closed_without_throwing_in_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = build_evaluation_rule_calibration_manifest(
                real_sample_execution_manifest_json=Path(tmp_dir) / "missing.json",
                target_backend="json-file",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("real_sample_execution_manifest_missing", result["blocking_reasons"])
            self.assertEqual(result["summary"]["target_count"], 0)
            self.assertEqual(result["summary"]["tailored_insufficient_sample_state"], "INSUFFICIENT_SAMPLE")

    def test_tailored_review_calibration_reports_distribution_without_mutating_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "execution.json"
            _write_execution_manifest(
                path,
                [
                    _execution_item(
                        target_id="REAL-TAILORED",
                        document_counts={"COMPLETE_WITH_ATTACHMENTS": 1},
                        version_counts={"NO_SUPPLEMENT_DETECTED": 1},
                        source_text=(
                            "招标文件要求厂家授权、原厂唯一授权、本地社保、本地服务网点、"
                            "CMA检测报告、技术参数精确到小数、主观分45分、现场踏勘回执。"
                        ),
                    )
                ],
            )

            result = build_evaluation_rule_calibration_manifest(
                real_sample_execution_manifest_json=path,
                target_backend="json-file",
            )

            self.assertIn(TAILORED_REVIEW_RULE_CODE, result["manifest"]["calibrated_rule_codes"])
            tailored_item = result["manifest"]["tailored_items"][0]
            self.assertEqual(tailored_item["tailored_review_rule_code"], TAILORED_REVIEW_RULE_CODE)
            self.assertEqual(tailored_item["expected_tailored_review_state"], "REVIEW_REQUIRED")
            self.assertGreaterEqual(tailored_item["tailored_bid_index"], 41)
            self.assertEqual(result["summary"]["tailored_sample_count"], 1)
            self.assertEqual(result["summary"]["tailored_insufficient_sample_state"], "INSUFFICIENT_SAMPLE")
            self.assertFalse(
                result["summary"]["tailored_threshold_recommendation"][
                    "formal_rule_threshold_mutation_enabled"
                ]
            )
            self.assertFalse(result["manifest"]["safety"]["formal_rule_threshold_mutation_enabled"])


def _write_execution_manifest(path: Path, items: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "manifest_id": "EXEC-MANIFEST-001",
                    "manifest_sha256": "abc123",
                    "items": items,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _execution_item(
    *,
    target_id: str,
    state: str = "CAPTURED_WITH_SNAPSHOTS",
    document_counts: dict[str, int] | None = None,
    version_counts: dict[str, int] | None = None,
    ocr_required: int = 0,
    attachment_missing: int = 0,
    version_review: int = 0,
    unknown_count: int = 0,
    quality_reasons: list[str] | None = None,
    source_text: str = "",
) -> dict:
    return {
        "target_id": target_id,
        "document_kind": "tender_file",
        "jurisdiction": "CN-GD",
        "source_profile_id": "TEST-PROFILE",
        "target_execution_state": state,
        "source_text": source_text,
        "detail_snapshot_refs": [
            {
                "snapshot_id": f"{target_id}-DETAIL",
                "source_url": "https://example.test/detail.html",
                "document_completeness_state": next(iter(document_counts or {}), ""),
                "notice_version_chain_state": next(iter(version_counts or {}), ""),
            }
        ],
        "attachment_snapshot_refs": [{"snapshot_id": f"{target_id}-ATT"}],
        "parse_summary": {
            "document_completeness_state_counts": dict(document_counts or {}),
            "notice_version_chain_state_counts": dict(version_counts or {}),
            "ocr_required_count": ocr_required,
            "attachment_ocr_required_count": 0,
            "attachment_missing_review_count": attachment_missing,
            "clarification_version_review_count": version_review,
            "unknown_attachment_count": unknown_count,
            "document_quality_reasons": list(quality_reasons or []),
            "download_archive_quality_reasons": list(quality_reasons or []),
        },
    }


if __name__ == "__main__":
    unittest.main()
