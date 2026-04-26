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
_ADAPTER_FAMILIES = ("email", "sms", "phone_call", "wecom_im")
_TEMPLATE_BLOCKING_STATES = {
    "MISSING",
    "MISSING_APPROVAL",
    "PENDING",
    "PENDING_APPROVAL",
    "REVIEW",
    "REVIEW_REQUIRED",
    "NOT_APPROVED",
    "REJECTED",
    "BLOCKED",
}
_OPT_OUT_BLOCKING_STATES = {"OPTED_OUT", "BLOCKED"}
_UNSUBSCRIBE_BLOCKING_STATES = {"UNSUBSCRIBED", "OPTED_OUT", "BLOCKED"}
_BOUNCE_BLOCKING_STATES = {"BOUNCE", "HARD_BOUNCE", "INVALID_CONTACT_BOUNCE"}
_NO_STOP_VALUES = _EMPTY_VALUES | {"NONE", "NOT_STOPPED", "NO_STOP", "ACTIVE"}


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


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _state_token(value: Any, *, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    return text or default


def _adapter_family_for_channel(
    *,
    channel: str,
    contact_target: Mapping[str, Any],
    touch_record: Mapping[str, Any],
    authoritative_inputs: Mapping[str, Any],
    execution_vendor_payload: Mapping[str, Any],
) -> str:
    explicit_family = _normalize_token(
        authoritative_inputs.get("adapter_family")
        or authoritative_inputs.get("channel_adapter_family")
        or authoritative_inputs.get("sandbox_adapter_family")
    )
    if explicit_family in _ADAPTER_FAMILIES:
        return explicit_family

    tokens = [
        execution_vendor_payload.get("execution_vendor_id_optional"),
        execution_vendor_payload.get("execution_vendor_type_optional"),
        execution_vendor_payload.get("execution_vendor_role_optional"),
        authoritative_inputs.get("execution_vendor_id_optional"),
        authoritative_inputs.get("contact_channel"),
        authoritative_inputs.get("channel_family"),
        contact_target.get("contact_channel"),
        contact_target.get("channel_family"),
        touch_record.get("touch_channel"),
        channel,
    ]
    joined = " ".join(_normalize_token(value) for value in tokens if _has_value(value))
    if "wecom" in joined or "wechat" in joined or "im_direct" in joined or "social_dm" in joined:
        return "wecom_im"
    if "sms" in joined:
        return "sms"
    if "phone" in joined or "call" in joined or "voice" in joined:
        return "phone_call"
    return "email"


def _template_approval_state(authoritative_inputs: Mapping[str, Any], approval_state: str) -> str:
    for key in (
        "template_approval_state",
        "message_template_approval_state",
        "outreach_template_approval_state",
    ):
        if _has_value(authoritative_inputs.get(key)):
            return _state_token(authoritative_inputs.get(key))
    if any(
        _has_value(authoritative_inputs.get(key))
        for key in ("template_id_optional", "message_template_id_optional", "outreach_template_id_optional")
    ):
        return "APPROVED" if approval_state == "APPROVED" else "MISSING_APPROVAL"
    return "APPROVED_FOR_SANDBOX_RECORD"


def _contact_source_audit_state(
    *,
    contact_target: Mapping[str, Any],
    audit_state: str,
    authoritative_inputs: Mapping[str, Any],
) -> str:
    if authoritative_inputs.get("audit_trail_present") is False or audit_state == "MISSING":
        return "MISSING"
    source_auditability = _state_token(contact_target.get("source_auditability_state"))
    if source_auditability not in {"AUDITABLE", "AUDITED"}:
        return "MISSING"
    return "AUDITED"


def _frequency_control_state(contact_target: Mapping[str, Any]) -> str:
    state = _state_token(contact_target.get("frequency_policy_state"), default="REVIEW")
    if state == "BLOCK":
        return "HELD"
    if state == "ALLOW":
        return "ALLOW"
    return "REVIEW_REQUIRED"


def _unsubscribe_state(authoritative_inputs: Mapping[str, Any], opt_out_state: str) -> str:
    for key in ("unsubscribe_state", "unsubscribe_policy_state"):
        if _has_value(authoritative_inputs.get(key)):
            return _state_token(authoritative_inputs.get(key))
    if opt_out_state == "OPTED_OUT":
        return "UNSUBSCRIBED"
    if opt_out_state == "BLOCKED":
        return "BLOCKED"
    return "ACTIVE"


def _bounce_state(authoritative_inputs: Mapping[str, Any], touch_record: Mapping[str, Any]) -> str:
    for key in ("bounce_state", "delivery_bounce_state", "provider_bounce_state"):
        if _has_value(authoritative_inputs.get(key)):
            return _state_token(authoritative_inputs.get(key))
    failure_reason = _state_token(touch_record.get("failure_reason_tag_optional"), default="")
    if "BOUNCE" in failure_reason:
        return "HARD_BOUNCE" if "HARD" in failure_reason else "BOUNCE"
    return "NONE"


def _failure_state(
    *,
    provider_readiness: Mapping[str, Any],
    touch_record: Mapping[str, Any],
    bounce_state: str,
) -> dict[str, Any]:
    provider_failure = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_failure_class = _state_token(provider_failure.get("failure_class"), default="NONE")
    provider_failure_reason = str(provider_failure.get("failure_reason") or "")
    response_status = _state_token(touch_record.get("response_status"), default="NO_RESPONSE")
    failure_reason = _state_token(touch_record.get("failure_reason_tag_optional"), default="")
    if bounce_state != "NONE":
        return {
            "state": "FAILED",
            "failure_class": "BOUNCE",
            "failure_reason": bounce_state,
            "retryable": bounce_state not in {"HARD_BOUNCE", "INVALID_CONTACT_BOUNCE"},
            "provider_failure_class": provider_failure_class,
            "provider_failure_reason": provider_failure_reason,
        }
    if provider_failure_class not in {"", "NONE", "OK", "NO_FAILURE"}:
        return {
            "state": "FAILED",
            "failure_class": provider_failure_class,
            "failure_reason": provider_failure_reason,
            "retryable": bool(provider_failure.get("retryable", False)),
            "provider_failure_class": provider_failure_class,
            "provider_failure_reason": provider_failure_reason,
        }
    if response_status in {"INVALID_CONTACT", "WRONG_ROLE", "DECLINED", "OPTED_OUT"}:
        return {
            "state": "FAILED",
            "failure_class": "CONTACT_RESPONSE",
            "failure_reason": failure_reason or response_status,
            "retryable": response_status == "WRONG_ROLE",
            "provider_failure_class": provider_failure_class,
            "provider_failure_reason": provider_failure_reason,
        }
    return {
        "state": "NONE",
        "failure_class": "NONE",
        "failure_reason": "",
        "retryable": False,
        "provider_failure_class": provider_failure_class,
        "provider_failure_reason": provider_failure_reason,
    }


def _sandbox_execution_state(
    *,
    provider_suspended: bool,
    stopped: bool,
    hard_blocked: bool,
    held: bool,
) -> str:
    if provider_suspended:
        return "SUSPENDED"
    if stopped:
        return "STOPPED"
    if hard_blocked:
        return "BLOCKED"
    if held:
        return "HELD"
    return "SANDBOX_RECORDED"


def _blocking_stop_reason(value: Any) -> bool:
    reason = _state_token(value, default="")
    if reason in _NO_STOP_VALUES:
        return False
    if "REVIEW_REQUIRED" in reason or "QUIET_HOURS" in reason or "FREQUENCY" in reason:
        return False
    return bool(reason)


def _execution_timeline(
    *,
    now: str,
    sandbox_execution_state: str,
    provider_readiness: Mapping[str, Any],
    template_approval_state: str,
    contact_source_audit_state: str,
    frequency_control_state: str,
    quiet_hours_state: str,
    opt_out_state: str,
    unsubscribe_state: str,
    bounce_state: str,
    retry_state: str,
    stop_state: str,
) -> list[dict[str, Any]]:
    return [
        {
            "event": "sandbox_execution_record_created",
            "at": now,
            "state": "RECORDED",
            "real_provider_call_enabled": False,
        },
        {
            "event": "provider_adapter_readiness_evaluated",
            "at": now,
            "state": provider_readiness.get("readiness_state"),
            "provider_adapter_suspended": bool(provider_readiness.get("provider_adapter_suspended", False)),
            "real_provider_call_enabled": False,
        },
        {"event": "template_approval_evaluated", "at": now, "state": template_approval_state},
        {"event": "contact_source_audit_evaluated", "at": now, "state": contact_source_audit_state},
        {"event": "frequency_control_evaluated", "at": now, "state": frequency_control_state},
        {"event": "quiet_hours_evaluated", "at": now, "state": quiet_hours_state},
        {
            "event": "opt_out_unsubscribe_evaluated",
            "at": now,
            "opt_out_state": opt_out_state,
            "unsubscribe_state": unsubscribe_state,
        },
        {"event": "bounce_failure_evaluated", "at": now, "state": bounce_state},
        {
            "event": "retry_stop_policy_evaluated",
            "at": now,
            "retry_state": retry_state,
            "stop_state": stop_state,
            "real_retry_execution_enabled": False,
        },
        {
            "event": "sandbox_execution_readiness_decided",
            "at": now,
            "state": sandbox_execution_state,
            "live_execution_enabled": False,
            "real_send_attempted": False,
        },
    ]


def build_outbox_readiness_summary(outbox: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(outbox.get("blocked_reasons")))
    vendor_state = dict(outbox.get("vendor_adapter_state", {}))
    provider_readiness = dict(outbox.get("provider_adapter_readiness", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    retry_state = dict(outbox.get("retry_state", {}))
    stop_state = dict(outbox.get("stop_state", {}))
    sandbox_execution_state = str(outbox.get("sandbox_execution_state") or "BLOCKED")
    provider_suspended = bool(provider_readiness.get("provider_adapter_suspended", False)) or bool(
        outbox.get("provider_adapter_suspended", False)
    )
    if provider_suspended or sandbox_execution_state == "SUSPENDED":
        sandbox_execution_readiness = "SUSPENDED"
    elif sandbox_execution_state in {"BLOCKED", "STOPPED"}:
        sandbox_execution_readiness = "BLOCKED"
    elif sandbox_execution_state == "HELD":
        sandbox_execution_readiness = "HELD"
    else:
        sandbox_execution_readiness = "READY"
    sandbox_ready = sandbox_execution_readiness == "READY"
    return {
        "execution_id": outbox.get("execution_id"),
        "outbox_id": outbox.get("outbox_id"),
        "outreach_plan_id": outbox.get("outreach_plan_id"),
        "touch_record_id": outbox.get("touch_record_id"),
        "contact_target_id": outbox.get("contact_target_id"),
        "opportunity_id": outbox.get("opportunity_id"),
        "channel": outbox.get("channel"),
        "adapter_family": outbox.get("adapter_family"),
        "provider_family": outbox.get("provider_family", "sales_outreach"),
        "sandbox_execution_state": sandbox_execution_state,
        "sandbox_execution_readiness": sandbox_execution_readiness,
        "sandbox_execution_record_ready": bool(outbox.get("execution_id")),
        "governed_execution_mode": outbox.get("governed_execution_mode", "INTERNAL_GOVERNED"),
        "readback_ready": bool(outbox.get("outbox_id")),
        "ready_for_real_send": False,
        "dry_run_ready": sandbox_ready,
        "live_execution_enabled": False,
        "real_send_attempted": False,
        "external_delivery_enabled": False,
        "approval_state": outbox.get("approval_state"),
        "audit_state": outbox.get("audit_state"),
        "template_approval_state": outbox.get("template_approval_state"),
        "contact_source_audit_state": outbox.get("contact_source_audit_state"),
        "frequency_control_state": outbox.get("frequency_control_state"),
        "quiet_hours_state": outbox.get("quiet_hours_state"),
        "opt_out_state": outbox.get("opt_out_state"),
        "unsubscribe_state": outbox.get("unsubscribe_state"),
        "bounce_state": outbox.get("bounce_state"),
        "failure_state": dict(outbox.get("failure_state", {})),
        "retry_state": retry_state.get("state"),
        "stop_state": stop_state.get("state"),
        "vendor_adapter_state": vendor_state.get("state"),
        "blocked_reason_count": len(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "execution_timeline": list(outbox.get("execution_timeline", [])),
        "replay_state": dict(outbox.get("replay_state", {})),
        "provider_adapter_config_source": outbox.get("provider_adapter_config_source"),
        "provider_adapter_mode": outbox.get("provider_adapter_mode"),
        "provider_adapter_readback_only": bool(provider_readiness.get("readback_only", True)),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": provider_suspended,
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
    execution_id = build_id("EXEC", project_id, touch_record_id)
    channel = str(
        touch_record.get("touch_channel")
        or contact_target.get("channel_family")
        or contact_target.get("contact_channel")
        or "UNKNOWN"
    )
    adapter_family = _adapter_family_for_channel(
        channel=channel,
        contact_target=contact_target,
        touch_record=touch_record,
        authoritative_inputs=authoritative_inputs,
        execution_vendor_payload=execution_vendor_payload,
    )
    provider_family = str(provider_readiness.get("family") or "sales_outreach")
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
    stop_reason_blocks = _blocking_stop_reason(stop_reason)
    stop_state = "STOPPED" if stop_reason_blocks else str(stop_semantics or "ACTIVE")
    if _state_token(stop_state, default="ACTIVE") in _NO_STOP_VALUES:
        stop_state = "ACTIVE"
    dry_run_state = "DRY_RUN_RECEIPT_ONLY" if run_mode == "DRY_RUN" else "INTERNAL_DRY_RUN_CARRIER_ONLY"
    template_approval_state = _template_approval_state(authoritative_inputs, approval_state)
    template_approval_blocked = template_approval_state in _TEMPLATE_BLOCKING_STATES
    contact_source_audit_state = _contact_source_audit_state(
        contact_target=contact_target,
        audit_state=audit_state,
        authoritative_inputs=authoritative_inputs,
    )
    frequency_control_state = _frequency_control_state(contact_target)
    opt_out_state = _state_token(contact_target.get("opt_out_state"), default="PENDING_CONFIRMATION")
    unsubscribe_state = _unsubscribe_state(authoritative_inputs, opt_out_state)
    bounce_state = _bounce_state(authoritative_inputs, touch_record)
    failure_state = _failure_state(
        provider_readiness=provider_readiness,
        touch_record=touch_record,
        bounce_state=bounce_state,
    )
    stop_decision_reason = stop_reason
    opt_out_blocked = opt_out_state in _OPT_OUT_BLOCKING_STATES
    unsubscribe_blocked = unsubscribe_state in _UNSUBSCRIBE_BLOCKING_STATES
    bounce_blocked = bounce_state in _BOUNCE_BLOCKING_STATES
    if stop_state != "STOPPED" and opt_out_blocked:
        stop_state = "STOPPED"
        stop_decision_reason = "opt_out"
    if stop_state != "STOPPED" and unsubscribe_blocked:
        stop_state = "STOPPED"
        stop_decision_reason = "unsubscribe"
    if stop_state != "STOPPED" and bounce_blocked:
        stop_state = "STOPPED"
        stop_decision_reason = f"bounce:{bounce_state}"
    held = frequency_control_state == "HELD" or quiet_hours_state == "SCHEDULED"
    stopped = stop_state == "STOPPED" or opt_out_blocked or unsubscribe_blocked or bounce_blocked
    hard_blocked = (
        requested_live
        or vendor_connection_requested
        or execution_decision == "BLOCK"
        or approval_missing
        or audit_state == "MISSING"
        or template_approval_blocked
        or contact_source_audit_state == "MISSING"
    )
    sandbox_execution_state = _sandbox_execution_state(
        provider_suspended=provider_suspended,
        stopped=stopped,
        hard_blocked=hard_blocked,
        held=held,
    )
    execution_timeline = _execution_timeline(
        now=now,
        sandbox_execution_state=sandbox_execution_state,
        provider_readiness=provider_readiness,
        template_approval_state=template_approval_state,
        contact_source_audit_state=contact_source_audit_state,
        frequency_control_state=frequency_control_state,
        quiet_hours_state=quiet_hours_state,
        opt_out_state=opt_out_state,
        unsubscribe_state=unsubscribe_state,
        bounce_state=bounce_state,
        retry_state=retry_state,
        stop_state=stop_state,
    )

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
    if template_approval_blocked:
        blocked_reasons.append("template_approval_missing")
    if contact_source_audit_state == "MISSING":
        blocked_reasons.append("contact_source_audit_missing")
    if frequency_control_state == "HELD":
        blocked_reasons.append("frequency_control_held")
    elif frequency_control_state == "REVIEW_REQUIRED":
        blocked_reasons.append("frequency_control_review_required")
    if quiet_hours_state == "SCHEDULED":
        blocked_reasons.append("quiet_hours_schedule")
    if opt_out_blocked:
        blocked_reasons.append("opt_out_blocked")
    if unsubscribe_blocked:
        blocked_reasons.append("unsubscribe_blocked")
    if bounce_state != "NONE":
        blocked_reasons.append(f"bounce_state:{bounce_state}")
    if failure_state.get("state") == "FAILED":
        blocked_reasons.append(f"failure_taxonomy:{failure_state.get('failure_class')}")
    if stop_reason_blocks:
        blocked_reasons.append(f"stop_condition:{stop_reason}")
    if _blocking_stop_reason(stop_decision_reason) and stop_decision_reason != stop_reason:
        blocked_reasons.append(f"stop_condition:{stop_decision_reason}")
    if provider_suspended:
        blocked_reasons.append("provider_adapter_suspended_fail_closed")
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
        "execution_id": execution_id,
        "outbox_id": outbox_id,
        "outreach_plan_id": outreach_plan.get("outreach_plan_id"),
        "touch_record_id": touch_record_id,
        "contact_target_id": contact_target.get("contact_target_id"),
        "opportunity_id": touch_record.get("opportunity_id") or contact_target.get("opportunity_id"),
        "project_id": project_id,
        "channel": channel,
        "adapter_family": adapter_family,
        "sandbox_execution_state": sandbox_execution_state,
        "provider_family": provider_family,
        "template_approval_state": template_approval_state,
        "contact_source_audit_state": contact_source_audit_state,
        "frequency_control_state": frequency_control_state,
        "opt_out_state": opt_out_state,
        "unsubscribe_state": unsubscribe_state,
        "bounce_state": bounce_state,
        "failure_state": failure_state,
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
            "adapter_family": adapter_family,
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
            "sandbox_retry_plan_only": True,
            "sandbox_retry_execution_enabled": False,
            "real_retry_execution_enabled": False,
        },
        "stop_policy": {
            "stop_policy_id": outreach_plan.get("stop_policy_id"),
        },
        "stop_state": {
            "state": stop_state,
            "stop_reason_optional": stop_reason,
            "stop_decision_reason_optional": stop_decision_reason,
            "stop_semantics": stop_semantics,
            "live_send_readiness_enabled": False,
        },
        "dry_run_execution_state": {
            "state": dry_run_state,
            "dry_run_receipt_id": build_id("DRYRUN", project_id, touch_record_id),
            "receipt_scope": "INTERNAL_SIMULATION_ONLY",
            "real_send_attempted": False,
        },
        "live_execution_enabled": False,
        "real_send_attempted": False,
        "external_delivery_enabled": False,
        "execution_timeline": execution_timeline,
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
        "replay_state": {
            "state": "REPLAYABLE",
            "repository_backed": True,
            "sandbox_record_replayable": True,
            "execution_timeline_replayable": True,
            "provider_status_replayable": bool(
                dict(provider_readiness.get("provider_status_readback", {})).get("replayable", True)
            ),
            "real_provider_call_executed": False,
        },
        "channel_vendor_boundary": {
            "channel": channel,
            "adapter_family": adapter_family,
            "vendor_connection_enabled": False,
            "direct_vendor_call_enabled": False,
            "external_vendor_connection_enabled": False,
            "external_delivery_enabled": False,
            "real_provider_receipt_allowed": False,
            "provider_adapter_family": "sales_outreach",
            "provider_family": provider_family,
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
