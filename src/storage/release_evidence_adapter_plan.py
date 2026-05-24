from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from storage.runtime_closeout_precedence import (
    blocker_ledger_record,
    closeout_precedence_decision,
    closeout_precedence_summary,
)
from stage4_verification.regional_hard_defect_sources import resolve_release_evidence_local_housing_adapter
from stage4_verification.verification_scope_policy import (
    CROSS_REGION_INFORMATION_SOURCE_TYPES,
    CURRENT_PROJECT_MAINLINE_PRIORITY_MODE,
    CURRENT_PROJECT_MAINLINE_PRIORITY_REGION_CODE,
    RELEASE_EVIDENCE_QUERY_REGION_RULE,
)


RELEASE_EVIDENCE_ADAPTER_PLAN_KIND = "release_evidence_adapter_plan_v1_manifest"
RELEASE_EVIDENCE_ADAPTER_PLAN_VERSION = 1
RELEASE_EVIDENCE_ADAPTER_PLAN_ADAPTER_ID = "release-evidence-adapter-plan-v1"

DEFAULT_BATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")
DEFAULT_P13B_OPERATIONAL_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/p13b-operational-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/release-evidence-adapter-plan-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
ALLOWED_ADAPTER_RESULT_STATES = ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"]
PROJECT_CODE_FIELD_KEYS = {
    "projectcode",
    "projectcodes",
    "projectno",
    "projectnum",
    "projectid",
    "projectpubliccode",
    "prooforserialcode",
    "proofcode",
    "sourceprojectcode",
    "gdcicprojectcode",
    "gdcicprojectcodes",
    "gdcicprojectcodevariants",
    "projectcodevariants",
    "tradeprojectcode",
    "prjnum",
    "prjcode",
    "tenderprojectcode",
    "sectioncode",
    "bidsectioncode",
}
PROJECT_CODE_URL_QUERY_KEYS = {
    "projectcode",
    "project_code",
    "projectno",
    "projectnum",
    "projectid",
    "project_id",
    "project_public_code",
    "source_project_code",
    "gdcic_project_code",
    "trade_project_code",
    "prjnum",
    "prjcode",
    "tenderprojectcode",
    "sectioncode",
    "bidsectioncode",
}

SOURCE_TARGET_ALIASES = {
    "construction_permit": "construction_permit",
    "construction_permit_change": "project_manager_change_notice",
    "contract_public_info": "contract_performance",
    "contract_public_record": "contract_performance",
    "contract_filing": "contract_performance",
    "contract_filing_or_contract_public_info": "contract_performance",
    "contract_filing_or_contract_credit_info": "contract_performance",
    "contract_credit_info": "contract_performance",
    "completion_filing": "completion_acceptance",
    "completion_or_acceptance_filing": "completion_acceptance",
    "completion_acceptance_or_completion_filing": "completion_acceptance",
    "project_manager_change_notice": "project_manager_change_notice",
    "project_manager_change_notice_or_permit_change": "project_manager_change_notice",
}

TARGET_POLICY = {
    "construction_permit": {
        "evidence_family": "B_ENHANCEMENT_OFFICIAL_READBACK",
        "source_role": "permit_or_license_window_enhancement",
    },
    "contract_performance": {
        "evidence_family": "B_ENHANCEMENT_OFFICIAL_READBACK",
        "source_role": "contract_or_performance_window_enhancement",
    },
    "completion_acceptance": {
        "evidence_family": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
        "source_role": "completion_or_acceptance_release_explanation",
    },
    "project_manager_change_notice": {
        "evidence_family": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
        "source_role": "project_manager_change_or_responsibility_window_split",
    },
}

EXECUTION_PRIORITY_POLICY = {
    "policy_id": "RELEASE-EVIDENCE-QUERY-REGION-PRIORITY-V1",
    "current_project_mainline_priority_mode": CURRENT_PROJECT_MAINLINE_PRIORITY_MODE,
    "current_project_mainline_priority_region_code": CURRENT_PROJECT_MAINLINE_PRIORITY_REGION_CODE,
    "current_project_mainline_priority_note": "Guangdong priority applies to current candidate project live closeout, not to forcing historical release evidence into Guangdong sources.",
    "release_evidence_query_region_rule": RELEASE_EVIDENCE_QUERY_REGION_RULE,
    "release_evidence_follows_historical_overlap_project_jurisdiction": True,
    "do_not_force_release_evidence_to_current_project_region": True,
    "cross_region_information_checks_allowed": True,
    "cross_region_information_source_types": list(CROSS_REGION_INFORMATION_SOURCE_TYPES),
    "query_miss_is_not_clearance": True,
    "customer_visible_allowed": False,
    "no_legal_conclusion": True,
}


def build_release_evidence_adapter_plan(
    *,
    batch_closeout_json: str | Path | None = None,
    batch_closeout_root: str | Path = DEFAULT_BATCH_CLOSEOUT_ROOT,
    p13b_operational_closeout_json: str | Path | None = None,
    p13b_operational_closeout_root: str | Path | None = DEFAULT_P13B_OPERATIONAL_CLOSEOUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    batch_path = Path(batch_closeout_json) if batch_closeout_json else Path(batch_closeout_root) / "evidence-batch-closeout-v1.json"
    batch_payload = _load_json(batch_path, blocking_reasons, "evidence_batch_closeout_missing_or_invalid")
    batch_manifest = _source_manifest(batch_payload)

    operational_path = _resolve_optional_json(
        explicit_json=p13b_operational_closeout_json,
        root=p13b_operational_closeout_root,
        default_file_name="p13b-operational-closeout-v1.json",
    )
    operational_payload = _load_json(operational_path, [], "p13b_operational_closeout_missing_or_invalid") if operational_path else {}
    operational_manifest = _source_manifest(operational_payload)

    closeout_records = [
        dict(record)
        for record in _list(batch_manifest.get("closeout_records"))
        if isinstance(record, Mapping)
    ]
    source_task_records = [
        dict(record)
        for record in _list(operational_manifest.get("release_evidence_probe_task_records"))
        if isinstance(record, Mapping)
    ]
    source_plan_records = [
        dict(record)
        for record in _list(operational_manifest.get("release_evidence_probe_plan_records"))
        if isinstance(record, Mapping)
    ]
    source_tasks_by_project = _tasks_by_project(source_task_records)
    source_plans_by_project = _records_by_project(source_plan_records)
    project_plan_records = [
        _project_plan_record(
            closeout=record,
            source_tasks=source_tasks_by_project.get(str(record.get("project_id") or ""), []),
            source_plan=source_plans_by_project.get(str(record.get("project_id") or ""), {}),
            created_at=created,
        )
        for record in closeout_records
    ]
    project_plan_lookup = _records_by_project(project_plan_records)
    adapter_task_records = [
        task
        for closeout in closeout_records
        for task in _adapter_tasks_for_project(
            closeout=closeout,
            source_tasks=source_tasks_by_project.get(str(closeout.get("project_id") or ""), []),
            source_plan=source_plans_by_project.get(str(closeout.get("project_id") or ""), {}),
            project_plan=project_plan_lookup.get(str(closeout.get("project_id") or ""), {}),
            created_at=created,
        )
    ]
    summary = _summary(
        project_plan_records=project_plan_records,
        adapter_task_records=adapter_task_records,
        blocking_reasons=blocking_reasons,
        operational_supplied=bool(operational_manifest),
    )
    manifest = {
        "manifest_version": RELEASE_EVIDENCE_ADAPTER_PLAN_VERSION,
        "manifest_kind": RELEASE_EVIDENCE_ADAPTER_PLAN_KIND,
        "adapter_id": RELEASE_EVIDENCE_ADAPTER_PLAN_ADAPTER_ID,
        "pipeline_stage": "ReleaseEvidenceAdapterPlanV1",
        "manifest_id": f"RELEASE-EVIDENCE-ADAPTER-PLAN-{_fingerprint({'summary': summary, 'tasks': adapter_task_records})[:16]}",
        "created_at": created,
        "source_batch_closeout_json": str(batch_path),
        "source_batch_closeout_manifest_id": str(batch_manifest.get("manifest_id") or ""),
        "source_p13b_operational_closeout_json": str(operational_path or ""),
        "source_p13b_operational_closeout_manifest_id": str(operational_manifest.get("manifest_id") or ""),
        "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
        "target_policy": TARGET_POLICY,
        "execution_priority_policy": EXECUTION_PRIORITY_POLICY,
        "project_release_evidence_plan_records": project_plan_records,
        "release_evidence_adapter_task_records": adapter_task_records,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    result = {
        "release_evidence_adapter_plan_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, project_plan_records, adapter_task_records)
    return result


def _project_plan_record(
    *,
    closeout: Mapping[str, Any],
    source_tasks: list[Mapping[str, Any]],
    source_plan: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    project_id = str(closeout.get("project_id") or "")
    closeout_state = str(closeout.get("closeout_state") or "")
    closeout_precedence = closeout_precedence_decision(
        closeout,
        task_family="release_evidence_query",
        runtime_layer="controller decision:release_evidence_adapter_plan",
    )
    suppressed = bool(closeout_precedence.get("suppressed_dispatch") or closeout_precedence.get("should_suppress_dispatch"))
    projection_only_terminal = _release_evidence_projection_only_terminal(closeout_precedence)
    blocker_record = (
        blocker_ledger_record(closeout, closeout_precedence, ledger_scope="stage4_release_evidence_query")
        if suppressed and not projection_only_terminal
        else {}
    )
    is_a_signal = closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW" or str(
        closeout.get("evidence_grade") or ""
    ).startswith("A_")
    normalized_targets = _task_target_types(source_tasks)
    if suppressed:
        plan_state = "RELEASE_EVIDENCE_TERMINAL_CLOSEOUT_SUPPRESSED"
        next_action = str(
            closeout_precedence.get("operator_next_action")
            or closeout_precedence.get("next_action")
            or "project_to_review_ready_status_projection_without_duplicate_dispatch"
        )
    elif is_a_signal and source_tasks:
        plan_state = "RELEASE_EVIDENCE_ADAPTER_TASKS_PLANNED"
        next_action = "run_release_evidence_adapters_when_live_approved"
    elif is_a_signal:
        plan_state = "RELEASE_EVIDENCE_SOURCE_PLAN_REQUIRED"
        next_action = "build_p13b_operational_closeout_or_region_release_source_plan"
    else:
        plan_state = "NO_A_SIGNAL_RELEASE_EVIDENCE_NOT_PLANNED"
        next_action = str(closeout.get("next_action_label") or "keep_internal_review_without_release_adapter_plan")
    region_code = str(
        source_plan.get("release_evidence_query_region_code")
        or _first_non_empty(task.get("release_evidence_query_region_code") for task in source_tasks)
    )
    jurisdiction_adapter = resolve_release_evidence_local_housing_adapter(region_code) if region_code else {}
    return {
        "release_evidence_project_plan_id": _stable_id("REL-EVIDENCE-PROJECT-PLAN", project_id, closeout_state),
        "project_id": project_id,
        "project_name": str(closeout.get("project_name") or ""),
        "closeout_state": closeout_state,
        "evidence_state": str(closeout.get("evidence_state") or ""),
        "evidence_grade": str(closeout.get("evidence_grade") or ""),
        "release_evidence_project_plan_state": plan_state,
        "source_release_evidence_probe_task_count": len(source_tasks),
        "normalized_target_types": normalized_targets,
        "release_evidence_query_region_code": region_code,
        "release_evidence_query_region_basis": str(
            source_plan.get("release_evidence_query_region_basis")
            or _first_non_empty(task.get("release_evidence_query_region_basis") for task in source_tasks)
        ),
        "local_housing_authority_adapter_scope": str(
            source_plan.get("local_housing_authority_adapter_scope")
            or _first_non_empty(task.get("local_housing_authority_adapter_scope") for task in source_tasks)
        ),
        "local_housing_authority_adapter_region_code": str(
            source_plan.get("local_housing_authority_adapter_region_code")
            or _first_non_empty(task.get("local_housing_authority_adapter_region_code") for task in source_tasks)
        ),
        "non_guangdong_release_adapter_rule": str(
            source_plan.get("non_guangdong_release_adapter_rule")
            or _first_non_empty(task.get("non_guangdong_release_adapter_rule") for task in source_tasks)
        ),
        "jurisdiction_local_housing_adapter": jurisdiction_adapter,
        "jurisdiction_adapter_resolution_state": str(jurisdiction_adapter.get("adapter_resolution_state") or ""),
        "no_fallback_to_guangdong_or_guangzhou": bool(
            jurisdiction_adapter.get("no_fallback_to_guangdong_or_guangzhou")
        ),
        "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
        "execution_priority_policy": EXECUTION_PRIORITY_POLICY,
        "recommended_next_action": next_action,
        "closeout_precedence": closeout_precedence,
        "closeout_precedence_state": str(closeout_precedence.get("closeout_precedence_state") or ""),
        "closeout_precedence_suppressed": suppressed,
        "runtime_blocker_ledger_record": blocker_record,
        "runtime_blocker_ledger_records": [blocker_record] if blocker_record else [],
        "operator_projection": _project_plan_operator_projection(
            closeout=closeout,
            closeout_precedence=closeout_precedence,
            plan_state=plan_state,
            next_action=next_action,
        ),
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "created_at": created_at,
    }


def _release_evidence_projection_only_terminal(closeout_precedence: Mapping[str, Any]) -> bool:
    task_scope = str(closeout_precedence.get("task_scope") or "")
    terminal_marker = (
        closeout_precedence.get("terminal_marker")
        if isinstance(closeout_precedence.get("terminal_marker"), Mapping)
        else {}
    )
    terminal_state = str(
        terminal_marker.get("terminal_state") or terminal_marker.get("terminal_grade") or ""
    ).strip()
    return bool(
        task_scope == "release_evidence_query"
        and (
            terminal_state in {
                "MATCHED",
                "REVIEW_READY",
                "RELEASE_FIELD_QUERY_REVIEW_READY",
                "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
            }
            or terminal_state.startswith(("B_", "C_"))
        )
    )


def _adapter_tasks_for_project(
    *,
    closeout: Mapping[str, Any],
    source_tasks: list[Mapping[str, Any]],
    source_plan: Mapping[str, Any],
    project_plan: Mapping[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    if bool(project_plan.get("closeout_precedence_suppressed")):
        return []
    if str(closeout.get("closeout_state") or "") != "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW" and not str(
        closeout.get("evidence_grade") or ""
    ).startswith("A_"):
        return []
    rows: list[dict[str, Any]] = []
    for source_task in source_tasks:
        region_code = str(
            source_task.get("local_housing_authority_adapter_region_code")
            or source_task.get("release_evidence_query_region_code")
            or source_plan.get("release_evidence_query_region_code")
            or ""
        )
        jurisdiction_adapter = resolve_release_evidence_local_housing_adapter(region_code) if region_code else {}
        for target_type in _normalized_target_types(source_task):
            policy = TARGET_POLICY.get(target_type)
            if not policy:
                continue
            query_params = _release_adapter_task_query_params(source_task)
            rows.append(
                {
                    "release_evidence_adapter_task_id": _stable_id(
                        "REL-EVIDENCE-ADAPTER-TASK",
                        source_task.get("release_evidence_probe_task_id"),
                        target_type,
                    ),
                    "source_release_evidence_probe_task_id": str(source_task.get("release_evidence_probe_task_id") or ""),
                    "source_release_evidence_probe_plan_id": str(source_task.get("release_evidence_probe_plan_id") or ""),
                    "project_id": str(closeout.get("project_id") or source_task.get("project_id") or ""),
                    "project_name": str(closeout.get("project_name") or source_task.get("project_name") or ""),
                    "candidate_company_name": str(source_task.get("candidate_company_name") or ""),
                    "matched_person_names": _list(source_task.get("matched_person_names")),
                    "release_evidence_target_type": target_type,
                    "release_evidence_grade_on_match": policy["evidence_family"],
                    "release_evidence_source_role": policy["source_role"],
                    "initial_release_evidence_abcd_grade": str(
                        source_task.get("initial_release_evidence_abcd_grade") or "A_STRONG_TIME_OVERLAP_SIGNAL"
                    ),
                    "release_evidence_query_region_code": str(source_task.get("release_evidence_query_region_code") or ""),
                    "release_evidence_query_region_basis": str(source_task.get("release_evidence_query_region_basis") or ""),
                    "release_evidence_query_region_rule": RELEASE_EVIDENCE_QUERY_REGION_RULE,
                    "release_evidence_follows_historical_overlap_project_jurisdiction": True,
                    "do_not_force_release_evidence_to_current_project_region": True,
                    "current_project_mainline_priority_mode": CURRENT_PROJECT_MAINLINE_PRIORITY_MODE,
                    "current_project_mainline_priority_region_code": CURRENT_PROJECT_MAINLINE_PRIORITY_REGION_CODE,
                    "cross_region_information_checks_allowed": True,
                    "cross_region_information_source_types": list(CROSS_REGION_INFORMATION_SOURCE_TYPES),
                    "local_housing_authority_adapter_scope": str(source_task.get("local_housing_authority_adapter_scope") or ""),
                    "local_housing_authority_adapter_region_code": str(
                        source_task.get("local_housing_authority_adapter_region_code") or ""
                    ),
                    "non_guangdong_release_adapter_rule": str(source_task.get("non_guangdong_release_adapter_rule") or ""),
                    "jurisdiction_local_housing_adapter": jurisdiction_adapter,
                    "jurisdiction_adapter_resolution_state": str(
                        jurisdiction_adapter.get("adapter_resolution_state") or ""
                    ),
                    "no_fallback_to_guangdong_or_guangzhou": bool(
                        jurisdiction_adapter.get("no_fallback_to_guangdong_or_guangzhou")
                    ),
                    "source_entry_id": str(
                        source_task.get("source_entry_id")
                        or jurisdiction_adapter.get("entry_id")
                        or ""
                    ),
                    "subsource_id": str(source_task.get("subsource_id") or ""),
                    "source_profile_id": str(
                        source_task.get("source_profile_id")
                        or jurisdiction_adapter.get("source_profile_id")
                        or ""
                    ),
                    "source_name": str(
                        source_task.get("source_name")
                        or jurisdiction_adapter.get("source_name")
                        or ""
                    ),
                    "source_url": str(
                        source_task.get("source_url")
                        or jurisdiction_adapter.get("source_url")
                        or ""
                    ),
                    "api_url": str(source_task.get("api_url") or ""),
                    "official_reference_url": str(
                        source_task.get("official_reference_url")
                        or jurisdiction_adapter.get("official_reference_url")
                        or ""
                    ),
                    "trigger_source_url": str(source_task.get("trigger_source_url") or ""),
                    "query_params": query_params,
                    "next_adapter": str(
                        source_task.get("next_adapter")
                        or jurisdiction_adapter.get("next_adapter")
                        or ""
                    ),
                    "runtime_status": str(source_task.get("runtime_status") or ""),
                    "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
                    "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
                    "matched_means": "public_record_supports_enhancement_or_reverse_explanation_not_legal_conclusion",
                    "not_found_means": "source_query_miss_or_no_public_match_not_clearance",
                    "blocked_means": "source_blocked_or_unavailable_needs_review",
                    "needs_browser_means": "browser_or_authorized_runtime_required_before_field_readback",
                    "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                    "readback_ready": False,
                    "query_miss_is_not_clearance": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "created_at": created_at,
                    "source_plan_region_code": str(source_plan.get("release_evidence_query_region_code") or ""),
                }
            )
    return _dedupe_records(rows, ("source_release_evidence_probe_task_id", "release_evidence_target_type"))


def _task_target_types(source_tasks: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        target_type
        for task in source_tasks
        for target_type in _normalized_target_types(task)
        if target_type in TARGET_POLICY
    )


def _normalized_target_types(task: Mapping[str, Any]) -> list[str]:
    raw_values = [
        *_list(task.get("matched_target_source_types")),
        *_list(task.get("canonical_release_evidence_source_targets")),
        *_list(task.get("requested_release_evidence_source_targets")),
    ]
    return _dedupe(SOURCE_TARGET_ALIASES.get(str(value or ""), str(value or "")) for value in raw_values)


def _release_adapter_task_query_params(source_task: Mapping[str, Any]) -> dict[str, Any]:
    raw_params = dict(source_task.get("query_params") or {})
    project_code_variants = _project_code_variants(
        [
            *_list(raw_params.get("projectCodeVariants")),
            *_list(raw_params.get("gdcicProjectCodeVariants")),
            *_list(raw_params.get("projectCodes")),
            raw_params.get("projectCode"),
            raw_params.get("sourceProjectCode"),
            raw_params.get("tradeProjectCode"),
            source_task.get("project_code_candidates"),
            source_task.get("gdcic_project_code_candidates"),
            source_task.get("project_codes"),
            source_task.get("gdcic_project_codes"),
            source_task.get("project_code"),
            source_task.get("source_project_code"),
            source_task.get("project_public_code"),
            source_task.get("gdcic_project_code"),
            source_task.get("trade_project_code"),
            source_task.get("source_results"),
            source_task.get("bid_show_records"),
            source_task.get("data_ggzy_bid_show_records"),
            source_task.get("ygp_project_records"),
            source_task.get("ygp_flow_matrix_records"),
            source_task.get("ygp_flow_bucket_records"),
            source_task.get("ygp_flow_item_records"),
            source_task.get("ygp_detail_readback_records"),
            source_task.get("guangdong_ygp_flow_matrix"),
            source_task.get("ygp_flow_matrix"),
            source_task.get("source_refs"),
            source_task.get("trigger_source_url"),
        ]
    )
    gdcic_project_code_variants = _gdcic_project_code_variants(project_code_variants)
    merged = dict(raw_params)
    if project_code_variants:
        merged["projectCodeVariants"] = project_code_variants
    if gdcic_project_code_variants:
        merged["gdcicProjectCodeVariants"] = gdcic_project_code_variants
        merged["projectCode"] = _first_non_empty(gdcic_project_code_variants)
    trade_project_code = _first_non_empty(code for code in project_code_variants if code.upper().startswith("JG"))
    if trade_project_code:
        merged["tradeProjectCode"] = trade_project_code
    return merged


def _summary(
    *,
    project_plan_records: list[Mapping[str, Any]],
    adapter_task_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    operational_supplied: bool,
) -> dict[str, Any]:
    precedence = closeout_precedence_summary(
        record.get("closeout_precedence")
        for record in project_plan_records
        if isinstance(record.get("closeout_precedence"), Mapping)
    )
    blocker_records = [
        record.get("runtime_blocker_ledger_record")
        for record in project_plan_records
        if isinstance(record.get("runtime_blocker_ledger_record"), Mapping)
        and record.get("runtime_blocker_ledger_record")
    ]
    project_code_recall = _project_code_recall_summary(adapter_task_records)
    return {
        "release_evidence_adapter_plan_state": "RELEASE_EVIDENCE_ADAPTER_PLAN_READY"
        if not blocking_reasons
        else "RELEASE_EVIDENCE_ADAPTER_PLAN_INPUT_BLOCKED",
        "project_plan_count": len(project_plan_records),
        "project_plan_state_counts": _counts(record.get("release_evidence_project_plan_state") for record in project_plan_records),
        "adapter_task_count": len(adapter_task_records),
        "adapter_task_target_type_counts": _counts(record.get("release_evidence_target_type") for record in adapter_task_records),
        "adapter_task_grade_on_match_counts": _counts(record.get("release_evidence_grade_on_match") for record in adapter_task_records),
        "stage4_release_adapter_plan_project_code_recall_summary": project_code_recall,
        "local_housing_region_counts": _counts(record.get("local_housing_authority_adapter_region_code") for record in adapter_task_records),
        "jurisdiction_adapter_resolution_state_counts": _counts(
            record.get("jurisdiction_adapter_resolution_state") for record in adapter_task_records
        ),
        "runtime_blocker_ledger_count": len(blocker_records),
        "runtime_blocker_ledger_state_counts": _counts(
            record.get("blocker_state") for record in blocker_records if isinstance(record, Mapping)
        ),
        "runtime_blocker_ledger_layer_counts": _counts(
            record.get("runtime_layer") for record in blocker_records if isinstance(record, Mapping)
        ),
        "runtime_blocker_ledger_scope_counts": _counts(
            record.get("ledger_scope") for record in blocker_records if isinstance(record, Mapping)
        ),
        "runtime_blocker_ledger_operator_next_action_counts": _counts(
            record.get("operator_next_action") or record.get("next_action")
            for record in blocker_records
            if isinstance(record, Mapping)
        ),
        "operational_closeout_supplied": operational_supplied,
        "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
        "execution_priority_policy": EXECUTION_PRIORITY_POLICY,
        **precedence,
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _project_code_recall_summary(adapter_task_records: list[Mapping[str, Any]]) -> dict[str, Any]:
    with_gdcic = 0
    missing_gdcic = 0
    with_trade = 0
    code_only = 0
    gdcic_variants: list[str] = []
    trade_codes: list[str] = []
    for record in adapter_task_records:
        query_params = dict(record.get("query_params") or {})
        gdcic_codes = _gdcic_project_code_variants(
            [
                query_params.get("gdcicProjectCodeVariants"),
                query_params.get("projectCode"),
            ]
        )
        trade_code = str(query_params.get("tradeProjectCode") or "").strip()
        if gdcic_codes:
            with_gdcic += 1
            gdcic_variants.extend(gdcic_codes)
        else:
            missing_gdcic += 1
        if trade_code:
            with_trade += 1
            trade_codes.append(trade_code)
        if gdcic_codes and not str(record.get("project_name") or "").strip():
            code_only += 1
    return {
        "project_code_recall_state": (
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT"
            if with_gdcic
            else "NO_GDCIC_PROJECT_CODE_VARIANTS"
        ),
        "adapter_task_count": len(adapter_task_records),
        "with_gdcic_project_code_variant_task_count": with_gdcic,
        "missing_gdcic_project_code_variant_task_count": missing_gdcic,
        "trade_project_code_only_task_count": max(with_trade - with_gdcic, 0),
        "with_trade_project_code_task_count": with_trade,
        "code_only_project_code_task_count": code_only,
        "sample_gdcic_project_code_variants": _dedupe(gdcic_variants)[:10],
        "sample_trade_project_codes": _dedupe(trade_codes)[:10],
        "gdcic_project_code_route_ready": bool(with_gdcic),
        "jg_trade_code_not_sent_to_gdcic_project_code": True,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    project_plan_records: list[Mapping[str, Any]],
    adapter_task_records: list[Mapping[str, Any]],
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
    result["manifest"]["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result["manifest"].items() if key != "manifest_sha256"}
    )
    _write_json(out_dir / "release-evidence-project-plan-table.json", {"summary": result["summary"], "records": project_plan_records})
    _write_json(out_dir / "release-evidence-adapter-task-table.json", {"summary": result["summary"], "records": adapter_task_records})
    _write_json(out_dir / "release-evidence-adapter-plan-v1.json", result)


def _project_plan_operator_projection(
    *,
    closeout: Mapping[str, Any],
    closeout_precedence: Mapping[str, Any],
    plan_state: str,
    next_action: str,
) -> dict[str, Any]:
    suppressed = bool(closeout_precedence.get("suppressed_dispatch") or closeout_precedence.get("should_suppress_dispatch"))
    return {
        "projection_state": (
            "RELEASE_EVIDENCE_TERMINAL_STATUS_PROJECTION"
            if suppressed
            else "RELEASE_EVIDENCE_QUEUE_READY"
        ),
        "current_state": plan_state,
        "owner_status": plan_state,
        "evidence_level": str(closeout.get("evidence_grade") or ""),
        "blocker_reason": str(
            closeout_precedence.get("suppression_reason")
            or closeout.get("next_action_label")
            or ""
        ),
        "next_action": next_action,
        "input_refs": dict(closeout.get("source_refs") or {}),
        "output_artifact": "release-evidence-adapter-plan-v1.json",
        "raw_json_required_for_next_step": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _resolve_optional_json(*, explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> Path | None:
    if explicit_json:
        return Path(explicit_json)
    if root:
        return Path(root) / default_file_name
    return None


def _load_json(path: Path | None, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if path is None or not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blocking_reasons.append(missing_reason)
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload) if isinstance(payload, Mapping) else {}


def _tasks_by_project(records: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out.setdefault(project_id, []).append(record)
    return out


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out[project_id] = record
    return out


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
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _dedupe_records(rows: Iterable[Mapping[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _first_non_empty(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _project_code_variants(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        for raw in _collect_project_code_values(value):
            text = str(raw or "").strip()
            if not text:
                continue
            if _looks_like_explicit_project_code(text):
                out.append(text.upper() if re.search(r"[A-Za-z]", text) else text)
                continue
            for match in re.findall(r"\b[A-Z]{1,8}\d{4}-\d{3,8}(?:-\d{3})?\b", text, flags=re.IGNORECASE):
                out.append(match.upper())
            for match in re.findall(r"\bE\d{12,22}\b", text, flags=re.IGNORECASE):
                out.append(match.upper())
            for match in re.findall(r"\b\d{6,12}-\d{4}-\d{3,8}(?:-\d{1,8})?\b", text):
                out.append(match)
            for match in re.findall(r"\b\d{4}-\d{6}-\d{2}-\d{2}-\d{6}\b", text):
                out.append(match)
            for match in re.findall(r"\b\d{12,22}\b", text):
                out.append(match)
    return _dedupe(out)


def _gdcic_project_code_variants(values: Iterable[Any]) -> list[str]:
    return _dedupe(
        code for code in _project_code_variants(values) if _looks_like_gdcic_project_code_variant(code)
    )


def _collect_project_code_values(value: Any) -> list[str]:
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, Mapping):
        field_name = _first_non_empty(
            [
                value.get("field_name"),
                value.get("fieldName"),
                value.get("field_key"),
                value.get("fieldKey"),
                value.get("label"),
                value.get("name"),
            ]
        )
        if _looks_like_project_code_field(field_name):
            for key in ("field_value", "fieldValue", "field_value_optional", "value", "raw_value", "text"):
                out.extend(_collect_project_code_values(value.get(key)))
        for raw_key, nested_value in value.items():
            key = _normalize_key(raw_key)
            if key in PROJECT_CODE_FIELD_KEYS:
                out.extend(_flatten_project_code_values(nested_value))
                continue
            if key in {"sourceurl", "triggerurl", "url", "apiurl", "officialreferenceurl"}:
                out.extend(_project_code_values_from_url(nested_value))
                continue
            if key in {
                "querycontext",
                "queryinput",
                "source_results",
                "sourceresults",
                "samplerecords",
                "limitedreadback",
                "bidshowrecords",
                "dataggzybidshowrecords",
                "ygpprojectrecords",
                "ygpflowmatrixrecords",
                "ygpflowbucketrecords",
                "ygpflowitemrecords",
                "ygpdetailreadbackrecords",
                "guangdongygpflowmatrix",
                "ygpflowmatrix",
                "nodelist",
                "dslist",
                "detail",
                "manifest",
                "sourcerefs",
            }:
                out.extend(_collect_project_code_values(nested_value))
                continue
            if isinstance(nested_value, Mapping) or (
                isinstance(nested_value, (list, tuple))
                and any(isinstance(item, Mapping) for item in nested_value)
            ):
                out.extend(_collect_project_code_values(nested_value))
        return _dedupe(out)
    if isinstance(value, (list, tuple, set)):
        for item in value:
            out.extend(_collect_project_code_values(item))
        return _dedupe(out)
    text = str(value or "").strip()
    return [text] if text else []


def _flatten_project_code_values(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        out: list[str] = []
        for nested_value in value.values():
            out.extend(_flatten_project_code_values(nested_value))
        return _dedupe(out)
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_project_code_values(item))
        return _dedupe(out)
    text = str(value or "").strip()
    return [text] if text else []


def _project_code_values_from_url(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parsed = urllib.parse.urlparse(text)
    query_texts = [parsed.query]
    if "?" in parsed.fragment:
        query_texts.append(parsed.fragment.split("?", 1)[1])
    out: list[str] = []
    for query_text in query_texts:
        for key, items in urllib.parse.parse_qs(query_text).items():
            if key in PROJECT_CODE_URL_QUERY_KEYS or _normalize_key(key) in PROJECT_CODE_FIELD_KEYS:
                out.extend(items)
    return _dedupe(out)


def _looks_like_project_code_field(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = _normalize_key(text)
    if normalized in PROJECT_CODE_FIELD_KEYS:
        return True
    return any(
        marker in text
        for marker in ("项目代码", "项目编号", "项目编码", "工程代码", "工程编号", "工程编码", "招标项目编号", "招标编号", "标段编号")
    )


def _looks_like_explicit_project_code(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 48:
        return False
    if re.fullmatch(r"JG\d{4}-\d{3,8}(?:-\d{3})?", text, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"\d{12,22}", text):
        return True
    if re.fullmatch(r"E\d{12,22}", text, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"\d{6,12}-\d{4}-\d{3,8}(?:-\d{1,8})?", text):
        return True
    if re.fullmatch(r"\d{4}-\d{6}-\d{2}-\d{2}-\d{6}", text):
        return True
    return False


def _looks_like_gdcic_project_code_variant(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(
        re.fullmatch(r"\d{12,22}", text)
        or re.fullmatch(r"E\d{12,22}", text, flags=re.IGNORECASE)
        or re.fullmatch(r"\d{6,12}-\d{4}-\d{3,8}(?:-\d{1,8})?", text)
    )


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Release Evidence Adapter Plan v1.")
    parser.add_argument("--batch-closeout-json", default="")
    parser.add_argument("--batch-closeout-root", default=str(DEFAULT_BATCH_CLOSEOUT_ROOT))
    parser.add_argument("--p13b-operational-closeout-json", default="")
    parser.add_argument("--p13b-operational-closeout-root", default=str(DEFAULT_P13B_OPERATIONAL_CLOSEOUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_release_evidence_adapter_plan(
        batch_closeout_json=args.batch_closeout_json or None,
        batch_closeout_root=args.batch_closeout_root,
        p13b_operational_closeout_json=args.p13b_operational_closeout_json or None,
        p13b_operational_closeout_root=args.p13b_operational_closeout_root or None,
        output_root=args.output_root,
        created_at=args.created_at or None,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXECUTION_PRIORITY_POLICY",
    "RELEASE_EVIDENCE_ADAPTER_PLAN_KIND",
    "build_release_evidence_adapter_plan",
]
