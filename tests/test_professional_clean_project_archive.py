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

from shared.settings import Settings  # noqa: E402
from storage.db import DatabaseSession  # noqa: E402
from storage.professional_clean_project_archive import (  # noqa: E402
    build_professional_clean_project_archive_manifest,
)
from storage.repositories.object_storage_repo import ObjectStorageRepository  # noqa: E402


class TestProfessionalCleanProjectArchive(unittest.TestCase):
    def test_materializes_project_folder_and_project_file_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_snapshot(
                repo,
                snapshot_id="SNAP-DETAIL-001",
                data=b"<html><body>qualification detail</body></html>",
                content_type="text/html",
                source_url="https://example.test/detail.html",
            )
            _save_snapshot(
                repo,
                snapshot_id="SNAP-TENDER-PDF-001",
                data=b"%PDF-1.4 tender file",
                content_type="application/pdf",
                source_url="https://example.test/tender.pdf",
            )
            execution_path = Path(tmp_dir) / "run-manifest.json"
            output_root = Path(tmp_dir) / "professional-clean-v1"
            _write_execution_manifest(
                execution_path,
                [
                    _project_sample(
                        detail_snapshot_id="SNAP-DETAIL-001",
                        attachment_snapshot_id="SNAP-TENDER-PDF-001",
                    )
                ],
            )

            result = build_professional_clean_project_archive_manifest(
                real_sample_execution_manifest_json=execution_path,
                output_root=output_root,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_count"], 1)
            self.assertEqual(summary["detail_file_count"], 1)
            self.assertEqual(summary["attachment_file_count"], 1)
            self.assertEqual(summary["valid_tender_attachment_count"], 1)
            item = result["manifest"]["items"][0]
            project_dir = Path(item["project_dir"])
            self.assertTrue((project_dir / "project.json").exists())
            self.assertTrue((project_dir / "audit.json").exists())
            self.assertTrue((output_root / "project-file-audit.json").exists())
            self.assertTrue(item["qualification_section_found"])
            self.assertTrue(item["scoring_section_found"])
            self.assertTrue(item["technical_section_found"])
            self.assertEqual(
                item["project_completeness_contract"]["download_completeness_state"],
                "DOWNLOAD_COMPLETE",
            )
            self.assertEqual(
                item["project_completeness_contract"]["parse_completeness_state"],
                "PARSE_COMPLETE",
            )
            self.assertEqual(
                item["project_completeness_contract"]["overall_project_readiness_state"],
                "PROJECT_READY_FOR_SIGNAL_ANALYSIS",
            )
            self.assertEqual(len(item["file_inventory"]), 2)
            self.assertEqual(item["verification_urls"]["url_count"], 2)
            self.assertIn(
                "https://example.test/detail.html",
                item["verification_urls"]["project_source_urls"],
            )
            self.assertIn(
                "https://example.test/tender.pdf",
                item["verification_urls"]["attachment_snapshot_urls"],
            )
            self.assertIn(
                "verify_attachment_links_match_file_inventory",
                item["verification_urls"]["verification_workflow"],
            )
            project_payload = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
            self.assertIn("verification_urls", project_payload)
            self.assertEqual(
                item["parse_metrics"]["file_level_parse_attribution_state"],
                "PROJECT_LEVEL_ONLY_MISSING_FILE_LEVEL_ATTRIBUTION",
            )
            parse_summary_payload = json.loads(
                (project_dir / "parsed" / "parse-summary.json").read_text(encoding="utf-8")
            )
            self.assertIn("verification_urls", parse_summary_payload)
            self.assertFalse(item["failure_reasons"])

    def test_flags_stage_pollution_and_html_attachment_pollution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_snapshot(
                repo,
                snapshot_id="SNAP-DETAIL-HTML-002",
                data=b"<html><body>candidate notice</body></html>",
                content_type="text/html",
                source_url="https://example.test/candidate.html",
            )
            _save_snapshot(
                repo,
                snapshot_id="SNAP-HTML-POLLUTION-002",
                data=b"<html><body>rss</body></html>",
                content_type="text/html",
                source_url="https://example.test/rss.html",
            )
            execution_path = Path(tmp_dir) / "run-manifest.json"
            output_root = Path(tmp_dir) / "professional-clean-v1"
            _write_execution_manifest(
                execution_path,
                [
                    _project_sample(
                        project_name="某工程中标候选人公示",
                        source_text="某工程中标候选人公示",
                        detail_snapshot_id="SNAP-DETAIL-HTML-002",
                        attachment_snapshot_id="SNAP-HTML-POLLUTION-002",
                        attachment_role_type="UNKNOWN_ATTACHMENT_ROLE",
                        attachment_source_url="https://example.test/rss.html",
                    )
                ],
            )

            result = build_professional_clean_project_archive_manifest(
                real_sample_execution_manifest_json=execution_path,
                output_root=output_root,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["html_pollution_file_count"], 1)
            self.assertEqual(item["valid_tender_attachment_count"], 0)
            self.assertIn("valid_tender_attachment_missing", item["failure_reasons"])
            self.assertIn("html_pollution_attachment_present", item["failure_reasons"])
            self.assertIn(
                "tender_file_stage_text_contains:中标候选人公示",
                item["failure_reasons"],
            )
            self.assertIn("required_section_text_missing", item["failure_reasons"])
            self.assertEqual(result["summary"]["stage_pollution_project_count"], 1)

    def test_separates_download_gap_from_parse_gap_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_snapshot(
                repo,
                snapshot_id="SNAP-DETAIL-003",
                data=b"<html><body>detail</body></html>",
                content_type="text/html",
                source_url="https://example.test/detail.html",
            )
            _save_snapshot(
                repo,
                snapshot_id="SNAP-TENDER-PDF-003",
                data=b"%PDF-1.4 tender file",
                content_type="application/pdf",
                source_url="https://example.test/tender.pdf",
            )
            execution_path = Path(tmp_dir) / "run-manifest.json"
            output_root = Path(tmp_dir) / "professional-clean-v1"
            sample = _project_sample(
                detail_snapshot_id="SNAP-DETAIL-003",
                attachment_snapshot_id="SNAP-TENDER-PDF-003",
            )
            sample["source_text"] = "招标文件"
            sample["parse_summary"] = {
                "stage3_parse_success_count": 0,
                "stage3_parse_failed_count": 1,
                "attachment_missing_review_count": 0,
                "unknown_attachment_count": 0,
                "text_probe": "招标文件",
            }
            _write_execution_manifest(execution_path, [sample])

            result = build_professional_clean_project_archive_manifest(
                real_sample_execution_manifest_json=execution_path,
                output_root=output_root,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(
                item["project_completeness_contract"]["download_completeness_state"],
                "DOWNLOAD_COMPLETE",
            )
            self.assertEqual(
                item["project_completeness_contract"]["parse_completeness_state"],
                "PARSE_INCOMPLETE",
            )
            self.assertEqual(
                item["project_completeness_contract"]["overall_project_readiness_state"],
                "PARSE_BLOCKED",
            )
            self.assertIn("stage3_parse_failed", item["failure_reasons"])
            self.assertIn(
                "downloaded_tender_attachment_but_parse_success_missing",
                item["failure_reasons"],
            )
            attachment_rows = [row for row in item["file_inventory"] if row["file_role"] == "attachment"]
            self.assertEqual(attachment_rows[0]["download_state"], "DOWNLOADED_REPLAYABLE")
            self.assertEqual(attachment_rows[0]["parse_state"], "PARSE_FAILED")
            self.assertEqual(result["summary"]["download_incomplete_project_count"], 0)
            self.assertEqual(result["summary"]["parse_incomplete_project_count"], 1)

    def test_missing_attachment_is_download_gap_not_parse_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_snapshot(
                repo,
                snapshot_id="SNAP-DETAIL-004",
                data=b"<html><body>detail</body></html>",
                content_type="text/html",
                source_url="https://example.test/detail.html",
            )
            execution_path = Path(tmp_dir) / "run-manifest.json"
            output_root = Path(tmp_dir) / "professional-clean-v1"
            sample = _project_sample(
                detail_snapshot_id="SNAP-DETAIL-004",
                attachment_snapshot_id="SNAP-MISSING-ATT-004",
            )
            sample["attachment_snapshot_refs"] = []
            sample["parse_summary"] = {
                "stage3_parse_success_count": 0,
                "stage3_parse_failed_count": 0,
                "attachment_missing_review_count": 1,
                "unknown_attachment_count": 0,
                "text_probe": "资格条件\n评分办法\n技术参数",
                "document_quality_reasons": ["guangzhou_ywtb_attachment_download_link_not_found"],
            }
            _write_execution_manifest(execution_path, [sample])

            result = build_professional_clean_project_archive_manifest(
                real_sample_execution_manifest_json=execution_path,
                output_root=output_root,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(
                item["project_completeness_contract"]["download_completeness_state"],
                "DOWNLOAD_INCOMPLETE",
            )
            self.assertIn(
                "tender_attachment_not_found_or_not_downloaded",
                item["project_completeness_contract"]["download_blocking_reasons"],
            )
            self.assertIn("attachment_missing_review", item["failure_reasons"])
            self.assertIn("guangzhou_ywtb_attachment_download_link_not_found", item["failure_reasons"])
            self.assertEqual(item["attachment_file_count"], 0)
            self.assertEqual(result["summary"]["download_incomplete_project_count"], 1)

    def test_unknown_role_pdf_with_extracted_text_keeps_attachment_url_and_counts_as_tender_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_snapshot(
                repo,
                snapshot_id="SNAP-DETAIL-005",
                data=b"<html><body>detail</body></html>",
                content_type="text/html",
                source_url="https://example.test/detail.html",
            )
            _save_snapshot(
                repo,
                snapshot_id="SNAP-TENDER-PDF-005",
                data=b"%PDF-1.4 extracted tender text",
                content_type="application/pdf",
                source_url="https://example.test/download/招标文件.pdf",
            )
            execution_path = Path(tmp_dir) / "run-manifest.json"
            output_root = Path(tmp_dir) / "professional-clean-v1"
            sample = _project_sample(
                detail_snapshot_id="SNAP-DETAIL-005",
                attachment_snapshot_id="SNAP-TENDER-PDF-005",
            )
            sample["attachment_snapshot_refs"] = [
                {
                    "snapshot_id": "SNAP-TENDER-PDF-005",
                    "attachment_url": "https://example.test/download/招标文件.pdf",
                    "attachment_role_type": "UNKNOWN_ATTACHMENT_ROLE",
                    "parse_state": "PDF_TEXT_EXTRACTED",
                }
            ]
            _write_execution_manifest(execution_path, [sample])

            result = build_professional_clean_project_archive_manifest(
                real_sample_execution_manifest_json=execution_path,
                output_root=output_root,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            attachment_rows = [row for row in item["file_inventory"] if row["file_role"] == "attachment"]
            self.assertEqual(item["valid_tender_attachment_count"], 1)
            self.assertTrue(attachment_rows[0]["valid_tender_attachment"])
            self.assertEqual(
                attachment_rows[0]["source_url"],
                "https://example.test/download/招标文件.pdf",
            )
            self.assertIn(
                "https://example.test/download/招标文件.pdf",
                item["verification_urls"]["attachment_snapshot_urls"],
            )

    def test_qualification_only_parse_is_marked_as_section_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            _save_snapshot(
                repo,
                snapshot_id="SNAP-DETAIL-006",
                data=b"<html><body>detail</body></html>",
                content_type="text/html",
                source_url="https://example.test/detail.html",
            )
            _save_snapshot(
                repo,
                snapshot_id="SNAP-TENDER-PDF-006",
                data=b"%PDF-1.4 tender file",
                content_type="application/pdf",
                source_url="https://example.test/tender.pdf",
            )
            execution_path = Path(tmp_dir) / "run-manifest.json"
            output_root = Path(tmp_dir) / "professional-clean-v1"
            sample = _project_sample(
                source_text="投标人资格要求：具备市政公用工程施工总承包资质。",
                detail_snapshot_id="SNAP-DETAIL-006",
                attachment_snapshot_id="SNAP-TENDER-PDF-006",
            )
            sample["parse_summary"] = {
                "stage3_parse_success_count": 1,
                "stage3_parse_failed_count": 0,
                "attachment_missing_review_count": 0,
                "unknown_attachment_count": 0,
                "text_probe": "投标人资格要求：具备市政公用工程施工总承包资质。",
            }
            _write_execution_manifest(execution_path, [sample])

            result = build_professional_clean_project_archive_manifest(
                real_sample_execution_manifest_json=execution_path,
                output_root=output_root,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertTrue(item["qualification_section_found"])
            self.assertFalse(item["scoring_section_found"])
            self.assertFalse(item["technical_section_found"])
            self.assertEqual(item["section_analysis_state"], "SECTION_PARTIAL_QUALIFICATION_ONLY")
            self.assertIn(
                "section_partial_qualification_only",
                item["parse_metrics"]["parse_insufficiency_reasons"],
            )
            self.assertEqual(
                item["project_completeness_contract"]["parse_completeness_state"],
                "PARSE_INCOMPLETE",
            )


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


def _save_snapshot(
    repo: ObjectStorageRepository,
    *,
    snapshot_id: str,
    data: bytes,
    content_type: str,
    source_url: str,
) -> None:
    repo.save_snapshot(
        data,
        snapshot_id=snapshot_id,
        snapshot_kind="test_snapshot",
        content_type=content_type,
        source_url_optional=source_url,
        source_family_optional="test",
        lineage_refs={"project_id": "PROJ-CN-GD-CLEAN-001"},
    )


def _write_execution_manifest(path: Path, project_sample_items: list[dict[str, object]]) -> None:
    payload = {
        "manifest": {
            "manifest_id": "REAL-SAMPLE-CLEAN-TEST",
            "project_sample_items": project_sample_items,
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _project_sample(
    *,
    project_name: str = "某工程招标公告",
    source_text: str = "资格条件\n评分办法\n技术参数\n招标文件",
    detail_snapshot_id: str,
    attachment_snapshot_id: str,
    attachment_role_type: str = "TENDER_FILE",
    attachment_source_url: str = "https://example.test/tender.pdf",
) -> dict[str, object]:
    return {
        "target_id": "REAL-GD-TENDER-001::clean",
        "parent_target_id": "REAL-GD-TENDER-001",
        "candidate_key": "clean",
        "project_id": "PROJ-CN-GD-CLEAN-001",
        "project_name": project_name,
        "source_url": "https://example.test/detail.html",
        "document_kind": "tender_file",
        "jurisdiction": "CN-GD",
        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
        "document_completeness_state": "COMPLETE_WITH_ATTACHMENTS",
        "notice_version_chain_state": "NO_SUPPLEMENT_DETECTED",
        "source_text": source_text,
        "detail_snapshot_refs": [
            {
                "snapshot_id": detail_snapshot_id,
                "source_url": "https://example.test/detail.html",
            }
        ],
        "attachment_snapshot_refs": [
            {
                "snapshot_id": attachment_snapshot_id,
                "source_url": attachment_source_url,
                "attachment_role_type": attachment_role_type,
                "attachment_link_text": "招标文件",
            }
        ],
        "parse_summary": {
            "stage3_parse_success_count": 1,
            "stage3_parse_failed_count": 0,
            "attachment_missing_review_count": 0,
            "unknown_attachment_count": 0,
            "text_probe": source_text,
        },
        "failure_taxonomy": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
