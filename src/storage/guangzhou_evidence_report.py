from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_EVIDENCE_REPORT_KIND = "guangzhou_evidence_report_v1_manifest"
GUANGZHOU_EVIDENCE_REPORT_VERSION = 1
GUANGZHOU_EVIDENCE_REPORT_ADAPTER_ID = "guangzhou-evidence-report-v1-builder"

DEFAULT_FLOW_ROOT = Path("tmp/evaluation-real-samples/guangzhou-flowurl-analysis-72h-v1")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/guangzhou-download-human-v1")
DEFAULT_RESPONSIBLE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-responsible-person-early-probe-v3")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v4-merged")
DEFAULT_READINESS_ROOT = Path("tmp/evaluation-real-samples/guangzhou-upstream-readiness-with-stage4-groups-v3")
DEFAULT_ACTIVE_CONFLICT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-active-conflict-probe-v1")
DEFAULT_GDCIC_QUERY_PROBE_ROOT = Path("tmp/evaluation-real-samples/guangdong-gdcic-query-probe-v1")
DEFAULT_GUANGDONG_LOCAL_VERIFICATION_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-verification-probe-v1")
DEFAULT_GUANGDONG_LOCAL_FIELD_QUERY_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-field-query-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-v1")

FORBIDDEN_TERMS = ("是不是本人", "确认本人", "无风险", "无冲突", "冲突成立", "造假成立", "违法成立")

ACTIVE_CONFLICT_SOURCE_CATEGORIES = (
    "local_public_resource_candidate_or_award_notices",
    "local_housing_construction_or_administrative_approval_platform",
    "construction_permit",
    "contract_filing",
    "completion_or_acceptance_filing",
    "project_manager_change_notice",
    "administrative_penalty_or_complaint_decision",
    "public_web_clues_with_replayable_source_url",
)


def build_guangzhou_evidence_report(
    *,
    flow_root: str | Path = DEFAULT_FLOW_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    responsible_person_root: str | Path = DEFAULT_RESPONSIBLE_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    readiness_root: str | Path = DEFAULT_READINESS_ROOT,
    active_conflict_probe_root: str | Path = DEFAULT_ACTIVE_CONFLICT_ROOT,
    gdcic_query_probe_root: str | Path = DEFAULT_GDCIC_QUERY_PROBE_ROOT,
    guangdong_local_verification_root: str | Path = DEFAULT_GUANGDONG_LOCAL_VERIFICATION_ROOT,
    guangdong_local_field_query_root: str | Path = DEFAULT_GUANGDONG_LOCAL_FIELD_QUERY_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    flow_dir = Path(flow_root)
    download_dir = Path(download_root)
    responsible_dir = Path(responsible_person_root)
    stage4_dir = Path(stage4_execution_root)
    readiness_dir = Path(readiness_root)
    active_conflict_dir = Path(active_conflict_probe_root)
    gdcic_query_dir = Path(gdcic_query_probe_root)
    guangdong_local_dir = Path(guangdong_local_verification_root)
    guangdong_local_field_dir = Path(guangdong_local_field_query_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    flow_manifest = _source_manifest(_load_json(flow_dir / "run-manifest.json", missing_inputs, "flow_run_manifest_missing"))
    analysis_manifest = _source_manifest(_load_json(flow_dir / "analysis-plan.json", [], "analysis_plan_missing"))
    download_manifest = _source_manifest(_load_json(download_dir / "download-probe-manifest.json", missing_inputs, "download_probe_manifest_missing"))
    responsible_manifest = _source_manifest(_load_json(responsible_dir / "responsible-person-early-probe.json", missing_inputs, "responsible_person_early_probe_missing"))
    stage4_manifest = _source_manifest(_load_json(stage4_dir / "company-first-stage4-execution.json", [], "stage4_execution_manifest_missing"))
    readiness_manifest = _source_manifest(_load_json(readiness_dir / "guangzhou-upstream-readiness-report.json", [], "readiness_report_missing"))
    active_conflict_manifest = _source_manifest(_load_json_optional(active_conflict_dir / "guangzhou-active-conflict-probe-v1.json"))
    gdcic_query_manifest = _source_manifest(_load_json_optional(gdcic_query_dir / "guangdong-gdcic-query-probe-v1.json"))
    guangdong_local_manifest = _source_manifest(
        _load_json_optional(guangdong_local_dir / "guangdong-local-verification-probe-v1.json")
    )
    guangdong_local_field_manifest = _source_manifest(
        _load_json_optional(guangdong_local_field_dir / "guangdong-local-field-query-probe-v1.json")
    )

    project_ids = _project_ids(
        flow_manifest,
        analysis_manifest,
        download_manifest,
        responsible_manifest,
        stage4_manifest,
        readiness_manifest,
    )
    project_reports = [
        _project_report(
            project_id=project_id,
            flow_manifest=flow_manifest,
            analysis_manifest=analysis_manifest,
            download_manifest=download_manifest,
            responsible_manifest=responsible_manifest,
            stage4_manifest=stage4_manifest,
            readiness_manifest=readiness_manifest,
            active_conflict_manifest=active_conflict_manifest,
            gdcic_query_manifest=gdcic_query_manifest,
            guangdong_local_manifest=guangdong_local_manifest,
            guangdong_local_field_manifest=guangdong_local_field_manifest,
        )
        for project_id in project_ids
    ]
    summary = _summary(
        project_reports=project_reports,
        missing_inputs=missing_inputs,
        active_conflict_manifest=active_conflict_manifest,
        gdcic_query_manifest=gdcic_query_manifest,
        guangdong_local_manifest=guangdong_local_manifest,
        guangdong_local_field_manifest=guangdong_local_field_manifest,
    )
    guangdong_local_field_failure_review = _guangdong_local_field_failure_review(
        guangdong_local_field_manifest,
        project_reports,
    )
    summary["guangdong_local_field_query_failure_review"] = guangdong_local_field_failure_review
    manifest = {
        "manifest_version": GUANGZHOU_EVIDENCE_REPORT_VERSION,
        "manifest_kind": GUANGZHOU_EVIDENCE_REPORT_KIND,
        "adapter_id": GUANGZHOU_EVIDENCE_REPORT_ADAPTER_ID,
        "pipeline_stage": "GuangzhouEvidenceReportV1",
        "manifest_id": f"GUANGZHOU-EVIDENCE-REPORT-{_fingerprint({'projects': project_reports, 'summary': summary})[:16]}",
        "created_at": created,
        "source_flow_root": str(flow_dir),
        "source_download_root": str(download_dir),
        "source_responsible_person_root": str(responsible_dir),
        "source_stage4_execution_root": str(stage4_dir),
        "source_readiness_root": str(readiness_dir),
        "source_active_conflict_probe_root": str(active_conflict_dir),
        "source_gdcic_query_probe_root": str(gdcic_query_dir),
        "source_guangdong_local_verification_root": str(guangdong_local_dir),
        "source_guangdong_local_field_query_root": str(guangdong_local_field_dir),
        "report_sections": [
            "verification_evidence",
            "process_stability",
            "optimization_recommendations",
        ],
        "project_reports": project_reports,
        "summary": summary,
        "guangdong_local_field_query_summary": summary.get("guangdong_local_field_query_summary", {}),
        "guangdong_local_field_query_failure_review": guangdong_local_field_failure_review,
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
        "guangzhou_evidence_report_mode": "BUILT",
        "safe_to_execute": not missing_inputs,
        "blocking_reasons": missing_inputs,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*missing_inputs, *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangzhou-evidence-report-v1.json").write_text(text, encoding="utf-8")
    (out_dir / "guangdong-local-field-query-failure-review.json").write_text(
        json.dumps(guangdong_local_field_failure_review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _project_report(
    *,
    project_id: str,
    flow_manifest: Mapping[str, Any],
    analysis_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    responsible_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
    readiness_manifest: Mapping[str, Any],
    active_conflict_manifest: Mapping[str, Any],
    gdcic_query_manifest: Mapping[str, Any],
    guangdong_local_manifest: Mapping[str, Any],
    guangdong_local_field_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    flow_items = _items_for_project(flow_manifest, project_id)
    analysis_items = _items_for_project(analysis_manifest, project_id)
    download_items = _items_for_project(download_manifest, project_id)
    responsible_item = _first(_items_for_project(responsible_manifest, project_id))
    stage4_items = _items_for_project(stage4_manifest, project_id)
    readiness_project = _first(_project_records_for_project(readiness_manifest, project_id))
    active_conflict_project = _first(_project_task_records_for_project(active_conflict_manifest, project_id))
    gdcic_query_project = _first(_gdcic_project_records_for_project(gdcic_query_manifest, project_id))
    guangdong_local_project = _first(_guangdong_local_project_records_for_project(guangdong_local_manifest, project_id))
    guangdong_local_field_project = _first(
        _guangdong_local_field_project_records_for_project(guangdong_local_field_manifest, project_id)
    )
    guangdong_local_field_tasks = _guangdong_local_field_tasks_for_project(
        guangdong_local_field_manifest,
        project_id,
    )
    local_field_probe_state = _local_field_project_state(
        guangdong_local_field_project,
        guangdong_local_field_tasks,
    )
    group_records = list(readiness_project.get("candidate_group_verification_records") or [])
    if not group_records:
        group_records = _candidate_groups_from_responsible(responsible_item)
    responsible_stage4_inputs = _responsible_stage4_inputs_for_project(responsible_manifest, project_id)
    responsible_chain_state = _responsible_person_verification_chain_state(
        project_id=project_id,
        responsible_item=responsible_item,
        stage4_items=stage4_items,
        group_records=group_records,
        responsible_stage4_inputs=responsible_stage4_inputs,
    )
    local_credit_source_context = _local_credit_source_context(local_field_probe_state)

    flow_08_registry = _flow_08_registry(analysis_items=analysis_items, download_items=download_items)
    targeted_parse_required = any(bool(row.get("flow_08_targeted_parse_required")) for row in group_records) or bool(
        responsible_item.get("flow_08_targeted_parse_required")
    )
    release_evidence_matrix = _release_evidence_matrix(
        project_id=project_id,
        group_records=group_records,
        guangdong_local_field_tasks=guangdong_local_field_tasks,
    )
    verification_evidence = {
        "project_id": project_id,
        "project_name": _project_name(project_id, flow_items, download_items, responsible_item, readiness_project),
        "candidate_group_records": [_group_record(row) for row in group_records],
        "candidate_group_count": len(group_records),
        "resolved_candidate_group_count": sum(1 for row in group_records if "RESOLVED" in str(row.get("group_resolution_state") or "")),
        "public_registration_match_state": _public_registration_state(group_records),
        "responsible_person_verification_chain": responsible_chain_state,
        "flow_08_targeted_parse_required": targeted_parse_required,
        "flow_08_registry": flow_08_registry,
        "candidate_notice_source_urls": _source_urls_for_flow([*flow_items, *download_items], "07"),
        "project_source_urls": _dedupe(row.get("source_url") for row in [*flow_items, *download_items]),
        "active_conflict_probe_tasks": _active_conflict_tasks(project_id=project_id, group_records=group_records),
        "active_conflict_probe_state": (
            "TASKS_READY"
            if active_conflict_project
            else "PLAN_ONLY_TASKS_NOT_BUILT"
        ),
        "release_evidence_matrix": release_evidence_matrix,
        "release_evidence_matrix_state": (
            "RELEASE_SOURCE_READBACK_PRESENT_REVIEW_REQUIRED"
            if any(row.get("release_source_readback_present") for row in release_evidence_matrix)
            else "RELEASE_READBACK_REQUIRED"
        ),
        "active_conflict_probe_task_ids": _list(active_conflict_project.get("task_ids")),
        "gdcic_probe_state": (
            "READY"
            if gdcic_query_project
            else "NOT_BUILT"
        ),
        "gdcic_query_task_ids": _list(gdcic_query_project.get("query_task_ids")),
        "gdcic_readback_ready_count": _int(gdcic_query_project.get("readback_ready_count")),
        "gdcic_blocker_taxonomy_counts": dict(gdcic_query_project.get("blocker_taxonomy_counts") or {}),
        "guangdong_local_verification_probe_state": (
            "READY"
            if guangdong_local_project
            else "NOT_BUILT"
        ),
        "guangdong_local_query_task_ids": _list(guangdong_local_project.get("query_task_ids")),
        "guangdong_local_readback_ready_count": _int(guangdong_local_project.get("readback_ready_count")),
        "guangdong_local_source_profile_ids": _list(guangdong_local_project.get("source_profile_ids")),
        "guangdong_local_blocker_taxonomy_counts": dict(guangdong_local_project.get("blocker_taxonomy_counts") or {}),
        "guangdong_local_field_query_probe_state": (
            "READY"
            if guangdong_local_field_project
            else "NOT_BUILT"
        ),
        "guangdong_local_field_query_task_ids": _list(guangdong_local_field_project.get("field_query_task_ids")),
        "guangdong_local_field_readback_ready_count": _int(guangdong_local_field_project.get("readback_ready_count")),
        "guangdong_local_field_keyword_hit_count": _int(guangdong_local_field_project.get("keyword_hit_count")),
        "guangdong_local_field_source_profile_ids": _list(guangdong_local_field_project.get("source_profile_ids")),
        "guangdong_local_field_blocker_taxonomy_counts": dict(
            guangdong_local_field_project.get("blocker_taxonomy_counts") or {}
        ),
        "local_field_probe_state": local_field_probe_state,
        "local_credit_source_context": local_credit_source_context,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    process_stability = {
        "flow_07_present": any(_flow_no(row) == "07" for row in [*flow_items, *download_items]),
        "flow_08_present": flow_08_registry["flow_08_present"],
        "flow_08_default_parse_state": "REGISTER_ONLY_NO_DEFAULT_PARSE",
        "download_probe_flow_count": len(download_items),
        "download_attempted_count": sum(_int(row.get("download_attempted_count")) for row in download_items),
        "attachment_snapshot_count": sum(_int(row.get("attachment_snapshot_count")) for row in download_items),
        "responsible_person_early_probe_state": str(responsible_item.get("early_probe_state") or ""),
        "responsible_person_stage4_readiness_state": str(responsible_item.get("stage4_readiness_state") or ""),
        "stage4_execution_job_count": len(stage4_items),
        "stage4_readback_ready_count": sum(1 for row in stage4_items if str(row.get("stage4_execution_state") or "") == "READBACK_READY"),
        "guangdong_local_field_blocker_taxonomy_counts": dict(local_field_probe_state.get("blocker_taxonomy_counts") or {}),
        "local_field_source_stability": local_credit_source_context,
        "failure_taxonomy": _dedupe(
            reason
            for row in [*flow_items, *download_items, responsible_item, readiness_project]
            for reason in _list(row.get("failure_taxonomy") or row.get("blocking_layers") or row.get("fail_closed_reasons"))
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    optimization_recommendations = _recommendations(
        verification_evidence=verification_evidence,
        process_stability=process_stability,
    )
    return {
        "project_id": project_id,
        "project_name": verification_evidence["project_name"],
        "verification_evidence": verification_evidence,
        "process_stability": process_stability,
        "responsible_person_verification_chain": responsible_chain_state,
        "local_field_probe_state": local_field_probe_state,
        "optimization_recommendations": optimization_recommendations,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_08_registry(*, analysis_items: list[Mapping[str, Any]], download_items: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [row for row in [*analysis_items, *download_items] if _flow_no(row) == "08"]
    attachment_names: list[str] = []
    attachment_urls: list[str] = []
    for row in rows:
        for ref in _list(row.get("attachment_snapshot_refs")):
            if not isinstance(ref, Mapping):
                continue
            attachment_names.append(str(ref.get("attachment_link_text") or Path(str(ref.get("attachment_url") or "")).name or ""))
            attachment_urls.append(str(ref.get("attachment_url") or ref.get("source_url") or ""))
    return {
        "flow_08_present": bool(rows),
        "source_urls": _dedupe(row.get("source_url") for row in rows),
        "published_dates": _dedupe(row.get("published_date") for row in rows),
        "attachment_count": sum(_int(row.get("listed_attachment_count")) for row in download_items if _flow_no(row) == "08") or len(attachment_urls),
        "attachment_names": _dedupe(attachment_names),
        "attachment_urls": _dedupe(attachment_urls),
        "default_download_policy": "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED",
        "default_parse_depth": "LIST_ONLY",
        "default_parse_required": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _group_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_group_id": str(row.get("candidate_group_id") or ""),
        "candidate_group_order": str(row.get("candidate_group_order") or ""),
        "candidate_group_members": _list(row.get("candidate_group_members")),
        "responsible_person_name": str(row.get("responsible_person_name") or ""),
        "certificate_no": str(row.get("certificate_no") or row.get("resolved_certificate_no_optional") or ""),
        "matched_company_names": _list(row.get("matched_company_names")),
        "group_resolution_state": str(row.get("group_resolution_state") or ""),
        "flow_08_targeted_parse_required": bool(row.get("flow_08_targeted_parse_required")),
        "member_records": _list(row.get("member_records")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_groups_from_responsible(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in _list(item.get("candidate_groups")):
        if not isinstance(group, Mapping):
            continue
        out.append(
            {
                "candidate_group_id": str(group.get("candidate_group_id") or ""),
                "candidate_group_order": str(group.get("candidate_group_order") or group.get("rank") or ""),
                "candidate_group_members": _list(group.get("candidate_group_members") or group.get("company_names")),
                "responsible_person_name": str(group.get("responsible_person_name") or ""),
                "certificate_no": str(group.get("certificate_no") or ""),
                "matched_company_names": [],
                "group_resolution_state": "PENDING_STAGE4_PUBLIC_REGISTRATION_MATCH",
                "flow_08_targeted_parse_required": bool(item.get("flow_08_targeted_parse_required")),
                "member_records": [],
            }
        )
    return out


def _active_conflict_tasks(*, project_id: str, group_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for group in group_records:
        person = str(group.get("responsible_person_name") or "").strip()
        if not person:
            continue
        companies = _dedupe([*_list(group.get("matched_company_names")), *_list(group.get("candidate_group_members"))])
        tasks.append(
            {
                "project_id": project_id,
                "candidate_group_id": str(group.get("candidate_group_id") or ""),
                "responsible_person_name": person,
                "company_names": companies,
                "probe_state": "PLAN_ONLY_NOT_EXECUTED",
                "source_categories": list(ACTIVE_CONFLICT_SOURCE_CATEGORIES),
                "release_evidence_matrix": _release_evidence_matrix_for_group(
                    project_id=project_id,
                    group=group,
                    project_level_readback_counts={},
                ),
                "jzsc_usage_boundary": "AUXILIARY_ONLY_NOT_REALTIME_ACTIVE_CONFLICT_SINGLE_SOURCE",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return tasks


def _release_evidence_matrix(
    *,
    project_id: str,
    group_records: list[Mapping[str, Any]],
    guangdong_local_field_tasks: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    project_level_readback_counts = _local_field_release_readback_counts(guangdong_local_field_tasks)
    matrix: list[dict[str, Any]] = []
    for group in group_records:
        if not _text(group.get("responsible_person_name")):
            continue
        matrix.append(
            _release_evidence_matrix_for_group(
                project_id=project_id,
                group=group,
                project_level_readback_counts=project_level_readback_counts,
            )
        )
    return matrix


def _release_evidence_matrix_for_group(
    *,
    project_id: str,
    group: Mapping[str, Any],
    project_level_readback_counts: Mapping[str, int],
) -> dict[str, Any]:
    completion_count = _int(project_level_readback_counts.get("completion_acceptance_public_record"))
    construction_count = _int(project_level_readback_counts.get("construction_permit_public_record"))
    contract_count = _int(project_level_readback_counts.get("contract_or_performance_public_record"))
    return {
        "project_id": project_id,
        "candidate_group_id": _text(group.get("candidate_group_id")),
        "candidate_group_order": _text(group.get("candidate_group_order")),
        "responsible_person_name": _text(group.get("responsible_person_name")),
        "certificate_no": _text(group.get("certificate_no") or group.get("resolved_certificate_no_optional")),
        "candidate_group_members": _list(group.get("candidate_group_members")),
        "matched_company_names": _list(group.get("matched_company_names")),
        "matrix_state": (
            "RELEASE_SOURCE_READBACK_PRESENT_REVIEW_REQUIRED"
            if completion_count
            else "RELEASE_READBACK_REQUIRED"
        ),
        "current_project_evidence_targets": [
            "flow_07_candidate_notice",
            "public_registration_match",
            "candidate_company_or_consortium_member_binding",
        ],
        "occupied_project_evidence_targets": [
            "local_public_resource_candidate_or_award_notice",
            "construction_permit",
            "contract_filing_or_contract_public_info",
            "performance_or_project_role_public_record",
            "project_manager_change_notice",
        ],
        "release_evidence_targets": [
            "completion_acceptance_or_completion_filing",
            "project_manager_change_notice_or_permit_change",
            "contract_agreed_work_acceptance_or_handover",
            "non_contractor_suspension_over_120_days_with_construction_unit_consent",
            "same_project_adjacent_section_or_phase_exception",
            "guangzhou_construction_project_safety_standardization_assessment_result_notice",
        ],
        "project_level_readback_counts": {
            "construction_permit_public_record": construction_count,
            "completion_acceptance_public_record": completion_count,
            "contract_or_performance_public_record": contract_count,
        },
        "release_source_readback_present": bool(completion_count),
        "time_window_required": True,
        "evidence_strength_state": (
            "RELEASE_SOURCE_PRESENT_BUT_REVIEW_REQUIRED"
            if completion_count
            else "INSUFFICIENT_EVIDENCE_PENDING_EXTERNAL_READBACK"
        ),
        "allowed_internal_output_state": "PROJECT_MANAGER_RELEASE_RISK_CLUE_REVIEW",
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _local_field_release_readback_counts(tasks: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "construction_permit_public_record": 0,
        "completion_acceptance_public_record": 0,
        "contract_or_performance_public_record": 0,
    }
    for task in tasks:
        for record in _list((task.get("field_match_summary") or {}).get("source_specific_records")):
            if not isinstance(record, Mapping):
                continue
            record_type = _text(record.get("record_type"))
            adapter_id = _text(record.get("source_specific_adapter_id"))
            if record_type == "construction_permit_public_record":
                counts["construction_permit_public_record"] += 1
            elif record_type == "completion_acceptance_public_record":
                counts["completion_acceptance_public_record"] += 1
            elif adapter_id == "guangdong_gdcic_contract_performance_public_page_v1":
                counts["contract_or_performance_public_record"] += 1
    return counts


def _responsible_person_verification_chain_state(
    *,
    project_id: str,
    responsible_item: Mapping[str, Any],
    stage4_items: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
    responsible_stage4_inputs: list[Mapping[str, Any]],
) -> dict[str, Any]:
    source_07_groups = [
        group for group in _list(responsible_item.get("candidate_groups")) if isinstance(group, Mapping)
    ]
    source_07_certificates_are_usable = _source_07_certificates_are_usable(responsible_item)
    source_07_certificate_ready = [
        _source_07_candidate_record(group)
        for group in source_07_groups
        if source_07_certificates_are_usable and _text(group.get("certificate_no"))
    ]
    source_07_certificate_missing = [
        _source_07_candidate_record(group)
        for group in source_07_groups
        if _text(group.get("responsible_person_name"))
        and (not source_07_certificates_are_usable or not _text(group.get("certificate_no")))
    ]
    stage4_inputs = _stage4_public_registration_inputs(
        responsible_stage4_inputs=responsible_stage4_inputs,
        stage4_items=stage4_items,
        group_records=group_records,
    )
    supplement_plan = _company_first_supplement_plan(responsible_item, stage4_items)
    flow_08_plan = _flow_08_targeted_parse_plan(
        responsible_item=responsible_item,
        stage4_items=stage4_items,
        group_records=group_records,
    )
    if _text(responsible_item.get("responsible_role")) == "not_applicable":
        chain_state = "RESPONSIBLE_PERSON_NOT_APPLICABLE"
    elif stage4_inputs:
        chain_state = "PUBLIC_REGISTRATION_CHAIN_READY"
    elif supplement_plan:
        chain_state = "COMPANY_FIRST_SUPPLEMENT_REQUIRED"
    else:
        chain_state = "PUBLIC_REGISTRATION_CHAIN_REVIEW_REQUIRED"
    return {
        "project_id": project_id,
        "chain_state": chain_state,
        "early_probe_state": _text(responsible_item.get("early_probe_state")),
        "stage4_readiness_state": _text(responsible_item.get("stage4_readiness_state")),
        "responsible_role": _text(responsible_item.get("responsible_role")),
        "source_07_certificate_ready_count": len(source_07_certificate_ready),
        "source_07_certificate_ready_records": source_07_certificate_ready,
        "source_07_certificate_missing_count": len(source_07_certificate_missing),
        "source_07_certificate_missing_records": source_07_certificate_missing,
        "stage4_public_registration_input_count": len(stage4_inputs),
        "stage4_public_registration_verification_inputs": stage4_inputs,
        "company_first_supplement_required_count": len(supplement_plan),
        "company_first_supplement_plan": supplement_plan,
        "company_first_supplement_resolved_count": sum(
            1 for item in supplement_plan if _text(item.get("supplement_state")) == "COMPANY_FIRST_CERTIFICATE_RESOLVED"
        ),
        "flow_08_targeted_parse_required": bool(flow_08_plan),
        "flow_08_targeted_parse_plan": flow_08_plan,
        "chain_priority": "RESPONSIBLE_PERSON_PUBLIC_REGISTRATION_FIRST",
        "local_credit_sources_role": "SUPPLEMENTARY_ONLY",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _source_07_candidate_record(group: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_group_id": _text(group.get("candidate_group_id")),
        "candidate_group_order": _text(group.get("candidate_group_order") or group.get("rank")),
        "candidate_group_members": _list(group.get("candidate_group_members") or group.get("company_names")),
        "responsible_person_name": _text(group.get("responsible_person_name")),
        "certificate_no": _text(group.get("certificate_no")),
        "certificate_source": "FLOW_07_CANDIDATE_NOTICE",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _source_07_certificates_are_usable(responsible_item: Mapping[str, Any]) -> bool:
    early_probe_state = _text(responsible_item.get("early_probe_state"))
    if bool(responsible_item.get("flow_08_targeted_parse_required")):
        return False
    if early_probe_state in {
        "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED",
        "NAME_ENUMERATION_FALLBACK_REQUIRED",
        "FLOW_08_TARGETED_PARSE_REQUIRED",
    }:
        return False
    return True


def _stage4_public_registration_inputs(
    *,
    responsible_stage4_inputs: list[Mapping[str, Any]],
    stage4_items: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for item in responsible_stage4_inputs:
        certificate_no = _text(item.get("certificate_no") or item.get("project_manager_certificate_no"))
        if not certificate_no:
            continue
        inputs.append(
            _stage4_registration_input_record(
                item,
                certificate_no=certificate_no,
                certificate_source="FLOW_07_CANDIDATE_NOTICE",
                input_state="READY_FROM_07_CERTIFICATE",
            )
        )
    for item in stage4_items:
        certificate_no = _text(item.get("resolved_certificate_no_optional") or item.get("certificate_no"))
        if not certificate_no:
            continue
        source_certificate = _text(item.get("source_certificate_no_optional"))
        inputs.append(
            _stage4_registration_input_record(
                item,
                certificate_no=certificate_no,
                certificate_source="FLOW_07_CANDIDATE_NOTICE" if source_certificate else "COMPANY_FIRST_SUPPLEMENT",
                input_state="READY_FROM_COMPANY_FIRST_SUPPLEMENT" if not source_certificate else "READY_FROM_07_CERTIFICATE",
            )
        )
    for group in group_records:
        certificate_no = _text(group.get("certificate_no") or group.get("resolved_certificate_no_optional"))
        person_name = _text(group.get("responsible_person_name"))
        for company_name in _list(group.get("matched_company_names")):
            if certificate_no and person_name and company_name:
                inputs.append(
                    {
                        "candidate_group_id": _text(group.get("candidate_group_id")),
                        "candidate_group_order": _text(group.get("candidate_group_order")),
                        "candidate_company_name": _text(company_name),
                        "responsible_person_name": person_name,
                        "certificate_no": certificate_no,
                        "certificate_source": "STAGE4_OR_READINESS_RESOLVED",
                        "input_state": "READY_FROM_EXISTING_READBACK",
                        "stage4_live_provider_enabled": False,
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                )
    return _dedupe_records(
        inputs,
        keys=("candidate_group_id", "candidate_company_name", "responsible_person_name", "certificate_no"),
    )


def _stage4_registration_input_record(
    item: Mapping[str, Any],
    *,
    certificate_no: str,
    certificate_source: str,
    input_state: str,
) -> dict[str, Any]:
    return {
        "stage4_input_id": _text(item.get("stage4_input_id") or item.get("job_id")),
        "candidate_group_id": _text(item.get("candidate_group_id")),
        "candidate_group_order": _text(item.get("candidate_group_order")),
        "candidate_company_name": _text(item.get("candidate_company_name") or item.get("matched_company_name_optional")),
        "responsible_person_name": _text(item.get("responsible_person_name") or item.get("project_manager_name")),
        "certificate_no": certificate_no,
        "certificate_source": certificate_source,
        "input_state": input_state,
        "registered_unit_name_optional": _text(item.get("registered_unit_name_optional")),
        "stage4_live_provider_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _company_first_supplement_plan(
    responsible_item: Mapping[str, Any],
    stage4_items: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    source_07_certificates_are_usable = _source_07_certificates_are_usable(responsible_item)
    targets = [target for target in _list(responsible_item.get("verification_targets")) if isinstance(target, Mapping)]
    if not targets:
        targets = [
            {
                "candidate_company_name": _first_text(
                    _list(group.get("candidate_group_members") or group.get("company_names"))
                ),
                "responsible_person_name": group.get("responsible_person_name"),
                "certificate_no": group.get("certificate_no") if source_07_certificates_are_usable else "",
            }
            for group in _list(responsible_item.get("candidate_groups"))
            if isinstance(group, Mapping)
        ]
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        company_name = _text(target.get("candidate_company_name"))
        person_name = _text(target.get("responsible_person_name"))
        if not company_name or not person_name or _text(target.get("certificate_no")):
            continue
        stage4_match = _first(
            [
                dict(item)
                for item in stage4_items
                if _text(item.get("candidate_company_name")) == company_name
                and _text(item.get("responsible_person_name")) == person_name
            ]
        )
        resolved_certificate = _text(stage4_match.get("resolved_certificate_no_optional"))
        plans.append(
            {
                "candidate_company_name": company_name,
                "responsible_person_name": person_name,
                "source_07_certificate_state": "MISSING",
                "supplement_route": "COMPANY_FIRST_THEN_NAME_ENUMERATION_FALLBACK",
                "supplement_state": _text(stage4_match.get("supplement_after_execution_state")) or "PENDING_COMPANY_FIRST_SUPPLEMENT",
                "resolved_certificate_no_optional": resolved_certificate,
                "next_action": (
                    "BUILD_STAGE4_REGISTRATION_INPUT_FROM_SUPPLEMENT"
                    if resolved_certificate
                    else "RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT"
                ),
                "flow_08_targeted_parse_required": bool(stage4_match.get("flow_08_targeted_parse_required")),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return _dedupe_records(plans, keys=("candidate_company_name", "responsible_person_name"))


def _flow_08_targeted_parse_plan(
    *,
    responsible_item: Mapping[str, Any],
    stage4_items: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    triggered = bool(responsible_item.get("flow_08_targeted_parse_required")) or any(
        bool(item.get("flow_08_targeted_parse_required")) for item in [*stage4_items, *group_records]
    )
    if not triggered:
        return []
    records: list[dict[str, Any]] = []
    for item in [*stage4_items, *group_records]:
        if bool(item.get("flow_08_targeted_parse_required")):
            records.append(
                {
                    "candidate_group_id": _text(item.get("candidate_group_id")),
                    "candidate_company_name": _text(item.get("candidate_company_name")),
                    "responsible_person_name": _text(item.get("responsible_person_name")),
                    "trigger": "STAGE4_COMPANY_FIRST_AND_NAME_ENUMERATION_UNMATCHED",
                    "parse_policy": "TARGETED_ONLY",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return _dedupe_records(records, keys=("candidate_group_id", "candidate_company_name", "responsible_person_name"))


def _local_credit_source_context(local_field_probe_state: Mapping[str, Any]) -> dict[str, Any]:
    source_summaries = _list(local_field_probe_state.get("source_profile_summaries"))
    suitability = [_source_suitability(summary) for summary in source_summaries if isinstance(summary, Mapping)]
    return {
        "source_role": "SUPPLEMENTARY_ONLY_NOT_PRIMARY_RESPONSIBLE_PERSON_CHAIN",
        "source_profile_suitability": suitability,
        "supplementary_no_record_source_profile_ids": [
            item["source_profile_id"] for item in suitability if item.get("source_state") == "NO_RECORD_SUPPLEMENTARY_ONLY"
        ],
        "blocked_or_retry_later_source_profile_ids": [
            item["source_profile_id"] for item in suitability if bool(item.get("retry_later_only"))
        ],
        "not_primary_verification_source_profile_ids": [
            item["source_profile_id"] for item in suitability if bool(item.get("not_primary_verification_source"))
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _source_suitability(source_summary: Mapping[str, Any]) -> dict[str, Any]:
    source_profile_id = _text(source_summary.get("source_profile_id"))
    blockers = dict(source_summary.get("blocker_taxonomy_counts") or {})
    source_state = "SUPPLEMENTARY_ONLY"
    reason = "local_credit_source_is_not_primary_responsible_person_registration_chain"
    retry_later_only = False
    if source_profile_id == "GUANGDONG-CREDIT-GD-HOME":
        if any(key in blockers for key in ("gd_credit_gd_rate_limited_or_temporary_unavailable", "gd_credit_gd_public_list_rendered_fallback_ready")):
            source_state = "TEMPORARY_UNAVAILABLE_OR_RENDERED_FALLBACK_ONLY"
            reason = "temporary_unavailable_or_rendered_fallback_only"
            retry_later_only = True
    elif source_profile_id == "GUANGDONG-GDCIC-HOME" and "gd_gdcic_contract_system_sso_login_required" in blockers:
        source_state = "SSO_REQUIRED_SUPPLEMENTARY_ONLY"
        reason = "contract_system_sso_required"
        retry_later_only = True
    elif source_profile_id == "GUANGDONG-TZXM-HOME" and "gd_tzxm_project_approval_no_record_review" in blockers:
        source_state = "NO_RECORD_SUPPLEMENTARY_ONLY"
        reason = "project_approval_no_record"
    elif source_profile_id == "GUANGDONG-ZFCXJST-PENALTY-PUBLICITY" and "gd_zfcxjst_penalty_publicity_no_record_review" in blockers:
        source_state = "NO_RECORD_SUPPLEMENTARY_ONLY"
        reason = "housing_penalty_no_record"
    elif source_profile_id == "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY" and "guangzhou_zfcj_xyxx_api_no_record_review" in blockers:
        source_state = "NO_RECORD_SUPPLEMENTARY_ONLY"
        reason = "city_double_publicity_no_record"
    elif source_profile_id == "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM":
        source_state = "DELEGATED_FIELD_ADAPTER"
        reason = "handled_by_separate_gdcic_adapter"
    return {
        "source_profile_id": source_profile_id,
        "source_state": source_state,
        "reason": reason,
        "task_count": _int(source_summary.get("task_count")),
        "readback_ready_count": _int(source_summary.get("readback_ready_count")),
        "keyword_hit_count": _int(source_summary.get("keyword_hit_count")),
        "blocker_taxonomy_counts": blockers,
        "not_primary_verification_source": True,
        "retry_later_only": retry_later_only,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _creditgd_retry_later_only(local_context: Mapping[str, Any]) -> bool:
    for item in _list(local_context.get("source_profile_suitability")):
        if isinstance(item, Mapping) and item.get("source_profile_id") == "GUANGDONG-CREDIT-GD-HOME":
            return bool(item.get("retry_later_only"))
    return False


def _recommendations(*, verification_evidence: Mapping[str, Any], process_stability: Mapping[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    responsible_chain = verification_evidence.get("responsible_person_verification_chain") or {}
    local_context = verification_evidence.get("local_credit_source_context") or {}
    if verification_evidence.get("flow_08_targeted_parse_required"):
        recommendations.append(_recommendation("RUN_FLOW_08_TARGETED_PARSE", "存在 08 定向解析触发条件，先按目标文件关键词解析。"))
    elif verification_evidence.get("public_registration_match_state") == "ALL_GROUPS_RESOLVED":
        recommendations.append(_recommendation("READY_FOR_INTERNAL_EVIDENCE_PACKAGE_REVIEW", "候选组公开注册信息已匹配，08 保持登记状态。"))
    else:
        recommendations.append(_recommendation("SUPPLEMENT_PUBLIC_REGISTRATION_MATCH", "公开注册信息匹配仍需补查，暂不扩大 08 解析。"))
    if _int(responsible_chain.get("stage4_public_registration_input_count")):
        recommendations.append(
            _recommendation(
                "run_stage4_registration_probe",
                "优先使用候选公司、负责人姓名和证书号进入公开注册信息核验链。",
            )
        )
    if _int(responsible_chain.get("company_first_supplement_required_count")):
        recommendations.append(
            _recommendation(
                "company_first_certificate_supplement",
                "07 未给出证书号的候选人按公司优先补证；已有补证结果时直接进入注册信息复核。",
            )
        )
    recommendations.append(
        _recommendation(
            "flow_08_targeted_parse_if_stage4_unmatched",
            "仅在公司优先和姓名枚举仍未完成公开注册信息匹配时，再触发 08 定向解析计划。",
        )
    )
    if _creditgd_retry_later_only(local_context):
        recommendations.append(
            _recommendation(
                "retry_creditgd_later_only",
                "CreditGD 当前只保留为补充重试源，不作为负责人主核验链入口。",
            )
        )
    if verification_evidence.get("guangdong_local_verification_probe_state") == "READY":
        recommendations.append(
            _recommendation(
                "GUANGDONG_LOCAL_VERIFICATION_PROBE_READY",
                "已生成广东省级和广州城市补强公开源核验任务；入口可达不等于字段级结论。",
            )
        )
    if process_stability.get("failure_taxonomy"):
        recommendations.append(_recommendation("REPAIR_PROCESS_STABILITY_ITEMS", "存在采集、下载或核验过程失败分类，先修可定位失败。"))
    if verification_evidence.get("active_conflict_probe_state") == "TASKS_READY":
        recommendations.append(_recommendation("ACTIVE_CONFLICT_EXTERNAL_SOURCE_TASKS_READY", "已生成地方公开来源待核验任务清单，不用四库单独下结论。"))
    else:
        recommendations.append(_recommendation("BUILD_ACTIVE_CONFLICT_EXTERNAL_SOURCE_PROBE", "按地方公开来源生成在建/履约冲突线索任务，不用四库单独下结论。"))
    if verification_evidence.get("gdcic_probe_state") == "READY":
        if _int(verification_evidence.get("gdcic_readback_ready_count")):
            recommendations.append(_recommendation("GDCIC_PUBLIC_SOURCE_READBACK_READY", "广东三库一平台公开源已有字段回放摘要，可作为外部线索继续复核。"))
        else:
            recommendations.append(_recommendation("GDCIC_PUBLIC_SOURCE_REVIEW_REQUIRED", "广东三库一平台探针已生成，公开源命中或阻断状态需继续复核。"))
    return recommendations


def _recommendation(action: str, reason: str) -> dict[str, Any]:
    return {
        "recommended_action": action,
        "reason": reason,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    project_reports: list[Mapping[str, Any]],
    missing_inputs: list[str],
    active_conflict_manifest: Mapping[str, Any],
    gdcic_query_manifest: Mapping[str, Any],
    guangdong_local_manifest: Mapping[str, Any],
    guangdong_local_field_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    groups = [
        group
        for project in project_reports
        for group in _list(((project.get("verification_evidence") or {}).get("candidate_group_records")))
        if isinstance(group, Mapping)
    ]
    flow_08_required = [
        project
        for project in project_reports
        if bool((project.get("verification_evidence") or {}).get("flow_08_targeted_parse_required"))
    ]
    local_field_summary = _local_field_query_summary(guangdong_local_field_manifest)
    responsible_chains = [
        project.get("responsible_person_verification_chain") or {}
        for project in project_reports
    ]
    return {
        "report_state": "READY" if not missing_inputs else "INPUT_BLOCKED",
        "project_count": len(project_reports),
        "candidate_group_count": len(groups),
        "resolved_candidate_group_count": sum(1 for group in groups if "RESOLVED" in str(group.get("group_resolution_state") or "")),
        "flow_08_present_project_count": sum(1 for project in project_reports if bool(((project.get("verification_evidence") or {}).get("flow_08_registry") or {}).get("flow_08_present"))),
        "flow_08_targeted_parse_required_project_count": len(flow_08_required),
        "active_conflict_probe_task_count": sum(len(_list((project.get("verification_evidence") or {}).get("active_conflict_probe_tasks"))) for project in project_reports),
        "source_07_certificate_ready_candidate_count": sum(
            _int(chain.get("source_07_certificate_ready_count")) for chain in responsible_chains
        ),
        "source_07_certificate_missing_candidate_count": sum(
            _int(chain.get("source_07_certificate_missing_count")) for chain in responsible_chains
        ),
        "stage4_public_registration_input_count": sum(
            _int(chain.get("stage4_public_registration_input_count")) for chain in responsible_chains
        ),
        "company_first_supplement_plan_count": sum(
            _int(chain.get("company_first_supplement_required_count")) for chain in responsible_chains
        ),
        "active_conflict_external_probe_state": (
            "TASKS_READY"
            if active_conflict_manifest
            else "NOT_BUILT"
        ),
        "active_conflict_external_probe_task_count": _int(
            (active_conflict_manifest.get("summary") or {}).get("active_conflict_probe_task_count")
        ),
        "gdcic_probe_state": (
            "READY"
            if gdcic_query_manifest
            else "NOT_BUILT"
        ),
        "gdcic_query_probe_task_count": _int(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_query_probe_task_count")
        ),
        "gdcic_readback_ready_count": _int(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_readback_ready_count")
        ),
        "gdcic_person_directory_readback_ready_count": _int(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_person_directory_readback_ready_count")
        ),
        "gdcic_company_project_readback_ready_count": _int(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_company_project_readback_ready_count")
        ),
        "gdcic_certificate_route_readback_ready_count": _int(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_certificate_route_readback_ready_count")
        ),
        "gdcic_certificate_field_candidate_count": _int(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_certificate_field_candidate_count")
        ),
        "gdcic_captcha_blocked_task_count": _int(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_captcha_blocked_task_count")
        ),
        "gdcic_blocker_taxonomy_counts": dict(
            (gdcic_query_manifest.get("summary") or {}).get("gdcic_blocker_taxonomy_counts") or {}
        ),
        "guangdong_local_verification_probe_state": (
            "READY"
            if guangdong_local_manifest
            else "NOT_BUILT"
        ),
        "guangdong_local_verification_task_count": _int(
            (guangdong_local_manifest.get("summary") or {}).get("guangdong_local_verification_task_count")
        ),
        "guangdong_local_readback_ready_count": _int(
            (guangdong_local_manifest.get("summary") or {}).get("readback_ready_count")
        ),
        "guangdong_local_source_profile_task_counts": dict(
            (guangdong_local_manifest.get("summary") or {}).get("source_profile_task_counts") or {}
        ),
        "guangdong_local_blocker_taxonomy_counts": dict(
            (guangdong_local_manifest.get("summary") or {}).get("blocker_taxonomy_counts") or {}
        ),
        "guangdong_local_field_query_probe_state": (
            "READY"
            if guangdong_local_field_manifest
            else "NOT_BUILT"
        ),
        "guangdong_local_field_query_task_count": _int(
            (guangdong_local_field_manifest.get("summary") or {}).get("guangdong_local_field_query_task_count")
        ),
        "guangdong_local_field_readback_ready_count": _int(
            (guangdong_local_field_manifest.get("summary") or {}).get("readback_ready_count")
        ),
        "guangdong_local_field_keyword_hit_task_count": _int(
            (guangdong_local_field_manifest.get("summary") or {}).get("keyword_hit_task_count")
        ),
        "guangdong_local_field_probe_state_counts": dict(
            (guangdong_local_field_manifest.get("summary") or {}).get("field_query_probe_state_counts") or {}
        ),
        "guangdong_local_field_blocker_taxonomy_counts": dict(
            (guangdong_local_field_manifest.get("summary") or {}).get("blocker_taxonomy_counts") or {}
        ),
        "guangdong_local_field_query_summary": local_field_summary,
        "section_names": ["verification_evidence", "process_stability", "optimization_recommendations"],
        "blocking_reasons": missing_inputs,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _public_registration_state(group_records: list[Mapping[str, Any]]) -> str:
    if not group_records:
        return "NO_CANDIDATE_GROUPS"
    resolved = sum(1 for row in group_records if "RESOLVED" in str(row.get("group_resolution_state") or ""))
    if resolved == len(group_records):
        return "ALL_GROUPS_RESOLVED"
    if resolved:
        return "PARTIAL_GROUPS_RESOLVED"
    return "GROUPS_PENDING_OR_UNRESOLVED"


def _project_ids(*manifests: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for manifest in manifests:
        for key in ("project_sample_items", "items", "project_records"):
            for item in _list(manifest.get(key)):
                if isinstance(item, Mapping):
                    ids.append(str(item.get("project_id") or ""))
    return _dedupe(ids)


def _items_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("project_sample_items", "items"):
        for item in _list(manifest.get(key)):
            if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id:
                out.append(dict(item))
    return out


def _project_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _project_task_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_task_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _gdcic_project_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_task_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _responsible_stage4_inputs_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    stage4_inputs = manifest.get("stage4_candidate_verification_inputs") or {}
    return [
        dict(item)
        for item in _list(stage4_inputs.get("items"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _guangdong_local_project_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_task_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _guangdong_local_field_project_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_task_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _guangdong_local_field_tasks_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("field_task_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _local_field_project_state(
    project_record: Mapping[str, Any],
    field_tasks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if field_tasks:
        return {
            "probe_state": "READY",
            "task_count": len(field_tasks),
            "readback_ready_count": sum(1 for task in field_tasks if bool(task.get("readback_ready"))),
            "keyword_hit_count": sum(1 for task in field_tasks if _field_task_has_keyword_hit(task)),
            "source_profile_task_counts": _counts(task.get("source_profile_id") for task in field_tasks),
            "source_profile_summaries": _local_field_source_summaries(field_tasks),
            "source_profile_ids": _dedupe(task.get("source_profile_id") for task in field_tasks),
            "field_query_probe_state_counts": _counts(task.get("field_query_probe_state") for task in field_tasks),
            "blocker_taxonomy_counts": _counts(
                blocker for task in field_tasks for blocker in _list(task.get("blocker_taxonomy"))
            ),
            "no_match_review_required_count": sum(
                1 for task in field_tasks if str(task.get("field_query_probe_state") or "") == "NO_FIELD_MATCH_REVIEW_REQUIRED"
            ),
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
    if project_record:
        state_counts = dict(project_record.get("field_query_probe_state_counts") or {})
        return {
            "probe_state": str(project_record.get("probe_state") or "READY"),
            "task_count": _int(project_record.get("field_query_task_count") or project_record.get("query_task_count")),
            "readback_ready_count": _int(project_record.get("readback_ready_count")),
            "keyword_hit_count": _int(project_record.get("keyword_hit_count")),
            "source_profile_task_counts": dict(project_record.get("source_profile_task_counts") or {}),
            "source_profile_summaries": [
                {
                    "source_profile_id": source_profile_id,
                    "task_count": _int(task_count),
                    "readback_ready_count": 0,
                    "keyword_hit_count": 0,
                    "field_query_probe_state_counts": {},
                    "blocker_taxonomy_counts": {},
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                }
                for source_profile_id, task_count in dict(project_record.get("source_profile_task_counts") or {}).items()
            ],
            "source_profile_ids": _list(project_record.get("source_profile_ids")),
            "field_query_probe_state_counts": state_counts,
            "blocker_taxonomy_counts": dict(project_record.get("blocker_taxonomy_counts") or {}),
            "no_match_review_required_count": _int(state_counts.get("NO_FIELD_MATCH_REVIEW_REQUIRED")),
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
    return {
        "probe_state": "NOT_BUILT",
        "task_count": 0,
        "readback_ready_count": 0,
        "keyword_hit_count": 0,
        "source_profile_task_counts": {},
        "source_profile_summaries": [],
        "source_profile_ids": [],
        "field_query_probe_state_counts": {},
        "blocker_taxonomy_counts": {},
        "no_match_review_required_count": 0,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _local_field_query_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    manifest_summary = manifest.get("summary") or {}
    field_tasks = [dict(item) for item in _list(manifest.get("field_task_records")) if isinstance(item, Mapping)]
    if field_tasks:
        source_summaries = _local_field_source_summaries(field_tasks)
        return {
            "probe_state": str(manifest_summary.get("probe_state") or "READY"),
            "task_count": len(field_tasks),
            "readback_ready_count": sum(1 for task in field_tasks if bool(task.get("readback_ready"))),
            "keyword_hit_count": sum(1 for task in field_tasks if _field_task_has_keyword_hit(task)),
            "source_profile_task_counts": _counts(task.get("source_profile_id") for task in field_tasks),
            "source_profile_summaries": source_summaries,
            "field_query_probe_state_counts": _counts(task.get("field_query_probe_state") for task in field_tasks),
            "blocker_taxonomy_counts": _counts(
                blocker for task in field_tasks for blocker in _list(task.get("blocker_taxonomy"))
            ),
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
    return {
        "probe_state": str(manifest_summary.get("probe_state") or ("READY" if manifest else "NOT_BUILT")),
        "task_count": _int(manifest_summary.get("guangdong_local_field_query_task_count")),
        "readback_ready_count": _int(manifest_summary.get("readback_ready_count")),
        "keyword_hit_count": _int(manifest_summary.get("keyword_hit_task_count")),
        "source_profile_task_counts": dict(manifest_summary.get("source_profile_task_counts") or {}),
        "source_profile_summaries": [
            {
                "source_profile_id": source_profile_id,
                "task_count": _int(task_count),
                "readback_ready_count": 0,
                "keyword_hit_count": 0,
                "field_query_probe_state_counts": {},
                "blocker_taxonomy_counts": {},
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
            for source_profile_id, task_count in dict(manifest_summary.get("source_profile_task_counts") or {}).items()
        ],
        "field_query_probe_state_counts": dict(manifest_summary.get("field_query_probe_state_counts") or {}),
        "blocker_taxonomy_counts": dict(manifest_summary.get("blocker_taxonomy_counts") or {}),
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _guangdong_local_field_failure_review(
    manifest: Mapping[str, Any],
    project_reports: list[Mapping[str, Any]],
) -> dict[str, Any]:
    summary = _local_field_query_summary(manifest)
    source_profile_reviews = [
        _source_suitability(source_summary)
        for source_summary in _list(summary.get("source_profile_summaries"))
        if isinstance(source_summary, Mapping)
    ]
    project_certificate_reviews: list[dict[str, Any]] = []
    for project in project_reports:
        chain = project.get("responsible_person_verification_chain") or {}
        project_certificate_reviews.append(
            {
                "project_id": str(project.get("project_id") or ""),
                "project_name": str(project.get("project_name") or ""),
                "source_07_certificate_ready_count": _int(chain.get("source_07_certificate_ready_count")),
                "source_07_certificate_ready_records": _list(chain.get("source_07_certificate_ready_records")),
                "source_07_certificate_missing_count": _int(chain.get("source_07_certificate_missing_count")),
                "source_07_certificate_missing_records": _list(chain.get("source_07_certificate_missing_records")),
                "company_first_supplement_plan_count": _int(chain.get("company_first_supplement_required_count")),
                "stage4_public_registration_input_count": _int(chain.get("stage4_public_registration_input_count")),
                "flow_08_targeted_parse_required": bool(chain.get("flow_08_targeted_parse_required")),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return {
        "review_state": "READY" if manifest else "NOT_BUILT",
        "review_purpose": "REFOCUS_ON_RESPONSIBLE_PERSON_PUBLIC_REGISTRATION_CHAIN",
        "source_profile_summaries": source_profile_reviews,
        "project_certificate_reviews": project_certificate_reviews,
        "not_primary_source_profile_ids": [
            item["source_profile_id"] for item in source_profile_reviews if bool(item.get("not_primary_verification_source"))
        ],
        "retry_later_only_source_profile_ids": [
            item["source_profile_id"] for item in source_profile_reviews if bool(item.get("retry_later_only"))
        ],
        "primary_chain_next_step": "RESPONSIBLE_PERSON_PUBLIC_REGISTRATION_FIRST",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _local_field_source_summaries(field_tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    source_summaries: list[dict[str, Any]] = []
    for source_profile_id in _dedupe(task.get("source_profile_id") for task in field_tasks):
        source_tasks = [
            task
            for task in field_tasks
            if str(task.get("source_profile_id") or "") == source_profile_id
        ]
        source_summaries.append(
            {
                "source_profile_id": source_profile_id,
                "task_count": len(source_tasks),
                "readback_ready_count": sum(1 for task in source_tasks if bool(task.get("readback_ready"))),
                "keyword_hit_count": sum(1 for task in source_tasks if _field_task_has_keyword_hit(task)),
                "field_query_probe_state_counts": _counts(task.get("field_query_probe_state") for task in source_tasks),
                "blocker_taxonomy_counts": _counts(
                    blocker for task in source_tasks for blocker in _list(task.get("blocker_taxonomy"))
                ),
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return source_summaries


def _field_task_has_keyword_hit(task: Mapping[str, Any]) -> bool:
    field_summary = task.get("field_summary") or {}
    if _int(field_summary.get("matched_keyword_count") or field_summary.get("keyword_hit_count")):
        return True
    if _int(task.get("keyword_hit_count")):
        return True
    return bool(_list((task.get("field_match_summary") or {}).get("source_specific_records")))


def _project_name(project_id: str, *sources: Any) -> str:
    for source in sources:
        if isinstance(source, Mapping):
            text = str(source.get("project_name") or "").strip()
            if text:
                return text
        for item in _list(source):
            if isinstance(item, Mapping):
                text = str(item.get("project_name") or "").strip()
                if text:
                    return text
    return project_id


def _flow_no(row: Mapping[str, Any]) -> str:
    return str(row.get("flow_no") or row.get("guangzhou_flow_no") or "").zfill(2)


def _load_json(path: Path, missing_inputs: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        missing_inputs.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _source_urls_for_flow(rows: list[Mapping[str, Any]], flow_no: str) -> list[str]:
    return _dedupe(row.get("source_url") for row in rows if _flow_no(row) == flow_no)


def _first(items: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(items[0]) if items else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(values: list[Any]) -> str:
    return _text(values[0]) if values else ""


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _dedupe_records(records: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        marker = tuple(str(record.get(key) or "") for key in keys)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(record)
    return out


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou EvidenceReport v1.")
    parser.add_argument("--flow-root", default=str(DEFAULT_FLOW_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--responsible-person-root", default=str(DEFAULT_RESPONSIBLE_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--readiness-root", default=str(DEFAULT_READINESS_ROOT))
    parser.add_argument("--active-conflict-probe-root", default=str(DEFAULT_ACTIVE_CONFLICT_ROOT))
    parser.add_argument("--gdcic-query-probe-root", default=str(DEFAULT_GDCIC_QUERY_PROBE_ROOT))
    parser.add_argument("--guangdong-local-verification-root", default=str(DEFAULT_GUANGDONG_LOCAL_VERIFICATION_ROOT))
    parser.add_argument("--guangdong-local-field-query-root", default=str(DEFAULT_GUANGDONG_LOCAL_FIELD_QUERY_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_evidence_report(
        flow_root=args.flow_root,
        download_root=args.download_root,
        responsible_person_root=args.responsible_person_root,
        stage4_execution_root=args.stage4_execution_root,
        readiness_root=args.readiness_root,
        active_conflict_probe_root=args.active_conflict_probe_root,
        gdcic_query_probe_root=args.gdcic_query_probe_root,
        guangdong_local_verification_root=args.guangdong_local_verification_root,
        guangdong_local_field_query_root=args.guangdong_local_field_query_root,
        output_root=args.output_root,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
