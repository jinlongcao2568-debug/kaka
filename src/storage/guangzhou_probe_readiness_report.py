from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_UPSTREAM_READINESS_REPORT_KIND = "guangzhou_upstream_readiness_report_manifest"
GUANGZHOU_UPSTREAM_READINESS_REPORT_VERSION = 1
GUANGZHOU_UPSTREAM_READINESS_REPORT_ADAPTER_ID = "guangzhou-upstream-readiness-report-v1"


def build_guangzhou_upstream_readiness_report(
    *,
    flow_root: str | Path,
    download_root: str | Path,
    evidence_strategy_root: str | Path,
    archive_extract_root: str | Path,
    parse_root: str | Path,
    output_root: str | Path,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    flow_dir = Path(flow_root)
    download_dir = Path(download_root)
    strategy_dir = Path(evidence_strategy_root)
    archive_dir = Path(archive_extract_root)
    parse_dir = Path(parse_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    flow_manifest = _source_manifest(_load_json(flow_dir / "run-manifest.json", missing_inputs, "flow_run_manifest_missing"))
    flow_url_manifest = _source_manifest(_load_json(flow_dir / "flow-url-manifest.json", [], "flow_url_manifest_missing"))
    analysis_manifest = _source_manifest(_load_json(flow_dir / "analysis-plan.json", [], "analysis_plan_missing"))
    download_manifest = _source_manifest(_load_download_manifest(download_dir, missing_inputs))
    strategy_manifest = _source_manifest(_load_json(strategy_dir / "evidence-verification-strategy.json", [], "evidence_strategy_missing"))
    archive_manifest = _source_manifest(_load_json(archive_dir / "archive-extract-probe-manifest.json", [], "archive_extract_manifest_missing"))
    parse_manifest = _source_manifest(_load_json(parse_dir / "parse-probe-manifest.json", missing_inputs, "parse_probe_manifest_missing"))
    stage4_manifest = _source_manifest(_load_json(parse_dir / "stage4_candidate_verification_inputs.json", [], "stage4_inputs_missing"))

    project_ids = _project_ids(
        flow_manifest=flow_manifest,
        download_manifest=download_manifest,
        parse_manifest=parse_manifest,
        stage4_manifest=stage4_manifest,
    )
    project_records = [
        _project_record(
            project_id=project_id,
            flow_manifest=flow_manifest,
            analysis_manifest=analysis_manifest,
            download_manifest=download_manifest,
            strategy_manifest=strategy_manifest,
            archive_manifest=archive_manifest,
            parse_manifest=parse_manifest,
            stage4_manifest=stage4_manifest,
        )
        for project_id in project_ids
    ]
    flow_records = _flow_records(
        flow_manifest=flow_manifest,
        analysis_manifest=analysis_manifest,
        download_manifest=download_manifest,
        strategy_manifest=strategy_manifest,
        parse_manifest=parse_manifest,
        stage4_manifest=stage4_manifest,
    )
    summary = _summary(
        project_records=project_records,
        flow_records=flow_records,
        flow_manifest=flow_manifest,
        flow_url_manifest=flow_url_manifest,
        download_manifest=download_manifest,
        strategy_manifest=strategy_manifest,
        archive_manifest=archive_manifest,
        parse_manifest=parse_manifest,
        stage4_manifest=stage4_manifest,
        missing_inputs=missing_inputs,
    )
    manifest = {
        "manifest_version": GUANGZHOU_UPSTREAM_READINESS_REPORT_VERSION,
        "manifest_kind": GUANGZHOU_UPSTREAM_READINESS_REPORT_KIND,
        "adapter_id": GUANGZHOU_UPSTREAM_READINESS_REPORT_ADAPTER_ID,
        "pipeline_stage": "UpstreamReadinessReport",
        "manifest_id": f"GUANGZHOU-UPSTREAM-READINESS-{_fingerprint({'summary': summary, 'projects': project_records})[:16]}",
        "created_at": created,
        "source_flow_root": str(flow_dir),
        "source_download_root": str(download_dir),
        "source_evidence_strategy_root": str(strategy_dir),
        "source_archive_extract_root": str(archive_dir),
        "source_parse_root": str(parse_dir),
        "summary": summary,
        "project_records": project_records,
        "flow_records": flow_records,
        "repair_backlog": _repair_backlog(project_records=project_records, flow_records=flow_records, summary=summary),
        "safety": {
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_upstream_readiness_report_mode": "BUILT",
        "safe_to_continue_stage4": summary["safe_to_continue_stage4"],
        "blocking_reasons": summary["stage4_blocking_reasons"],
        "manifest": manifest,
        "summary": summary,
    }
    (out_dir / "guangzhou-upstream-readiness-report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _project_record(
    *,
    project_id: str,
    flow_manifest: Mapping[str, Any],
    analysis_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    strategy_manifest: Mapping[str, Any],
    archive_manifest: Mapping[str, Any],
    parse_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    flow_samples = _samples_for_project(flow_manifest, project_id)
    analysis_items = _items_for_project(analysis_manifest, project_id)
    download_samples = _samples_for_project(download_manifest, project_id)
    strategy_items = _items_for_project(strategy_manifest, project_id)
    archive_samples = _samples_for_project(archive_manifest, project_id)
    parse_samples = _samples_for_project(parse_manifest, project_id)
    parse_items = _items_for_project(parse_manifest, project_id)
    stage4_items = _items_for_project(stage4_manifest, project_id)
    project_name = _first_text(
        [item.get("project_name") for item in [*download_samples, *flow_samples, *parse_samples, *stage4_items]]
    )
    listed_attachments = sum(_listed_attachment_count(sample) for sample in download_samples)
    attempted_downloads = sum(_download_attempt_count(sample) for sample in download_samples)
    attachment_snapshots = sum(len(list(sample.get("attachment_snapshot_refs") or [])) for sample in download_samples)
    parse_attempted = sum(_int((sample.get("parse_metrics") or {}).get("parse_attempted_file_count")) for sample in parse_samples)
    parse_success = sum(_int((sample.get("parse_metrics") or {}).get("stage3_parse_success_count")) for sample in parse_samples)
    stage4_pm = sum(1 for item in stage4_items if item.get("project_manager_name"))
    stage4_cert = sum(1 for item in stage4_items if item.get("project_manager_certificate_no"))
    blockers = _project_blockers(
        flow_samples=flow_samples,
        download_samples=download_samples,
        parse_samples=parse_samples,
        stage4_items=stage4_items,
        listed_attachments=listed_attachments,
        attachment_snapshots=attachment_snapshots,
        parse_attempted=parse_attempted,
        parse_success=parse_success,
        stage4_pm=stage4_pm,
        stage4_cert=stage4_cert,
    )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "flow_url_count": len(flow_samples),
        "analysis_plan_item_count": len(analysis_items),
        "download_probe_flow_count": len(download_samples),
        "evidence_strategy_item_count": len(strategy_items),
        "archive_extract_sample_count": len(archive_samples),
        "parse_probe_flow_count": len(parse_samples),
        "stage4_input_count": len(stage4_items),
        "listed_attachment_count": listed_attachments,
        "download_attempted_count": attempted_downloads,
        "attachment_snapshot_count": attachment_snapshots,
        "download_snapshot_success_rate": _rate(attachment_snapshots, attempted_downloads or listed_attachments),
        "parse_attempted_file_count": parse_attempted,
        "parse_success_count": parse_success,
        "parse_success_rate": _rate(parse_success, parse_attempted),
        "stage4_project_manager_input_count": stage4_pm,
        "stage4_certificate_input_count": stage4_cert,
        "failure_taxonomy": _dedupe(
            reason
            for row in [*flow_samples, *download_samples, *parse_samples, *parse_items]
            for reason in list(row.get("failure_taxonomy") or row.get("parse_error_taxonomy") or [])
        ),
        "blocking_layers": blockers,
        "readiness_state": "READY_FOR_STAGE4_PROBE" if not blockers else "UPSTREAM_REPAIR_REQUIRED",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_records(
    *,
    flow_manifest: Mapping[str, Any],
    analysis_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    strategy_manifest: Mapping[str, Any],
    parse_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    keys: set[tuple[str, str]] = set()
    for row in [
        *list(flow_manifest.get("project_sample_items") or []),
        *list(download_manifest.get("project_sample_items") or []),
        *list(parse_manifest.get("project_sample_items") or []),
        *list(stage4_manifest.get("items") or []),
    ]:
        if isinstance(row, Mapping):
            project_id = str(row.get("project_id") or "")
            flow_no = _flow_no(row.get("guangzhou_flow_no") or row.get("flow_no"))
            if project_id and flow_no:
                keys.add((project_id, flow_no))
    records: list[dict[str, Any]] = []
    for project_id, flow_no in sorted(keys):
        flow_samples = _samples_for_project_flow(flow_manifest, project_id, flow_no)
        analysis_items = _items_for_project_flow(analysis_manifest, project_id, flow_no)
        download_samples = _samples_for_project_flow(download_manifest, project_id, flow_no)
        strategy_items = _items_for_project_flow(strategy_manifest, project_id, flow_no)
        parse_samples = _samples_for_project_flow(parse_manifest, project_id, flow_no)
        stage4_items = _items_for_project_flow(stage4_manifest, project_id, flow_no)
        listed = sum(_listed_attachment_count(sample) for sample in download_samples)
        attempted = sum(_download_attempt_count(sample) for sample in download_samples)
        snapshots = sum(len(list(sample.get("attachment_snapshot_refs") or [])) for sample in download_samples)
        parse_attempted = sum(_int((sample.get("parse_metrics") or {}).get("parse_attempted_file_count")) for sample in parse_samples)
        parse_success = sum(_int((sample.get("parse_metrics") or {}).get("stage3_parse_success_count")) for sample in parse_samples)
        flow_blockers = _flow_blockers(
            analysis_items=analysis_items,
            download_samples=download_samples,
            listed=listed,
            attempted=attempted,
            snapshots=snapshots,
            parse_samples=parse_samples,
            parse_attempted=parse_attempted,
            parse_success=parse_success,
            stage4_items=stage4_items,
        )
        records.append(
            {
                "project_id": project_id,
                "project_name": _first_text([row.get("project_name") for row in [*flow_samples, *download_samples, *parse_samples, *stage4_items]]),
                "flow_no": flow_no,
                "flow_title": _first_text([row.get("guangzhou_flow_title") or row.get("flow_title") for row in [*flow_samples, *download_samples, *parse_samples, *stage4_items]]),
                "source_urls": _dedupe(row.get("source_url") for row in [*flow_samples, *download_samples, *parse_samples, *stage4_items]),
                "analysis_download_policies": _counts(item.get("download_policy") for item in analysis_items),
                "analysis_parse_depths": _counts(item.get("parse_depth") for item in analysis_items),
                "download_state_counts": _counts(sample.get("target_execution_state") for sample in download_samples),
                "listed_attachment_count": listed,
                "download_attempted_count": attempted,
                "attachment_snapshot_count": snapshots,
                "download_snapshot_success_rate": _rate(snapshots, attempted or listed),
                "strategy_extract_policy_counts": _counts(item.get("extract_policy") for item in strategy_items),
                "parse_state_counts": _counts(item.get("parse_probe_state") or item.get("stage3_parse_state") for item in parse_samples),
                "parse_attempted_file_count": parse_attempted,
                "parse_success_count": parse_success,
                "parse_success_rate": _rate(parse_success, parse_attempted),
                "stage4_input_count": len(stage4_items),
                "stage4_project_manager_input_count": sum(1 for item in stage4_items if item.get("project_manager_name")),
                "stage4_certificate_input_count": sum(1 for item in stage4_items if item.get("project_manager_certificate_no")),
                "failure_taxonomy": _dedupe(
                    reason
                    for row in [*flow_samples, *download_samples, *parse_samples]
                    for reason in list(row.get("failure_taxonomy") or row.get("parse_error_taxonomy") or [])
                ),
                "blocking_layers": flow_blockers,
                "readiness_state": "FLOW_READY_FOR_NEXT_PROBE" if not flow_blockers else "FLOW_REPAIR_REQUIRED",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _summary(
    *,
    project_records: list[Mapping[str, Any]],
    flow_records: list[Mapping[str, Any]],
    flow_manifest: Mapping[str, Any],
    flow_url_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    strategy_manifest: Mapping[str, Any],
    archive_manifest: Mapping[str, Any],
    parse_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
    missing_inputs: list[str],
) -> dict[str, Any]:
    flow_summary = dict(flow_manifest.get("summary") or {})
    flow_url_summary = dict(flow_url_manifest.get("summary") or {})
    download_summary = dict(download_manifest.get("summary") or {})
    strategy_summary = dict(strategy_manifest.get("summary") or {})
    archive_summary = dict(archive_manifest.get("summary") or {})
    parse_summary = dict(parse_manifest.get("summary") or {})
    stage4_summary = dict(stage4_manifest.get("summary") or {})
    flow_project_count = _int(flow_summary.get("unique_project_count") or flow_url_summary.get("project_count"))
    download_project_count = _int(download_summary.get("unique_project_count") or download_summary.get("project_sample_count"))
    stage4_pm = _int(stage4_summary.get("with_project_manager_count"))
    stage4_cert = _int(stage4_summary.get("with_certificate_count"))
    blocking = []
    if missing_inputs:
        blocking.extend(missing_inputs)
    if flow_project_count and download_project_count and download_project_count < flow_project_count:
        blocking.append("download_probe_project_coverage_below_flowurl_projects")
    if _rate(_int(download_summary.get("attachment_snapshot_count")), _int(download_summary.get("download_attempted_count"))) < 0.8:
        blocking.append("attachment_snapshot_success_rate_below_target")
    if _int(download_summary.get("timeout_interrupted_count")) > 0:
        blocking.append("download_probe_timeout_interrupted")
    if _int(download_summary.get("partial_segment_count")) > 0:
        blocking.append("download_probe_partial_segment_present")
    if _rate(_int(parse_summary.get("parse_success_count")), _int(parse_summary.get("parse_attempted_file_count"))) < 0.8:
        blocking.append("parse_success_rate_below_target")
    if stage4_pm == 0:
        blocking.append("stage4_project_manager_inputs_missing")
    if stage4_cert == 0:
        blocking.append("stage4_certificate_inputs_missing")
    return {
        "readiness_state": "READY_FOR_STAGE4_PROBE" if not blocking else "UPSTREAM_NOT_READY_FOR_STAGE4",
        "safe_to_continue_stage4": not blocking,
        "stage4_blocking_reasons": _dedupe(blocking),
        "flowurl_project_count": flow_project_count,
        "flowurl_flow_count": _int(flow_summary.get("project_sample_count") or flow_url_summary.get("flow_url_count")),
        "download_probe_project_count": download_project_count,
        "download_probe_flow_count": _int(download_summary.get("project_sample_count")),
        "download_attempted_count": _int(download_summary.get("download_attempted_count")),
        "attachment_snapshot_count": _int(download_summary.get("attachment_snapshot_count")),
        "attachment_snapshot_success_rate": _rate(_int(download_summary.get("attachment_snapshot_count")), _int(download_summary.get("download_attempted_count"))),
        "evidence_strategy_item_count": _int(strategy_summary.get("strategy_item_count")),
        "archive_extract_state": str(archive_summary.get("archive_extract_state") or ""),
        "archive_child_snapshot_count": _int(archive_summary.get("child_snapshot_count")),
        "parse_attempted_file_count": _int(parse_summary.get("parse_attempted_file_count")),
        "parse_success_count": _int(parse_summary.get("parse_success_count")),
        "parse_success_rate": _rate(_int(parse_summary.get("parse_success_count")), _int(parse_summary.get("parse_attempted_file_count"))),
        "parse_review_required_count": _int(parse_summary.get("parse_review_required_count")),
        "stage4_input_count": _int(stage4_summary.get("stage4_input_count")),
        "stage4_project_manager_input_count": stage4_pm,
        "stage4_certificate_input_count": stage4_cert,
        "project_repair_required_count": sum(1 for row in project_records if row.get("readiness_state") != "READY_FOR_STAGE4_PROBE"),
        "flow_repair_required_count": sum(1 for row in flow_records if row.get("readiness_state") != "FLOW_READY_FOR_NEXT_PROBE"),
        "download_failure_taxonomy_counts": dict(download_summary.get("failure_taxonomy_counts") or {}),
        "download_segment_state_counts": dict(download_summary.get("segment_state_counts") or {}),
        "download_deferred_attachment_count": _int(download_summary.get("deferred_attachment_count")),
        "parse_failure_taxonomy_counts": dict(parse_summary.get("parse_failure_taxonomy_counts") or {}),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _repair_backlog(*, project_records: list[Mapping[str, Any]], flow_records: list[Mapping[str, Any]], summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    backlog: list[dict[str, Any]] = []
    if "download_probe_project_coverage_below_flowurl_projects" in summary.get("stage4_blocking_reasons", []):
        backlog.append(
            {
                "priority": 1,
                "repair_layer": "DownloadProbeCoverage",
                "repair_action": "扩大 DownloadProbe 输入到 FlowUrlOnly 已发现的 5 个项目，先不要进入 Stage4。",
                "evidence": {
                    "flowurl_project_count": summary.get("flowurl_project_count"),
                    "download_probe_project_count": summary.get("download_probe_project_count"),
                },
            }
        )
    if "attachment_snapshot_success_rate_below_target" in summary.get("stage4_blocking_reasons", []):
        backlog.append(
            {
                "priority": 2,
                "repair_layer": "Stage2AttachmentDownload",
                "repair_action": "按项目/流程修附件接口失败、过期链接和非下载导航误入，目标附件 snapshot 成功率先到 80%。",
                "evidence": summary.get("download_failure_taxonomy_counts"),
            }
        )
    if any(reason in summary.get("stage4_blocking_reasons", []) for reason in ("download_probe_timeout_interrupted", "download_probe_partial_segment_present", "download_probe_partial_manifest_used")):
        backlog.append(
            {
                "priority": 2,
                "repair_layer": "DownloadRepairResume",
                "repair_action": "按 08/07/04/03 分段续跑 DownloadRepair，优先补齐 timeout/partial segment，不进入 Stage4。",
                "evidence": {
                    "download_segment_state_counts": summary.get("download_segment_state_counts"),
                    "download_probe_project_count": summary.get("download_probe_project_count"),
                },
            }
        )
    if "parse_success_rate_below_target" in summary.get("stage4_blocking_reasons", []):
        backlog.append(
            {
                "priority": 3,
                "repair_layer": "Stage3ParseProbe",
                "repair_action": "优先修 MarkItDown 空文本、UnsupportedFormat 和表格歧义；必要时引入 OCR/Office 专项解析。",
                "evidence": summary.get("parse_failure_taxonomy_counts"),
            }
        )
    if any(reason in summary.get("stage4_blocking_reasons", []) for reason in ("stage4_project_manager_inputs_missing", "stage4_certificate_inputs_missing")):
        backlog.append(
            {
                "priority": 4,
                "repair_layer": "FieldExtraction",
                "repair_action": "先提升 07 候选公示和 08 投标文件公开里的项目负责人、证书编号抽取，再接 Stage4 核验。",
                "evidence": {
                    "stage4_project_manager_input_count": summary.get("stage4_project_manager_input_count"),
                    "stage4_certificate_input_count": summary.get("stage4_certificate_input_count"),
                },
            }
        )
    for record in flow_records:
        if not record.get("blocking_layers"):
            continue
        backlog.append(
            {
                "priority": 10,
                "repair_layer": "ProjectFlow",
                "project_id": record.get("project_id"),
                "flow_no": record.get("flow_no"),
                "flow_title": record.get("flow_title"),
                "repair_action": "查看该项目流程的 blocking_layers 和 failure_taxonomy 后定向修复。",
                "blocking_layers": record.get("blocking_layers"),
                "failure_taxonomy": record.get("failure_taxonomy"),
                "source_urls": record.get("source_urls"),
            }
        )
    return backlog


def _project_blockers(
    *,
    flow_samples: list[Mapping[str, Any]],
    download_samples: list[Mapping[str, Any]],
    parse_samples: list[Mapping[str, Any]],
    stage4_items: list[Mapping[str, Any]],
    listed_attachments: int,
    attachment_snapshots: int,
    parse_attempted: int,
    parse_success: int,
    stage4_pm: int,
    stage4_cert: int,
) -> list[str]:
    blockers: list[str] = []
    if flow_samples and not download_samples:
        blockers.append("download_probe_not_run_for_project")
    if listed_attachments and attachment_snapshots < listed_attachments:
        blockers.append("attachment_download_incomplete")
    if parse_attempted and parse_success < parse_attempted:
        blockers.append("parse_incomplete")
    if parse_samples and not stage4_items:
        blockers.append("stage4_inputs_not_generated")
    if stage4_items and stage4_pm == 0:
        blockers.append("project_manager_input_missing")
    if stage4_items and stage4_cert == 0:
        blockers.append("certificate_input_missing")
    return blockers


def _flow_blockers(
    *,
    analysis_items: list[Mapping[str, Any]],
    download_samples: list[Mapping[str, Any]],
    listed: int,
    attempted: int,
    snapshots: int,
    parse_samples: list[Mapping[str, Any]],
    parse_attempted: int,
    parse_success: int,
    stage4_items: list[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    download_required = any(str(item.get("download_policy") or "").startswith("DOWNLOAD") or str(item.get("download_policy") or "") == "LIST_ALL_THEN_TARGETED_DOWNLOAD" for item in analysis_items)
    if download_required and not download_samples:
        blockers.append("download_probe_not_run_for_required_flow")
    if listed and snapshots < (attempted or listed):
        blockers.append("attachment_snapshot_incomplete_for_flow")
    if parse_attempted and parse_success < parse_attempted:
        blockers.append("parse_incomplete_for_flow")
    if parse_samples and not stage4_items and any(_flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no")) in {"07", "08"} for sample in parse_samples):
        blockers.append("candidate_stage4_input_missing_for_flow")
    return blockers


def _project_ids(*, flow_manifest: Mapping[str, Any], download_manifest: Mapping[str, Any], parse_manifest: Mapping[str, Any], stage4_manifest: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()
    for manifest in (flow_manifest, download_manifest, parse_manifest):
        for sample in list(manifest.get("project_sample_items") or []):
            if isinstance(sample, Mapping) and sample.get("project_id"):
                values.add(str(sample.get("project_id")))
    for item in list(stage4_manifest.get("items") or []):
        if isinstance(item, Mapping) and item.get("project_id"):
            values.add(str(item.get("project_id")))
    return sorted(values)


def _samples_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in list(manifest.get("project_sample_items") or []) if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id]


def _items_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in list(manifest.get("items") or []) if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id]


def _samples_for_project_flow(manifest: Mapping[str, Any], project_id: str, flow_no: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list(manifest.get("project_sample_items") or [])
        if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id and _flow_no(row.get("guangzhou_flow_no") or row.get("flow_no")) == flow_no
    ]


def _items_for_project_flow(manifest: Mapping[str, Any], project_id: str, flow_no: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list(manifest.get("items") or [])
        if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id and _flow_no(row.get("guangzhou_flow_no") or row.get("flow_no")) == flow_no
    ]


def _listed_attachment_count(sample: Mapping[str, Any]) -> int:
    return _int(sample.get("listed_attachment_count") or sample.get("attachment_link_count") or len(list(sample.get("listed_attachment_items") or [])) or len(list(sample.get("attachment_snapshot_refs") or [])))


def _download_attempt_count(sample: Mapping[str, Any]) -> int:
    return _int(sample.get("download_attempted_count") or sample.get("attachment_download_attempt_count") or len(list(sample.get("attachment_download_attempts") or [])) or len(list(sample.get("attachment_snapshot_refs") or [])))


def _load_json(path: Path, missing_inputs: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        missing_inputs.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _load_download_manifest(download_dir: Path, missing_inputs: list[str]) -> dict[str, Any]:
    candidates = [
        (download_dir / "download-probe-manifest.json", ""),
        (download_dir / "download-repair-merged-manifest.json", ""),
        (download_dir / "download-probe-manifest.partial.json", "download_probe_partial_manifest_used"),
    ]
    for path, marker in candidates:
        if path.exists():
            if marker:
                missing_inputs.append(marker)
            data = json.loads(path.read_text(encoding="utf-8"))
            return dict(data) if isinstance(data, Mapping) else {}
    missing_inputs.append("download_probe_manifest_missing")
    return {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _flow_no(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(2) if text else ""


def _first_text(values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou upstream readiness report.")
    parser.add_argument("--flow-root", required=True)
    parser.add_argument("--download-root", required=True)
    parser.add_argument("--evidence-strategy-root", required=True)
    parser.add_argument("--archive-extract-root", required=True)
    parser.add_argument("--parse-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_upstream_readiness_report(
        flow_root=args.flow_root,
        download_root=args.download_root,
        evidence_strategy_root=args.evidence_strategy_root,
        archive_extract_root=args.archive_extract_root,
        parse_root=args.parse_root,
        output_root=args.output_root,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "guangzhou-upstream-readiness-report.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"guangzhou upstream readiness built: safe_to_continue_stage4={result['safe_to_continue_stage4']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GUANGZHOU_UPSTREAM_READINESS_REPORT_KIND",
    "build_guangzhou_upstream_readiness_report",
]
