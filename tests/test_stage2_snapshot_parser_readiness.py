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
from stage2_ingestion.real_public_url_fetcher import REAL_PUBLIC_DETAIL_SNAPSHOT_KIND  # noqa: E402
from stage2_ingestion.snapshot_parser_readiness import (  # noqa: E402
    STAGE2_SNAPSHOT_PARSER_READINESS_KIND,
    build_stage2_snapshot_parser_readiness,
)
from storage.db import DatabaseSession  # noqa: E402
from storage.repositories.object_storage_repo import ObjectStorageRepository  # noqa: E402


def _repo(root: Path) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(root / "storage.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(root / "objects"),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


class Stage2SnapshotParserReadinessTests(unittest.TestCase):
    def test_readiness_aggregates_stage1_5_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            stable_root = parent / "stage1-5-limit3-stable"
            stable_root.mkdir()
            repo = _repo(stable_root)
            repo.save_snapshot(
                b"<html><head><title>Stable</title></head><body><table><tr><th>\xe9\xa1\xb9\xe7\x9b\xae\xe5\x90\x8d\xe7\xa7\xb0</th><td>\xe6\xb5\x8b\xe8\xaf\x95\xe9\xa1\xb9\xe7\x9b\xae</td></tr></table><a href='./a.pdf'>download</a></body></html>",
                snapshot_id="REAL-DETAIL-STABLE",
                snapshot_kind=REAL_PUBLIC_DETAIL_SNAPSHOT_KIND,
                content_type="text/html; charset=utf-8",
                source_url_optional="https://example.gov/detail.html",
                source_family_optional="local_public_resource_trading_center",
                lineage_refs={"project_id": "PROJ-STABLE"},
            )
            empty_root = parent / "stage1-5-limit3-empty"
            empty_root.mkdir()
            unrelated_root = parent / "other-run"
            unrelated_root.mkdir()

            result = build_stage2_snapshot_parser_readiness(
                input_parent=parent,
                output_dir=parent / "out",
                max_snapshots_per_root=20,
            )

            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_kind"], STAGE2_SNAPSHOT_PARSER_READINESS_KIND)
            self.assertEqual(manifest["summary"]["root_count"], 2)
            self.assertEqual(manifest["summary"]["compared_root_count"], 1)
            self.assertEqual(manifest["summary"]["stable_root_count"], 1)
            self.assertEqual(manifest["summary"]["no_html_snapshot_root_count"], 1)
            self.assertEqual(manifest["summary"]["compared_snapshot_total"], 1)
            self.assertGreaterEqual(manifest["summary"]["parser_field_candidate_total"], 1)
            self.assertGreaterEqual(manifest["summary"]["parser_table_total"], 1)
            self.assertGreaterEqual(manifest["summary"]["parser_table_label_value_pair_total"], 1)
            self.assertGreaterEqual(manifest["summary"]["stage3_html_field_total"], 1)
            states = {row["root_name"]: row["readiness_state"] for row in manifest["root_records"]}
            self.assertEqual(states["stage1-5-limit3-stable"], "STABLE_FOR_REPLAY")
            self.assertEqual(states["stage1-5-limit3-empty"], "NO_HTML_SNAPSHOTS_FOUND")
            self.assertTrue(Path(result["json_path"]).exists())
            self.assertTrue(Path(result["markdown_path"]).exists())
            persisted = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"]["stable_root_count"], 1)

    def test_readiness_can_exclude_empty_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            (parent / "stage1-5-limit3-empty").mkdir()

            result = build_stage2_snapshot_parser_readiness(
                input_parent=parent,
                output_dir=parent / "out",
                include_empty_roots=False,
            )

            self.assertEqual(result["manifest"]["summary"]["root_count"], 0)
            self.assertEqual(result["manifest"]["summary"]["readiness_state"], "NO_INPUT_ROOTS_FOUND")


if __name__ == "__main__":
    unittest.main()
