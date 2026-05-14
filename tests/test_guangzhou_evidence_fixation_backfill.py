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

from storage.guangzhou_evidence_fixation_backfill import build_guangzhou_evidence_fixation_backfill  # noqa: E402


class GuangzhouEvidenceFixationBackfillTests(unittest.TestCase):
    def test_backfills_flow_and_candidate_notice_from_download_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_internal_package(root / "package")
            _write_download(root / "download")
            _write_flow(root / "flow")
            _write_gdcic(root / "gdcic")
            _write_stage4(root / "stage4")

            result = build_guangzhou_evidence_fixation_backfill(
                internal_evidence_package_root=root / "package",
                download_root=root / "download",
                flow_root=root / "flow",
                gdcic_query_probe_root=root / "gdcic",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

        self.assertTrue(result["safe_to_execute"])
        records = result["manifest"]["backfill_records"]
        by_source_id = {record["source_fixation_id"]: record for record in records}
        self.assertEqual(by_source_id["FIX-FLOW"]["backfill_state"], "BACKFILLED_FROM_DOWNLOAD_DETAIL_SNAPSHOT")
        self.assertEqual(by_source_id["FIX-FLOW"]["backfilled_fields"]["snapshot_id"], "SNAP-DETAIL-07")
        self.assertEqual(by_source_id["FIX-CANDIDATE"]["backfill_state"], "BACKFILLED_FROM_DOWNLOAD_DETAIL_SNAPSHOT")
        self.assertEqual(by_source_id["FIX-CANDIDATE"]["backfilled_fields"]["sha256"], "a" * 64)
        self.assertEqual(result["summary"]["backfilled_record_count"], 3)

    def test_gdcic_summary_uses_query_task_source_url_and_record_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_internal_package(root / "package")
            _write_download(root / "download")
            _write_flow(root / "flow")
            _write_gdcic(root / "gdcic")
            _write_stage4(root / "stage4")

            result = build_guangzhou_evidence_fixation_backfill(
                internal_evidence_package_root=root / "package",
                download_root=root / "download",
                flow_root=root / "flow",
                gdcic_query_probe_root=root / "gdcic",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
            )

        gdcic = {record["source_fixation_id"]: record for record in result["manifest"]["backfill_records"]}["FIX-GDCIC"]
        self.assertEqual(gdcic["backfill_state"], "BACKFILLED_FROM_GDCIC_QUERY_TASK")
        self.assertEqual(gdcic["backfilled_fields"]["source_url"], "https://skypt.gdcic.net/openplatform/")
        self.assertTrue(gdcic["backfilled_fields"]["readback_record_sha256"])
        self.assertEqual(gdcic["remaining_gap_reasons"], [])

    def test_stage4_snapshot_gets_record_hash_only_not_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_internal_package(root / "package")
            _write_download(root / "download")
            _write_flow(root / "flow")
            _write_gdcic(root / "gdcic")
            _write_stage4(root / "stage4")

            result = build_guangzhou_evidence_fixation_backfill(
                internal_evidence_package_root=root / "package",
                download_root=root / "download",
                flow_root=root / "flow",
                gdcic_query_probe_root=root / "gdcic",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
            )

        stage4 = {record["source_fixation_id"]: record for record in result["manifest"]["backfill_records"]}["FIX-STAGE4"]
        self.assertEqual(stage4["backfill_state"], "RECORD_HASH_BACKFILLED_CONTENT_HASH_NOT_AVAILABLE")
        self.assertEqual(stage4["backfilled_fields"]["sha256"], "")
        self.assertTrue(stage4["backfilled_fields"]["readback_record_sha256"])
        self.assertIn("source_content_sha256_not_available_from_current_artifacts", stage4["remaining_gap_reasons"])

    def test_unmatched_gap_is_classified_unfixable_without_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_internal_package(root / "package", include_unmatched=True)
            _write_download(root / "download")
            _write_flow(root / "flow")
            _write_gdcic(root / "gdcic")
            _write_stage4(root / "stage4")

            result = build_guangzhou_evidence_fixation_backfill(
                internal_evidence_package_root=root / "package",
                download_root=root / "download",
                flow_root=root / "flow",
                gdcic_query_probe_root=root / "gdcic",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
            )

        summary = result["summary"]
        self.assertEqual(summary["unfixable_with_current_artifacts_count"], 1)
        unmatched = {record["source_fixation_id"]: record for record in result["manifest"]["backfill_records"]}["FIX-UNMATCHED"]
        self.assertEqual(unmatched["backfill_state"], "UNFIXABLE_WITH_CURRENT_ARTIFACTS")
        self.assertIn("missing_download_snapshot", unmatched["remaining_gap_reasons"])
        text = json.dumps(result, ensure_ascii=False)
        for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
            self.assertNotIn(term, text)


def _write_internal_package(root: Path, *, include_unmatched: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    records = [
        _fix("FIX-FLOW", "flow_url_manifest", "https://example.test/project/07.html", "07"),
        _fix("FIX-CANDIDATE", "evidence_report_candidate_notice_url", "https://example.test/project/07.html", "07"),
        _fix("FIX-GDCIC", "official_source_readback_summary", "", "", readback_ref="TASK-1"),
        _fix("FIX-STAGE4", "stage4_company_personnel_readback", "https://jzsc.example.test/person", "07", snapshot_id="SNAP-STAGE4"),
    ]
    if include_unmatched:
        records.append(_fix("FIX-UNMATCHED", "flow_url_manifest", "https://example.test/project/missing.html", "03"))
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_internal_evidence_package_manifest_v1",
            "source_fixation_records": records,
            "summary": {"fixation_gap_count": len(records)},
        }
    }
    (root / "internal-evidence-package-manifest-v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fix(
    source_id: str,
    family: str,
    url: str,
    flow_no: str,
    *,
    snapshot_id: str = "",
    readback_ref: str = "",
) -> dict[str, object]:
    reasons = ["sha256_or_hash_missing"]
    if not snapshot_id and not readback_ref:
        reasons.append("snapshot_or_readback_ref_missing")
    if not url:
        reasons.append("source_url_missing")
    return {
        "source_fixation_id": source_id,
        "project_id": "PROJ-CN-GD-JG2026-10000",
        "candidate_group_id": "G1",
        "source_family": family,
        "source_url": url,
        "flow_no": flow_no,
        "flow_title": "中标候选人公示",
        "snapshot_id": snapshot_id,
        "readback_ref": readback_ref,
        "sha256": "",
        "fixation_state": "FIXATION_GAP_REVIEW",
        "fixation_gap_reasons": reasons,
    }


def _write_download(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    ref = {
        "snapshot_id": "SNAP-DETAIL-07",
        "source_url": "https://example.test/project/07.html",
        "readback_state": "READBACK_READY",
        "sha256": "a" * 64,
        "human_readable_path": "projects/project/07/detail.html",
        "content_type": "text/html",
        "byte_size": 1234,
    }
    payload = {
        "manifest": {
            "manifest_kind": "download_probe_manifest",
            "project_sample_items": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-10000",
                    "guangzhou_flow_no": "07",
                    "source_url": "https://example.test/project/07.html",
                    "detail_snapshot_refs": [ref],
                }
            ],
        }
    }
    (root / "download-probe-manifest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (root / "human-readable-file-map.json").write_text(json.dumps([ref | {"project_id": "PROJ-CN-GD-JG2026-10000", "flow_no": "07"}], ensure_ascii=False), encoding="utf-8")


def _write_flow(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run-manifest.json").write_text(json.dumps({"manifest": {"project_sample_items": []}}, ensure_ascii=False), encoding="utf-8")


def _write_gdcic(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "query_task_records": [
                {
                    "query_task_id": "TASK-1",
                    "project_id": "PROJ-CN-GD-JG2026-10000",
                    "source_url": "https://skypt.gdcic.net/openplatform/",
                    "query_params": {"personName": "张三"},
                    "field_summary": {"record_count": 1},
                }
            ]
        }
    }
    (root / "guangdong-gdcic-query-probe-v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_stage4(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "items": [
                {
                    "job_id": "JOB-1",
                    "project_id": "PROJ-CN-GD-JG2026-10000",
                    "candidate_group_id": "G1",
                    "company_personnel_source_snapshot_id": "SNAP-STAGE4",
                    "company_personnel_source_url": "https://jzsc.example.test/person",
                    "stage4_execution_state": "READBACK_READY",
                }
            ]
        }
    }
    (root / "company-first-stage4-execution.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
