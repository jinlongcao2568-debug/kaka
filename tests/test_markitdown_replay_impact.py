from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings  # noqa: E402
from stage3_parsing import markitdown_adapter  # noqa: E402
from storage.db import DatabaseSession  # noqa: E402
from storage.markitdown_replay_impact import (  # noqa: E402
    INSUFFICIENT_REPLAYABLE_SNAPSHOT,
    build_markitdown_replay_impact_manifest,
)
from storage.repositories.object_storage_repo import ObjectStorageRepository  # noqa: E402


DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class TestMarkItDownReplayImpact(unittest.TestCase):
    def test_replay_records_text_qualification_and_tailored_signal_gain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_attachment_snapshot(
                repo,
                snapshot_id="SNAP-MARKITDOWN-GAIN",
                content_type=DOCX_CONTENT_TYPE,
                source_url="https://example.test/tender.docx",
            )
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            _write_execution_manifest(
                execution_path,
                [
                    _project_item(
                        target_id="REAL-MARKITDOWN-GAIN",
                        attachment_snapshot_id="SNAP-MARKITDOWN-GAIN",
                    )
                ],
            )
            _write_calibration_manifest(
                calibration_path,
                [_calibration_item(target_id="REAL-MARKITDOWN-GAIN", index=0, signal_count=0)],
            )
            markitdown_text = (
                "项目名称: MarkItDown附件工程\n"
                "资格条件: 投标时须提供厂家授权、本地社保和检测报告。\n"
                "评分办法: 技术方案主观分占比较高。"
            )

            with patch(
                "stage3_parsing.real_parser.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=markitdown_text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_length=len(markitdown_text),
                    text_probe=markitdown_text,
                ),
            ):
                result = build_markitdown_replay_impact_manifest(
                    real_sample_execution_manifest_json=execution_path,
                    rule_calibration_manifest_json=calibration_path,
                    object_repository=repo,
                    created_at="2026-05-09T00:00:00+08:00",
                )

            summary = result["summary"]
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(summary["project_sample_count"], 1)
            self.assertEqual(summary["replay_attempted_count"], 1)
            self.assertEqual(
                summary["markitdown_state_counts"][markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED],
                1,
            )
            self.assertEqual(summary["attachment_text_gain_count"], 1)
            self.assertGreater(summary["qualification_block_gain_count"], 0)
            self.assertGreater(
                summary["tailored_signal_delta"]["signal_count_delta_sum"],
                0,
            )
            self.assertFalse(summary["formal_rule_threshold_mutation_enabled"])
            self.assertFalse(summary["formal_seed_weight_mutation_enabled"])

    def test_non_tender_document_keeps_hits_but_blocks_formal_index_gain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_attachment_snapshot(
                repo,
                snapshot_id="SNAP-MARKITDOWN-GUARDRAIL",
                content_type=DOCX_CONTENT_TYPE,
                source_url="https://example.test/candidate.docx",
            )
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            _write_execution_manifest(
                execution_path,
                [
                    _project_item(
                        target_id="REAL-MARKITDOWN-GUARDRAIL",
                        document_kind="candidate_notice",
                        attachment_role_type="CLARIFICATION_OR_ADDENDUM",
                        attachment_snapshot_id="SNAP-MARKITDOWN-GUARDRAIL",
                    )
                ],
            )
            _write_calibration_manifest(
                calibration_path,
                [_calibration_item(target_id="REAL-MARKITDOWN-GUARDRAIL", index=0, signal_count=0)],
            )
            markitdown_text = "资格条件: 投标时须提供厂家授权、本地社保和类似业绩。"

            with patch(
                "stage3_parsing.real_parser.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=markitdown_text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_length=len(markitdown_text),
                    text_probe=markitdown_text,
                ),
            ):
                result = build_markitdown_replay_impact_manifest(
                    real_sample_execution_manifest_json=execution_path,
                    rule_calibration_manifest_json=calibration_path,
                    object_repository=repo,
                    created_at="2026-05-09T00:00:00+08:00",
                )

            item = result["manifest"]["items"][0]
            self.assertTrue(item["non_tender_document_guardrail_applied"])
            self.assertGreater(item["replay_tailored_signal_count"], 0)
            self.assertEqual(item["replay_tailored_bid_index"], 0)
            self.assertEqual(result["summary"]["non_tender_document_guardrail_hits"], 1)

    def test_missing_snapshot_fails_closed_without_fabricating_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            _write_execution_manifest(
                execution_path,
                [
                    _project_item(
                        target_id="REAL-MISSING-SNAPSHOT",
                        attachment_snapshot_id="SNAP-MISSING",
                    )
                ],
            )
            _write_calibration_manifest(
                calibration_path,
                [_calibration_item(target_id="REAL-MISSING-SNAPSHOT", index=0, signal_count=0)],
            )

            result = build_markitdown_replay_impact_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                object_repository=repo,
                created_at="2026-05-09T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(summary["replay_attempted_count"], 1)
            self.assertEqual(summary["snapshot_readback_failure_counts"]["MISSING_MANIFEST"], 1)
            self.assertEqual(summary["attachment_text_gain_count"], 0)

    def test_no_replayable_attachments_reports_insufficient_replayable_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            _write_execution_manifest(
                execution_path,
                [_project_item(target_id="REAL-NO-ATTACHMENT", attachment_snapshot_id="")],
            )
            _write_calibration_manifest(
                calibration_path,
                [_calibration_item(target_id="REAL-NO-ATTACHMENT", index=0, signal_count=0)],
            )

            result = build_markitdown_replay_impact_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                object_repository=repo,
                created_at="2026-05-09T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["replay_attempted_count"], 0)
            self.assertEqual(
                result["summary"]["recommended_next_action"],
                INSUFFICIENT_REPLAYABLE_SNAPSHOT,
            )

    def test_report_keeps_internal_boundaries_and_omits_prohibited_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            execution_path = Path(tmp_dir) / "execution.json"
            calibration_path = Path(tmp_dir) / "calibration.json"
            _write_execution_manifest(
                execution_path,
                [_project_item(target_id="REAL-SAFE", attachment_snapshot_id="")],
            )
            _write_calibration_manifest(
                calibration_path,
                [_calibration_item(target_id="REAL-SAFE", index=0, signal_count=0)],
            )

            result = build_markitdown_replay_impact_manifest(
                real_sample_execution_manifest_json=execution_path,
                rule_calibration_manifest_json=calibration_path,
                object_repository=repo,
                created_at="2026-05-09T00:00:00+08:00",
            )
            report_text = json.dumps(result["manifest"], ensure_ascii=False)

            self.assertFalse(result["manifest"]["safety"]["customer_visible_allowed"])
            self.assertFalse(result["manifest"]["safety"]["formal_rule_threshold_mutation_enabled"])
            self.assertTrue(result["manifest"]["safety"]["no_legal_conclusion"])
            for term in ["已内定", "违法成立", "控标成立", "必然废标"]:
                self.assertNotIn(term, report_text)


def _repo(tmp_dir: str) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(Path(tmp_dir) / "storage.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(Path(tmp_dir) / "objects"),
    )
    return ObjectStorageRepository(
        session=DatabaseSession(settings=settings),
        settings=settings,
    )


def _save_attachment_snapshot(
    repo: ObjectStorageRepository,
    *,
    snapshot_id: str,
    content_type: str,
    source_url: str,
) -> None:
    repo.save_snapshot(
        b"not a valid office document",
        snapshot_id=snapshot_id,
        snapshot_kind="raw_attachment",
        content_type=content_type,
        source_url_optional=source_url,
        source_family_optional="unit-test-public-source",
        lineage_refs={"project_id": "P-MARKITDOWN-REPLAY"},
        created_at="2026-05-09T00:00:00+08:00",
    )


def _write_execution_manifest(path: Path, project_sample_items: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "manifest_id": "REAL-SAMPLE-MANIFEST-TEST",
                    "project_sample_items": project_sample_items,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_calibration_manifest(path: Path, tailored_items: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "manifest_id": "RULE-CALIBRATION-MANIFEST-TEST",
                    "tailored_items": tailored_items,
                    "summary": {
                        "tailored_sample_count": len(tailored_items),
                        "tailored_insufficient_sample_state": "INSUFFICIENT_SAMPLE",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _project_item(
    *,
    target_id: str,
    attachment_snapshot_id: str,
    document_kind: str = "tender_file",
    attachment_role_type: str = "TENDER_DOCUMENT",
) -> dict:
    attachment_refs = []
    if attachment_snapshot_id:
        attachment_refs.append(
            {
                "snapshot_id": attachment_snapshot_id,
                "attachment_url": f"https://example.test/{attachment_snapshot_id}.docx",
                "attachment_role_type": attachment_role_type,
            }
        )
    return {
        "target_id": target_id,
        "parent_target_id": "REAL-PARENT",
        "candidate_key": target_id.rsplit("-", 1)[-1],
        "project_id": f"PROJ-{target_id}",
        "project_name": f"测试项目 {target_id}",
        "source_url": f"https://example.test/{target_id}.html",
        "document_kind": document_kind,
        "jurisdiction": "CN-ZJ",
        "source_profile_id": "TEST-SOURCE",
        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
        "source_text": "项目名称: 测试项目\n招标文件正文可解析。",
        "attachment_snapshot_refs": attachment_refs,
        "parse_summary": {
            "text_probe": "项目名称: 测试项目\n招标文件正文可解析。",
            "document_completeness_state_counts": {"COMPLETE_WITH_ATTACHMENTS": 1},
            "notice_version_chain_state_counts": {"ATTACHMENTS_LINKED": 1},
            "attachment_missing_review_count": 0,
            "ocr_required_count": 0,
            "attachment_ocr_required_count": 0,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _calibration_item(*, target_id: str, index: int, signal_count: int) -> dict:
    return {
        "target_id": target_id,
        "parent_target_id": "REAL-PARENT",
        "candidate_key": target_id.rsplit("-", 1)[-1],
        "project_id": f"PROJ-{target_id}",
        "document_kind": "tender_file",
        "tailored_bid_index": index,
        "tailored_bid_signal_count": signal_count,
        "tailored_bid_signal_families": {},
        "tailored_bid_stage5_review_required": index >= 21,
        "tailored_bid_ai_review_required": index >= 41,
        "expected_tailored_review_state": "REVIEW_REQUIRED" if index >= 21 else "PASS",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
