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
            self.assertIn("candidate_evidence_certificate_inputs_missing_parse_required", summary["stage4_blocking_reasons"])
            self.assertEqual(summary["candidate_evidence_certificate_gate_state"], "CERTIFICATE_MISSING_PARSE_REQUIRED")
            self.assertTrue(result["manifest"]["repair_backlog"])
            self.assertTrue((output_root / "guangzhou-upstream-readiness-report.json").exists())
            p2 = next(row for row in result["manifest"]["project_records"] if row["project_id"] == "PROJ-CN-GD-JG2026-22222")
            self.assertIn("download_probe_not_run_for_project", p2["blocking_layers"])

    def test_report_reads_partial_download_manifest_and_blocks_stage4(self) -> None:
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
            _write_download_manifest(download_root, partial=True)
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
            self.assertIn("download_probe_partial_manifest_used", summary["stage4_blocking_reasons"])
            self.assertIn("attachment_snapshot_success_rate_below_target", summary["stage4_blocking_reasons"])

    def test_report_allows_stage4_when_flow_07_certificate_exists_even_if_parse_rate_is_low(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow_root = root / "flow"
            download_root = root / "download"
            strategy_root = root / "strategy"
            archive_root = root / "archive"
            parse_root = root / "parse"
            output_root = root / "report"
            _write_flow_manifest(flow_root, include_only_candidate_project=True)
            _write_analysis_plan(flow_root, include_only_candidate_project=True)
            _write_download_manifest(download_root, complete_candidate=True)
            _write_strategy_manifest(strategy_root)
            _write_archive_manifest(archive_root)
            _write_parse_manifest(parse_root, candidate_parse_review=True)
            _write_stage4_inputs(parse_root, flow_07_certificate=True)

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
            self.assertTrue(result["safe_to_continue_stage4"])
            self.assertEqual(summary["readiness_state"], "READY_FOR_STAGE4_PROBE")
            self.assertEqual(summary["candidate_evidence_certificate_gate_state"], "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION")
            self.assertEqual(summary["parse_success_rate_gate_state"], "DEFERRED_AFTER_CANDIDATE_CERTIFICATE_GATE")
            self.assertNotIn("parse_success_rate_below_target", summary["stage4_blocking_reasons"])
            self.assertNotIn("candidate_evidence_certificate_inputs_missing_parse_required", summary["stage4_blocking_reasons"])
            flow_07 = next(row for row in result["manifest"]["flow_records"] if row["flow_no"] == "07")
            self.assertEqual(flow_07["readiness_state"], "FLOW_READY_FOR_NEXT_PROBE")

    def test_report_allows_stage4_when_certificate_is_found_in_flow_08_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow_root = root / "flow"
            download_root = root / "download"
            strategy_root = root / "strategy"
            archive_root = root / "archive"
            parse_root = root / "parse"
            output_root = root / "report"
            _write_flow_manifest(flow_root, include_candidate_and_bid_publicity_project=True)
            _write_analysis_plan(flow_root, include_candidate_and_bid_publicity_project=True)
            _write_download_manifest(download_root, complete_candidate=True, complete_flow_no="08")
            _write_strategy_manifest(strategy_root)
            _write_archive_manifest(archive_root)
            _write_parse_manifest(parse_root, candidate_parse_review=True, candidate_parse_flow_no="08")
            _write_stage4_inputs(parse_root, flow_08_certificate=True)

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
            self.assertTrue(result["safe_to_continue_stage4"])
            self.assertEqual(summary["candidate_evidence_certificate_gate_state"], "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION_FROM_FLOW_08_FALLBACK")
            self.assertEqual(summary["candidate_evidence_certificate_source_flows"], ["08"])
            self.assertEqual(summary["candidate_evidence_projects_with_flow_08_fallback_certificate_count"], 1)
            self.assertEqual(summary["stage4_execution_scope"], "ALL_READY_CANDIDATE_CERTIFICATE_PROJECTS")
            self.assertNotIn("candidate_evidence_certificate_inputs_missing_parse_required", summary["stage4_blocking_reasons"])

    def test_report_does_not_treat_non_07_certificate_as_candidate_gate_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow_root = root / "flow"
            download_root = root / "download"
            strategy_root = root / "strategy"
            archive_root = root / "archive"
            parse_root = root / "parse"
            output_root = root / "report"
            _write_flow_manifest(flow_root, include_only_candidate_project=True)
            _write_analysis_plan(flow_root, include_only_candidate_project=True)
            _write_download_manifest(download_root, complete_candidate=True)
            _write_strategy_manifest(strategy_root)
            _write_archive_manifest(archive_root)
            _write_parse_manifest(parse_root, candidate_parse_review=True)
            _write_stage4_inputs(parse_root, non_07_certificate=True)

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
            self.assertEqual(summary["candidate_evidence_certificate_gate_state"], "CERTIFICATE_MISSING_PARSE_REQUIRED")
            self.assertIn("candidate_evidence_certificate_inputs_missing_parse_required", summary["stage4_blocking_reasons"])

    def test_report_includes_candidate_group_stage4_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow_root = root / "flow"
            download_root = root / "download"
            strategy_root = root / "strategy"
            archive_root = root / "archive"
            parse_root = root / "parse"
            stage4_execution_root = root / "stage4-execution"
            output_root = root / "report"
            _write_flow_manifest(flow_root, include_only_candidate_project=True)
            _write_analysis_plan(flow_root, include_only_candidate_project=True)
            _write_download_manifest(download_root, complete_candidate=True)
            _write_strategy_manifest(strategy_root)
            _write_archive_manifest(archive_root)
            _write_parse_manifest(parse_root, candidate_parse_review=True)
            _write_stage4_inputs(parse_root, flow_07_certificate=True)
            _write_stage4_execution_manifest(stage4_execution_root)

            result = build_guangzhou_upstream_readiness_report(
                flow_root=flow_root,
                download_root=download_root,
                evidence_strategy_root=strategy_root,
                archive_extract_root=archive_root,
                parse_root=parse_root,
                stage4_execution_root=stage4_execution_root,
                output_root=output_root,
                created_at="2026-05-11T00:00:00+08:00",
            )

            summary = result["summary"]["candidate_group_verification_summary"]
            self.assertEqual(summary["candidate_group_count"], 1)
            self.assertEqual(summary["resolved_group_count"], 1)
            self.assertEqual(summary["matched_company_names"], ["北京神州新桥科技有限公司"])
            project = result["manifest"]["project_records"][0]
            group_record = project["candidate_group_verification_records"][0]
            self.assertEqual(group_record["group_resolution_state"], "RESOLVED_BY_CONSORTIUM_MEMBER")
            self.assertEqual(group_record["matched_company_names"], ["北京神州新桥科技有限公司"])
            self.assertEqual(group_record["nonmatched_but_group_resolved_count"], 2)
            self.assertFalse(group_record["flow_08_targeted_parse_required"])
            self.assertEqual(group_record["member_records"][0]["resolved_certificate_no_optional"], "")

    def test_report_does_not_mark_all_resolved_groups_as_flow08_required_when_parse_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow_root = root / "flow"
            download_root = root / "download"
            strategy_root = root / "strategy"
            archive_root = root / "archive"
            parse_root = root / "parse"
            stage4_execution_root = root / "stage4-execution"
            output_root = root / "report"
            _write_flow_manifest(flow_root, include_only_candidate_project=True)
            _write_analysis_plan(flow_root, include_only_candidate_project=True)
            _write_download_manifest(download_root, complete_candidate=True)
            _write_strategy_manifest(strategy_root)
            _write_archive_manifest(archive_root)
            _write_stage4_execution_manifest(stage4_execution_root)

            result = build_guangzhou_upstream_readiness_report(
                flow_root=flow_root,
                download_root=download_root,
                evidence_strategy_root=strategy_root,
                archive_extract_root=archive_root,
                parse_root=parse_root,
                stage4_execution_root=stage4_execution_root,
                output_root=output_root,
                created_at="2026-05-11T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertFalse(summary["safe_to_continue_stage4"])
            self.assertEqual(summary["readiness_state"], "STAGE4_GROUP_VERIFICATION_READY_PARSE_DEFERRED")
            self.assertEqual(summary["stage4_execution_scope"], "CANDIDATE_GROUPS_RESOLVED_PARSE_DEFERRED")
            self.assertEqual(summary["candidate_group_stage4_gate_state"], "GROUPS_RESOLVED")
            self.assertIn("parse_probe_manifest_missing", summary["stage4_blocking_reasons"])

    def test_flow_08_register_only_does_not_block_when_not_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            flow_root = root / "flow"
            download_root = root / "download"
            strategy_root = root / "strategy"
            archive_root = root / "archive"
            parse_root = root / "parse"
            stage4_execution_root = root / "stage4-execution"
            output_root = root / "report"
            _write_flow_manifest(flow_root, include_candidate_and_bid_publicity_project=True)
            _write_analysis_plan(flow_root, include_candidate_and_bid_publicity_project=True)
            _write_download_manifest(download_root, complete_candidate=True)
            _append_flow08_register_only_download_sample(download_root)
            _write_strategy_manifest(strategy_root)
            _write_archive_manifest(archive_root)
            _write_stage4_execution_manifest(stage4_execution_root)

            result = build_guangzhou_upstream_readiness_report(
                flow_root=flow_root,
                download_root=download_root,
                evidence_strategy_root=strategy_root,
                archive_extract_root=archive_root,
                parse_root=parse_root,
                stage4_execution_root=stage4_execution_root,
                output_root=output_root,
                created_at="2026-05-11T00:00:00+08:00",
            )

            project = result["manifest"]["project_records"][0]
            flow_08 = next(row for row in result["manifest"]["flow_records"] if row["flow_no"] == "08")
            self.assertFalse(project["flow_08_targeted_parse_required"])
            self.assertNotIn("attachment_download_incomplete", project["blocking_layers"])
            self.assertFalse(flow_08["flow_08_targeted_parse_required"])
            self.assertNotIn("attachment_snapshot_incomplete_for_flow", flow_08["blocking_layers"])


def _write_flow_manifest(
    root: Path,
    *,
    include_only_candidate_project: bool = False,
    include_candidate_and_bid_publicity_project: bool = False,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    samples = [
        _sample("PROJ-CN-GD-JG2026-11111", "03", "招标公告/关联公告"),
        _sample("PROJ-CN-GD-JG2026-22222", "07", "中标候选人公示"),
    ]
    if include_only_candidate_project:
        samples = [_sample("PROJ-CN-GD-JG2026-22222", "07", "中标候选人公示")]
    if include_candidate_and_bid_publicity_project:
        samples = [
            _sample("PROJ-CN-GD-JG2026-22222", "07", "中标候选人公示"),
            _sample("PROJ-CN-GD-JG2026-22222", "08", "投标(资格预审申请)文件公开"),
        ]
    payload = {
        "manifest": {
            "manifest_kind": "evaluation_real_project_sample_execution_manifest",
            "project_sample_items": samples,
            "summary": {"unique_project_count": len({str(row["project_id"]) for row in samples}), "project_sample_count": len(samples)},
        }
    }
    (root / "run-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "flow-url-manifest.json").write_text(
        json.dumps({"manifest": {"manifest_kind": "guangzhou_flow_url_manifest", "summary": {"project_count": len({str(row["project_id"]) for row in samples}), "flow_url_count": len(samples)}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_analysis_plan(
    root: Path,
    *,
    include_only_candidate_project: bool = False,
    include_candidate_and_bid_publicity_project: bool = False,
) -> None:
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
        {
            "project_id": "PROJ-CN-GD-JG2026-22222",
            "flow_no": "08",
            "source_url": "https://example.test/22222/08.html",
            "download_policy": "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED",
            "parse_depth": "LIST_ONLY",
            "flow_08_targeted_parse_required": False,
        },
    ]
    if include_only_candidate_project:
        items = [item for item in items if item["project_id"] == "PROJ-CN-GD-JG2026-22222" and item["flow_no"] == "07"]
    if include_candidate_and_bid_publicity_project:
        items = [item for item in items if item["project_id"] == "PROJ-CN-GD-JG2026-22222"]
    (root / "analysis-plan.json").write_text(json.dumps({"manifest": {"items": items, "summary": {"project_count": 2}}}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_download_manifest(root: Path, *, partial: bool = False, complete_candidate: bool = False, complete_flow_no: str = "07") -> None:
    root.mkdir(parents=True, exist_ok=True)
    if complete_candidate:
        flow_title = "投标(资格预审申请)文件公开" if complete_flow_no == "08" else "中标候选人公示"
        samples = [
            {
                **_sample("PROJ-CN-GD-JG2026-22222", complete_flow_no, flow_title),
                "pipeline_stage": "DownloadProbe",
                "target_execution_state": "DOWNLOAD_PROBE_CAPTURED",
                "listed_attachment_count": 1,
                "download_attempted_count": 1,
                "failure_taxonomy": [],
                "attachment_snapshot_refs": [
                    {
                        "snapshot_id": "ATT-7",
                        "attachment_url": "https://example.test/candidate.pdf",
                        "content_type": "application/pdf",
                    }
                ],
            }
        ]
    else:
        samples = [
            {
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
        ]
    payload = {
        "manifest": {
            "project_sample_items": samples,
            "summary": {
                "unique_project_count": len({str(row["project_id"]) for row in samples}),
                "project_sample_count": len(samples),
                "download_attempted_count": sum(int(row["download_attempted_count"]) for row in samples),
                "attachment_snapshot_count": sum(len(row["attachment_snapshot_refs"]) for row in samples),
                "failure_taxonomy_counts": {} if complete_candidate else {"ATTACHMENT_INTERFACE_ERROR": 1},
            },
        }
    }
    filename = "download-probe-manifest.partial.json" if partial else "download-probe-manifest.json"
    (root / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_flow08_register_only_download_sample(root: Path) -> None:
    path = root / "download-probe-manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = payload["manifest"]
    samples = list(manifest.get("project_sample_items") or [])
    samples.append(
        {
            **_sample("PROJ-CN-GD-JG2026-22222", "08", "投标(资格预审申请)文件公开"),
            "pipeline_stage": "DownloadProbe",
            "target_execution_state": "DOWNLOAD_PROBE_REGISTER_ONLY",
            "listed_attachment_count": 3,
            "download_attempted_count": 0,
            "failure_taxonomy": [],
            "attachment_snapshot_refs": [],
        }
    )
    manifest["project_sample_items"] = samples
    manifest["summary"] = {
        **dict(manifest.get("summary") or {}),
        "unique_project_count": len({str(row["project_id"]) for row in samples}),
        "project_sample_count": len(samples),
        "download_attempted_count": sum(int(row.get("download_attempted_count") or 0) for row in samples),
        "attachment_snapshot_count": sum(len(row.get("attachment_snapshot_refs") or []) for row in samples),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _write_parse_manifest(root: Path, *, candidate_parse_review: bool = False, candidate_parse_flow_no: str = "07") -> None:
    root.mkdir(parents=True, exist_ok=True)
    flow_no = candidate_parse_flow_no if candidate_parse_review else "03"
    project_id = "PROJ-CN-GD-JG2026-22222" if candidate_parse_review else "PROJ-CN-GD-JG2026-11111"
    flow_title = "投标(资格预审申请)文件公开" if candidate_parse_review and flow_no == "08" else "中标候选人公示" if candidate_parse_review else "招标公告/关联公告"
    sample = {
        **_sample(project_id, flow_no, flow_title),
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
        "project_id": project_id,
        "flow_no": flow_no,
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


def _write_stage4_inputs(
    root: Path,
    *,
    flow_07_certificate: bool = False,
    flow_08_certificate: bool = False,
    non_07_certificate: bool = False,
) -> None:
    items = []
    if flow_07_certificate:
        items = [
            {
                "stage4_input_id": "STAGE4-CANDIDATE-INPUT-07",
                "project_id": "PROJ-CN-GD-JG2026-22222",
                "project_name": "PROJ-CN-GD-JG2026-22222测试项目",
                "flow_no": "07",
                "flow_title": "中标候选人公示",
                "project_manager_name": "张三",
                "project_manager_certificate_no": "粤1442020202100001",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        ]
    elif flow_08_certificate:
        items = [
            {
                "stage4_input_id": "STAGE4-CANDIDATE-INPUT-08",
                "project_id": "PROJ-CN-GD-JG2026-22222",
                "project_name": "PROJ-CN-GD-JG2026-22222测试项目",
                "flow_no": "08",
                "flow_title": "投标(资格预审申请)文件公开",
                "project_manager_name": "李四",
                "project_manager_certificate_no": "粤1442020202100002",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        ]
    elif non_07_certificate:
        items = [
            {
                "stage4_input_id": "STAGE4-CANDIDATE-INPUT-03",
                "project_id": "PROJ-CN-GD-JG2026-22222",
                "project_name": "PROJ-CN-GD-JG2026-22222测试项目",
                "flow_no": "03",
                "flow_title": "招标公告/关联公告",
                "project_manager_name": "张三",
                "project_manager_certificate_no": "粤1442020202100001",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        ]
    payload = {
        "manifest_kind": "stage4_candidate_verification_inputs_manifest",
        "items": items,
        "summary": {
            "stage4_input_count": len(items),
            "with_project_manager_count": sum(1 for item in items if item.get("project_manager_name")),
            "with_certificate_count": sum(1 for item in items if item.get("project_manager_certificate_no")),
        },
    }
    (root / "stage4_candidate_verification_inputs.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_stage4_execution_manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    members = ["云浮市易安停科技有限公司", "中裕工程集团有限公司", "北京神州新桥科技有限公司"]
    items = [
        {
            "project_id": "PROJ-CN-GD-JG2026-22222",
            "project_name": "PROJ-CN-GD-JG2026-22222测试项目",
            "flow_no": "07",
            "flow_title": "中标候选人公示",
            "candidate_group_id": "GROUP-22222-1",
            "candidate_group_order": 1,
            "candidate_group_members": members,
            "candidate_company_name": "云浮市易安停科技有限公司",
            "consortium_member_role": "lead",
            "responsible_person_name": "王立亮",
            "source_certificate_no_optional": "京1112017201745983",
            "resolved_certificate_no_optional": "王立亮",
            "supplement_after_execution_state": "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED",
            "candidate_group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER",
            "candidate_group_matched_company_name_optional": "北京神州新桥科技有限公司",
            "flow_08_targeted_parse_required": False,
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-22222",
            "project_name": "PROJ-CN-GD-JG2026-22222测试项目",
            "flow_no": "07",
            "flow_title": "中标候选人公示",
            "candidate_group_id": "GROUP-22222-1",
            "candidate_group_order": 1,
            "candidate_group_members": members,
            "candidate_company_name": "中裕工程集团有限公司",
            "consortium_member_role": "member",
            "responsible_person_name": "王立亮",
            "source_certificate_no_optional": "京1112017201745983",
            "supplement_after_execution_state": "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED",
            "candidate_group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER",
            "candidate_group_matched_company_name_optional": "北京神州新桥科技有限公司",
            "flow_08_targeted_parse_required": False,
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-22222",
            "project_name": "PROJ-CN-GD-JG2026-22222测试项目",
            "flow_no": "07",
            "flow_title": "中标候选人公示",
            "candidate_group_id": "GROUP-22222-1",
            "candidate_group_order": 1,
            "candidate_group_members": members,
            "candidate_company_name": "北京神州新桥科技有限公司",
            "consortium_member_role": "member",
            "responsible_person_name": "王立亮",
            "source_certificate_no_optional": "京1112017201745983",
            "resolved_certificate_no_optional": "京1112017201745983",
            "registered_unit_name_optional": "北京神州新桥科技有限公司",
            "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
            "candidate_group_resolution_state": "RESOLVED_BY_THIS_MEMBER",
            "candidate_group_matched_company_name_optional": "北京神州新桥科技有限公司",
            "flow_08_targeted_parse_required": False,
        },
    ]
    payload = {
        "manifest": {
            "manifest_kind": "company_first_stage4_execution_manifest",
            "items": items,
            "summary": {
                "job_count": len(items),
                "candidate_group_resolved_count": 1,
                "stage4_execution_state_counts": {"FAIL_CLOSED": 2, "READBACK_READY": 1},
            },
        }
    }
    (root / "company-first-stage4-execution.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
