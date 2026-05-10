from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings  # noqa: E402
from storage.db import DatabaseSession  # noqa: E402
from storage.guangzhou_archive_extract_probe import build_guangzhou_archive_extract_probe  # noqa: E402
from storage.repositories.object_storage_repo import ObjectStorageRepository  # noqa: E402


class GuangzhouArchiveExtractProbeTests(unittest.TestCase):
    def test_targeted_zip_extracts_safe_child_snapshot_and_blocks_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            strategy_root = root / "strategy"
            output_root = root / "extract"
            repo = _repo(root)
            _save_snapshot(
                repo,
                "ATT-ZIP-1",
                _zip_bytes({"候选人公示.pdf": b"%PDF candidate", "../evil.pdf": b"%PDF evil"}),
                "application/zip",
            )
            _write_download_manifest(input_root)
            _write_strategy_manifest(strategy_root)

            result = build_guangzhou_archive_extract_probe(
                input_root=input_root,
                strategy_root=strategy_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                storage_path=root / "storage.json",
                object_storage_path=root / "objects",
                execute=True,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            item = result["manifest"]["items"][0]
            self.assertEqual(item["archive_extract_state"], "TARGETED_CHILD_SNAPSHOTS_CAPTURED")
            self.assertEqual(item["child_snapshot_count"], 1)
            self.assertIn("archive_member_path_traversal_blocked", item["failure_taxonomy"])
            child_ref = item["child_snapshot_refs"][0]
            self.assertEqual(child_ref["archive_inner_path"], "候选人公示.pdf")
            self.assertTrue(repo.replay_snapshot(child_ref["snapshot_id"])["replayable"])
            self.assertTrue(Path(child_ref["local_path"]).exists())

    def test_oversize_zip_member_fails_closed_without_child_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            strategy_root = root / "strategy"
            repo = _repo(root)
            _save_snapshot(repo, "ATT-ZIP-1", _zip_bytes({"超限文件.pdf": b"%PDF too-large"}), "application/zip")
            _write_download_manifest(input_root)
            _write_strategy_manifest(strategy_root)

            result = build_guangzhou_archive_extract_probe(
                input_root=input_root,
                strategy_root=strategy_root,
                output_root=root / "extract",
                project_ids=["JG2026-10815"],
                storage_path=root / "storage.json",
                object_storage_path=root / "objects",
                max_single_file_bytes=8,
                execute=True,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["archive_extract_state"], "ARCHIVE_EXTRACT_REVIEW_REQUIRED")
            self.assertEqual(item["child_snapshot_refs"], [])
            self.assertIn("archive_member_single_file_size_limit_exceeded", item["failure_taxonomy"])

    def test_no_archive_candidates_is_not_a_blocking_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            strategy_root = root / "strategy"
            _write_download_manifest(input_root)
            _write_strategy_manifest(strategy_root, extract_policy="TEXT_PROBE")

            result = build_guangzhou_archive_extract_probe(
                input_root=input_root,
                strategy_root=strategy_root,
                output_root=root / "extract",
                project_ids=["JG2026-10815"],
                execute=True,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["archive_extract_state"], "NO_ARCHIVE_CANDIDATES")
            self.assertEqual(result["manifest"]["items"], [])


def _repo(root: Path) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(root / "storage.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(root / "objects"),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def _save_snapshot(repo: ObjectStorageRepository, snapshot_id: str, data: bytes, content_type: str) -> None:
    repo.save_snapshot(
        data,
        snapshot_id=snapshot_id,
        snapshot_kind="downloaded_attachment",
        content_type=content_type,
        source_url_optional="https://example.test/candidate.zip",
        source_family_optional="GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        lineage_refs={"project_id": "PROJ-CN-GD-JG2026-10815", "flow_no": "07"},
        created_at="2026-05-10T00:00:00+08:00",
        adapter_id="test",
        source_visibility_state="PUBLIC_VISIBLE",
        fetch_mode="TEST",
    )


def _write_download_manifest(input_root: Path) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    sample = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "source_url": "https://example.test/07.html",
        "document_kind": "candidate_notice",
        "pipeline_stage": "DownloadProbe",
        "jurisdiction": "CN-GD",
        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        "guangzhou_flow_no": "07",
        "guangzhou_flow_title": "中标候选人公示",
        "guangzhou_flow_folder": str(input_root / "projects" / "CN-GD" / "PROJ-CN-GD-JG2026-10815" / "07_中标候选人公示" / "2026-05-10_广州测试项目"),
        "attachment_snapshot_refs": [
            {
                "snapshot_id": "ATT-ZIP-1",
                "attachment_url": "https://example.test/candidate.zip",
                "source_url": "https://example.test/candidate.zip",
                "attachment_link_text": "候选人附件.zip",
                "attachment_role_type": "CANDIDATE_NOTICE_ATTACHMENT",
                "content_type": "application/zip",
                "byte_size": 100,
            }
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_download_probe_manifest",
            "source_input_root": str(input_root),
            "project_sample_items": [sample],
        }
    }
    (input_root / "download-probe-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_strategy_manifest(strategy_root: Path, *, extract_policy: str = "TARGETED_EXTRACT") -> None:
    strategy_root.mkdir(parents=True, exist_ok=True)
    item = {
        "evidence_strategy_item_id": "EVIDENCE-STRATEGY-07-001",
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "flow_no": "07",
        "flow_title": "中标候选人公示",
        "document_kind": "candidate_notice",
        "source_url": "https://example.test/07.html",
        "published_date": "2026-05-10",
        "attachment_snapshot_id": "ATT-ZIP-1",
        "attachment_url": "https://example.test/candidate.zip",
        "attachment_link_text": "候选人附件.zip",
        "attachment_role_type": "CANDIDATE_NOTICE_ATTACHMENT",
        "extract_policy": extract_policy,
        "parse_policy": "TEXT_PROBE",
        "target_fields": ["candidate_company", "project_manager_name", "certificate_no", "bid_price"],
        "stage4_targets": ["project_manager_qualification", "candidate_verification"],
        "file_name_priority_keywords": ["候选", "项目负责人", "证书"],
        "max_extract_files": 2,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload = {
        "manifest": {
            "manifest_kind": "evidence_verification_strategy_manifest",
            "items": [item],
            "project_ids": ["PROJ-CN-GD-JG2026-10815"],
        }
    }
    (strategy_root / "evidence-verification-strategy.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
