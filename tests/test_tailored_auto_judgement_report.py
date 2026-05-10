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

from storage.tailored_auto_judgement_report import (  # noqa: E402
    build_tailored_auto_judgement_report_manifest,
)


class TestTailoredAutoJudgementReport(unittest.TestCase):
    def test_sample_ready_with_50_project_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            project_items = [
                _project_item(
                    target_id=f"REAL-AUTO-{idx:03d}",
                    source_text="资格条件\n投标人须提供厂家授权、本地社保和本地服务网点证明。",
                )
                for idx in range(50)
            ]
            _write_execution_manifest(execution_path, project_items)
            _write_calibration_manifest(calibration_path, project_items, tailored_sample_count=50)

            result = build_tailored_auto_judgement_report_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                created_at="2026-05-09T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["sample_state"], "SAMPLE_READY")
            self.assertEqual(result["summary"]["sample_count"], 50)
            self.assertEqual(
                result["summary"]["system_judgement_state_counts"]["RISK_CLUE_DETECTED"],
                50,
            )
            self.assertFalse(result["summary"]["formal_rule_threshold_mutation_enabled"])
            self.assertFalse(result["manifest"]["safety"]["customer_visible_allowed"])

    def test_insufficient_sample_when_fewer_than_50(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            project_items = [
                _project_item(target_id="REAL-AUTO-LOW", source_text="普通公告文本。")
            ]
            _write_execution_manifest(execution_path, project_items)
            _write_calibration_manifest(calibration_path, project_items, tailored_sample_count=1)

            result = build_tailored_auto_judgement_report_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                created_at="2026-05-09T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["sample_state"], "INSUFFICIENT_SAMPLE")
            self.assertEqual(result["summary"]["sample_count"], 1)

    def test_multi_indices_enter_judgement_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            project_items = [
                _project_item(
                    target_id="REAL-AUTO-TAILORED",
                    source_text="资格条件\n投标人须提供厂家授权、本地社保和现场踏勘回执。",
                ),
                _project_item(
                    target_id="REAL-AUTO-COLLUSION",
                    source_text="投诉材料显示存在围标、串标、串通投标、同一IP、同一CA。",
                    document_kind="complaint_decision",
                    input_observable_from=["complaint_case", "post_award_notice", "internal_material"],
                    calibration_indices={"bid_rigging_index": 30},
                ),
                _project_item(
                    target_id="REAL-AUTO-COVER",
                    source_text="历史公告显示陪标、护航报价、凑三家、异常高价护航。",
                    document_kind="candidate_notice",
                    input_observable_from=["complaint_case", "post_award_notice", "internal_material"],
                ),
                _project_item(
                    target_id="REAL-AUTO-FATAL",
                    source_text="废标条款\n投标保证金错误、投标有效期不足、签字盖章缺失均为无效投标。",
                ),
            ]
            _write_execution_manifest(execution_path, project_items)
            _write_calibration_manifest(calibration_path, project_items, tailored_sample_count=50)

            result = build_tailored_auto_judgement_report_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                created_at="2026-05-09T00:00:00+08:00",
            )

            items = {item["target_id"]: item for item in result["manifest"]["items"]}
            self.assertGreaterEqual(items["REAL-AUTO-TAILORED"]["tailored_bid_index"], 21)
            self.assertGreaterEqual(items["REAL-AUTO-COLLUSION"]["bid_rigging_index"], 21)
            self.assertGreaterEqual(items["REAL-AUTO-COVER"]["cover_bid_index"], 21)
            self.assertGreaterEqual(
                items["REAL-AUTO-FATAL"]["fatal_rejection_complexity_index"],
                21,
            )
            self.assertIn("控标风险线索", items["REAL-AUTO-TAILORED"]["primary_allowed_terms"])
            self.assertIn("围标线索", items["REAL-AUTO-COLLUSION"]["primary_allowed_terms"])
            self.assertIn("串标线索", items["REAL-AUTO-COLLUSION"]["primary_allowed_terms"])
            self.assertIn("陪标线索", items["REAL-AUTO-COVER"]["primary_allowed_terms"])
            self.assertIn("废标风险线索", items["REAL-AUTO-FATAL"]["primary_allowed_terms"])

    def test_evidence_blocker_sets_retry_parse_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            project_items = [
                _project_item(
                    target_id="REAL-AUTO-BLOCKED",
                    source_text="资格条件\n投标人须提供厂家授权。",
                    document_counts={"PARTIAL_REVIEW_REQUIRED": 1},
                    ocr_required_count=1,
                    attachment_missing_review_count=1,
                    failure_taxonomy=["detail_body_too_small", "http_status:502"],
                )
            ]
            _write_execution_manifest(execution_path, project_items)
            _write_calibration_manifest(calibration_path, project_items, tailored_sample_count=50)

            result = build_tailored_auto_judgement_report_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                created_at="2026-05-09T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["system_judgement_state"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual(item["recommended_system_action"], "EVIDENCE_BLOCKED_RETRY_PARSE")
            self.assertIn(
                "document_completeness_state=PARTIAL_REVIEW_REQUIRED",
                item["evidence_status"]["evidence_blocker_reasons"],
            )

    def test_section_guardrail_keeps_hit_without_caution_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            project_items = [
                _project_item(
                    target_id="REAL-AUTO-GUARDRAIL",
                    source_text="合同付款\n付款时需提供厂家授权和本地社保证明。",
                    document_kind="tender_file",
                )
            ]
            _write_execution_manifest(execution_path, project_items)
            _write_calibration_manifest(calibration_path, project_items, tailored_sample_count=50)

            result = build_tailored_auto_judgement_report_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                created_at="2026-05-09T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["tailored_bid_index"], 0)
            self.assertGreater(item["tailored_bid_signal_count"], 0)
            self.assertEqual(item["system_judgement_state"], "WEAK_SIGNAL_ONLY")
            self.assertEqual(item["recommended_system_action"], "TRACK_LOW_PRIORITY")
            self.assertGreater(item["section_guardrail_blocked_count"], 0)

    def test_optional_inputs_missing_fail_closed_without_blocking_required_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            project_items = [_project_item(target_id="REAL-AUTO-OPTIONAL")]
            _write_execution_manifest(execution_path, project_items)
            _write_calibration_manifest(calibration_path, project_items, tailored_sample_count=50)

            result = build_tailored_auto_judgement_report_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                tailored_review_adjudication_json=Path(tmp_dir) / "missing-adjudication.json",
                markitdown_replay_impact_json=Path(tmp_dir) / "missing-markitdown.json",
                created_at="2026-05-09T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(
                result["manifest"]["optional_input_states"]["tailored_review_adjudication"],
                "MISSING_OPTIONAL",
            )
            self.assertEqual(
                result["manifest"]["optional_input_states"]["markitdown_replay_impact"],
                "MISSING_OPTIONAL",
            )

    def test_report_does_not_embed_forbidden_legal_conclusion_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            project_items = [
                _project_item(
                    target_id="REAL-AUTO-FORBIDDEN",
                    source_text="资格条件\n厂家授权、本地社保、检测报告。",
                )
            ]
            _write_execution_manifest(execution_path, project_items)
            _write_calibration_manifest(calibration_path, project_items, tailored_sample_count=50)

            result = build_tailored_auto_judgement_report_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                created_at="2026-05-09T00:00:00+08:00",
            )

            report_text = json.dumps(result["manifest"], ensure_ascii=False)
            for forbidden in ("已内定", "违法成立", "控标成立", "必然废标"):
                self.assertNotIn(forbidden, report_text)


def _write_execution_manifest(path: Path, project_items: list[dict[str, object]]) -> None:
    payload = {
        "manifest": {
            "manifest_id": "REAL-SAMPLE-EXECUTION-TEST",
            "project_sample_items": project_items,
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_calibration_manifest(
    path: Path,
    project_items: list[dict[str, object]],
    *,
    tailored_sample_count: int,
) -> None:
    tailored_items = [
        {
            "target_id": str(item["target_id"]),
            "parent_target_id": item.get("parent_target_id", ""),
            "candidate_key": item.get("candidate_key", ""),
            "project_id": item.get("project_id", ""),
            "project_name": item.get("project_name", ""),
            "document_kind": item.get("document_kind", "tender_file"),
            "jurisdiction": item.get("jurisdiction", "广东"),
            "source_profile_id": item.get("source_profile_id", "GUANGZHOU-TRADING-GROUP"),
            "tailored_bid_index": 0,
            "bid_rigging_index": dict(item.get("calibration_indices") or {}).get("bid_rigging_index", 0),
            "cover_bid_index": dict(item.get("calibration_indices") or {}).get("cover_bid_index", 0),
            "collusion_trace_index": dict(item.get("calibration_indices") or {}).get("collusion_trace_index", 0),
            "fatal_rejection_complexity_index": dict(item.get("calibration_indices") or {}).get(
                "fatal_rejection_complexity_index",
                0,
            ),
            "electronic_supervision_index": dict(item.get("calibration_indices") or {}).get(
                "electronic_supervision_index",
                0,
            ),
            "tailored_bid_signal_count": 0,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for item in project_items
    ]
    payload = {
        "manifest": {
            "manifest_id": "FILE-RULE-CALIBRATION-TEST",
            "tailored_items": tailored_items,
            "summary": {
                "tailored_sample_count": tailored_sample_count,
                "tailored_insufficient_sample_state": (
                    "SAMPLE_READY" if tailored_sample_count >= 50 else "INSUFFICIENT_SAMPLE"
                ),
            },
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _project_item(
    *,
    target_id: str,
    source_text: str = "普通招标公告。",
    document_kind: str = "tender_file",
    input_observable_from: list[str] | None = None,
    document_counts: dict[str, int] | None = None,
    ocr_required_count: int = 0,
    attachment_missing_review_count: int = 0,
    failure_taxonomy: list[str] | None = None,
    calibration_indices: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "target_id": target_id,
        "parent_target_id": "TARGET-AUTO-JUDGEMENT",
        "candidate_key": target_id,
        "project_id": target_id.replace("REAL-", "PROJ-"),
        "project_name": f"{target_id} 招标项目",
        "source_url": f"https://example.test/{target_id}.html",
        "document_kind": document_kind,
        "jurisdiction": "广东",
        "source_profile_id": "GUANGZHOU-TRADING-GROUP",
        "target_execution_state": "CAPTURE_OK",
        "source_text": source_text,
        "input_observable_from": input_observable_from or ["tender_file"],
        "failure_taxonomy": failure_taxonomy or [],
        "calibration_indices": calibration_indices or {},
        "parse_summary": {
            "text_probe": source_text,
            "document_completeness_state_counts": document_counts or {"COMPLETE_WITH_ATTACHMENTS": 1},
            "notice_version_chain_state_counts": {"NO_SUPPLEMENT_DETECTED": 1},
            "ocr_required_count": ocr_required_count,
            "attachment_ocr_required_count": 0,
            "attachment_missing_review_count": attachment_missing_review_count,
        },
    }


if __name__ == "__main__":
    unittest.main()
