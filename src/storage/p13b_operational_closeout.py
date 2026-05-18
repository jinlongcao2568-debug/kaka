from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from stage4_verification.regional_hard_defect_sources import build_regional_hard_defect_source_plan


P13B_OPERATIONAL_CLOSEOUT_KIND = "p13b_operational_closeout_v1_manifest"
P13B_OPERATIONAL_CLOSEOUT_VERSION = 1
P13B_OPERATIONAL_CLOSEOUT_ADAPTER_ID = "p13b-operational-closeout-v1-builder"

DEFAULT_COMPANY_HISTORY_TRIAGE_ROOT = Path("tmp/evaluation-real-samples/p13b-company-history-overlap-triage-v1")
DEFAULT_ORIGINAL_NOTICE_BACKTRACE_ROOT = Path("tmp/evaluation-real-samples/p13b-original-notice-backtrace-v1")
DEFAULT_OVERLAP_TRIAGE_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/p13b-overlap-triage-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-operational-closeout-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
ALLOWED_PROJECT_STATES = {
    "OVERLAP_SIGNAL_REVIEW_REQUIRED",
    "ORIGINAL_NOTICE_READBACK_REQUIRED",
    "SOURCE_LIMIT_DEFERRED",
    "YGP_READBACK_BLOCKED_OR_UNSUPPORTED",
    "NO_OVERLAP_SIGNAL_REVIEW",
}
NEXT_ACTION_BY_STATE = {
    "OVERLAP_SIGNAL_REVIEW_REQUIRED": "targeted_release_evidence_probe",
    "ORIGINAL_NOTICE_READBACK_REQUIRED": "targeted_original_notice_01_to_12_backtrace",
    "SOURCE_LIMIT_DEFERRED": "rerun_with_higher_live_budget_after_review",
    "YGP_READBACK_BLOCKED_OR_UNSUPPORTED": "prepare_local_ygp_readback_or_keep_blocked_taxonomy",
    "NO_OVERLAP_SIGNAL_REVIEW": "keep_internal_review_no_clearance_conclusion",
}
DEFAULT_RELEASE_EVIDENCE_SOURCE_TARGETS = [
    "construction_permit",
    "contract_filing_or_contract_credit_info",
    "completion_or_acceptance_filing",
    "project_manager_change_notice",
]
RELEASE_EVIDENCE_SOURCE_TARGET_ALIASES = {
    "contract_filing_or_contract_credit_info": ("contract_public_info",),
    "contract_filing_or_contract_public_info": ("contract_public_info",),
    "contract_credit_info": ("contract_public_info",),
    "completion_or_acceptance_filing": ("completion_filing",),
    "completion_acceptance_or_completion_filing": ("completion_filing",),
    "construction_permit_change": ("construction_permit", "project_manager_change_notice"),
    "project_manager_change_notice_or_permit_change": ("project_manager_change_notice", "construction_permit"),
    "administrative_penalty_or_complaint_decision": (
        "administrative_penalty_public_record",
        "complaint_or_supervision_decision",
    ),
}
INITIAL_RELEASE_EVIDENCE_ABCD_GRADE = "A_STRONG_TIME_OVERLAP_SIGNAL"
DOWNSTREAM_RELEASE_EVIDENCE_POSSIBLE_ABCD_GRADES = [
    "B_ENHANCEMENT_OFFICIAL_READBACK",
    "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
    "D_INSUFFICIENT_OR_BLOCKED_READBACK",
]
P13B_RELEASE_EVIDENCE_ABCD_POLICY = {
    "policy_id": "P13B_RELEASE_EVIDENCE_ABCD_GRADING_V1",
    "initial_signal_grade": INITIAL_RELEASE_EVIDENCE_ABCD_GRADE,
    "primary_bcd_source_scope": "HISTORICAL_PROJECT_LOCAL_HOUSING_AUTHORITY_ONLY",
    "auxiliary_sources_not_default_bcd": [
        "national_jzsc_platform",
        "province_project_approval_system",
        "province_wide_credit_or_penalty_sources",
    ],
    "grades": {
        "A_STRONG_TIME_OVERLAP_SIGNAL": {
            "trigger": "data_ggzy_bid_show_or_targeted_original_notice_same_person_company_time_window_overlap",
            "downstream_probe_required_for_initial_signal_value": False,
        },
        "B_ENHANCEMENT_OFFICIAL_READBACK": {
            "trigger": "targeted_permit_contract_performance_or_personnel_public_readback_hit",
            "role": "enhance_initial_signal",
        },
        "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": {
            "trigger": "targeted_completion_change_release_or_exemption_public_readback_hit",
            "role": "reverse_explanation_or_responsibility_window_split",
        },
        "D_INSUFFICIENT_OR_BLOCKED_READBACK": {
            "trigger": "targeted_source_blocked_unavailable_or_no_public_field_match_after_attempt",
            "role": "evidence_gap_not_signal_downgrade",
        },
    },
    "region_rule": "query_historical_overlap_project_region_first_then_current_project_region_fallback",
}
P13B_PRIMARY_RELEASE_SOURCE_SCOPE = "HISTORICAL_PROJECT_LOCAL_HOUSING_AUTHORITY_ONLY"
P13B_LOCAL_HOUSING_ADAPTER_REQUIRED = "LOCAL_HOUSING_AUTHORITY_ADAPTER_REQUIRED"
REGION_CODE_BY_CITY_PREFIX = {
    "11": "CN-BJ",
    "12": "CN-TJ",
    "13": "CN-HE",
    "14": "CN-SX",
    "15": "CN-NM",
    "21": "CN-LN",
    "22": "CN-JL",
    "23": "CN-HL",
    "31": "CN-SH",
    "32": "CN-JS",
    "33": "CN-ZJ",
    "34": "CN-AH",
    "35": "CN-FJ",
    "36": "CN-JX",
    "37": "CN-SD",
    "41": "CN-HA",
    "42": "CN-HB",
    "43": "CN-HN",
    "44": "CN-GD",
    "45": "CN-GX",
    "46": "CN-HI",
    "50": "CN-CQ",
    "51": "CN-SC",
    "52": "CN-GZ",
    "53": "CN-YN",
    "54": "CN-XZ",
    "61": "CN-SN",
    "62": "CN-GS",
    "63": "CN-QH",
    "64": "CN-NX",
    "65": "CN-XJ",
}
REGION_CODE_BY_AREA_HINT = (
    ("CN-GD", ("广东", "广州", "深圳", "珠海", "佛山", "东莞", "惠州", "中山", "江门", "肇庆", "清远", "汕头", "湛江", "茂名", "韶关", "河源", "梅州", "汕尾", "阳江", "潮州", "揭阳", "云浮")),
    ("CN-ZJ", ("浙江", "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水")),
    ("CN-SC", ("四川", "成都", "绵阳", "德阳", "宜宾", "泸州", "南充", "达州", "乐山", "眉山", "内江", "自贡")),
    ("CN-JS", ("江苏", "南京", "苏州", "无锡", "常州", "南通", "扬州", "镇江", "泰州", "盐城", "徐州", "淮安", "连云港", "宿迁")),
    ("CN-HB", ("湖北", "武汉", "宜昌", "襄阳", "荆州", "黄石", "十堰", "孝感", "黄冈", "咸宁", "随州")),
    ("CN-SD", ("山东", "济南", "青岛", "烟台", "潍坊", "临沂", "济宁", "淄博", "泰安", "威海", "日照", "德州", "聊城", "滨州", "菏泽")),
    ("CN-HN", ("湖南", "长沙", "株洲", "湘潭", "衡阳", "岳阳", "常德", "益阳", "郴州", "永州", "怀化", "娄底")),
    ("CN-HA", ("河南", "郑州", "洛阳", "开封", "新乡", "许昌", "平顶山", "安阳", "焦作", "南阳", "商丘", "信阳", "周口", "驻马店")),
)


def build_p13b_operational_closeout(
    *,
    company_history_triage_root: str | Path = DEFAULT_COMPANY_HISTORY_TRIAGE_ROOT,
    original_notice_backtrace_root: str | Path = DEFAULT_ORIGINAL_NOTICE_BACKTRACE_ROOT,
    overlap_triage_closeout_root: str | Path = DEFAULT_OVERLAP_TRIAGE_CLOSEOUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    company_dir = Path(company_history_triage_root)
    original_dir = Path(original_notice_backtrace_root)
    closeout_dir = Path(overlap_triage_closeout_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    company_payload = _load_json(
        company_dir / "company-history-overlap-triage-v1.json",
        blocking_reasons,
        "p13b_company_history_overlap_triage_missing",
    )
    original_payload = _load_json(
        original_dir / "original-notice-backtrace-v1.json",
        blocking_reasons,
        "p13b_original_notice_backtrace_missing",
    )
    closeout_payload = _load_json(
        closeout_dir / "p13b-overlap-triage-closeout-v1.json",
        blocking_reasons,
        "p13b_overlap_triage_closeout_missing",
    )

    company_manifest = _source_manifest(company_payload)
    original_manifest = _source_manifest(original_payload)
    closeout_manifest = _source_manifest(closeout_payload)
    company_summary = _summary(company_payload)
    original_summary = _summary(original_payload)
    closeout_summary = _summary(closeout_payload)

    project_records = [
        dict(record)
        for record in _list(closeout_manifest.get("project_overlap_triage_records"))
        if isinstance(record, Mapping)
    ]
    unexpected_states = sorted(
        {
            str(record.get("project_overlap_triage_state") or "")
            for record in project_records
            if str(record.get("project_overlap_triage_state") or "") not in ALLOWED_PROJECT_STATES
        }
    )
    if unexpected_states:
        blocking_reasons.extend(f"unexpected_project_overlap_triage_state:{state}" for state in unexpected_states)

    project_next_action_records = [
        _project_next_action_record(record)
        for record in project_records
    ]
    release_evidence_probe_plan_records = _release_evidence_probe_plan_records(
        closeout_manifest=closeout_manifest,
        project_records=project_records,
        created_at=created,
    )
    release_evidence_probe_task_records = _release_evidence_probe_task_records(
        closeout_manifest=closeout_manifest,
        project_records=project_records,
        plan_records=release_evidence_probe_plan_records,
        created_at=created,
    )
    budget_audit_records = _budget_audit_records(
        company_manifest=company_manifest,
        original_manifest=original_manifest,
        closeout_manifest=closeout_manifest,
        company_summary=company_summary,
        original_summary=original_summary,
        closeout_summary=closeout_summary,
        created_at=created,
    )

    summary = _build_summary(
        project_records=project_records,
        company_summary=company_summary,
        original_summary=original_summary,
        closeout_summary=closeout_summary,
        blocking_reasons=blocking_reasons,
    )
    summary["release_evidence_probe_task_count"] = len(release_evidence_probe_task_records)
    summary["release_evidence_initial_abcd_grade_counts"] = _counts(
        record.get("initial_release_evidence_abcd_grade") for record in release_evidence_probe_plan_records
    )
    summary["release_evidence_query_region_basis_counts"] = _counts(
        record.get("release_evidence_query_region_basis") for record in release_evidence_probe_plan_records
    )
    summary["release_evidence_task_initial_abcd_grade_counts"] = _counts(
        record.get("initial_release_evidence_abcd_grade") for record in release_evidence_probe_task_records
    )
    manifest = {
        "manifest_version": P13B_OPERATIONAL_CLOSEOUT_VERSION,
        "manifest_kind": P13B_OPERATIONAL_CLOSEOUT_KIND,
        "adapter_id": P13B_OPERATIONAL_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "P13BOperationalCloseoutV1",
        "manifest_id": f"P13B-OPERATIONAL-CLOSEOUT-{_fingerprint({'summary': summary, 'projects': project_records})[:16]}",
        "created_at": created,
        "source_company_history_triage_root": str(company_dir),
        "source_original_notice_backtrace_root": str(original_dir),
        "source_overlap_triage_closeout_root": str(closeout_dir),
        "summary": summary,
        "release_evidence_abcd_policy": P13B_RELEASE_EVIDENCE_ABCD_POLICY,
        "project_next_action_records": project_next_action_records,
        "release_evidence_probe_plan_records": release_evidence_probe_plan_records,
        "release_evidence_probe_task_records": release_evidence_probe_task_records,
        "budget_audit_records": budget_audit_records,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "flow_08_parse_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "p13b_operational_closeout_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(
        out_dir,
        result,
        project_next_action_records,
        release_evidence_probe_plan_records,
        release_evidence_probe_task_records,
        budget_audit_records,
    )
    return result


def _project_next_action_record(record: Mapping[str, Any]) -> dict[str, Any]:
    state = str(record.get("project_overlap_triage_state") or "")
    return {
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "city_code": str(record.get("city_code") or ""),
        "project_overlap_triage_state": state,
        "recommended_next_action": NEXT_ACTION_BY_STATE.get(state, "manual_review_unexpected_state"),
        "candidate_companies": _list(record.get("candidate_companies")),
        "responsible_person_names": _list(record.get("responsible_person_names")),
        "release_evidence_trigger_count": _int(record.get("release_evidence_trigger_count")),
        "original_notice_readback_count": _int(record.get("original_notice_readback_count")),
        "source_limit_deferred_count": _int(record.get("source_limit_deferred_count")),
        "original_notice_state_counts": dict(record.get("original_notice_state_counts") or {}),
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _release_evidence_probe_plan_records(
    *,
    closeout_manifest: Mapping[str, Any],
    project_records: list[Mapping[str, Any]],
    created_at: str,
) -> list[dict[str, Any]]:
    project_by_id = {str(record.get("project_id") or ""): record for record in project_records}
    rows: list[dict[str, Any]] = []
    for trigger in _list(closeout_manifest.get("release_evidence_trigger_records")):
        if not isinstance(trigger, Mapping):
            continue
        project_id = str(trigger.get("project_id") or "")
        project = project_by_id.get(project_id, {})
        candidate_company = str(trigger.get("candidate_company_name") or "")
        person_names = _list(trigger.get("matched_person_names")) or _list(trigger.get("responsible_person_names"))
        region_context = _release_evidence_region_context(trigger, project)
        city_code = str(region_context["current_project_city_code"])
        region_code = str(region_context["release_evidence_query_region_code"])
        source_targets = _list(trigger.get("release_evidence_source_targets")) or DEFAULT_RELEASE_EVIDENCE_SOURCE_TARGETS
        source_plan = build_regional_hard_defect_source_plan(
            {
                "region_code": region_code,
                "project_id": project_id,
                "project_name": str(trigger.get("project_name") or project.get("project_name") or trigger.get("bid_project_name") or ""),
                "candidate_company": candidate_company,
                "project_manager_name": str(person_names[0] if person_names else ""),
                "source_url": str(trigger.get("source_url") or ""),
            }
        )
        primary_entries = _p13b_primary_release_source_entries(
            source_plan,
            city_code=city_code,
            region_code=region_code,
            region_context=region_context,
        )
        rows.append(
            {
                "release_evidence_probe_plan_id": _stable_id(
                    "P13B-RELEASE-PROBE-PLAN",
                    trigger.get("release_evidence_trigger_id"),
                    project_id,
                    candidate_company,
                    trigger.get("source_url"),
                ),
                "release_evidence_trigger_id": str(trigger.get("release_evidence_trigger_id") or ""),
                "source_stage": str(trigger.get("source_stage") or ""),
                "project_id": project_id,
                "project_name": str(trigger.get("project_name") or project.get("project_name") or ""),
                "city_code": city_code,
                "region_code": region_code,
                "current_project_city_code": city_code,
                "current_project_region_code": str(region_context["current_project_region_code"]),
                "historical_project_area_code": str(region_context["historical_project_area_code"]),
                "historical_project_region_code": str(region_context["historical_project_region_code"]),
                "release_evidence_query_region_code": region_code,
                "release_evidence_query_region_basis": str(region_context["release_evidence_query_region_basis"]),
                "release_evidence_query_region_missing": bool(region_context["release_evidence_query_region_missing"]),
                "candidate_company_name": candidate_company,
                "matched_person_names": person_names,
                "source_url": str(trigger.get("source_url") or ""),
                "extracted_period_text": str(trigger.get("extracted_period_text") or ""),
                "extracted_award_date": str(trigger.get("extracted_award_date") or ""),
                "time_window_review_state": str(trigger.get("time_window_review_state") or ""),
                "estimated_performance_end_date": str(trigger.get("estimated_performance_end_date") or ""),
                "release_evidence_source_targets": source_targets,
                "source_plan_state": str(source_plan.get("plan_state") or ""),
                "source_plan_coverage_state": str(source_plan.get("coverage_state") or ""),
                "source_entry_count": len(primary_entries),
                "source_plan_total_entry_count": len(_list(source_plan.get("source_entries"))),
                "primary_release_evidence_source_scope": P13B_PRIMARY_RELEASE_SOURCE_SCOPE,
                "primary_release_evidence_source_selection_state": (
                    "PRIMARY_LOCAL_HOUSING_AUTHORITY_SOURCE_READY"
                    if primary_entries
                    else P13B_LOCAL_HOUSING_ADAPTER_REQUIRED
                ),
                "auxiliary_sources_not_default_bcd": [
                    "national_jzsc_platform",
                    "province_project_approval_system",
                    "province_wide_credit_or_penalty_sources",
                ],
                "next_required_runtime_adapters": _next_adapters_for_primary_entries(primary_entries),
                "initial_release_evidence_abcd_grade": INITIAL_RELEASE_EVIDENCE_ABCD_GRADE,
                "initial_release_evidence_abcd_grade_basis": [
                    "same_person_company_time_window_overlap_from_data_ggzy_or_targeted_original_notice"
                ],
                "downstream_probe_role": "enhancement_or_reverse_explanation_not_prerequisite_for_initial_signal",
                "downstream_possible_release_evidence_abcd_grades": list(DOWNSTREAM_RELEASE_EVIDENCE_POSSIBLE_ABCD_GRADES),
                "recommended_next_action": "prepare_targeted_release_evidence_probe_tasks",
                "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                "query_miss_is_not_clearance": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "created_at": created_at,
            }
        )
    return rows


def _release_evidence_probe_task_records(
    *,
    closeout_manifest: Mapping[str, Any],
    project_records: list[Mapping[str, Any]],
    plan_records: list[Mapping[str, Any]],
    created_at: str,
) -> list[dict[str, Any]]:
    project_by_id = {str(record.get("project_id") or ""): record for record in project_records}
    plan_by_trigger_id = {
        str(record.get("release_evidence_trigger_id") or ""): record
        for record in plan_records
    }
    rows: list[dict[str, Any]] = []
    for trigger in _list(closeout_manifest.get("release_evidence_trigger_records")):
        if not isinstance(trigger, Mapping):
            continue
        project_id = str(trigger.get("project_id") or "")
        project = project_by_id.get(project_id, {})
        trigger_id = str(trigger.get("release_evidence_trigger_id") or "")
        plan = plan_by_trigger_id.get(trigger_id, {})
        candidate_company = str(trigger.get("candidate_company_name") or "")
        person_names = _list(trigger.get("matched_person_names")) or _list(trigger.get("responsible_person_names"))
        region_context = _release_evidence_region_context(trigger, project)
        city_code = str(region_context["current_project_city_code"])
        region_code = str(region_context["release_evidence_query_region_code"])
        raw_source_targets = _list(trigger.get("release_evidence_source_targets")) or DEFAULT_RELEASE_EVIDENCE_SOURCE_TARGETS
        canonical_source_targets = _canonical_source_targets(raw_source_targets)
        source_plan = build_regional_hard_defect_source_plan(
            {
                "region_code": region_code,
                "project_id": project_id,
                "project_name": str(trigger.get("project_name") or project.get("project_name") or trigger.get("bid_project_name") or ""),
                "candidate_company": candidate_company,
                "project_manager_name": str(person_names[0] if person_names else ""),
                "source_url": str(trigger.get("source_url") or ""),
            }
        )
        primary_entries = _p13b_primary_release_source_entries(
            source_plan,
            city_code=city_code,
            region_code=region_code,
            region_context=region_context,
        )
        for entry in primary_entries:
            if not isinstance(entry, Mapping):
                continue
            rows.extend(
                _task_rows_for_source_entry(
                    trigger=trigger,
                    plan=plan,
                    project=project,
                    region_context=region_context,
                    entry=entry,
                    raw_source_targets=raw_source_targets,
                    canonical_source_targets=canonical_source_targets,
                    person_names=person_names,
                    created_at=created_at,
                )
            )
    return rows


def _task_rows_for_source_entry(
    *,
    trigger: Mapping[str, Any],
    plan: Mapping[str, Any],
    project: Mapping[str, Any],
    region_context: Mapping[str, Any],
    entry: Mapping[str, Any],
    raw_source_targets: list[Any],
    canonical_source_targets: list[str],
    person_names: list[Any],
    created_at: str,
) -> list[dict[str, Any]]:
    rows = []
    parent_row = _task_row_from_source(
        trigger=trigger,
        plan=plan,
        project=project,
        region_context=region_context,
        source=entry,
        parent_entry=entry,
        source_granularity="source_entry",
        raw_source_targets=raw_source_targets,
        canonical_source_targets=canonical_source_targets,
        person_names=person_names,
        created_at=created_at,
    )
    if parent_row:
        rows.append(parent_row)
    for subsource in _list(entry.get("verified_public_subsources")):
        if not isinstance(subsource, Mapping):
            continue
        child_row = _task_row_from_source(
            trigger=trigger,
            plan=plan,
            project=project,
            region_context=region_context,
            source=subsource,
            parent_entry=entry,
            source_granularity="verified_public_subsource",
            raw_source_targets=raw_source_targets,
            canonical_source_targets=canonical_source_targets,
            person_names=person_names,
            created_at=created_at,
        )
        if child_row:
            rows.append(child_row)
    return rows


def _task_row_from_source(
    *,
    trigger: Mapping[str, Any],
    plan: Mapping[str, Any],
    project: Mapping[str, Any],
    region_context: Mapping[str, Any],
    source: Mapping[str, Any],
    parent_entry: Mapping[str, Any],
    source_granularity: str,
    raw_source_targets: list[Any],
    canonical_source_targets: list[str],
    person_names: list[Any],
    created_at: str,
) -> dict[str, Any] | None:
    source_target_types = _canonical_source_targets(_list(source.get("target_source_types")))
    matched_target_types = sorted(set(source_target_types) & set(canonical_source_targets))
    if not matched_target_types:
        return None
    project_id = str(trigger.get("project_id") or "")
    source_entry_id = str(parent_entry.get("entry_id") or "")
    subsource_id = str(source.get("subsource_id") or "")
    source_profile_id = str(source.get("source_profile_id") or parent_entry.get("source_profile_id") or "")
    candidate_company = str(trigger.get("candidate_company_name") or "")
    project_name = str(trigger.get("project_name") or project.get("project_name") or "")
    task_source_url = str(source.get("source_url") or parent_entry.get("source_url") or "")
    task_id = _stable_id(
        "P13B-RELEASE-PROBE-TASK",
        trigger.get("release_evidence_trigger_id"),
        project_id,
        candidate_company,
        source_entry_id,
        subsource_id,
        ",".join(matched_target_types),
    )
    return {
        "release_evidence_probe_task_id": task_id,
        "release_evidence_probe_plan_id": str(plan.get("release_evidence_probe_plan_id") or ""),
        "release_evidence_trigger_id": str(trigger.get("release_evidence_trigger_id") or ""),
        "source_stage": str(trigger.get("source_stage") or ""),
        "project_id": project_id,
        "project_name": project_name,
        "city_code": str(project.get("city_code") or trigger.get("city_code") or ""),
        "region_code": str(plan.get("region_code") or region_context.get("release_evidence_query_region_code") or ""),
        "current_project_city_code": str(region_context.get("current_project_city_code") or ""),
        "current_project_region_code": str(region_context.get("current_project_region_code") or ""),
        "historical_project_area_code": str(region_context.get("historical_project_area_code") or ""),
        "historical_project_region_code": str(region_context.get("historical_project_region_code") or ""),
        "release_evidence_query_region_code": str(region_context.get("release_evidence_query_region_code") or ""),
        "release_evidence_query_region_basis": str(region_context.get("release_evidence_query_region_basis") or ""),
        "release_evidence_query_region_missing": bool(region_context.get("release_evidence_query_region_missing")),
        "candidate_company_name": candidate_company,
        "matched_person_names": person_names,
        "trigger_source_url": str(trigger.get("source_url") or ""),
        "extracted_period_text": str(trigger.get("extracted_period_text") or ""),
        "extracted_award_date": str(trigger.get("extracted_award_date") or ""),
        "time_window_review_state": str(trigger.get("time_window_review_state") or ""),
        "estimated_performance_end_date": str(trigger.get("estimated_performance_end_date") or ""),
        "source_granularity": source_granularity,
        "source_entry_id": source_entry_id,
        "subsource_id": subsource_id,
        "source_profile_id": source_profile_id,
        "source_profile_ids": _list(parent_entry.get("source_profile_ids")) or ([source_profile_id] if source_profile_id else []),
        "source_name": str(source.get("source_name") or parent_entry.get("source_name") or ""),
        "source_url": task_source_url,
        "api_url": str(source.get("api_url") or ""),
        "official_reference_url": str(
            source.get("official_reference_url")
            or source.get("official_parent_url")
            or parent_entry.get("official_reference_url")
            or parent_entry.get("official_parent_url")
            or ""
        ),
        "source_family": str(source.get("source_family") or parent_entry.get("source_family") or ""),
        "requested_release_evidence_source_targets": raw_source_targets,
        "canonical_release_evidence_source_targets": canonical_source_targets,
        "source_target_source_types": source_target_types,
        "matched_target_source_types": matched_target_types,
        "initial_release_evidence_abcd_grade": str(
            trigger.get("initial_release_evidence_abcd_grade")
            or plan.get("initial_release_evidence_abcd_grade")
            or INITIAL_RELEASE_EVIDENCE_ABCD_GRADE
        ),
        "initial_release_evidence_abcd_grade_basis": _list(
            trigger.get("initial_release_evidence_abcd_grade_basis")
            or plan.get("initial_release_evidence_abcd_grade_basis")
        )
        or ["same_person_company_time_window_overlap_from_data_ggzy_or_targeted_original_notice"],
        "downstream_probe_role": str(
            plan.get("downstream_probe_role")
            or "enhancement_or_reverse_explanation_not_prerequisite_for_initial_signal"
        ),
        "downstream_possible_release_evidence_abcd_grades": _list(
            plan.get("downstream_possible_release_evidence_abcd_grades")
        )
        or list(DOWNSTREAM_RELEASE_EVIDENCE_POSSIBLE_ABCD_GRADES),
        "query_keys": _list(source.get("query_keys")) or _list(parent_entry.get("query_keys")),
        "query_params": _release_evidence_query_params(
            project_id=project_id,
            project_name=project_name,
            candidate_company=candidate_company,
            person_names=person_names,
            source_profile_id=source_profile_id,
            source_target_types=matched_target_types,
            trigger_source_url=str(trigger.get("source_url") or ""),
            region_context=region_context,
        ),
        "runtime_status": str(source.get("runtime_status") or parent_entry.get("runtime_status") or ""),
        "next_adapter": str(source.get("next_adapter") or parent_entry.get("next_adapter") or ""),
        "task_state": "PLAN_ONLY_NOT_EXECUTED",
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "readback_ready": False,
        "recommended_next_action": "run_targeted_release_evidence_probe_adapter_when_approved",
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "created_at": created_at,
    }


def _release_evidence_query_params(
    *,
    project_id: str,
    project_name: str,
    candidate_company: str,
    person_names: list[Any],
    source_profile_id: str,
    source_target_types: list[str],
    trigger_source_url: str,
    region_context: Mapping[str, Any],
) -> dict[str, Any]:
    primary_person_name = str(person_names[0] if person_names else "")
    return {
        "projectId": project_id,
        "projectName": project_name,
        "candidateCompanyName": candidate_company,
        "projectManagerName": primary_person_name,
        "projectManagerNameVariants": _dedupe([str(item) for item in person_names if str(item)]),
        "sourceProfileId": source_profile_id,
        "targetSourceTypes": source_target_types,
        "triggerSourceUrl": trigger_source_url,
        "currentProjectCityCode": str(region_context.get("current_project_city_code") or ""),
        "currentProjectRegionCode": str(region_context.get("current_project_region_code") or ""),
        "historicalProjectAreaCode": str(region_context.get("historical_project_area_code") or ""),
        "historicalProjectRegionCode": str(region_context.get("historical_project_region_code") or ""),
        "releaseEvidenceQueryRegionCode": str(region_context.get("release_evidence_query_region_code") or ""),
        "releaseEvidenceQueryRegionBasis": str(region_context.get("release_evidence_query_region_basis") or ""),
        "keywords": _dedupe([project_name, candidate_company, primary_person_name]),
    }


def _canonical_source_targets(values: list[Any]) -> list[str]:
    targets: list[str] = []
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        aliases = RELEASE_EVIDENCE_SOURCE_TARGET_ALIASES.get(key, (key,))
        targets.extend(str(alias) for alias in aliases if str(alias).strip())
    return _dedupe(targets)


def _source_entry_is_immediate_for_project(
    entry: Mapping[str, Any],
    *,
    city_code: str,
    region_code: str,
    historical_area_code: str,
) -> bool:
    profile_id = str(entry.get("source_profile_id") or "")
    entry_region = str(entry.get("region_code") or "").upper()
    normalized_region = str(region_code or "").upper()
    if profile_id == "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY":
        if str(historical_area_code or "").strip():
            return _area_text_matches_city(
                historical_area_code,
                city_prefix="4401",
                city_name="广州",
            )
        return str(city_code or "").startswith("4401") or _area_text_matches_city(
            historical_area_code,
            city_prefix="4401",
            city_name="广州",
        )
    if entry_region and entry_region != normalized_region:
        return False
    return True


def _p13b_primary_release_source_entries(
    source_plan: Mapping[str, Any],
    *,
    city_code: str,
    region_code: str,
    region_context: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    for entry in _list(source_plan.get("source_entries")):
        if not isinstance(entry, Mapping):
            continue
        if not _source_entry_is_immediate_for_project(
            entry,
            city_code=city_code,
            region_code=region_code,
            historical_area_code=str(region_context.get("historical_project_area_code") or ""),
        ):
            continue
        if not _source_entry_is_p13b_primary_release_source(entry, region_code=region_code):
            continue
        entries.append(entry)
    return entries


def _source_entry_is_p13b_primary_release_source(entry: Mapping[str, Any], *, region_code: str) -> bool:
    entry_id = str(entry.get("entry_id") or "")
    entry_region = str(entry.get("region_code") or "").upper()
    source_family = str(entry.get("source_family") or "")
    normalized_region = str(region_code or "").upper()
    if entry_id == "GZ-ZFCJ-CREDIT-DOUBLE-PUBLICITY":
        return normalized_region == "CN-GD"
    if source_family == "regional_construction_market_public_service" and entry_region == normalized_region:
        return True
    return False


def _next_adapters_for_primary_entries(entries: list[Mapping[str, Any]]) -> list[str]:
    adapters = _dedupe(
        [
            str(entry.get("next_adapter") or "")
            for entry in entries
            if str(entry.get("next_adapter") or "").strip()
        ]
    )
    for entry in entries:
        for subsource in _list(entry.get("verified_public_subsources")):
            if not isinstance(subsource, Mapping):
                continue
            adapter = str(subsource.get("next_adapter") or "").strip()
            if adapter:
                adapters = _dedupe([*adapters, adapter])
    return adapters or ["local_housing_authority_release_evidence_adapter_required"]


def _release_evidence_region_context(trigger: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, Any]:
    current_city_code = str(project.get("city_code") or trigger.get("city_code") or "")
    current_region_code = str(
        project.get("region_code")
        or trigger.get("current_project_region_code")
        or trigger.get("region_code")
        or _region_code_from_city_code(current_city_code)
        or ""
    ).upper()
    historical_area_code = str(
        trigger.get("historical_project_area_code")
        or trigger.get("bid_area_code")
        or ""
    )
    historical_region_code = str(
        trigger.get("historical_project_region_code")
        or _region_code_from_area_text(historical_area_code)
        or ""
    ).upper()
    query_region_code = historical_region_code or current_region_code
    if historical_region_code:
        basis = "HISTORICAL_OVERLAP_PROJECT_REGION"
    elif query_region_code:
        basis = "CURRENT_PROJECT_REGION_FALLBACK"
    else:
        basis = "REGION_UNRESOLVED"
    return {
        "current_project_city_code": current_city_code,
        "current_project_region_code": current_region_code,
        "historical_project_area_code": historical_area_code,
        "historical_project_region_code": historical_region_code,
        "release_evidence_query_region_code": query_region_code,
        "release_evidence_query_region_basis": basis,
        "release_evidence_query_region_missing": not bool(historical_region_code),
    }


def _budget_audit_records(
    *,
    company_manifest: Mapping[str, Any],
    original_manifest: Mapping[str, Any],
    closeout_manifest: Mapping[str, Any],
    company_summary: Mapping[str, Any],
    original_summary: Mapping[str, Any],
    closeout_summary: Mapping[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    company_rows = [
        dict(record)
        for record in _list(closeout_manifest.get("company_history_readback_records"))
        if isinstance(record, Mapping)
    ]
    original_rows = [
        dict(record)
        for record in _list(closeout_manifest.get("original_notice_readback_records"))
        if isinstance(record, Mapping)
    ]
    return [
        {
            "budget_scope": "COMPANY_HISTORY_QUERY",
            "execution_mode": str(company_manifest.get("execution_mode") or company_summary.get("execution_mode") or ""),
            "configured_limit": _int_or_none(company_manifest.get("max_live_companies")),
            "actual_processed_count": _int(company_summary.get("queried_company_count")),
            "deferred_count": sum(1 for row in company_rows if str(row.get("triage_closeout_state") or "") == "SOURCE_LIMIT_DEFERRED"),
            "blocker_count": sum(1 for row in company_rows if str(row.get("triage_closeout_state") or "") == "ORIGINAL_NOTICE_READBACK_REQUIRED"),
            "budget_state": _budget_state(
                configured_limit=_int_or_none(company_manifest.get("max_live_companies")),
                actual_processed_count=_int(company_summary.get("queried_company_count")),
                deferred_count=sum(1 for row in company_rows if str(row.get("triage_closeout_state") or "") == "SOURCE_LIMIT_DEFERRED"),
            ),
            "history_window_years": _list(company_manifest.get("history_window_years")),
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        {
            "budget_scope": "BID_RECORDS_PER_COMPANY",
            "execution_mode": str(company_manifest.get("execution_mode") or company_summary.get("execution_mode") or ""),
            "configured_limit": _int_or_none(company_manifest.get("max_bid_records_per_company")),
            "actual_processed_count": _int(closeout_summary.get("bid_show_record_count")),
            "deferred_count": 0,
            "blocker_count": 0,
            "budget_state": _budget_state(
                configured_limit=_int_or_none(company_manifest.get("max_bid_records_per_company")),
                actual_processed_count=_int(closeout_summary.get("bid_show_record_count")),
                deferred_count=0,
            ),
            "history_window_years": _list(company_manifest.get("history_window_years")),
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        {
            "budget_scope": "ORIGINAL_NOTICE_BACKTRACE",
            "execution_mode": str(original_manifest.get("execution_mode") or original_summary.get("execution_mode") or ""),
            "configured_limit": _int_or_none(original_manifest.get("max_live_original_notices")),
            "actual_processed_count": _int(original_summary.get("live_processed_count") or original_summary.get("original_notice_fetch_count")),
            "deferred_count": sum(1 for row in original_rows if str(row.get("triage_closeout_state") or "") == "SOURCE_LIMIT_DEFERRED"),
            "blocker_count": sum(1 for row in original_rows if str(row.get("triage_closeout_state") or "") == "ORIGINAL_NOTICE_READBACK_REQUIRED"),
            "budget_state": _budget_state(
                configured_limit=_int_or_none(original_manifest.get("max_live_original_notices")),
                actual_processed_count=_int(original_summary.get("live_processed_count") or original_summary.get("original_notice_fetch_count")),
                deferred_count=sum(1 for row in original_rows if str(row.get("triage_closeout_state") or "") == "SOURCE_LIMIT_DEFERRED"),
            ),
            "history_window_years": [],
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    ]


def _budget_state(*, configured_limit: int | None, actual_processed_count: int, deferred_count: int) -> str:
    if configured_limit is None:
        return "BUDGET_UNSPECIFIED"
    if deferred_count > 0:
        return "BUDGET_LIMIT_DEFERRED"
    if actual_processed_count > configured_limit:
        return "BUDGET_EXCEEDED_REVIEW"
    return "BUDGET_WITHIN_LIMIT"


def _build_summary(
    *,
    project_records: list[Mapping[str, Any]],
    company_summary: Mapping[str, Any],
    original_summary: Mapping[str, Any],
    closeout_summary: Mapping[str, Any],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    state_counts = _counts(record.get("project_overlap_triage_state") for record in project_records)
    return {
        "p13b_operational_closeout_state": "P13B_OPERATIONAL_CLOSEOUT_READY" if not blocking_reasons else "P13B_OPERATIONAL_CLOSEOUT_INPUT_BLOCKED",
        "input_project_count": len(project_records) or _int(company_summary.get("project_task_count")),
        "queried_company_count": _int(company_summary.get("queried_company_count")),
        "source_limit_deferred_count": state_counts.get("SOURCE_LIMIT_DEFERRED", 0),
        "original_notice_backtrace_required_count": state_counts.get("ORIGINAL_NOTICE_READBACK_REQUIRED", 0),
        "release_evidence_trigger_count": state_counts.get("OVERLAP_SIGNAL_REVIEW_REQUIRED", 0),
        "release_evidence_probe_plan_count": _int(closeout_summary.get("release_evidence_trigger_count")) or state_counts.get("OVERLAP_SIGNAL_REVIEW_REQUIRED", 0),
        "ygp_readback_blocked_or_unsupported_count": state_counts.get("YGP_READBACK_BLOCKED_OR_UNSUPPORTED", 0),
        "no_overlap_signal_review_count": state_counts.get("NO_OVERLAP_SIGNAL_REVIEW", 0),
        "project_state_counts": state_counts,
        "company_history_execution_mode": str(company_summary.get("execution_mode") or ""),
        "original_notice_execution_mode": str(original_summary.get("execution_mode") or ""),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    project_next_action_records: list[Mapping[str, Any]],
    release_evidence_probe_plan_records: list[Mapping[str, Any]],
    release_evidence_probe_task_records: list[Mapping[str, Any]],
    budget_audit_records: list[Mapping[str, Any]],
) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *list(result.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    _write_json(out_dir / "p13b-project-next-action-table.json", {"summary": result["summary"], "records": project_next_action_records})
    _write_json(out_dir / "p13b-release-evidence-probe-plan-table.json", {"summary": result["summary"], "records": release_evidence_probe_plan_records})
    _write_json(out_dir / "p13b-release-evidence-probe-task-table.json", {"summary": result["summary"], "records": release_evidence_probe_task_records})
    _write_json(out_dir / "p13b-budget-audit-table.json", {"summary": result["summary"], "records": budget_audit_records})
    _write_json(out_dir / "p13b-operational-closeout-v1.json", result)


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = payload.get("summary") if isinstance(payload, Mapping) else {}
    if isinstance(summary, Mapping):
        return summary
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping) and isinstance(manifest.get("summary"), Mapping):
        return manifest["summary"]  # type: ignore[return-value]
    return {}


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


def _dedupe(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return int(value)
        return int(value)
    except Exception:
        return None


def _region_code_from_city_code(city_code: str) -> str:
    code = str(city_code or "")
    for prefix, region_code in REGION_CODE_BY_CITY_PREFIX.items():
        if code.startswith(prefix):
            return region_code
    return ""


def _region_code_from_area_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper.startswith("CN-"):
        return upper
    digits = "".join(char for char in text if char.isdigit())
    if digits:
        region_code = _region_code_from_city_code(digits)
        if region_code:
            return region_code
    for region_code, hints in REGION_CODE_BY_AREA_HINT:
        if any(hint in text for hint in hints):
            return region_code
    return ""


def _area_text_matches_city(value: Any, *, city_prefix: str, city_name: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    digits = "".join(char for char in text if char.isdigit())
    if digits.startswith(city_prefix):
        return True
    if city_name and city_name in text:
        return True
    return False


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B operational closeout v1.")
    parser.add_argument("--company-history-triage-root", default=str(DEFAULT_COMPANY_HISTORY_TRIAGE_ROOT))
    parser.add_argument("--original-notice-backtrace-root", default=str(DEFAULT_ORIGINAL_NOTICE_BACKTRACE_ROOT))
    parser.add_argument("--overlap-triage-closeout-root", default=str(DEFAULT_OVERLAP_TRIAGE_CLOSEOUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_operational_closeout(
        company_history_triage_root=args.company_history_triage_root,
        original_notice_backtrace_root=args.original_notice_backtrace_root,
        overlap_triage_closeout_root=args.overlap_triage_closeout_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            "p13b operational closeout built: "
            f"state={summary.get('p13b_operational_closeout_state')} "
            f"projects={summary.get('input_project_count')} "
            f"release_triggers={summary.get('release_evidence_trigger_count')}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
