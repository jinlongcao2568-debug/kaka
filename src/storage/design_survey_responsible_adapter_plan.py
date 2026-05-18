from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


DESIGN_SURVEY_ADAPTER_PLAN_KIND = "design_survey_responsible_adapter_plan_v1_manifest"
DESIGN_SURVEY_ADAPTER_PLAN_VERSION = 1
DESIGN_SURVEY_ADAPTER_PLAN_ID = "design-survey-responsible-adapter-plan-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/design-survey-responsible-adapter-plan-v1")

CONSTRUCTION_RELEASE_TARGETS = (
    "construction_permit",
    "contract_public_info",
    "completion_filing",
    "project_manager_change_notice",
)


def build_design_survey_responsible_adapter_plan(
    *,
    stage16_storage_json: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    storage_path = Path(stage16_storage_json)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    storage_payload = _load_json(storage_path)
    if not storage_payload:
        blocking_reasons.append("stage16_storage_json_missing_or_invalid")
    refs = _latest_autonomous_run_refs(storage_payload)
    if storage_payload and not refs:
        blocking_reasons.append("operator_autonomous_opportunity_search_run_missing")

    candidate_options = _json_value(refs.get("candidate_options_json"), [])
    closed_loop_results = _json_value(refs.get("closed_loop_results_json"), [])
    readbacks_by_project = _readbacks_by_project(closed_loop_results)
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}

    project_records: list[dict[str, Any]] = []
    stage4_items: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []

    for candidate in candidate_options if isinstance(candidate_options, list) else []:
        if not isinstance(candidate, Mapping):
            continue
        project_id = str(candidate.get("project_id") or "").strip()
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue
        if not _is_design_survey_candidate(candidate):
            if selected_projects:
                skipped_records.append(_skipped_record(candidate, "not_design_survey_candidate", created_at=created))
            continue

        readback = readbacks_by_project.get(project_id, {})
        project = _project_record(candidate, readback=readback, created_at=created)
        project_records.append(project)
        if project["adapter_readiness_state"] != "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN":
            continue

        companies = _split_consortium_companies(project["candidate_company_text"])
        group_id = _candidate_group_id(project["project_id"], companies) if len(companies) > 1 else ""
        group_members = [company["company_name"] for company in companies]
        for index, company in enumerate(companies, start=1):
            stage4_items.append(
                _stage4_input_item(
                    project=project,
                    company=company,
                    group_id=group_id,
                    group_order=str(index),
                    group_members=group_members,
                    created_at=created,
                )
            )
            task_records.extend(
                _company_task_records(
                    project=project,
                    company=company,
                    group_id=group_id,
                    group_members=group_members,
                    created_at=created,
                )
            )
        task_records.extend(_project_task_records(project=project, group_id=group_id, created_at=created))

    stage4_inputs = _stage4_candidate_verification_inputs(stage4_items, created_at=created)
    verification_task_table = {
        "summary": _task_summary(task_records),
        "records": task_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    project_table = {
        "summary": _project_summary(project_records),
        "records": project_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = _summary(
        project_records=project_records,
        skipped_records=skipped_records,
        stage4_items=stage4_items,
        task_records=task_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": DESIGN_SURVEY_ADAPTER_PLAN_VERSION,
        "manifest_kind": DESIGN_SURVEY_ADAPTER_PLAN_KIND,
        "adapter_id": DESIGN_SURVEY_ADAPTER_PLAN_ID,
        "pipeline_stage": "DesignSurveyResponsibleAdapterPlanV1",
        "manifest_id": f"DESIGN-SURVEY-RESP-PLAN-{_fingerprint({'summary': summary, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_stage16_storage_json": str(storage_path),
        "project_table": project_table,
        "stage4_candidate_verification_inputs": stage4_inputs,
        "design_survey_verification_task_table": verification_task_table,
        "skipped_records": skipped_records,
        "summary": summary,
        "scope_guardrails": _scope_guardrails(),
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "design_survey_responsible_adapter_plan_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }

    _write_json(out_dir / "design-survey-responsible-adapter-plan-v1.json", result)
    _write_json(out_dir / "design-survey-project-table.json", project_table)
    _write_json(out_dir / "design-survey-stage4-candidate-verification-inputs.json", stage4_inputs)
    _write_json(out_dir / "design-survey-verification-task-table.json", verification_task_table)
    return result


def _project_record(candidate: Mapping[str, Any], *, readback: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    project_id = str(candidate.get("project_id") or "").strip()
    company_text = str(candidate.get("candidate_company") or "").strip()
    person = _responsible_person(candidate)
    role = _responsible_role(candidate)
    companies = _split_consortium_companies(company_text)
    missing: list[str] = []
    if not project_id:
        missing.append("project_id_missing")
    if not company_text or not companies:
        missing.append("candidate_company_missing")
    if not person:
        missing.append("responsible_person_missing")
    readiness = (
        "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN"
        if not missing
        else "BLOCKED_DESIGN_SURVEY_TARGET_FIELDS_MISSING"
    )
    return {
        "design_survey_project_id": _stable_id("DESIGN-SURVEY-PROJECT", project_id),
        "project_id": project_id,
        "project_name": str(candidate.get("project_name") or ""),
        "source_url": str(candidate.get("source_url") or ""),
        "candidate_company_text": company_text,
        "candidate_group_members": [company["company_name"] for company in companies],
        "responsible_person_name": person,
        "responsible_role": role,
        "certificate_no_optional": _certificate_no(candidate),
        "engineering_work_lane": str(candidate.get("engineering_work_lane") or ""),
        "opportunity_priority_class": str(candidate.get("opportunity_priority_class") or ""),
        "stage2_detail_capture_state": str(candidate.get("stage2_detail_capture_state") or ""),
        "stage3_detail_parse_state": str(candidate.get("stage3_detail_parse_state") or ""),
        "stage5_rule_gate_status": str(readback.get("stage5_rule_gate_status") or ""),
        "stage5_evidence_gate_status": str(readback.get("stage5_evidence_gate_status") or ""),
        "current_project_time_window": _current_project_time_window(candidate, readback),
        "adapter_readiness_state": readiness,
        "recommended_next_action": (
            "run_design_survey_stage4_person_company_certificate_and_qualification_plan"
            if readiness == "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN"
            else "targeted_current_notice_or_attachment_readback_for_design_survey_responsible_fields"
        ),
        "review_reasons": missing,
        "scope_guardrail": "design_survey_not_construction_project_manager_release_mainline",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _stage4_input_item(
    *,
    project: Mapping[str, Any],
    company: Mapping[str, str],
    group_id: str,
    group_order: str,
    group_members: list[str],
    created_at: str,
) -> dict[str, Any]:
    company_name = company["company_name"]
    role = str(project.get("responsible_role") or "survey_design_project_lead")
    return {
        "stage4_input_id": _stable_id(
            "DESIGN-SURVEY-STAGE4",
            project.get("project_id"),
            company_name,
            project.get("responsible_person_name"),
            role,
        ),
        "source_probe_adapter_id": DESIGN_SURVEY_ADAPTER_PLAN_ID,
        "project_id": project.get("project_id"),
        "project_name": project.get("project_name"),
        "flow_no": "07",
        "flow_title": "中标候选人公示",
        "source_07_detail_path": project.get("source_url"),
        "candidate_company_name": company_name,
        "candidate_group_id": group_id,
        "candidate_group_order": group_order if group_id else "",
        "candidate_group_members": group_members,
        "candidate_group_match_mode": "ANY_CONSORTIUM_MEMBER" if group_id and len(group_members) > 1 else "SINGLE_COMPANY",
        "consortium_member_role": company.get("consortium_member_role", ""),
        "responsible_person_name": project.get("responsible_person_name"),
        "project_manager_name": project.get("responsible_person_name"),
        "responsible_role": role,
        "certificate_no": project.get("certificate_no_optional") or "",
        "project_manager_certificate_no": project.get("certificate_no_optional") or "",
        "person_public_id_optional": "",
        "recommended_stage4_route": "JZSC_COMPANY_FIRST_OR_LOCAL_DESIGN_SURVEY_PERSONNEL_REGISTRY",
        "stage4_live_provider_enabled": False,
        "review_required": True,
        "review_reason": "design_survey_responsible_role_requires_person_company_certificate_and_qualification_check",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _company_task_records(
    *,
    project: Mapping[str, Any],
    company: Mapping[str, str],
    group_id: str,
    group_members: list[str],
    created_at: str,
) -> list[dict[str, Any]]:
    company_name = company["company_name"]
    base = {
        "project_id": project.get("project_id"),
        "project_name": project.get("project_name"),
        "candidate_company_name": company_name,
        "candidate_group_id": group_id,
        "candidate_group_members": group_members,
        "consortium_member_role": company.get("consortium_member_role", ""),
        "responsible_person_name": project.get("responsible_person_name"),
        "responsible_role": project.get("responsible_role"),
        "source_07_detail_path": project.get("source_url"),
        "execution_state": "PLAN_ONLY_NOT_EXECUTED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    source_families = [
        "jzsc_company_personnel_public_record",
        "local_design_survey_personnel_registry",
    ]
    if _highway_market_route_candidate(project, company_name):
        source_families.append("national_highway_construction_market_credit_personnel")
    return [
        {
            **base,
            "design_survey_verification_task_id": _stable_id(
                "DESIGN-SURVEY-TASK",
                project.get("project_id"),
                company_name,
                "person_company_certificate",
            ),
            "task_type": "DESIGN_SURVEY_PERSON_COMPANY_CERTIFICATE_MATCH",
            "source_families": source_families,
            "query_fields": {
                "company_name": company_name,
                "responsible_person_name": project.get("responsible_person_name"),
                "certificate_no_optional": project.get("certificate_no_optional") or "",
                "responsible_role": project.get("responsible_role"),
            },
            "success_fields": [
                "person_name",
                "registered_unit_name",
                "certificate_no_or_public_person_id",
                "registration_category_or_professional_title",
                "source_url_or_snapshot_id",
            ],
            "not_clearance_on_miss": True,
        },
        {
            **base,
            "design_survey_verification_task_id": _stable_id(
                "DESIGN-SURVEY-TASK",
                project.get("project_id"),
                company_name,
                "enterprise_qualification",
            ),
            "task_type": "DESIGN_SURVEY_ENTERPRISE_QUALIFICATION_CHECK",
            "source_families": [
                "jzsc_enterprise_qualification_public_record",
                "local_housing_construction_enterprise_qualification_registry",
            ],
            "query_fields": {
                "company_name": company_name,
                "project_name": project.get("project_name"),
                "responsible_role": project.get("responsible_role"),
            },
            "success_fields": [
                "enterprise_name",
                "qualification_category",
                "qualification_level",
                "valid_until",
                "source_url_or_snapshot_id",
            ],
            "not_clearance_on_miss": True,
        },
    ]


def _project_task_records(*, project: Mapping[str, Any], group_id: str, created_at: str) -> list[dict[str, Any]]:
    base = {
        "project_id": project.get("project_id"),
        "project_name": project.get("project_name"),
        "candidate_group_id": group_id,
        "candidate_group_members": list(project.get("candidate_group_members") or []),
        "responsible_person_name": project.get("responsible_person_name"),
        "responsible_role": project.get("responsible_role"),
        "source_07_detail_path": project.get("source_url"),
        "execution_state": "PLAN_ONLY_NOT_EXECUTED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return [
        {
            **base,
            "design_survey_verification_task_id": _stable_id(
                "DESIGN-SURVEY-TASK",
                project.get("project_id"),
                "current_notice_binding",
            ),
            "task_type": "CURRENT_NOTICE_BINDING_AND_ROLE_LINEAGE",
            "source_families": ["current_07_candidate_notice_snapshot", "attachment_field_lineage"],
            "query_fields": {
                "source_url": project.get("source_url"),
                "candidate_group_members": list(project.get("candidate_group_members") or []),
                "responsible_person_name": project.get("responsible_person_name"),
            },
            "success_fields": [
                "candidate_company_or_consortium_row",
                "responsible_person_label",
                "responsible_role",
                "field_lineage_or_snapshot_id",
            ],
            "not_clearance_on_miss": True,
        },
        {
            **base,
            "design_survey_verification_task_id": _stable_id(
                "DESIGN-SURVEY-TASK",
                project.get("project_id"),
                "service_clock",
            ),
            "task_type": "CURRENT_PROJECT_DESIGN_SURVEY_SERVICE_CLOCK",
            "source_families": ["current_07_candidate_notice_snapshot", "current_notice_attachment_readback"],
            "query_fields": {
                "project_name": project.get("project_name"),
                "current_project_time_window": dict(project.get("current_project_time_window") or {}),
            },
            "success_fields": [
                "service_period_text",
                "service_start_date_optional",
                "service_end_date_optional",
                "source_url_or_snapshot_id",
            ],
            "not_clearance_on_miss": True,
        },
        {
            **base,
            "design_survey_verification_task_id": _stable_id(
                "DESIGN-SURVEY-TASK",
                project.get("project_id"),
                "prior_design_survey_award_review",
            ),
            "task_type": "PRIOR_DESIGN_SURVEY_AWARD_HISTORY_REVIEW",
            "source_families": [
                "data_ggzy_company_award_history",
                "original_notice_targeted_readback_when_fields_missing",
            ],
            "query_fields": {
                "candidate_companies": list(project.get("candidate_group_members") or []),
                "responsible_person_name": project.get("responsible_person_name"),
                "current_project_time_window": dict(project.get("current_project_time_window") or {}),
            },
            "success_fields": [
                "historical_project_name",
                "historical_responsible_person_if_public",
                "historical_design_or_survey_service_period_if_public",
                "source_url_or_snapshot_id",
            ],
            "not_clearance_on_miss": True,
            "scope_note": "history review is a design/survey responsible-line clue, not a construction project-manager release conclusion",
        },
    ]


def _stage4_candidate_verification_inputs(items: list[Mapping[str, Any]], *, created_at: str) -> dict[str, Any]:
    return {
        "manifest_kind": "stage4_candidate_verification_inputs",
        "source_manifest_kind": DESIGN_SURVEY_ADAPTER_PLAN_KIND,
        "source_probe_adapter_id": DESIGN_SURVEY_ADAPTER_PLAN_ID,
        "created_at": created_at,
        "items": list(items),
        "summary": {
            "stage4_input_count": len(items),
            "project_count": len({item.get("project_id") for item in items}),
            "candidate_company_count": len({item.get("candidate_company_name") for item in items}),
            "design_survey_adapter_plan_only": True,
            "stage4_live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _scope_guardrails() -> dict[str, Any]:
    return {
        "does_not_apply_construction_project_manager_release_rule": True,
        "construction_release_source_targets_default_enabled": False,
        "forbidden_default_release_targets": list(CONSTRUCTION_RELEASE_TARGETS),
        "default_evidence_line": "person_company_certificate_and_enterprise_qualification_for_design_survey_role",
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    project_records: list[Mapping[str, Any]],
    skipped_records: list[Mapping[str, Any]],
    stage4_items: list[Mapping[str, Any]],
    task_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "design_survey_project_count": len(project_records),
        "ready_project_count": sum(
            1
            for record in project_records
            if str(record.get("adapter_readiness_state") or "") == "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN"
        ),
        "blocked_project_count": sum(
            1
            for record in project_records
            if str(record.get("adapter_readiness_state") or "") != "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN"
        ),
        "skipped_record_count": len(skipped_records),
        "stage4_input_count": len(stage4_items),
        "verification_task_count": len(task_records),
        "task_type_counts": _counts(record.get("task_type") for record in task_records),
        "responsible_role_counts": _counts(record.get("responsible_role") for record in project_records),
        "adapter_readiness_state_counts": _counts(record.get("adapter_readiness_state") for record in project_records),
        "highway_market_candidate_task_count": sum(
            1
            for record in task_records
            if "national_highway_construction_market_credit_personnel" in _list(record.get("source_families"))
        ),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "project_count": len(records),
        "adapter_readiness_state_counts": _counts(record.get("adapter_readiness_state") for record in records),
        "responsible_role_counts": _counts(record.get("responsible_role") for record in records),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _task_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "verification_task_count": len(records),
        "task_type_counts": _counts(record.get("task_type") for record in records),
        "execution_state_counts": _counts(record.get("execution_state") for record in records),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _is_design_survey_candidate(candidate: Mapping[str, Any]) -> bool:
    priority = str(candidate.get("opportunity_priority_class") or "").upper()
    lane = str(candidate.get("engineering_work_lane") or "").lower()
    if "DESIGN_SURVEY" in priority:
        return True
    if lane in {"survey_design", "design", "survey", "mapping", "planning_survey"}:
        return True
    text = " ".join(
        [
            str(candidate.get("project_name") or ""),
            str(candidate.get("primary_responsible_role") or ""),
        ]
    )
    if any(blocker in text for blocker in ("设计施工总承包", "工程总承包", "施工总承包", "EPC", "epc")):
        return False
    return any(keyword in text for keyword in ("勘察设计", "规划测绘", "测绘", "规划设计", "勘察", "设计"))


def _responsible_person(candidate: Mapping[str, Any]) -> str:
    for key in (
        "design_lead_name",
        "survey_lead_name",
        "primary_responsible_person_name",
        "project_manager_name",
        "chief_supervision_engineer_name",
    ):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def _responsible_role(candidate: Mapping[str, Any]) -> str:
    explicit = str(candidate.get("primary_responsible_role") or "").strip()
    if explicit:
        return explicit
    if str(candidate.get("design_lead_name") or "").strip():
        return "design_lead"
    if str(candidate.get("survey_lead_name") or "").strip():
        return "survey_lead"
    text = " ".join([str(candidate.get("project_name") or ""), str(candidate.get("engineering_work_lane") or "")])
    if any(keyword in text for keyword in ("测绘", "规划")):
        return "survey_mapping_project_lead"
    return "survey_design_project_lead"


def _certificate_no(candidate: Mapping[str, Any]) -> str:
    for key in (
        "project_manager_certificate_no",
        "certificate_no",
        "primary_responsible_certificate_no",
        "design_lead_certificate_no",
        "survey_lead_certificate_no",
    ):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def _current_project_time_window(candidate: Mapping[str, Any], readback: Mapping[str, Any]) -> dict[str, Any]:
    for source in (candidate, readback, readback.get("query_context") if isinstance(readback.get("query_context"), Mapping) else {}):
        window = source.get("current_project_time_window") or source.get("project_time_window")
        if isinstance(window, Mapping) and window:
            out = dict(window)
            out.setdefault("window_state", "CURRENT_PROJECT_TIME_WINDOW_PASSTHROUGH")
            out.setdefault("basis", "stage16_upstream_current_project_time_window")
            return out
    period_text = _first_text(
        [candidate, readback],
        (
            "current_project_period_text",
            "service_period_text",
            "design_service_period_text",
            "survey_service_period_text",
            "period_text",
            "duration_text",
            "服务期",
        ),
    )
    if period_text:
        return {
            "window_state": "CURRENT_PROJECT_TIME_WINDOW_PERIOD_TEXT_REVIEW",
            "period_text": period_text,
            "basis": "stage16_upstream_design_survey_period_text",
        }
    return {
        "window_state": "CURRENT_PROJECT_TIME_WINDOW_MISSING_REVIEW",
        "period_text": "",
        "basis": "design_survey_adapter_requires_current_notice_or_attachment_clock_readback",
    }


def _first_text(sources: Iterable[Mapping[str, Any]], keys: Iterable[str]) -> str:
    for source in sources:
        for key in keys:
            value = source.get(key)
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _highway_market_route_candidate(project: Mapping[str, Any], company_name: str) -> bool:
    text = " ".join(
        [
            str(project.get("project_name") or ""),
            company_name,
            str(project.get("responsible_role") or ""),
        ]
    )
    return any(
        keyword in text
        for keyword in ("高速", "公路", "路桥", "道路", "桥梁", "隧道", "交通规划", "交通运输", "设计研究院")
    )


def _split_consortium_companies(value: Any) -> list[dict[str, str]]:
    text = _clean_company_text(value)
    if not text:
        return []
    marker_matches = list(
        re.finditer(
            r"(?:^|[,，;；、])\s*[（(]\s*(?P<role>主|成)\s*[）)]\s*(?P<company>[^,，;；、]+)",
            text,
        )
    )
    rows: list[dict[str, str]] = []
    if marker_matches:
        for match in marker_matches:
            company = _clean_company_name(match.group("company"))
            if company:
                rows.append(
                    {
                        "company_name": company,
                        "consortium_member_role": "lead" if match.group("role") == "主" else "member",
                    }
                )
    else:
        parts = re.split(r"[,，;；、]", text)
        for index, part in enumerate(parts):
            company = _clean_company_name(part)
            if company:
                rows.append(
                    {
                        "company_name": company,
                        "consortium_member_role": "single" if len(parts) == 1 else ("lead" if index == 0 else "member"),
                    }
                )
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        key = row["company_name"]
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    if len(out) == 1:
        out[0]["consortium_member_role"] = "single"
    return out


def _clean_company_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[一二三四五六七八九十\d]+家[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _clean_company_name(value: Any) -> str:
    text = _clean_company_text(value)
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]\s*", "", text)
    text = re.sub(r"^(?:主|成)[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _candidate_group_id(project_id: Any, companies: list[Mapping[str, str]]) -> str:
    return f"CANDIDATE-GROUP-{_project_key(project_id) or _fingerprint(project_id)[:12]}-DESIGN-SURVEY-1"


def _skipped_record(candidate: Mapping[str, Any], reason: str, *, created_at: str) -> dict[str, Any]:
    return {
        "project_id": str(candidate.get("project_id") or ""),
        "project_name": str(candidate.get("project_name") or ""),
        "skip_reason": reason,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _latest_autonomous_run_refs(payload: Mapping[str, Any]) -> dict[str, Any]:
    operator_actions = payload.get("operator_actions") if isinstance(payload.get("operator_actions"), Mapping) else {}
    rows = operator_actions.get("operator-autonomous-opportunity-search-runs") if isinstance(operator_actions, Mapping) else []
    if not isinstance(rows, list) or not rows:
        return {}
    latest = rows[-1] if isinstance(rows[-1], Mapping) else {}
    refs = latest.get("object_refs") if isinstance(latest.get("object_refs"), Mapping) else {}
    return dict(refs)


def _readbacks_by_project(closed_loop_results: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in closed_loop_results if isinstance(closed_loop_results, list) else []:
        if not isinstance(row, Mapping):
            continue
        project_id = str(row.get("project_id") or "").strip()
        readback = row.get("real_public_stage4_9_readback")
        if project_id and isinstance(readback, Mapping):
            out[project_id] = readback
    return out


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"JG\d{4}-\d+(?:-\d+)?", text)
    if match:
        return match.group(0)
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build design/survey responsible-person adapter plan from Stage16 storage.")
    parser.add_argument("--stage16-storage-json", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_design_survey_responsible_adapter_plan(
        stage16_storage_json=args.stage16_storage_json,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
    )
    output_json = (
        Path(args.output_json)
        if args.output_json
        else Path(args.output_root) / "design-survey-responsible-adapter-plan-v1.json"
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "output_root": str(args.output_root),
                    "safe_to_execute": result["safe_to_execute"],
                    "summary": result["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DESIGN_SURVEY_ADAPTER_PLAN_KIND",
    "build_design_survey_responsible_adapter_plan",
]
