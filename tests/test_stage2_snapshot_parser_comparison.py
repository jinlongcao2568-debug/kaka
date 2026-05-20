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
from stage2_ingestion.snapshot_parser_comparison import (  # noqa: E402
    STAGE2_SNAPSHOT_PARSER_COMPARISON_KIND,
    build_stage2_snapshot_parser_comparison,
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


class Stage2SnapshotParserComparisonTests(unittest.TestCase):
    def test_comparison_reads_local_snapshot_manifests_without_live_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo(root)
            repo.save_snapshot(
                """
                <html><head><title>Candidate notice</title></head><body>
                  <table>
                    <tr><th>项目名称</th><td>测试道路工程</td></tr>
                    <tr><th>公告日期</th><td>2026-05-18</td></tr>
                  </table>
                  <a href="./files/notice.pdf">Attachment pdf download</a>
                  <a href="/jyxx/result.html">Result page</a>
                </body></html>
                """.encode("utf-8"),
                snapshot_id="REAL-DETAIL-001",
                snapshot_kind=REAL_PUBLIC_DETAIL_SNAPSHOT_KIND,
                content_type="text/html; charset=utf-8",
                source_url_optional="https://example.gov/jyxx/detail.html",
                source_family_optional="local_public_resource_trading_center",
                lineage_refs={"project_id": "PROJ-001", "flow_no": "07"},
            )
            repo.save_snapshot(
                b"""
                <html><head><title>Flow page</title></head><body>
                  <a href="/jyfw/002001/002001006/file-open.html">Public file page</a>
                  <a href="/jyfw/002001/002001003/result.html">Award result page</a>
                </body></html>
                """,
                snapshot_id="REAL-DETAIL-002",
                snapshot_kind=REAL_PUBLIC_DETAIL_SNAPSHOT_KIND,
                content_type="text/html; charset=utf-8",
                source_url_optional="https://example.gov/jyxx/flow.html",
                source_family_optional="local_public_resource_trading_center",
                lineage_refs={"project_id": "PROJ-002", "flow_no": "08"},
            )
            repo.save_snapshot(
                """
                <html><head><title>Navigation candidate</title></head><body>
                  <a href="/jyfw/002001/002001004/002001004005/trade_purchasetoplen6.html">网上答疑</a>
                </body></html>
                """.encode("utf-8"),
                snapshot_id="REAL-DETAIL-003",
                snapshot_kind=REAL_PUBLIC_DETAIL_SNAPSHOT_KIND,
                content_type="text/html; charset=utf-8",
                source_url_optional="https://example.gov/jyxx/nav.html",
                source_family_optional="local_public_resource_trading_center",
                lineage_refs={"project_id": "PROJ-003", "flow_no": "04"},
            )

            result = build_stage2_snapshot_parser_comparison(
                input_root=root,
                output_dir=root / "out",
                max_snapshots=20,
            )

            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_kind"], STAGE2_SNAPSHOT_PARSER_COMPARISON_KIND)
            self.assertEqual(manifest["summary"]["compared_snapshot_count"], 3)
            self.assertTrue(manifest["summary"]["no_live_request_all_true"])
            self.assertFalse(manifest["summary"]["customer_visible_allowed_any_true"])
            by_id = {row["snapshot_id"]: row for row in manifest["comparison_records"]}
            self.assertEqual(by_id["REAL-DETAIL-001"]["legacy_attachment_count"], 1)
            self.assertEqual(by_id["REAL-DETAIL-001"]["parser_attachment_count"], 1)
            self.assertGreaterEqual(by_id["REAL-DETAIL-001"]["parser_field_candidate_count"], 2)
            self.assertGreaterEqual(by_id["REAL-DETAIL-001"]["parser_table_count"], 1)
            self.assertGreaterEqual(by_id["REAL-DETAIL-001"]["parser_table_label_value_pair_count"], 2)
            self.assertGreaterEqual(by_id["REAL-DETAIL-001"]["stage3_html_field_count"], 2)
            self.assertIn("project_name", by_id["REAL-DETAIL-001"]["field_name_intersection"])
            self.assertIn("FIELD_SIGNAL_CANDIDATES_FOUND", by_id["REAL-DETAIL-001"]["quality_flags"])
            self.assertIn("TABLE_STRUCTURE_SIGNALS_FOUND", by_id["REAL-DETAIL-001"]["quality_flags"])
            self.assertEqual(by_id["REAL-DETAIL-002"]["parser_attachment_count"], 0)
            self.assertIn("NO_ATTACHMENT_CANDIDATES", by_id["REAL-DETAIL-002"]["quality_flags"])
            self.assertEqual(by_id["REAL-DETAIL-003"]["legacy_extra_strict_attachment_count"], 0)
            self.assertEqual(by_id["REAL-DETAIL-003"]["legacy_extra_navigation_candidate_count"], 1)
            self.assertIn("LEGACY_BROAD_NAVIGATION_CANDIDATES_NOT_COPIED", by_id["REAL-DETAIL-003"]["quality_flags"])
            self.assertTrue(Path(result["json_path"]).exists())
            self.assertTrue(Path(result["markdown_path"]).exists())
            persisted = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"]["compared_snapshot_count"], 3)

    def test_comparison_can_filter_by_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo(root)
            for idx in range(2):
                repo.save_snapshot(
                    f"<html><head><title>{idx}</title></head><body><a href='./a{idx}.pdf'>pdf</a></body></html>".encode(
                        "utf-8"
                    ),
                    snapshot_id=f"REAL-DETAIL-{idx}",
                    snapshot_kind=REAL_PUBLIC_DETAIL_SNAPSHOT_KIND,
                    content_type="text/html; charset=utf-8",
                    source_url_optional=f"https://example.gov/{idx}.html",
                    source_family_optional="local_public_resource_trading_center",
                    lineage_refs={"project_id": f"PROJ-{idx}"},
                )

            result = build_stage2_snapshot_parser_comparison(
                input_root=root,
                output_dir=root / "out",
                project_ids=["PROJ-1"],
            )

            self.assertEqual(result["manifest"]["summary"]["compared_snapshot_count"], 1)
            self.assertEqual(result["manifest"]["comparison_records"][0]["project_id"], "PROJ-1")


if __name__ == "__main__":
    unittest.main()
