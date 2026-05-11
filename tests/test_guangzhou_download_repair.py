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

from storage.guangzhou_download_repair import (  # noqa: E402
    build_download_repair_merged_manifest,
    build_download_repair_segment_manifest,
)


class GuangzhouDownloadRepairTests(unittest.TestCase):
    def test_segment_and_merge_manifests_preserve_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow08 = root / "segments" / "flow-08"
            flow03 = root / "segments" / "flow-03"
            _write_download_probe(flow08, flow_no="08", project_id="PROJ-CN-GD-JG2026-10815", snapshots=2, attempted=2)
            _write_download_probe(
                flow03,
                flow_no="03",
                project_id="PROJ-CN-GD-JG2026-11021",
                snapshots=1,
                attempted=2,
                partial=True,
                failure_taxonomy=["DEFERRED_BY_DOWNLOAD_REPAIR_LIMIT"],
            )

            seg08 = build_download_repair_segment_manifest(
                segment_root=flow08,
                flow_no="08",
                created_at="2026-05-11T00:00:00+08:00",
            )
            seg03 = build_download_repair_segment_manifest(
                segment_root=flow03,
                flow_no="03",
                timeout_interrupted=True,
                created_at="2026-05-11T00:00:00+08:00",
            )
            merged = build_download_repair_merged_manifest(
                output_root=root / "merged",
                segment_roots=[flow08, flow03],
                created_at="2026-05-11T00:00:00+08:00",
            )

            self.assertEqual(seg08["segment_state"], "CAPTURED")
            self.assertEqual(seg03["segment_state"], "TIMEOUT_INTERRUPTED")
            summary = merged["summary"]
            self.assertEqual(summary["download_probe_project_count"], 2)
            self.assertEqual(summary["attachment_snapshot_count"], 3)
            self.assertEqual(summary["download_attempted_count"], 4)
            self.assertEqual(summary["timeout_interrupted_count"], 1)
            self.assertEqual(summary["partial_segment_count"], 1)
            self.assertEqual(summary["failure_taxonomy_counts"]["DEFERRED_BY_DOWNLOAD_REPAIR_LIMIT"], 2)
            self.assertTrue((root / "merged" / "download-repair-merged-manifest.json").exists())
            self.assertTrue((root / "merged" / "download-probe-manifest.json").exists())

    def test_merge_builds_replay_store_for_parse_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow07 = root / "segments" / "flow-07"
            _write_download_probe(flow07, flow_no="07", project_id="PROJ-CN-GD-JG2026-10815", snapshots=1, attempted=1)
            _write_segment_replay_store(flow07, snapshot_id="ATT-0", object_key="objects/aa/aa01", data=b"candidate pdf")

            build_download_repair_merged_manifest(
                output_root=root / "merged",
                segment_roots=[flow07],
                created_at="2026-05-11T00:00:00+08:00",
            )

            merged_storage = json.loads((root / "merged" / "storage.json").read_text(encoding="utf-8"))
            self.assertIn("ATT-0", merged_storage["tables"]["evidence_snapshot_manifest"])
            self.assertTrue((root / "merged" / "objects" / "objects" / "aa" / "aa01").exists())
            merged_manifest = json.loads((root / "merged" / "download-probe-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                merged_manifest["manifest"]["object_storage_path_optional"],
                str(root / "merged" / "objects"),
            )

    def test_merge_manifest_includes_detail_transport_failure_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow03 = root / "segments" / "flow-03"
            _write_download_probe(
                flow03,
                flow_no="03",
                project_id="PROJ-CN-GD-JG2026-33333",
                snapshots=0,
                attempted=0,
                failure_taxonomy=["detail_ssl_protocol_error"],
                detail_transport_attempts=[
                    {
                        "route": "guangzhou_https_browser",
                        "state": "FAILED",
                        "failure_taxonomy": ["detail_ssl_protocol_error"],
                    }
                ],
            )

            merged = build_download_repair_merged_manifest(
                output_root=root / "merged",
                segment_roots=[flow03],
                created_at="2026-05-11T00:00:00+08:00",
            )

            matrix = merged["summary"]["detail_transport_failure_matrix"]
            self.assertEqual(len(matrix), 1)
            self.assertEqual(matrix[0]["project_id"], "PROJ-CN-GD-JG2026-33333")
            self.assertEqual(matrix[0]["detail_transport_attempts"][0]["route"], "guangzhou_https_browser")


def _write_download_probe(
    root: Path,
    *,
    flow_no: str,
    project_id: str,
    snapshots: int,
    attempted: int,
    partial: bool = False,
    failure_taxonomy: list[str] | None = None,
    detail_transport_attempts: list[dict[str, object]] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    failures = failure_taxonomy or []
    item = {
        "project_id": project_id,
        "project_name": f"{project_id}项目",
        "flow_no": flow_no,
        "flow_title": f"{flow_no}流程",
        "source_url": f"https://example.test/{project_id}/{flow_no}.html",
        "listed_attachment_count": attempted,
        "download_attempted_count": attempted,
        "attachment_snapshot_count": snapshots,
        "failure_taxonomy": failures,
    }
    sample = {
        "project_id": project_id,
        "project_name": f"{project_id}项目",
        "guangzhou_flow_no": flow_no,
        "source_url": f"https://example.test/{project_id}/{flow_no}.html",
        "target_execution_state": "DOWNLOAD_PROBE_CAPTURED" if not failures else "DOWNLOAD_PROBE_PARTIAL_REVIEW",
        "detail_snapshot_count": 1,
        "listed_attachment_count": attempted,
        "download_attempted_count": attempted,
        "attachment_snapshot_count": snapshots,
        "attachment_snapshot_refs": [{"snapshot_id": f"ATT-{index}"} for index in range(snapshots)],
        "failure_taxonomy": failures,
        "detail_transport_attempts": detail_transport_attempts or [],
    }
    payload = {
        "manifest": {
            "items": [item],
            "project_sample_items": [sample],
            "summary": {
                "flowurl_project_count": 5,
                "download_probe_project_count": 1,
                "download_attempted_count": attempted,
                "attachment_snapshot_count": snapshots,
                "failure_taxonomy_counts": {reason: 1 for reason in failures},
            },
        },
        "summary": {
            "flowurl_project_count": 5,
            "download_probe_project_count": 1,
            "download_attempted_count": attempted,
            "attachment_snapshot_count": snapshots,
            "failure_taxonomy_counts": {reason: 1 for reason in failures},
        },
    }
    filename = "download-probe-manifest.partial.json" if partial else "download-probe-manifest.json"
    (root / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_segment_replay_store(root: Path, *, snapshot_id: str, object_key: str, data: bytes) -> None:
    object_path = root / "objects" / object_key
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(data)
    storage = {
        "storage_version": 1,
        "tables": {
            "object_storage_object": {
                object_key: {
                    "object_type": "object_storage_object",
                    "record_id": object_key,
                    "payload": {
                        "object_key": object_key,
                        "content_type": "application/pdf",
                        "byte_size": len(data),
                        "sha256": "aa01",
                        "created_at": "2026-05-11T00:00:00+08:00",
                        "storage_backend": "local-filesystem",
                    },
                }
            },
            "evidence_snapshot_manifest": {
                snapshot_id: {
                    "object_type": "evidence_snapshot_manifest",
                    "record_id": snapshot_id,
                    "payload": {
                        "snapshot_id": snapshot_id,
                        "object_key": object_key,
                        "source_url_optional": "https://example.test/file.pdf",
                        "source_family_optional": "local_public_resource_trading_center",
                        "snapshot_kind": "real_public_attachment_snapshot",
                        "content_type": "application/pdf",
                        "byte_size": len(data),
                        "sha256": "aa01",
                        "lineage_refs": {},
                        "created_at": "2026-05-11T00:00:00+08:00",
                        "storage_backend": "local-filesystem",
                        "replay_metadata": {},
                        "fetch_audit": {},
                        "raw_snapshot_metadata": {},
                        "source_health": {},
                    },
                }
            },
        },
        "stage_states": {},
        "work_items": {},
        "operator_actions": {},
        "worker_queue_items": {},
        "worker_queue_events": {},
    }
    (root / "storage.json").write_text(json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
