from __future__ import annotations

from typing import Any, Mapping


ALLOWED_ADAPTER_RESULT_STATES = ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"]
DOWNSTREAM_PENDING_RELEASE_EVIDENCE_ABCD_GRADE = "PENDING_NOT_EXECUTED"

ENHANCEMENT_RELEASE_EVIDENCE_SOURCE_TYPES = {
    "construction_permit",
    "contract_public_info",
    "performance_public_record",
    "personnel_public_record",
    "administrative_license_public_record",
}
REVERSE_RELEASE_EVIDENCE_SOURCE_TYPES = {
    "completion_filing",
    "project_manager_change_notice",
    "completion_acceptance_or_completion_filing",
    "owner_approved_non_contractor_shutdown_over_120_days",
    "same_project_adjacent_section_or_phase_exception",
}


def adapter_result_state(readback: Mapping[str, Any]) -> str:
    state = str(readback.get("field_query_probe_state") or "")
    if state in {"FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE", "FIELD_READBACK_READY_PUBLIC_SOURCE"}:
        return "MATCHED"
    if state == "NO_FIELD_MATCH_REVIEW_REQUIRED":
        return "NOT_FOUND"
    if state.startswith("FAIL_CLOSED"):
        return "BLOCKED"
    return "NEEDS_BROWSER"


def adapter_result_state_basis(adapter_result_state: str, readback: Mapping[str, Any]) -> list[str]:
    state = str(readback.get("field_query_probe_state") or "")
    if adapter_result_state == "MATCHED":
        return ["public_source_readback_has_keyword_or_structured_record", f"field_query_probe_state:{state}"]
    if adapter_result_state == "NOT_FOUND":
        return ["public_source_queried_no_field_match_not_clearance", f"field_query_probe_state:{state}"]
    if adapter_result_state == "BLOCKED":
        blockers = _list(readback.get("blocker_taxonomy"))
        return ["public_source_blocked_or_transport_failed", f"field_query_probe_state:{state}", *blockers]
    return ["browser_authorized_runtime_or_followup_adapter_required", f"field_query_probe_state:{state}"]


def downstream_release_evidence_abcd_grade(
    target_source_types: list[Any],
    *,
    field_query_probe_state: str,
    readback_ready: bool,
) -> str:
    state = str(field_query_probe_state or "")
    if state in {"PLAN_ONLY_NOT_EXECUTED", "DELEGATED_TO_SEPARATE_FIELD_ADAPTER"}:
        return DOWNSTREAM_PENDING_RELEASE_EVIDENCE_ABCD_GRADE
    if state in {
        "LIVE_FIELD_QUERY_DEFERRED_BY_LIMIT",
        "LIVE_FIELD_QUERY_NEEDS_BROWSER",
        "LIVE_FIELD_QUERY_NEEDS_REGION_ADAPTER",
    } or state.startswith("FAIL_CLOSED"):
        return "D_INSUFFICIENT_OR_BLOCKED_READBACK"
    if state == "NO_FIELD_MATCH_REVIEW_REQUIRED":
        return "D_INSUFFICIENT_OR_BLOCKED_READBACK"
    if readback_ready or state in {"FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE", "FIELD_READBACK_READY_PUBLIC_SOURCE"}:
        normalized = {str(item) for item in target_source_types if str(item).strip()}
        if normalized & REVERSE_RELEASE_EVIDENCE_SOURCE_TYPES:
            return "C_REVERSE_EXPLANATION_OFFICIAL_READBACK"
        if normalized & ENHANCEMENT_RELEASE_EVIDENCE_SOURCE_TYPES:
            return "B_ENHANCEMENT_OFFICIAL_READBACK"
        return "B_ENHANCEMENT_OFFICIAL_READBACK"
    return DOWNSTREAM_PENDING_RELEASE_EVIDENCE_ABCD_GRADE


def downstream_release_evidence_abcd_basis(
    grade: str,
    target_source_types: list[Any],
    *,
    field_query_probe_state: str,
) -> list[str]:
    normalized = sorted({str(item) for item in target_source_types if str(item).strip()})
    if grade == DOWNSTREAM_PENDING_RELEASE_EVIDENCE_ABCD_GRADE:
        return ["downstream_probe_not_executed_in_this_run", f"field_query_probe_state:{field_query_probe_state}"]
    if grade == "D_INSUFFICIENT_OR_BLOCKED_READBACK":
        return ["targeted_source_no_hit_blocked_or_deferred_review", f"field_query_probe_state:{field_query_probe_state}"]
    if grade == "C_REVERSE_EXPLANATION_OFFICIAL_READBACK":
        return ["reverse_explanation_source_type_hit", *[f"target_source_type:{item}" for item in normalized]]
    return ["enhancement_source_type_hit", *[f"target_source_type:{item}" for item in normalized]]


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]
