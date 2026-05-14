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

from storage.guangzhou_evidence_fixation_recapture import build_guangzhou_evidence_fixation_recapture  # noqa: E402


class GuangzhouEvidenceFixationRecaptureTests(unittest.TestCase):
    def test_plan_only_builds_tasks_from_unfixable_backfill_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, flow_count=8, stage4_count=30)

            result = build_guangzhou_evidence_fixation_recapture(
                backfill_root=root / "backfill",
                internal_package_root=root / "package",
                flow_root=root / "flow",
                download_root=root / "download",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
                execute=False,
            )

            summary = result["summary"]
            self.assertEqual(summary["recapture_state"], "P9_RECAPTURE_PLAN_READY")
            self.assertEqual(summary["recapture_task_count"], 38)
            self.assertEqual(summary["flow_detail_recapture_task_count"], 8)
            self.assertEqual(summary["stage4_readback_recapture_task_count"], 30)
            self.assertEqual(summary["recapture_state_counts"]["PLAN_ONLY_NOT_EXECUTED"], 38)

    def test_execute_recaptures_flow_detail_snapshot_and_stage4_readback_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, flow_count=1, stage4_count=1)

            def fake_fetcher(url: str) -> dict[str, object]:
                return {
                    "status_code": 200,
                    "content_type": "text/html; charset=utf-8",
                    "body_bytes": f"<html><title>{url}</title><body>public flow detail</body></html>".encode(),
                    "route": "fake",
                }

            result = build_guangzhou_evidence_fixation_recapture(
                backfill_root=root / "backfill",
                internal_package_root=root / "package",
                flow_root=root / "flow",
                download_root=root / "download",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
                execute=True,
                flow_fetcher=fake_fetcher,
                created_at="2026-05-14T00:00:00+08:00",
            )

            records = result["manifest"]["recapture_records"]
            flow = next(row for row in records if row["recapture_task_type"] == "FLOW_DETAIL_RECAPTURE")
            stage4 = next(row for row in records if row["recapture_task_type"] == "STAGE4_READBACK_RECAPTURE")
            self.assertEqual(flow["recapture_state"], "FLOW_DETAIL_RECAPTURED")
            self.assertTrue(flow["snapshot_id"].startswith("P9-FLOW-"))
            self.assertEqual(len(flow["sha256"]), 64)
            self.assertEqual(stage4["recapture_state"], "STAGE4_READBACK_RECAPTURED")
            self.assertEqual(len(stage4["source_readback_sha256"]), 64)
            self.assertIn("resolved_certificate_no_optional", stage4["field_evidence_probe"])
            text = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("<html>", text)

    def test_execute_classifies_flow_fetch_blocker_without_fake_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, flow_count=1, stage4_count=0)

            def failing_fetcher(url: str) -> dict[str, object]:
                raise TimeoutError("timeout")

            result = build_guangzhou_evidence_fixation_recapture(
                backfill_root=root / "backfill",
                internal_package_root=root / "package",
                flow_root=root / "flow",
                download_root=root / "download",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
                execute=True,
                flow_fetcher=failing_fetcher,
            )

            record = result["manifest"]["recapture_records"][0]
            self.assertEqual(record["recapture_state"], "FLOW_DETAIL_RECAPTURE_BLOCKED")
            self.assertIn("flow_detail_recapture_exception:TimeoutError", record["failure_taxonomy"])
            self.assertNotIn("snapshot_id", record)


def _write_inputs(root: Path, *, flow_count: int, stage4_count: int) -> None:
    for name in ("backfill", "package", "flow", "download", "stage4"):
        (root / name).mkdir(parents=True, exist_ok=True)
    source_records = []
    backfill_records = []
    for idx in range(flow_count):
        source_id = f"FIX-FLOW-{idx}"
        source_records.append(
            {
                "source_fixation_id": source_id,
                "project_id": f"PROJ-CN-GD-JG2026-{idx:05d}",
                "source_family": "flow_url_manifest",
                "flow_no": "05",
                "source_url": f"https://jsgc.gzggzy.cn/flow/{idx}",
                "snapshot_id": "",
                "readback_ref": "",
                "sha256": "",
                "fixation_state": "FIXATION_GAP_REVIEW",
                "fixation_gap_reasons": ["snapshot_or_readback_ref_missing", "sha256_or_hash_missing"],
            }
        )
        backfill_records.append(
            {
                "source_fixation_id": source_id,
                "project_id": f"PROJ-CN-GD-JG2026-{idx:05d}",
                "source_family": "flow_url_manifest",
                "flow_no": "05",
                "source_url": f"https://jsgc.gzggzy.cn/flow/{idx}",
                "backfill_state": "UNFIXABLE_WITH_CURRENT_ARTIFACTS",
                "remaining_gap_reasons": ["missing_download_snapshot", "sha256_or_hash_missing"],
            }
        )
    stage4_items = []
    for idx in range(stage4_count):
        source_id = f"FIX-STAGE4-{idx}"
        job_id = f"STAGE4-JOB-{idx}"
        source_records.append(
            {
                "source_fixation_id": source_id,
                "project_id": f"PROJ-CN-GD-JG2026-S{idx:05d}",
                "candidate_group_id": f"GROUP-{idx}",
                "source_family": "stage4_company_personnel_readback",
                "flow_no": "07",
                "source_url": "https://jzsc.mohurd.gov.cn/data/person",
                "snapshot_id": "",
                "readback_ref": job_id,
                "sha256": "",
                "fixation_state": "FIXATION_GAP_REVIEW",
                "fixation_gap_reasons": ["sha256_or_hash_missing"],
            }
        )
        backfill_records.append(
            {
                "source_fixation_id": source_id,
                "project_id": f"PROJ-CN-GD-JG2026-S{idx:05d}",
                "candidate_group_id": f"GROUP-{idx}",
                "source_family": "stage4_company_personnel_readback",
                "flow_no": "07",
                "source_url": "https://jzsc.mohurd.gov.cn/data/person",
                "backfill_state": "UNFIXABLE_WITH_CURRENT_ARTIFACTS",
                "remaining_gap_reasons": ["stage4_snapshot_not_replayable", "sha256_or_hash_missing"],
            }
        )
        stage4_items.append(
            {
                "job_id": job_id,
                "project_id": f"PROJ-CN-GD-JG2026-S{idx:05d}",
                "candidate_group_id": f"GROUP-{idx}",
                "candidate_company_name": f"候选公司{idx}",
                "responsible_person_name": f"负责人{idx}",
                "resolved_certificate_no_optional": f"粤1442020{idx:04d}",
                "registered_unit_name_optional": f"候选公司{idx}",
                "matched_company_name_optional": f"候选公司{idx}",
                "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/person",
                "stage4_execution_state": "READBACK_READY",
                "readback_state": "READBACK_READY",
            }
        )
    (root / "package" / "internal-evidence-package-manifest-v1.json").write_text(
        json.dumps({"manifest": {"source_fixation_records": source_records}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "backfill" / "evidence-fixation-backfill-v1.json").write_text(
        json.dumps({"manifest": {"backfill_records": backfill_records}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "flow" / "run-manifest.json").write_text(json.dumps({"manifest": {"project_sample_items": []}}, ensure_ascii=False), encoding="utf-8")
    (root / "download" / "download-probe-manifest.json").write_text(json.dumps({"manifest": {}}, ensure_ascii=False), encoding="utf-8")
    (root / "stage4" / "company-first-stage4-execution.json").write_text(
        json.dumps({"manifest": {"items": stage4_items}}, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
