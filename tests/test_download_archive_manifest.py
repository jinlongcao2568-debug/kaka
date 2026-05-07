from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from shared.settings import Settings
from storage.db import DatabaseSession
from storage.download_archive_manifest import (
    CAPTURE_KIND_ATTACHMENT,
    CAPTURE_KIND_DEBUG_ARTIFACT,
    CAPTURE_KIND_DETAIL,
    CAPTURE_KIND_ENTRY,
    DOWNLOAD_RUN_MANIFEST_OBJECT_TYPE,
    append_download_archive_items,
    build_download_archive_manifest,
    build_download_archive_items,
    planned_download_archive_path,
    planned_download_archive_relative_path,
    sanitize_download_segment,
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class TestDownloadArchiveManifest(unittest.TestCase):
    def test_dry_run_does_not_create_archive_or_write_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "real-capture"
            result = build_download_archive_manifest(
                run_id="RUN-DRY",
                run_artifacts_root=root,
                items=[
                    {
                        "download_item_id": "DLI-ENTRY",
                        "candidate_id": "CAND-1",
                        "source_url": "https://example.test/a/detail",
                        "capture_kind": CAPTURE_KIND_ENTRY,
                    }
                ],
            )

            self.assertEqual(result["download_archive_mode"], "DRY_RUN")
            self.assertFalse(root.exists())
            self.assertFalse(result["execution"]["database_write_enabled"])
            self.assertFalse(result["execution"]["filesystem_write_enabled"])
            self.assertEqual(result["summary"]["item_count"], 1)

    def test_candidate_and_project_bucket_paths_are_stable(self) -> None:
        items = build_download_archive_items(
            run_id="RUN-BUCKET",
            raw_items=[
                {
                    "download_item_id": "DLI-PROJECT",
                    "project_id": "PROJECT:1",
                    "candidate_id": "CAND:1",
                    "source_url": "https://example.test/project",
                    "capture_kind": CAPTURE_KIND_ENTRY,
                },
                {
                    "download_item_id": "DLI-CANDIDATE",
                    "candidate_id": "CAND:2",
                    "source_url": "https://example.test/candidate",
                    "capture_kind": CAPTURE_KIND_ATTACHMENT,
                    "original_filename": "candidate-file.pdf",
                },
            ],
        )

        self.assertIn("downloads/PROJECT_1/pages/", items[0].archive_relative_path_optional)
        self.assertIn("downloads/CAND_2/attachments/", items[1].archive_relative_path_optional)

    def test_capture_kinds_use_expected_archive_directories(self) -> None:
        self.assertIn(
            "/pages/",
            planned_download_archive_relative_path(
                run_id="RUN-KIND",
                candidate_or_project_id="P1",
                capture_kind=CAPTURE_KIND_ENTRY,
                source_url="https://example.test/index.html",
                download_item_id="DLI-ENTRY",
            ),
        )
        self.assertIn(
            "/pages/",
            planned_download_archive_relative_path(
                run_id="RUN-KIND",
                candidate_or_project_id="P1",
                capture_kind=CAPTURE_KIND_DETAIL,
                source_url="https://example.test/detail.html",
                download_item_id="DLI-DETAIL",
            ),
        )
        self.assertIn(
            "/attachments/",
            planned_download_archive_relative_path(
                run_id="RUN-KIND",
                candidate_or_project_id="P1",
                capture_kind=CAPTURE_KIND_ATTACHMENT,
                original_filename="notice.pdf",
                source_url="https://example.test/notice.pdf",
                download_item_id="DLI-ATTACH",
            ),
        )
        self.assertIn(
            "/debug_artifacts/",
            planned_download_archive_relative_path(
                run_id="RUN-KIND",
                candidate_or_project_id="P1",
                capture_kind=CAPTURE_KIND_DEBUG_ARTIFACT,
                original_filename="trace.log",
                source_url="sandbox://debug/trace.log",
                download_item_id="DLI-DEBUG",
            ),
        )

    def test_path_sanitization_blocks_path_traversal_and_absolute_filenames(self) -> None:
        self.assertEqual(sanitize_download_segment('A<B>:"/\\|?*'), "A_B")
        with self.assertRaises(ValueError):
            planned_download_archive_relative_path(
                run_id="RUN-SAFE",
                candidate_or_project_id="P1",
                capture_kind=CAPTURE_KIND_ATTACHMENT,
                original_filename="..\\escape.pdf",
                source_url="https://example.test/escape.pdf",
                download_item_id="DLI-BAD",
            )
        with self.assertRaises(ValueError):
            planned_download_archive_relative_path(
                run_id="RUN-SAFE",
                candidate_or_project_id="P1",
                capture_kind=CAPTURE_KIND_ATTACHMENT,
                original_filename="C:\\temp\\escape.pdf",
                source_url="https://example.test/escape.pdf",
                download_item_id="DLI-BAD",
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "real-capture"
            target = planned_download_archive_path(
                run_id="../RUN-SAFE",
                candidate_or_project_id="../P1",
                capture_kind=CAPTURE_KIND_ENTRY,
                source_url="https://example.test/index.html",
                download_item_id="../DLI",
                run_artifacts_root=root,
            )
            self.assertTrue(str(target.resolve()).startswith(str(root.resolve())))

    def test_execute_writes_manifest_only_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "storage.sqlite"
            database_url = sqlalchemy_sqlite_url(db_path)
            root = Path(tmp_dir) / "real-capture"
            raw_items = [
                {
                    "download_item_id": "DLI-1",
                    "project_id": "PROJECT-1",
                    "source_url": "https://example.test/notice.html",
                    "source_family": "PUBLIC_RESOURCE_TRADING",
                    "capture_kind": CAPTURE_KIND_ENTRY,
                    "snapshot_id": "SNAP-1",
                    "object_key": "aa/bb",
                    "sha256": "abc123",
                    "byte_size": 128,
                    "content_type": "text/html",
                }
            ]

            first = build_download_archive_manifest(
                run_id="RUN-EXEC",
                run_artifacts_root=root,
                items=raw_items,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
            )
            second = build_download_archive_manifest(
                run_id="RUN-EXEC",
                run_artifacts_root=root,
                items=raw_items,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
            )

            self.assertTrue(first["execution"]["database_write_enabled"])
            self.assertFalse(first["execution"]["filesystem_write_enabled"])
            self.assertFalse(root.exists())
            self.assertEqual(first["manifest"]["manifest_id"], second["manifest"]["manifest_id"])

            session = DatabaseSession(
                settings=Settings(
                    storage_backend="sqlalchemy",
                    storage_database_url_optional=database_url,
                    storage_scope="shared",
                    storage_runtime_mode="explicit-path",
                )
            )
            try:
                records = session.list_records(DOWNLOAD_RUN_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(records), 1)
                record = records[0]
                payload_text = json.dumps(record.payload, ensure_ascii=False)
                self.assertEqual(record.record_id, "DOWNLOAD-RUN-MANIFEST-RUN-EXEC")
                self.assertEqual(record.payload["summary"]["item_count"], 1)
                self.assertIn("object_key_ref_count", record.payload["summary"])
                self.assertNotIn("bytes", payload_text.lower())
                self.assertNotIn("<html", payload_text.lower())
                self.assertNotIn("%pdf", payload_text.lower())
            finally:
                session.close()

    def test_append_download_archive_items_merges_by_item_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "storage.sqlite"
            database_url = sqlalchemy_sqlite_url(db_path)
            settings = Settings(
                storage_backend="sqlalchemy",
                storage_database_url_optional=database_url,
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            try:
                append_download_archive_items(
                    run_id="RUN-MERGE",
                    session=session,
                    execute=True,
                    items=[
                        {
                            "download_item_id": "DLI-ENTRY",
                            "project_id": "PROJECT-1",
                            "source_url": "https://example.test/entry.html",
                            "capture_kind": CAPTURE_KIND_ENTRY,
                            "download_status": "FETCHED_WITH_SNAPSHOT",
                        }
                    ],
                )
                append_download_archive_items(
                    run_id="RUN-MERGE",
                    session=session,
                    execute=True,
                    items=[
                        {
                            "download_item_id": "DLI-ENTRY",
                            "project_id": "PROJECT-1",
                            "source_url": "https://example.test/entry.html",
                            "capture_kind": CAPTURE_KIND_ENTRY,
                            "snapshot_id": "SNAP-UPDATED",
                            "download_status": "FETCHED_WITH_SNAPSHOT",
                        },
                        {
                            "download_item_id": "DLI-ATTACH",
                            "project_id": "PROJECT-1",
                            "source_url": "https://example.test/file.pdf",
                            "capture_kind": CAPTURE_KIND_ATTACHMENT,
                            "original_filename": "file.pdf",
                            "download_status": "FETCHED_WITH_SNAPSHOT",
                        },
                    ],
                )

                records = session.list_records(DOWNLOAD_RUN_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(records), 1)
                payload = records[0].payload
                self.assertEqual(payload["summary"]["item_count"], 2)
                items = {item["download_item_id"]: item for item in payload["items"]}
                self.assertEqual(items["DLI-ENTRY"]["snapshot_id_optional"], "SNAP-UPDATED")
                self.assertIn("/attachments/", items["DLI-ATTACH"]["archive_relative_path_optional"])
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
