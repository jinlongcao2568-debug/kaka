from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_UPSTREAM_READINESS_REPORT_KIND = "guangzhou_upstream_readiness_report_manifest"
GUANGZHOU_UPSTREAM_READINESS_REPORT_VERSION = 1
GUANGZHOU_UPSTREAM_READINESS_REPORT_ADAPTER_ID = "guangzhou-upstream-readiness-report-v1"
_CANDIDATE_CERTIFICATE_READY_STATES = {
    "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION",
    "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION_FROM_FLOW_08_FALLBACK",
}
_CANDIDATE_CERTIFICATE_GATE_STATES = {
    *_CANDIDATE_CERTIFICATE_READY_STATES,
    "CERTIFICATE_MISSING_PARSE_REQUIRED",
}


def build_guangzhou_upstream_readiness_report(
    *,
    flow_root: str | Path,
    download_root: str | Path,
    evidence_strategy_root: str | Path,
    archive_extract_root: str | Path,
    parse_root: str | Path,
    output_root: str | Path,
    stage4_execution_root: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    flow_dir = Path(flow_root)
    download_dir = Path(download_root)
    strategy_dir = Path(evidence_strategy_root)
    archive_dir = Path(archive_extract_root)
    parse_dir = Path(parse_root)
    stage4_execution_dir = Path(stage4_execution_root) if stage4_execution_root else None
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
    stage4_execution_manifest = _source_manifest(
        _load_json(stage4_execution_dir / "company-first-stage4-execution.json", [], "stage4_execution_manifest_missing")
        if stage4_execution_dir
        else {}
    )

    project_ids = _project_ids(
        flow_manifest=flow_manifest,
        download_manifest=download_manifest,
        parse_manifest=parse_manifest,
        stage4_manifest=stage4_manifest,
        stage4_execution_manifest=stage4_execution_manifest,
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
            stage4_execution_manifest=stage4_execution_manifest,
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
        stage4_execution_manifest=stage4_execution_manifest,
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
        stage4_execution_manifest=stage4_execution_manifest,
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
        "source_stage4_execution_root_optional": str(stage4_execution_dir or ""),
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
    stage4_execution_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    flow_samples = _samples_for_project(flow_manifest, project_id)
    analysis_items = _items_for_project(analysis_manifest, project_id)
    download_samples = _samples_for_project(download_manifest, project_id)
    strategy_items = _items_for_project(strategy_manifest, project_id)
    archive_samples = _samples_for_project(archive_manifest, project_id)
    parse_samples = _samples_for_project(parse_manifest, project_id)
    parse_items = _items_for_project(parse_manifest, project_id)
    stage4_items = _items_for_project(stage4_manifest, project_id)
    stage4_execution_items = _items_for_project(stage4_execution_manifest, project_id)
    candidate_group_records = _candidate_group_verification_records(stage4_execution_items)
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
    flow_07_stage4_items = [item for item in stage4_items if _flow_no(item.get("flow_no") or item.get("guangzhou_flow_no")) == "07"]
    flow_08_stage4_items = [item for item in stage4_items if _flow_no(item.get("flow_no") or item.get("guangzhou_flow_no")) == "08"]
    flow_07_cert = sum(1 for item in flow_07_stage4_items if item.get("project_manager_certificate_no"))
    flow_08_cert = sum(1 for item in flow_08_stage4_items if item.get("project_manager_certificate_no"))
    candidate_cert = flow_07_cert + flow_08_cert
    has_candidate_evidence_sample = any(_flow_no(row.get("guangzhou_flow_no") or row.get("flow_no")) in {"07", "08"} for row in [*flow_samples, *parse_samples, *stage4_items])
    flow_08_targeted_required = _flow_08_targeted_parse_required(
        analysis_items=analysis_items,
        stage4_items=stage4_items,
        candidate_group_records=candidate_group_records,
    )
    download_samples_for_gate = [
        sample
        for sample in download_samples
        if not (_flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no")) == "08" and not flow_08_targeted_required)
    ]
    listed_attachments_for_gate = sum(_listed_attachment_count(sample) for sample in download_samples_for_gate)
    attachment_snapshots_for_gate = sum(len(list(sample.get("attachment_snapshot_refs") or [])) for sample in download_samples_for_gate)
    blockers = _project_blockers(
        flow_samples=flow_samples,
        download_samples=download_samples_for_gate,
        parse_samples=parse_samples,
        stage4_items=stage4_items,
        listed_attachments=listed_attachments_for_gate,
        attachment_snapshots=attachment_snapshots_for_gate,
        parse_attempted=parse_attempted,
        parse_success=parse_success,
        stage4_pm=stage4_pm,
        stage4_cert=stage4_cert,
        candidate_certificate_inputs=candidate_cert,
    )
    candidate_gate_state = _candidate_certificate_gate_state(
        flow_07_certificate_inputs=flow_07_cert,
        flow_08_certificate_inputs=flow_08_cert,
        has_candidate_evidence_sample=has_candidate_evidence_sample,
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
        "flow_07_stage4_input_count": len(flow_07_stage4_items),
        "flow_07_certificate_input_count": flow_07_cert,
        "flow_08_stage4_input_count": len(flow_08_stage4_items),
        "flow_08_certificate_input_count": flow_08_cert,
        "flow_08_targeted_parse_required": flow_08_targeted_required,
        "candidate_evidence_certificate_input_count": candidate_cert,
        "candidate_evidence_certificate_source_flows": _dedupe(
            flow
            for flow, count in (("07", flow_07_cert), ("08", flow_08_cert))
            if count > 0
        ),
        "candidate_evidence_certificate_gate_state": candidate_gate_state,
        "candidate_group_verification_records": candidate_group_records,
        "candidate_group_verification_summary": _candidate_group_summary(candidate_group_records),
        "flow_07_certificate_gate_state": (
            "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION"
            if flow_07_cert > 0
            else "CERTIFICATE_MISSING_PARSE_REQUIRED"
            if flow_07_stage4_items or any(_flow_no(row.get("guangzhou_flow_no") or row.get("flow_no")) == "07" for row in [*flow_samples, *parse_samples])
            else "NO_FLOW_07_SAMPLE"
        ),
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
    stage4_execution_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    keys: set[tuple[str, str]] = set()
    for row in [
        *list(flow_manifest.get("project_sample_items") or []),
        *list(download_manifest.get("project_sample_items") or []),
        *list(parse_manifest.get("project_sample_items") or []),
        *list(stage4_manifest.get("items") or []),
        *list(stage4_execution_manifest.get("items") or []),
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
        stage4_execution_items = _items_for_project_flow(stage4_execution_manifest, project_id, flow_no)
        candidate_group_records = _candidate_group_verification_records(stage4_execution_items)
        listed = sum(_listed_attachment_count(sample) for sample in download_samples)
        attempted = sum(_download_attempt_count(sample) for sample in download_samples)
        snapshots = sum(len(list(sample.get("attachment_snapshot_refs") or [])) for sample in download_samples)
        parse_attempted = sum(_int((sample.get("parse_metrics") or {}).get("parse_attempted_file_count")) for sample in parse_samples)
        parse_success = sum(_int((sample.get("parse_metrics") or {}).get("stage3_parse_success_count")) for sample in parse_samples)
        stage4_pm = sum(1 for item in stage4_items if item.get("project_manager_name"))
        stage4_cert = sum(1 for item in stage4_items if item.get("project_manager_certificate_no"))
        flow_08_targeted_required = _flow_08_targeted_parse_required(
            analysis_items=analysis_items,
            stage4_items=stage4_items,
            candidate_group_records=candidate_group_records,
        )
        flow_blockers = _flow_blockers(
            flow_no=flow_no,
            analysis_items=analysis_items,
            download_samples=download_samples,
            listed=listed,
            attempted=attempted,
            snapshots=snapshots,
            parse_samples=parse_samples,
            parse_attempted=parse_attempted,
            parse_success=parse_success,
            stage4_items=stage4_items,
            stage4_certificate_inputs=stage4_cert,
            flow_08_targeted_parse_required=flow_08_targeted_required,
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
                "stage4_project_manager_input_count": stage4_pm,
                "stage4_certificate_input_count": stage4_cert,
                "flow_08_targeted_parse_required": flow_08_targeted_required,
                "flow_07_certificate_gate_state": (
                    "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION"
                    if flow_no == "07" and stage4_cert > 0
                    else "CERTIFICATE_MISSING_PARSE_REQUIRED"
                    if flow_no == "07"
                    else "NOT_FLOW_07"
                ),
                "candidate_group_verification_records": candidate_group_records,
                "candidate_group_verification_summary": _candidate_group_summary(candidate_group_records),
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
    stage4_execution_manifest: Mapping[str, Any],
    missing_inputs: list[str],
) -> dict[str, Any]:
    flow_summary = dict(flow_manifest.get("summary") or {})
    flow_url_summary = dict(flow_url_manifest.get("summary") or {})
    download_summary = dict(download_manifest.get("summary") or {})
    strategy_summary = dict(strategy_manifest.get("summary") or {})
    archive_summary = dict(archive_manifest.get("summary") or {})
    parse_summary = dict(parse_manifest.get("summary") or {})
    stage4_summary = dict(stage4_manifest.get("summary") or {})
    stage4_execution_summary = dict(stage4_execution_manifest.get("summary") or {})
    candidate_group_records = _candidate_group_verification_records(
        [dict(item) for item in list(stage4_execution_manifest.get("items") or []) if isinstance(item, Mapping)]
    )
    candidate_group_summary = _candidate_group_summary(candidate_group_records)
    candidate_group_resolved_count = _int(candidate_group_summary.get("resolved_group_count"))
    candidate_group_unresolved_count = _int(candidate_group_summary.get("unresolved_group_count"))
    candidate_group_resolved_project_ids = {
        str(row.get("project_id") or "")
        for row in candidate_group_records
        if row.get("group_resolution_state") == "RESOLVED_BY_CONSORTIUM_MEMBER"
    }
    candidate_group_unresolved_project_ids = {
        str(row.get("project_id") or "")
        for row in candidate_group_records
        if row.get("group_resolution_state") == "UNRESOLVED_NO_MEMBER_MATCHED"
    }
    flow_project_count = _int(flow_summary.get("unique_project_count") or flow_url_summary.get("project_count"))
    download_project_count = _int(download_summary.get("unique_project_count") or download_summary.get("project_sample_count"))
    stage4_pm = _int(stage4_summary.get("with_project_manager_count"))
    stage4_cert = _int(stage4_summary.get("with_certificate_count"))
    stage4_items = [dict(item) for item in list(stage4_manifest.get("items") or []) if isinstance(item, Mapping)]
    flow_07_stage4_items = [item for item in stage4_items if _flow_no(item.get("flow_no") or item.get("guangzhou_flow_no")) == "07"]
    flow_08_stage4_items = [item for item in stage4_items if _flow_no(item.get("flow_no") or item.get("guangzhou_flow_no")) == "08"]
    flow_07_pm = sum(1 for item in flow_07_stage4_items if item.get("project_manager_name"))
    flow_07_cert = sum(1 for item in flow_07_stage4_items if item.get("project_manager_certificate_no"))
    flow_08_pm = sum(1 for item in flow_08_stage4_items if item.get("project_manager_name"))
    flow_08_cert = sum(1 for item in flow_08_stage4_items if item.get("project_manager_certificate_no"))
    candidate_cert = flow_07_cert + flow_08_cert
    candidate_certificate_gate_ready = candidate_cert > 0 or candidate_group_resolved_count > 0
    flow_07_project_count = sum(1 for row in project_records if row.get("flow_07_certificate_gate_state") in {"READY_FOR_STAGE4_CERTIFICATE_VERIFICATION", "CERTIFICATE_MISSING_PARSE_REQUIRED"})
    flow_07_projects_with_certificate_count = sum(1 for row in project_records if row.get("flow_07_certificate_gate_state") == "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION")
    flow_07_projects_missing_certificate_count = sum(1 for row in project_records if row.get("flow_07_certificate_gate_state") == "CERTIFICATE_MISSING_PARSE_REQUIRED")
    candidate_project_count = sum(1 for row in project_records if row.get("candidate_evidence_certificate_gate_state") in _CANDIDATE_CERTIFICATE_GATE_STATES)
    candidate_projects_with_certificate_count = sum(1 for row in project_records if row.get("candidate_evidence_certificate_gate_state") in _CANDIDATE_CERTIFICATE_READY_STATES)
    candidate_projects_with_flow_07_certificate_count = sum(1 for row in project_records if row.get("candidate_evidence_certificate_gate_state") == "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION")
    candidate_projects_with_flow_08_fallback_certificate_count = sum(1 for row in project_records if row.get("candidate_evidence_certificate_gate_state") == "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION_FROM_FLOW_08_FALLBACK")
    candidate_projects_missing_certificate_count = sum(1 for row in project_records if row.get("candidate_evidence_certificate_gate_state") == "CERTIFICATE_MISSING_PARSE_REQUIRED")
    parse_success_rate = _rate(_int(parse_summary.get("parse_success_count")), _int(parse_summary.get("parse_attempted_file_count")))
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
    if parse_success_rate < 0.8 and not candidate_certificate_gate_ready:
        blocking.append("parse_success_rate_below_target")
    if not candidate_certificate_gate_ready:
        blocking.append("candidate_evidence_certificate_inputs_missing_parse_required")
    if candidate_group_unresolved_count > 0:
        blocking.append("candidate_group_unresolved_flow08_required")
    safe_to_continue_stage4 = not blocking
    if safe_to_continue_stage4 and candidate_projects_missing_certificate_count > 0:
        readiness_state = "READY_FOR_STAGE4_PROBE_PARTIAL_CANDIDATE_CERTIFICATE_SCOPE"
        stage4_execution_scope = "CANDIDATE_CERTIFICATE_READY_PROJECTS_ONLY"
    elif safe_to_continue_stage4:
        readiness_state = "READY_FOR_STAGE4_PROBE"
        stage4_execution_scope = "ALL_READY_CANDIDATE_CERTIFICATE_PROJECTS"
    elif candidate_group_resolved_count > 0 and candidate_group_unresolved_count == 0:
        readiness_state = "STAGE4_GROUP_VERIFICATION_READY_PARSE_DEFERRED"
        stage4_execution_scope = "CANDIDATE_GROUPS_RESOLVED_PARSE_DEFERRED"
    elif candidate_group_resolved_count > 0:
        readiness_state = "STAGE4_GROUP_VERIFICATION_PARTIAL_REVIEW_REQUIRED"
        stage4_execution_scope = "RESOLVED_GROUPS_READY_UNRESOLVED_REQUIRE_FLOW_08"
    else:
        readiness_state = "UPSTREAM_NOT_READY_FOR_STAGE4"
        stage4_execution_scope = "BLOCKED_UNTIL_CANDIDATE_CERTIFICATE"
    return {
        "readiness_state": readiness_state,
        "safe_to_continue_stage4": safe_to_continue_stage4,
        "stage4_execution_scope": stage4_execution_scope,
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
        "parse_success_rate": parse_success_rate,
        "parse_success_rate_gate_state": (
            "DEFERRED_AFTER_CANDIDATE_CERTIFICATE_GATE"
            if parse_success_rate < 0.8 and candidate_certificate_gate_ready
            else "BLOCKING_UNTIL_CANDIDATE_CERTIFICATE"
            if parse_success_rate < 0.8
            else "PASS"
        ),
        "parse_review_required_count": _int(parse_summary.get("parse_review_required_count")),
        "stage4_input_count": _int(stage4_summary.get("stage4_input_count")),
        "stage4_execution_job_count": _int(stage4_execution_summary.get("job_count")),
        "stage4_execution_state_counts": dict(stage4_execution_summary.get("stage4_execution_state_counts") or {}),
        "candidate_group_verification_summary": candidate_group_summary,
        "candidate_group_verification_records": candidate_group_records,
        "candidate_group_resolved_project_count": len(candidate_group_resolved_project_ids),
        "candidate_group_unresolved_project_count": len(candidate_group_unresolved_project_ids),
        "candidate_group_stage4_gate_state": (
            "PARTIAL_GROUPS_REQUIRE_FLOW_08"
            if candidate_group_resolved_count > 0 and candidate_group_unresolved_count > 0
            else "GROUPS_RESOLVED"
            if candidate_group_resolved_count > 0
            else "NOT_RUN"
        ),
        "stage4_project_manager_input_count": stage4_pm,
        "stage4_certificate_input_count": stage4_cert,
        "flow_07_stage4_input_count": len(flow_07_stage4_items),
        "flow_07_project_manager_input_count": flow_07_pm,
        "flow_07_certificate_input_count": flow_07_cert,
        "flow_08_stage4_input_count": len(flow_08_stage4_items),
        "flow_08_project_manager_input_count": flow_08_pm,
        "flow_08_certificate_input_count": flow_08_cert,
        "candidate_evidence_certificate_input_count": candidate_cert,
        "candidate_evidence_certificate_source_flows": _dedupe(
            flow
            for flow, count in (("07", flow_07_cert), ("08", flow_08_cert))
            if count > 0
        ),
        "candidate_evidence_project_count": candidate_project_count,
        "candidate_evidence_projects_with_certificate_count": candidate_projects_with_certificate_count,
        "candidate_evidence_projects_with_flow_07_certificate_count": candidate_projects_with_flow_07_certificate_count,
        "candidate_evidence_projects_with_flow_08_fallback_certificate_count": candidate_projects_with_flow_08_fallback_certificate_count,
        "candidate_evidence_projects_missing_certificate_count": candidate_projects_missing_certificate_count,
        "candidate_evidence_certificate_gate_state": (
            "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION"
            if flow_07_cert > 0
            else "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION_FROM_FLOW_08_FALLBACK"
            if flow_08_cert > 0
            else "READY_FROM_CANDIDATE_GROUP_STAGE4"
            if candidate_group_resolved_count > 0
            else "CERTIFICATE_MISSING_PARSE_REQUIRED"
        ),
        "flow_07_project_count": flow_07_project_count,
        "flow_07_projects_with_certificate_count": flow_07_projects_with_certificate_count,
        "flow_07_projects_missing_certificate_count": flow_07_projects_missing_certificate_count,
        "flow_07_certificate_gate_state": (
            "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION"
            if flow_07_cert > 0
            else "CERTIFICATE_MISSING_PARSE_REQUIRED"
        ),
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
                "repair_action": "07 候选线尚未抽到证书，继续修候选公示附件解析；必要时引入 OCR/Office 表格专项解析。",
                "evidence": summary.get("parse_failure_taxonomy_counts"),
            }
        )
    if summary.get("parse_success_rate_gate_state") == "DEFERRED_AFTER_CANDIDATE_CERTIFICATE_GATE":
        backlog.append(
            {
                "priority": 3,
                "repair_layer": "DeferredStage3ParseProbe",
                "repair_action": "候选证据线已抽到证书，允许先走 Stage4 核验；03/04/08 其他解析不足暂缓为后续证据补强任务。",
                "evidence": {
                    "parse_success_rate": summary.get("parse_success_rate"),
                    "candidate_evidence_certificate_input_count": summary.get("candidate_evidence_certificate_input_count"),
                    "candidate_evidence_certificate_source_flows": summary.get("candidate_evidence_certificate_source_flows"),
                },
            }
        )
    if "candidate_evidence_certificate_inputs_missing_parse_required" in summary.get("stage4_blocking_reasons", []):
        backlog.append(
            {
                "priority": 1,
                "repair_layer": "CandidateEvidenceCertificateExtraction",
                "repair_action": "先解析 07 中标候选人公示及副本附件；若 07 无证书，再解析 08 投标/资格预审申请文件公开，目标先抽到项目负责人证书号。",
                "evidence": {
                    "candidate_evidence_certificate_input_count": summary.get("candidate_evidence_certificate_input_count"),
                    "flow_07_certificate_input_count": summary.get("flow_07_certificate_input_count"),
                    "flow_08_certificate_input_count": summary.get("flow_08_certificate_input_count"),
                },
            }
        )
    if "candidate_group_unresolved_flow08_required" in summary.get("stage4_blocking_reasons", []):
        backlog.append(
            {
                "priority": 1,
                "repair_layer": "CandidateGroupFlow08TargetedParse",
                "repair_action": "候选组公司优先补证仍未匹配的负责人，进入 08 投标文件公开定向解析；已由同组成员解决的联合体不得重复升级为冲突。",
                "evidence": {
                    "candidate_group_verification_summary": summary.get("candidate_group_verification_summary"),
                    "candidate_group_stage4_gate_state": summary.get("candidate_group_stage4_gate_state"),
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
    for record in project_records:
        group_summary = dict(record.get("candidate_group_verification_summary") or {})
        if _int(group_summary.get("unresolved_group_count")) <= 0:
            continue
        backlog.append(
            {
                "priority": 4,
                "repair_layer": "CandidateGroupStage4Verification",
                "project_id": record.get("project_id"),
                "repair_action": "候选组 Stage4 公司优先和姓名枚举未匹配任何联合体成员；进入 08 定向解析或补证修复，不得直接输出最终冲突。",
                "candidate_group_verification_summary": group_summary,
            }
        )
    return backlog


def _candidate_group_verification_records(stage4_execution_items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for item in stage4_execution_items:
        group_id = str(item.get("candidate_group_id") or "").strip()
        if not group_id:
            continue
        key = (str(item.get("project_id") or ""), group_id, str(item.get("responsible_person_name") or ""))
        groups.setdefault(key, []).append(item)

    records: list[dict[str, Any]] = []
    for (project_id, group_id, person), items in sorted(groups.items(), key=lambda row: row[0]):
        matched_items = [
            item
            for item in items
            if item.get("candidate_group_resolution_state") == "RESOLVED_BY_THIS_MEMBER"
            or item.get("supplement_after_execution_state") == "COMPANY_FIRST_CERTIFICATE_RESOLVED"
            or item.get("verification_result") == "MATCHED"
        ]
        resolved_by_member_items = [
            item
            for item in items
            if item.get("candidate_group_resolution_state") == "RESOLVED_BY_CONSORTIUM_MEMBER"
            or item.get("supplement_after_execution_state") == "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED"
        ]
        pending_items = [item for item in items if item.get("candidate_group_resolution_state") == "PENDING_EXECUTION"]
        member_names = _dedupe(
            member
            for item in items
            for member in list(item.get("candidate_group_members") or [])
        ) or _dedupe(item.get("candidate_company_name") for item in items)
        matched_companies = _dedupe(
            item.get("candidate_company_name") or item.get("matched_company_name_optional")
            for item in matched_items
        )
        group_state = (
            "RESOLVED_BY_CONSORTIUM_MEMBER"
            if matched_items
            else "PENDING_EXECUTION"
            if pending_items and len(pending_items) == len(items)
            else "UNRESOLVED_NO_MEMBER_MATCHED"
        )
        records.append(
            {
                "project_id": project_id,
                "candidate_group_id": group_id,
                "candidate_group_order": _first_text(item.get("candidate_group_order") for item in items),
                "responsible_person_name": person,
                "certificate_no": _first_text(
                    _valid_certificate_no(
                        item.get("source_certificate_no_optional")
                        or item.get("resolved_certificate_no_optional")
                        or item.get("certificate_no")
                    )
                    for item in items
                ),
                "candidate_group_members": member_names,
                "target_count": len(items),
                "matched_company_names": matched_companies,
                "matched_member_count": len(matched_items),
                "nonmatched_but_group_resolved_count": len(resolved_by_member_items),
                "group_resolution_state": group_state,
                "flow_08_targeted_parse_required": bool(group_state == "UNRESOLVED_NO_MEMBER_MATCHED"),
                "member_records": [
                    {
                        "candidate_company_name": item.get("candidate_company_name", ""),
                        "consortium_member_role": item.get("consortium_member_role", ""),
                        "candidate_group_resolution_state": item.get("candidate_group_resolution_state", ""),
                        "supplement_after_execution_state": item.get("supplement_after_execution_state", ""),
                        "matched_company_name_optional": item.get("candidate_group_matched_company_name_optional")
                        or item.get("matched_company_name_optional", ""),
                        "resolved_certificate_no_optional": _valid_certificate_no(
                            item.get("resolved_certificate_no_optional", "")
                        ),
                        "registered_unit_name_optional": item.get("registered_unit_name_optional", ""),
                        "fail_closed_reasons": list(item.get("fail_closed_reasons") or []),
                    }
                    for item in items
                ],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _valid_certificate_no(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.search(r"\d{6,24}", text):
        return ""
    return text


def _candidate_group_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_group_count": len(records),
        "resolved_group_count": sum(1 for row in records if row.get("group_resolution_state") == "RESOLVED_BY_CONSORTIUM_MEMBER"),
        "pending_group_count": sum(1 for row in records if row.get("group_resolution_state") == "PENDING_EXECUTION"),
        "unresolved_group_count": sum(1 for row in records if row.get("group_resolution_state") == "UNRESOLVED_NO_MEMBER_MATCHED"),
        "group_resolution_state_counts": _counts(row.get("group_resolution_state") for row in records),
        "matched_company_names": _dedupe(company for row in records for company in list(row.get("matched_company_names") or [])),
        "flow_08_targeted_parse_required_count": sum(1 for row in records if row.get("flow_08_targeted_parse_required")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


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
    candidate_certificate_inputs: int,
) -> list[str]:
    blockers: list[str] = []
    has_candidate_evidence_flow = any(_flow_no(row.get("guangzhou_flow_no") or row.get("flow_no")) in {"07", "08"} for row in [*flow_samples, *parse_samples, *stage4_items])
    if flow_samples and not download_samples:
        blockers.append("download_probe_not_run_for_project")
    if listed_attachments and attachment_snapshots < listed_attachments:
        blockers.append("attachment_download_incomplete")
    if parse_attempted and parse_success < parse_attempted and not candidate_certificate_inputs:
        blockers.append("parse_incomplete")
    if parse_samples and not stage4_items:
        blockers.append("stage4_inputs_not_generated")
    if has_candidate_evidence_flow and not candidate_certificate_inputs:
        blockers.append("candidate_evidence_certificate_input_missing_parse_required")
    return blockers


def _flow_blockers(
    *,
    flow_no: str,
    analysis_items: list[Mapping[str, Any]],
    download_samples: list[Mapping[str, Any]],
    listed: int,
    attempted: int,
    snapshots: int,
    parse_samples: list[Mapping[str, Any]],
    parse_attempted: int,
    parse_success: int,
    stage4_items: list[Mapping[str, Any]],
    stage4_certificate_inputs: int,
    flow_08_targeted_parse_required: bool = False,
) -> list[str]:
    blockers: list[str] = []
    register_only_flow_08 = flow_no == "08" and not flow_08_targeted_parse_required and any(
        str(item.get("download_policy") or "") == "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED"
        for item in analysis_items
    )
    download_required = (
        not register_only_flow_08
        and any(
            str(item.get("download_policy") or "").startswith("DOWNLOAD")
            or str(item.get("download_policy") or "") == "LIST_ALL_THEN_TARGETED_DOWNLOAD"
            for item in analysis_items
        )
    )
    if download_required and not download_samples:
        blockers.append("download_probe_not_run_for_required_flow")
    if not register_only_flow_08 and listed and snapshots < (attempted or listed):
        blockers.append("attachment_snapshot_incomplete_for_flow")
    if not register_only_flow_08 and parse_attempted and parse_success < parse_attempted and not (flow_no in {"07", "08"} and stage4_certificate_inputs > 0):
        blockers.append("parse_incomplete_for_flow")
    if flow_no in {"07", "08"} and parse_samples and stage4_certificate_inputs == 0 and not register_only_flow_08:
        blockers.append("candidate_evidence_certificate_input_missing_parse_required")
    elif parse_samples and not stage4_items and any(_flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no")) == "08" for sample in parse_samples):
        blockers.append("candidate_stage4_input_missing_for_flow")
    return blockers


def _flow_08_targeted_parse_required(
    *,
    analysis_items: list[Mapping[str, Any]],
    stage4_items: list[Mapping[str, Any]],
    candidate_group_records: list[Mapping[str, Any]],
) -> bool:
    return any(
        bool(item.get("flow_08_targeted_parse_required"))
        for item in [*analysis_items, *stage4_items, *candidate_group_records]
    )


def _project_ids(
    *,
    flow_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    parse_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
    stage4_execution_manifest: Mapping[str, Any],
) -> list[str]:
    values: set[str] = set()
    for manifest in (flow_manifest, download_manifest, parse_manifest):
        for sample in list(manifest.get("project_sample_items") or []):
            if isinstance(sample, Mapping) and sample.get("project_id"):
                values.add(str(sample.get("project_id")))
    for item in list(stage4_manifest.get("items") or []):
        if isinstance(item, Mapping) and item.get("project_id"):
            values.add(str(item.get("project_id")))
    for item in list(stage4_execution_manifest.get("items") or []):
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


def _candidate_certificate_gate_state(
    *,
    flow_07_certificate_inputs: int,
    flow_08_certificate_inputs: int,
    has_candidate_evidence_sample: bool,
) -> str:
    if flow_07_certificate_inputs > 0:
        return "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION"
    if flow_08_certificate_inputs > 0:
        return "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION_FROM_FLOW_08_FALLBACK"
    if has_candidate_evidence_sample:
        return "CERTIFICATE_MISSING_PARSE_REQUIRED"
    return "NO_CANDIDATE_EVIDENCE_SAMPLE"


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
    parser.add_argument("--stage4-execution-root", default="")
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
        stage4_execution_root=args.stage4_execution_root or None,
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
