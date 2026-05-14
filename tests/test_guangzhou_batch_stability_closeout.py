from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.guangzhou_batch_stability_closeout import build_guangzhou_batch_stability_closeout  # noqa: E402


class GuangzhouBatchStabilityCloseoutTests(unittest.TestCase):
    def test_ready_when_ten_projects_have_p10_chain_and_no_unclassified_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_ids = [f"PROJ-CN-GD-JG2026-{idx:05d}" for idx in range(10001, 10011)]
            _write_p11_inputs(root, project_ids=project_ids, unfixable_count=0)

            result = build_guangzhou_batch_stability_closeout(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                evidence_report_root=root / "evidence",
                certificate_supplement_root=root / "certificate",
                internal_package_root=root / "internal",
                fixation_backfill_root=root / "backfill",
                recapture_root=root / "recapture",
                readable_report_root=root / "readable",
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["batch_closeout_state"], "P11_STABILITY_READY")
            self.assertEqual(summary["entry_project_count"], 10)
            self.assertEqual(summary["readable_report_project_count"], 10)
            self.assertEqual(summary["readable_ready_project_threshold"], 8)
            self.assertEqual(summary["unfixable_with_current_artifacts_count"], 0)
            self.assertEqual(summary["forbidden_term_scan_state"], "PASS")
            self.assertFalse(summary["customer_delivery_ready"])
            self.assertTrue((root / "out" / "guangzhou-batch-stability-closeout-v1.json").exists())

    def test_partial_source_coverage_when_recent_07_less_than_eight_but_chain_is_explained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_ids = [f"PROJ-CN-GD-JG2026-{idx:05d}" for idx in range(10001, 10006)]
            _write_p11_inputs(root, project_ids=project_ids, unfixable_count=0)

            result = build_guangzhou_batch_stability_closeout(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                evidence_report_root=root / "evidence",
                certificate_supplement_root=root / "certificate",
                internal_package_root=root / "internal",
                fixation_backfill_root=root / "backfill",
                recapture_root=root / "recapture",
                readable_report_root=root / "readable",
                output_root=root / "out",
            )

            summary = result["summary"]
            self.assertEqual(summary["batch_closeout_state"], "P11_PARTIAL_SOURCE_COVERAGE")
            self.assertEqual(summary["entry_project_count"], 5)
            self.assertEqual(summary["systemic_blockers"], [])

    def test_blocked_when_downstream_manifest_missing_or_fixation_has_unfixable_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_ids = [f"PROJ-CN-GD-JG2026-{idx:05d}" for idx in range(10001, 10011)]
            _write_p11_inputs(root, project_ids=project_ids, unfixable_count=2)
            (root / "readable" / "guangzhou-evidence-readable-report-v1.json").unlink()

            result = build_guangzhou_batch_stability_closeout(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                evidence_report_root=root / "evidence",
                certificate_supplement_root=root / "certificate",
                internal_package_root=root / "internal",
                fixation_backfill_root=root / "backfill",
                recapture_root=root / "recapture",
                readable_report_root=root / "readable",
                output_root=root / "out",
            )

            summary = result["summary"]
            self.assertEqual(summary["batch_closeout_state"], "P11_BLOCKED")
            self.assertIn("readable_report_missing", summary["missing_inputs"])
            self.assertIn("unclassified_or_unfixable_fixation_gap_present", summary["systemic_blockers"])
            self.assertIn("readable_report_project_threshold_not_met", summary["systemic_blockers"])


def _write_p11_inputs(root: Path, *, project_ids: list[str], unfixable_count: int) -> None:
    for folder in (
        "flow",
        "download",
        "responsible",
        "stage4",
        "readiness",
        "evidence",
        "certificate",
        "internal",
        "backfill",
        "recapture",
        "readable",
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)

    _write_json(
        root / "flow" / "run-manifest.json",
        {
            "summary": {
                "unique_project_count": len(project_ids),
                "selected_post_candidate_entry_count": len(project_ids),
                "project_sample_count": len(project_ids) * 4,
            },
            "project_sample_items": [{"project_id": project_id, "project_name": f"项目{project_id[-2:]}"} for project_id in project_ids],
        },
    )
    _write_json(
        root / "download" / "download-repair-merged-manifest.json",
        {
            "summary": {
                "download_probe_project_count": len(project_ids),
                "flow_item_count": len(project_ids) * 3,
                "attachment_snapshot_count": len(project_ids) * 10,
                "attachment_snapshot_success_rate": 1.0,
            },
            "project_records": [{"project_id": project_id, "project_name": f"项目{project_id[-2:]}"} for project_id in project_ids],
        },
    )
    _write_json(
        root / "responsible" / "responsible-person-early-probe.json",
        {
            "summary": {"project_count": len(project_ids), "certificate_ready_count": len(project_ids)},
            "project_records": [{"project_id": project_id, "early_probe_state": "CERTIFICATE_READY_FROM_07"} for project_id in project_ids],
        },
    )
    _write_json(
        root / "stage4" / "company-first-stage4-execution.json",
        {
            "summary": {"job_count": len(project_ids) * 2, "state_counts": {"COMPANY_FIRST_CERTIFICATE_RESOLVED": len(project_ids)}},
            "job_records": [{"project_id": project_id, "stage4_execution_state": "READBACK_READY"} for project_id in project_ids],
        },
    )
    _write_json(root / "readiness" / "guangzhou-upstream-readiness-report.json", {"safe_to_closeout_evidence_report": True})
    _write_json(
        root / "evidence" / "guangzhou-evidence-report-v1.json",
        {
            "summary": {
                "project_count": len(project_ids),
                "candidate_group_count": len(project_ids),
                "resolved_candidate_group_count": len(project_ids),
                "flow_08_targeted_parse_required_project_count": 0,
                "safe_to_closeout_evidence_report": True,
            },
            "project_reports": [{"project_id": project_id, "project_name": f"项目{project_id[-2:]}"} for project_id in project_ids],
        },
    )
    _write_json(root / "certificate" / "certificate-supplement-closeout-v1.json", {"summary": {"certificate_resolved_group_count": len(project_ids)}})
    _write_json(
        root / "internal" / "internal-evidence-package-manifest-v1.json",
        {
            "summary": {
                "project_count": len(project_ids),
                "candidate_group_count": len(project_ids),
                "certificate_resolved_group_count": len(project_ids),
                "flow_08_targeted_parse_required_count": 0,
                "source_fixation_record_count": len(project_ids) * 20,
                "forbidden_term_scan_state": "PASS",
            },
            "project_records": [{"project_id": project_id, "project_name": f"项目{project_id[-2:]}"} for project_id in project_ids],
        },
    )
    _write_json(
        root / "backfill" / "evidence-fixation-backfill-v1.json",
        {
            "summary": {
                "backfilled_no_remaining_gap_count": len(project_ids) * 8,
                "classified_record_hash_only_count": len(project_ids),
                "unfixable_with_current_artifacts_count": unfixable_count,
            }
        },
    )
    _write_json(root / "recapture" / "evidence-fixation-recapture-v1.json", {"summary": {"recapture_task_count": len(project_ids) * 2}})
    _write_json(
        root / "readable" / "guangzhou-evidence-readable-report-v1.json",
        {
            "summary": {"project_count": len(project_ids), "forbidden_term_scan_state": "PASS"},
            "project_records": [{"project_id": project_id, "project_name": f"项目{project_id[-2:]}"} for project_id in project_ids],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
