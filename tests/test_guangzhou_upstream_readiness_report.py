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

from storage.guangzhou_probe_readiness_report import build_guangzhou_upstream_readiness_report  # noqa: E402


class GuangzhouUpstreamReadinessReportTests(unittest.TestCase):
    def test_report_blocks_stage4_when_upstream_coverage_and_parse_are_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow_root = root / "flow"
            download_root = root / "download"
            strategy_root = root / "strategy"
            archive_root = root / "archive"
            parse_root = root / "parse"
            output_root = root / "report"
            _write_flow_manifest(flow_root)
            _write_analysis_plan(flow_root)
            _write_download_manifest(download_root)
            _write_strategy_manifest(strategy_root)
            _write_archive_manifest(archive_root)
            _write_parse_manifest(parse_root)
            _write_stage4_inputs(parse_root)

            result = build_guangzhou_upstream_readiness_report(
                flow_root=flow_root,
                download_root=download_root,
                evidence_strategy_root=strategy_root,
                archive_extract_root=archive_root,
                parse_root=parse_root,
                output_root=output_root,
                created_at="2026-05-11T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertFalse(result["safe_to_continue_stage4"])
            self.assertEqual(summary["readiness_state"], "UPSTREAM_NOT_READY_FOR_STAGE4")
            self.assertIn("download_probe_project_coverage_below_flowurl_projects", summary["stage4_blocking_reasons"])
            self.assertIn("attachment_snapshot_success_rate_below_target", summary["stage4_blocking_reasons"])
            self.assertIn("parse_success_rate_below_target", summary["stage4_blocking_reasons"])
            self.assertIn("stage4_project_manager_inputs_missing", summary["stage4_blocking_reasons"])
            self.assertIn("stage4_certificate_inputs_missing", summary["stage4_blocking_reasons"])
            self.assertTrue(result["manifest"]["repair_backlog"])
            self.assertTrue((output_root / "guangzhou-upstream-readiness-report.json").exists())
            p2 = next(row for row in result["manifest"]["project_records"] if row["project_id"] == "PROJ-CN-GD-JG2026-22222")
            self.assertIn("download_probe_not_run_for_project", p2["blocking_layers"])


def _write_flow_manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    samples = [
        _sample("PROJ-CN-GD-JG2026-11111", "03", "招标公告/关联公告"),
        _sample("PROJ-CN-GD-JG2026-22222", "07", "中标候选人公示"),
    ]
    payload = {
        "manifest": {
            "manifest_kind": "evaluation_real_project_sample_execution_manifest",
            "project_sample_items": samples,
            "summary": {"unique_project_count": 2, "project_sample_count": 2},
        }
    }
    (root / "run-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "flow-url-manifest.json").write_text(
        json.dumps({"manifest": {"manifest_kind": "guangzhou_flow_url_manifest", "summary": {"project_count": 2, "flow_url_count": 2}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_analysis_plan(root: Path) -> None:
    items = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11111",
            "flow_no": "03",
            "source_url": "https://example.test/11111/03.html",
            "download_policy": "DOWNLOAD_REQUIRED",
            "parse_depth": "SECTION_PARSE",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-22222",
            "flow_no": "07",
            "source_url": "https://example.test/22222/07.html",
            "download_policy": "DOWNLOAD_REQUIRED_IF_ATTACHMENT_PRESENT",
            "parse_depth": "TEXT_PROBE",
        },
    ]
    (root / "analysis-plan.json").write_text(json.dumps({"manifest": {"items": items, "summary": {"project_count": 2}}}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_download_manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    sample = {
        **_sample("PROJ-CN-GD-JG2026-11111", "03", "招标公告/关联公告"),
        "pipeline_stage": "DownloadProbe",
        "target_execution_state": "DOWNLOAD_PROBE_PARTIAL_REVIEW",
        "listed_attachment_count": 2,
        "download_attempted_count": 2,
        "failure_taxonomy": ["ATTACHMENT_INTERFACE_ERROR"],
        "attachment_snapshot_refs": [
            {
                "snapshot_id": "ATT-1",
                "attachment_url": "https://example.test/file.pdf",
                "content_type": "application/pdf",
            }
        ],
    }
    payload = {
        "manifest": {
            "project_sample_items": [sample],
            "summary": {
                "unique_project_count": 1,
                "project_sample_count": 1,
                "download_attempted_count": 2,
                "attachment_snapshot_count": 1,
                "failure_taxonomy_counts": {"ATTACHMENT_INTERFACE_ERROR": 1},
            },
        }
    }
    (root / "download-probe-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_strategy_manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    item = {
        "project_id": "PROJ-CN-GD-JG2026-11111",
        "flow_no": "03",
        "extract_policy": "SECTION_PARSE",
        "stage4_targets": ["project_manager_qualification"],
    }
    (root / "evidence-verification-strategy.json").write_text(
        json.dumps({"manifest": {"items": [item], "summary": {"strategy_item_count": 1}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_archive_manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "archive-extract-probe-manifest.json").write_text(
        json.dumps({"manifest": {"project_sample_items": [], "summary": {"archive_extract_state": "NO_ARCHIVE_CANDIDATES"}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_parse_manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    sample = {
        **_sample("PROJ-CN-GD-JG2026-11111", "03", "招标公告/关联公告"),
        "pipeline_stage": "ParseProbe",
        "parse_probe_state": "PARSE_PROBE_REVIEW_REQUIRED",
        "parse_metrics": {
            "parse_attempted_file_count": 1,
            "stage3_parse_success_count": 0,
            "stage3_parse_review_count": 1,
        },
        "failure_taxonomy": ["MARKITDOWN_TEXT_EMPTY"],
    }
    item = {
        "project_id": "PROJ-CN-GD-JG2026-11111",
        "flow_no": "03",
        "parse_state": "PARSE_REVIEW_REQUIRED",
        "parse_error_taxonomy": ["MARKITDOWN_TEXT_EMPTY"],
    }
    payload = {
        "manifest": {
            "project_sample_items": [sample],
            "items": [item],
            "summary": {
                "parse_attempted_file_count": 1,
                "parse_success_count": 0,
                "parse_review_required_count": 1,
                "parse_failure_taxonomy_counts": {"MARKITDOWN_TEXT_EMPTY": 1},
            },
        }
    }
    (root / "parse-probe-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_stage4_inputs(root: Path) -> None:
    payload = {
        "manifest_kind": "stage4_candidate_verification_inputs_manifest",
        "items": [],
        "summary": {
            "stage4_input_count": 0,
            "with_project_manager_count": 0,
            "with_certificate_count": 0,
        },
    }
    (root / "stage4_candidate_verification_inputs.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sample(project_id: str, flow_no: str, flow_title: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_name": f"{project_id}测试项目",
        "source_url": f"https://example.test/{project_id}/{flow_no}.html",
        "guangzhou_flow_no": flow_no,
        "guangzhou_flow_title": flow_title,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
