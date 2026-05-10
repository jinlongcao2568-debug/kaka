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

from storage.tailored_review_adjudication import (  # noqa: E402
    CONFIRMED_CLUE,
    INSUFFICIENT_EVIDENCE,
    LIKELY_FALSE_POSITIVE,
    NEEDS_HUMAN_REVIEW,
    build_tailored_review_adjudication_manifest,
)


class TestTailoredReviewAdjudication(unittest.TestCase):
    def test_extracts_nine_triggered_samples_stably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            calibration_path = Path(tmp_dir) / "calibration.json"
            execution_path = Path(tmp_dir) / "execution.json"
            triggered = [
                _calibration_item(
                    target_id=f"REAL-TRIGGER::{index}",
                    index=12,
                    risk_level="LOW",
                    expected_state="REVIEW_REQUIRED",
                    document_kind="candidate_notice",
                    signal_families={"qualification_customization": 1},
                )
                for index in range(9)
            ]
            pass_item = _calibration_item(
                target_id="REAL-PASS::1",
                index=0,
                risk_level="NO_SIGNAL",
                expected_state="PASS",
            )
            _write_calibration_manifest(
                calibration_path,
                tailored_items=triggered + [pass_item],
                tailored_sample_count=66,
            )
            _write_execution_manifest(
                execution_path,
                [_project_item(target_id=f"REAL-TRIGGER::{index}", document_kind="candidate_notice") for index in range(9)]
                + [_project_item(target_id="REAL-PASS::1")],
            )

            result = build_tailored_review_adjudication_manifest(
                rule_calibration_manifest_json=calibration_path,
                real_sample_execution_manifest_json=execution_path,
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["triggered_sample_count"], 9)
            self.assertEqual(result["summary"]["review_sample_count"], 9)
            self.assertEqual(result["manifest"]["items"][0]["target_id"], "REAL-TRIGGER::0")
            self.assertEqual(result["manifest"]["items"][-1]["target_id"], "REAL-TRIGGER::8")
            self.assertFalse(result["summary"]["formal_rule_threshold_mutation_enabled"])

    def test_classifies_confirmed_false_positive_insufficient_and_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            calibration_path = Path(tmp_dir) / "calibration.json"
            execution_path = Path(tmp_dir) / "execution.json"
            _write_calibration_manifest(
                calibration_path,
                tailored_items=[
                    _calibration_item(
                        target_id="REAL-CONFIRMED",
                        index=45,
                        risk_level="MEDIUM_CLUE_REVIEW",
                        signal_families={"authorization_binding": 1},
                    ),
                    _calibration_item(
                        target_id="REAL-MISMATCH",
                        index=21,
                        risk_level="WEAK_CLUE_REVIEW",
                        expected_reasons=["observable_mismatch:TAILORED-SIGNAL-0004"],
                        signal_families={"performance_personnel_binding": 1},
                    ),
                    _calibration_item(
                        target_id="REAL-PARTIAL",
                        index=21,
                        risk_level="WEAK_CLUE_REVIEW",
                        signal_families={"technical_parameter_customization": 1},
                        ai_reasons=["document_completeness_state=PARTIAL_REVIEW_REQUIRED"],
                    ),
                    _calibration_item(
                        target_id="REAL-HUMAN",
                        index=12,
                        risk_level="LOW",
                        signal_families={"qualification_customization": 1},
                    ),
                ],
                tailored_sample_count=66,
            )
            _write_execution_manifest(
                execution_path,
                [
                    _project_item(
                        target_id="REAL-CONFIRMED",
                        source_text="招标文件要求投标时提供厂家授权和原厂售后承诺。",
                    ),
                    _project_item(
                        target_id="REAL-MISMATCH",
                        document_kind="candidate_notice",
                        source_text="中标候选人公示出现人员业绩描述。",
                    ),
                    _project_item(
                        target_id="REAL-PARTIAL",
                        document_counts={"PARTIAL_REVIEW_REQUIRED": 1},
                        attachment_missing=1,
                    ),
                    _project_item(
                        target_id="REAL-HUMAN",
                        source_text="资格条件包含证书要求，是否必要需要人工判断行业背景。",
                    ),
                ],
            )

            result = build_tailored_review_adjudication_manifest(
                rule_calibration_manifest_json=calibration_path,
                real_sample_execution_manifest_json=execution_path,
            )

            dispositions = {
                item["target_id"]: item["review_disposition"]
                for item in result["manifest"]["items"]
            }
            self.assertEqual(dispositions["REAL-CONFIRMED"], CONFIRMED_CLUE)
            self.assertEqual(dispositions["REAL-MISMATCH"], LIKELY_FALSE_POSITIVE)
            self.assertEqual(dispositions["REAL-PARTIAL"], INSUFFICIENT_EVIDENCE)
            self.assertEqual(dispositions["REAL-HUMAN"], NEEDS_HUMAN_REVIEW)
            self.assertEqual(
                result["summary"]["recommended_next_action"],
                "MANUAL_REVIEW_BEFORE_WEIGHT_MUTATION",
            )

    def test_insufficient_sample_keeps_review_package_but_blocks_threshold_advice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            calibration_path = Path(tmp_dir) / "calibration.json"
            execution_path = Path(tmp_dir) / "execution.json"
            _write_calibration_manifest(
                calibration_path,
                tailored_items=[
                    _calibration_item(
                        target_id="REAL-ONE",
                        index=21,
                        risk_level="WEAK_CLUE_REVIEW",
                    )
                ],
                tailored_sample_count=12,
                sample_state="INSUFFICIENT_SAMPLE",
            )
            _write_execution_manifest(execution_path, [_project_item(target_id="REAL-ONE")])

            result = build_tailored_review_adjudication_manifest(
                rule_calibration_manifest_json=calibration_path,
                real_sample_execution_manifest_json=execution_path,
            )

            self.assertEqual(result["summary"]["review_sample_count"], 1)
            self.assertEqual(
                result["summary"]["threshold_advice_state"],
                "INSUFFICIENT_SAMPLE_NO_THRESHOLD_ADVICE",
            )
            self.assertFalse(result["summary"]["formal_seed_weight_mutation_enabled"])

    def test_report_keeps_internal_safety_boundaries_and_omits_prohibited_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            calibration_path = Path(tmp_dir) / "calibration.json"
            execution_path = Path(tmp_dir) / "execution.json"
            _write_calibration_manifest(
                calibration_path,
                tailored_items=[
                    _calibration_item(
                        target_id="REAL-SAFE",
                        index=21,
                        risk_level="WEAK_CLUE_REVIEW",
                    )
                ],
                tailored_sample_count=66,
            )
            _write_execution_manifest(execution_path, [_project_item(target_id="REAL-SAFE")])

            result = build_tailored_review_adjudication_manifest(
                rule_calibration_manifest_json=calibration_path,
                real_sample_execution_manifest_json=execution_path,
            )
            report_text = json.dumps(result["manifest"], ensure_ascii=False)

            self.assertFalse(result["manifest"]["safety"]["customer_visible_allowed"])
            self.assertFalse(result["manifest"]["safety"]["formal_rule_threshold_mutation_enabled"])
            self.assertTrue(result["manifest"]["safety"]["no_legal_conclusion"])
            for term in ["已内定", "违法成立", "控标成立", "必然废标"]:
                self.assertNotIn(term, report_text)


def _write_calibration_manifest(
    path: Path,
    *,
    tailored_items: list[dict],
    tailored_sample_count: int,
    sample_state: str = "SAMPLE_READY",
) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "manifest_id": "CAL-MANIFEST-001",
                    "tailored_items": tailored_items,
                    "summary": {
                        "tailored_sample_count": tailored_sample_count,
                        "tailored_insufficient_sample_state": sample_state,
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_execution_manifest(path: Path, project_sample_items: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "manifest_id": "REAL-MANIFEST-001",
                    "project_sample_items": project_sample_items,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _calibration_item(
    *,
    target_id: str,
    index: int,
    risk_level: str,
    expected_state: str = "REVIEW_REQUIRED",
    document_kind: str = "tender_file",
    signal_families: dict[str, int] | None = None,
    ai_reasons: list[str] | None = None,
    expected_reasons: list[str] | None = None,
) -> dict:
    return {
        "target_id": target_id,
        "parent_target_id": "PARENT",
        "candidate_key": target_id.rsplit("::", 1)[-1],
        "project_id": f"PROJ-{target_id}",
        "project_name": f"测试项目 {target_id}",
        "source_url": f"https://example.test/{target_id}.html",
        "document_kind": document_kind,
        "jurisdiction": "CN-ZJ",
        "source_profile_id": "TEST-SOURCE",
        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
        "failure_taxonomy": [],
        "tailored_bid_index": index,
        "tailored_bid_risk_level": risk_level,
        "tailored_bid_sub_indices": {"qualification_customization_index": index},
        "tailored_bid_signal_count": sum(dict(signal_families or {"qualification_customization": 1}).values()),
        "tailored_bid_counter_reason_count": 0,
        "tailored_bid_ai_review_required": expected_state == "REVIEW_REQUIRED",
        "tailored_bid_stage5_review_required": expected_state == "REVIEW_REQUIRED",
        "tailored_bid_evidence_state": "COMPLETE_EVIDENCE",
        "tailored_bid_ai_review_reasons": list(ai_reasons or []),
        "tailored_bid_signal_families": dict(signal_families or {"qualification_customization": 1}),
        "expected_tailored_review_state": expected_state,
        "expected_tailored_review_reasons": list(expected_reasons or []),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_item(
    *,
    target_id: str,
    document_kind: str = "tender_file",
    source_text: str = "招标文件资格条件、评分办法和技术参数可解析。",
    document_counts: dict[str, int] | None = None,
    attachment_missing: int = 0,
) -> dict:
    return {
        "target_id": target_id,
        "parent_target_id": "PARENT",
        "candidate_key": target_id.rsplit("::", 1)[-1],
        "project_id": f"PROJ-{target_id}",
        "project_name": f"测试项目 {target_id}",
        "source_url": f"https://example.test/{target_id}.html",
        "document_kind": document_kind,
        "jurisdiction": "CN-ZJ",
        "source_profile_id": "TEST-SOURCE",
        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
        "source_text": source_text,
        "failure_taxonomy": [],
        "detail_snapshot_refs": [
            {
                "snapshot_id": f"{target_id}-DETAIL",
                "source_url": f"https://example.test/{target_id}.html",
                "document_completeness_state": next(iter(document_counts or {"COMPLETE_WITH_ATTACHMENTS": 1})),
                "notice_version_chain_state": "NO_SUPPLEMENT_DETECTED",
            }
        ],
        "attachment_snapshot_refs": [{"snapshot_id": f"{target_id}-ATT"}],
        "parse_summary": {
            "document_completeness_state_counts": dict(document_counts or {"COMPLETE_WITH_ATTACHMENTS": 1}),
            "notice_version_chain_state_counts": {"NO_SUPPLEMENT_DETECTED": 1},
            "attachment_missing_review_count": attachment_missing,
            "ocr_required_count": 0,
            "attachment_ocr_required_count": 0,
            "text_probe": source_text,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
