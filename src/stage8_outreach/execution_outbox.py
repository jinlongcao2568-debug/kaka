from __future__ import annotations

from typing import Any, Mapping

from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_readiness_for_family,
)
from shared.utils import build_id, ensure_list
from stage8_outreach.candidate_compliance import execution_action_intent


OUTBOX_OBJECT_TYPE = "outreach_execution_outbox"
OUTBOX_SNAPSHOT_INPUT_KEY = "outreach_execution_outbox_snapshot"
OUTBOX_ID_INPUT_KEY = "outbox_id_optional"
OUTBOX_READINESS_INPUT_KEY = "outbox_readiness_summary"

_EMPTY_VALUES = {None, "", "UNKNOWN", "None"}


def _clean_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        if value in _EMPTY_VALUES:
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "live"}
    return bool(value)


def _state_from_decision(decision_state: str) -> str:
    if decision_state == "BLOCK":
        return "BLOCKED"
    if decision_state == "REVIEW":
        return "REVIEW_REQUIRED"
    return "READY"


def _has_value(value: Any) -> bool:
    return value not in _EMPTY_VALUES


def _retry_schedule_reasons(
    *,
    outreach_plan: Mapping[str, Any],
    touch_record: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if _truthy(touch_record.get("retry_scheduled_optional")):
        reasons.append("touch_retry_scheduled")
    if _has_value(outreach_plan.get("next_touch_due_at_optional")):
        reasons.append("retry_policy_next_touch_due")
    if _has_value(touch_record.get("next_step_optional")):
        reasons.append(f"next_step:{touch_record.get('next_step_optional')}")
    return _clean_list(reasons)


def build_outbox_readiness_summary(outbox: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(outbox.get("blocked_reasons")))
    vendor_state = dict(outbox.get("vendor_adapter_state", {}))
    provider_readiness = dict(outbox.get("provider_adapter_readiness", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    retry_state = dict(outbox.get("retry_state", {}))
    stop_state = dict(outbox.get("stop_state", {}))
    return {
        "outbox_id": outbox.get("outbox_id"),
        "outreach_plan_id": outbox.get("outreach_plan_id"),
        "touch_record_id": outbox.get("touch_record_id"),
        "governed_execution_mode": outbox.get("governed_execution_mode", "INTERNAL_GOVERNED"),
        "readback_ready": bool(outbox.get("outbox_id")),
        "ready_for_real_send": False,
        "dry_run_ready": True,
        "live_execution_enabled": False,
        "real_send_attempted": False,
        "approval_state": outbox.get("approval_state"),
        "audit_state": outbox.get("audit_state"),
        "quiet_hours_state": outbox.get("quiet_hours_state"),
        "retry_state": retry_state.get("state"),
        "stop_state": stop_state.get("state"),
        "vendor_adapter_state": vendor_state.get("state"),
        "blocked_reason_count": len(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "provider_adapter_config_source": outbox.get("provider_adapter_config_source"),
        "provider_adapter_mode": outbox.get("provider_adapter_mode"),
        "provider_adapter_readback_only": bool(provider_readiness.get("readback_only", True)),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": bool(provider_readiness.get("provider_adapter_suspended", False)),
        "provider_circuit_breaker_state": provider_circuit_breaker.get("state"),
        "provider_failure_class": provider_failure_taxonomy.get("failure_class"),
        "provider_status_replayable": bool(provider_status_readback.get("replayable", True)),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
    }


def build_outreach_execution_outbox_payload(
    *,
    runtime_state: Any,
    contact_target: Mapping[str, Any],
    outreach_plan: Mapping[str, Any],
    touch_record: Mapping[str, Any],
    authoritative_inputs: Mapping[str, Any],
    execution_vendor_payload: Mapping[str, Any],
    execution_vendor_trace: Mapping[str, Any],
    now: str,
    run_mode: str,
    approval_state: str,
    provider_adapter_readiness_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider_readiness = provider_readiness_for_family(
        provider_adapter_readiness_summary,
        "sales_outreach",
    )
    project_id = str(touch_record.get("project_id") or contact_target.get("project_id") or "")
    touch_record_id = str(touch_record.get("touch_record_id") or "")
    outbox_id = build_id("OUTBOX", project_id, touch_record_id)
    channel = str(
        touch_record.get("touch_channel")
        or contact_target.get("channel_family")
        or contact_target.get("contact_channel")
        or "UNKNOWN"
    )
    action_intent = execution_action_intent(run_mode)
    requested_live = (
        action_intent == "LIVE_EXECUTION"
        or _truthy(authoritative_inputs.get("live_execution_enabled"))
        or _truthy(authoritative_inputs.get("external_live_execution_requested"))
    )
    vendor_connection_requested = any(
        _truthy(authoritative_inputs.get(field_name))
        for field_name in (
            "vendor_connection_enabled",
            "direct_vendor_call_enabled",
            "external_vendor_connection_enabled",
            "vendor_direct_connection_requested",
            "crm_runtime_enabled",
        )
    )
    execution_decision = str(execution_vendor_trace.get("decision_state", "ALLOW"))
    vendor_state = _state_from_decision(execution_decision)
    if vendor_connection_requested:
        vendor_state = "BLOCKED"
    provider_suspended = bool(provider_readiness.get("provider_adapter_suspended", False))
    if provider_suspended:
        vendor_state = "BLOCKED"

    approval_missing = action_intent in {"APPROVAL_EXECUTION", "LIVE_EXECUTION"} and approval_state != "APPROVED"
    audit_ref_values = [
        contact_target.get("source_audit_ref"),
        contact_target.get("query_trace_id"),
        execution_vendor_payload.get("execution_trace_id_optional"),
    ]
    explicit_audit_absent = authoritative_inputs.get("audit_trail_present") is False
    missing_audit_refs = [
        name
        for name, value in zip(
            ("source_audit_ref", "query_trace_id", "execution_trace_id_optional"),
            audit_ref_values,
        )
        if value in _EMPTY_VALUES
    ]
    if explicit_audit_absent and "audit_trail_present" not in missing_audit_refs:
        missing_audit_refs.append("audit_trail_present")
    audit_state = "MISSING" if missing_audit_refs else "PRESENT"

    quiet_hours_policy_state = str(contact_target.get("quiet_hours_policy_state") or "")
    quiet_hours_state = (
        "SCHEDULED"
        if quiet_hours_policy_state == "BLOCK" or outreach_plan.get("plan_status") == "SCHEDULED"
        else quiet_hours_policy_state or "ALLOW"
    )
    retry_schedule_reasons = _retry_schedule_reasons(
        outreach_plan=outreach_plan,
        touch_record=touch_record,
    )
    retry_scheduled = bool(retry_schedule_reasons)
    retry_state = "SCHEDULED" if retry_scheduled else "NOT_SCHEDULED"
    stop_reason = touch_record.get("stop_reason_optional")
    stop_semantics = dict(outreach_plan.get("governed_metadata", {})).get("stop_semantics")
    stop_state = "STOPPED" if stop_reason not in _EMPTY_VALUES else str(stop_semantics or "ACTIVE")
    dry_run_state = "DRY_RUN_RECEIPT_ONLY" if run_mode == "DRY_RUN" else "INTERNAL_DRY_RUN_CARRIER_ONLY"

    blocked_reasons = []
    blocked_reasons.extend(ensure_list(contact_target.get("blocking_reasons")))
    blocked_reasons.extend(ensure_list(runtime_state.blocked_reasons))
    blocked_reasons.extend(ensure_list(runtime_state.permission_blocked_reasons))
    if requested_live:
        blocked_reasons.append("live_execution_requested_but_blocked")
    if vendor_connection_requested:
        blocked_reasons.append("vendor_connection_enabled=false")
    if execution_decision == "BLOCK":
        blocked_reasons.append(
            execution_vendor_trace.get("unresolved_reason_optional")
            or "execution_vendor_resolution_blocked"
        )
    if approval_missing:
        blocked_reasons.append(f"approval_state={approval_state}")
    if audit_state == "MISSING":
        blocked_reasons.append("audit_ref_missing")
    if quiet_hours_state == "SCHEDULED":
        blocked_reasons.append("quiet_hours_schedule")
    if stop_reason not in _EMPTY_VALUES:
        blocked_reasons.append(f"stop_condition:{stop_reason}")
    blocked_reasons.extend(
        [
            "internal_governed_outbox_only",
            "live_execution_enabled=false",
            "real_send_attempted=false",
            "external_vendor_connection_disabled",
        ]
    )
    blocked_reasons.extend(provider_readiness.get("blocked_reasons", []))

    outbox = {
        "outbox_id": outbox_id,
        "outreach_plan_id": outreach_plan.get("outreach_plan_id"),
        "touch_record_id": touch_record_id,
        "contact_target_id": contact_target.get("contact_target_id"),
        "opportunity_id": touch_record.get("opportunity_id") or contact_target.get("opportunity_id"),
        "project_id": project_id,
        "channel": channel,
        "vendor_adapter_state": {
            "state": vendor_state,
            "execution_vendor_id_optional": execution_vendor_payload.get("execution_vendor_id_optional"),
            "execution_vendor_type_optional": execution_vendor_payload.get("execution_vendor_type_optional"),
            "execution_vendor_role_optional": execution_vendor_payload.get("execution_vendor_role_optional"),
            "execution_trace_id_optional": execution_vendor_payload.get("execution_trace_id_optional"),
            "vendor_response_ref_optional": execution_vendor_payload.get("vendor_response_ref_optional"),
            "resolution_decision_state": execution_decision,
            "resolution_policy_state": execution_vendor_trace.get("policy_state"),
            "resolved_from": execution_vendor_trace.get("resolved_from"),
            "adapter_boundary": "INTERNAL_OUTBOX_CARRIER_ONLY",
            "vendor_connection_enabled": False,
            "direct_vendor_call_enabled": False,
            "external_vendor_connection_enabled": False,
            "provider_adapter_family": "sales_outreach",
            "provider_id": provider_readiness.get("provider_id"),
            "provider_mode": provider_readiness.get("mode"),
            "provider_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
            "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
            "provider_adapter_suspended": provider_suspended,
            "provider_circuit_breaker_state": dict(
                provider_readiness.get("provider_circuit_breaker", {})
            ).get("state"),
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
        },
        "approval_state": approval_state,
        "approval_readiness_summary": {
            "state": "MISSING_OR_PENDING" if approval_missing else "SATISFIED_FOR_INTERNAL_OUTBOX",
            "approval_state": approval_state,
            "approval_required_before_live": True,
            "ready_for_live_execution": False,
        },
        "audit_state": audit_state,
        "audit_readiness_summary": {
            "state": audit_state,
            "required_audit_refs": [
                "source_audit_ref",
                "query_trace_id",
                "execution_trace_id_optional",
            ],
            "missing_audit_refs": missing_audit_refs,
            "ready_for_live_execution": False,
        },
        "quiet_hours_state": quiet_hours_state,
        "retry_policy": {
            "retry_policy_id": outreach_plan.get("retry_policy_id"),
            "cadence_profile_id": outreach_plan.get("cadence_profile_id"),
            "max_retry_count": outreach_plan.get("max_retry_count"),
            "next_touch_due_at_optional": outreach_plan.get("next_touch_due_at_optional"),
        },
        "retry_state": {
            "state": retry_state,
            "retry_scheduled_optional": retry_scheduled,
            "scheduled_from": retry_schedule_reasons,
            "next_touch_due_at_optional": outreach_plan.get("next_touch_due_at_optional"),
            "next_step_optional": touch_record.get("next_step_optional"),
            "feedback_reason": touch_record.get("feedback_reason"),
            "retry_count": outreach_plan.get("retry_count"),
            "attempt_index": touch_record.get("attempt_index"),
        },
        "stop_policy": {
            "stop_policy_id": outreach_plan.get("stop_policy_id"),
        },
        "stop_state": {
            "state": stop_state,
            "stop_reason_optional": stop_reason,
            "stop_semantics": stop_semantics,
        },
        "dry_run_execution_state": {
            "state": dry_run_state,
            "dry_run_receipt_id": build_id("DRYRUN", project_id, touch_record_id),
            "receipt_scope": "INTERNAL_SIMULATION_ONLY",
            "real_send_attempted": False,
        },
        "live_execution_enabled": False,
        "real_send_attempted": False,
        "blocked_reasons": _clean_list(blocked_reasons),
        "governed_execution_mode": "INTERNAL_GOVERNED",
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: dict(provider_adapter_readiness_summary or {}),
        "provider_adapter_readiness": provider_readiness,
        "provider_adapter_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
        "provider_adapter_mode": provider_readiness.get("mode"),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": provider_suspended,
        "provider_circuit_breaker_state": dict(provider_readiness.get("provider_circuit_breaker", {})).get("state"),
        "provider_failure_taxonomy": dict(provider_readiness.get("provider_failure_taxonomy", {})),
        "provider_status_readback": dict(provider_readiness.get("provider_status_readback", {})),
        "requested_action_intent": action_intent,
        "requested_live_execution": requested_live,
        "channel_vendor_boundary": {
            "channel": channel,
            "vendor_connection_enabled": False,
            "direct_vendor_call_enabled": False,
            "external_vendor_connection_enabled": False,
            "real_provider_receipt_allowed": False,
            "provider_adapter_family": "sales_outreach",
            "provider_id": provider_readiness.get("provider_id"),
            "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
            "provider_adapter_suspended": provider_suspended,
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
            "allowed_adapter_scope": "INTERNAL_OUTBOX_CARRIER_ONLY",
        },
        "created_at": now,
    }
    outbox["outbox_readiness_summary"] = build_outbox_readiness_summary(outbox)
    return outbox


__all__ = [
    "OUTBOX_ID_INPUT_KEY",
    "OUTBOX_OBJECT_TYPE",
    "OUTBOX_READINESS_INPUT_KEY",
    "OUTBOX_SNAPSHOT_INPUT_KEY",
    "build_outbox_readiness_summary",
    "build_outreach_execution_outbox_payload",
]
