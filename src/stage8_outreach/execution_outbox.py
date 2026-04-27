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
_LIVE_APPROVED_STATES = {"APPROVED", "APPROVED_FOR_LIVE", "APPROVED_FOR_LIVE_PILOT"}
_SANDBOX_PASS_STATES = {"PASSED", "PASS", "SANDBOX_PASSED", "SANDBOX_RECORDED"}
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
_LIVE_TEMPLATE_APPROVED_STATES = {"APPROVED", "APPROVED_FOR_LIVE", "APPROVED_FOR_LIVE_PILOT"}
_OPT_OUT_BLOCKING_STATES = {"OPTED_OUT", "BLOCKED"}
_UNSUBSCRIBE_BLOCKING_STATES = {"UNSUBSCRIBED", "OPTED_OUT", "BLOCKED"}
_BOUNCE_BLOCKING_STATES = {"BOUNCE", "HARD_BOUNCE", "INVALID_CONTACT_BOUNCE"}
_COMPLAINT_BLOCKING_STATES = {
    "COMPLAINT",
    "COMPLAINT_RECEIVED",
    "CUSTOMER_COMPLAINT",
    "THRESHOLD_EXCEEDED",
    "BLOCKED",
    "SUSPENDED",
}
_FAILURE_THRESHOLD_BLOCKING_STATES = {
    "THRESHOLD_EXCEEDED",
    "FAILURE_THRESHOLD_EXCEEDED",
    "BLOCKED",
    "SUSPENDED",
}
_NO_STOP_VALUES = _EMPTY_VALUES | {"NONE", "NOT_STOPPED", "NO_STOP", "ACTIVE"}


def _clean_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        if _is_empty_value(value):
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _is_empty_value(value: Any) -> bool:
    try:
        return value in _EMPTY_VALUES
    except TypeError:
        return False


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
    return not _is_empty_value(value)


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


def _int_from_inputs(
    authoritative_inputs: Mapping[str, Any],
    *keys: str,
    default: int = 0,
) -> int:
    for key in keys:
        value = authoritative_inputs.get(key)
        if _is_empty_value(value):
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return default
    return default


def _operator_action_audit_refs(authoritative_inputs: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in (
        "operator_action_audit_refs",
        "operator_action_audit_ref",
        "stage8_operator_action_audit_refs",
        "stage8_operator_action_audit_ref",
        "live_pilot_operator_action_audit_refs",
        "live_pilot_operator_action_audit_ref",
    ):
        value = authoritative_inputs.get(key)
        if _is_empty_value(value):
            continue
        values.extend(ensure_list(value))
    expanded: list[str] = []
    for value in values:
        if isinstance(value, str) and "," in value:
            expanded.extend(part.strip() for part in value.split(","))
        else:
            expanded.append(str(value))
    return _clean_list(expanded)


def _pilot_scope(authoritative_inputs: Mapping[str, Any], *, live_execution_requested: bool) -> dict[str, Any]:
    approved_sample_size = _int_from_inputs(
        authoritative_inputs,
        "approved_sample_size",
        "pilot_approved_sample_size",
        "live_pilot_approved_sample_size",
        default=0,
    )
    requested_sample_size = _int_from_inputs(
        authoritative_inputs,
        "requested_sample_size",
        "pilot_requested_sample_size",
        "live_pilot_requested_sample_size",
        default=1 if live_execution_requested else 0,
    )
    max_sample_size = _int_from_inputs(
        authoritative_inputs,
        "max_small_sample_size",
        "live_pilot_max_sample_size",
        default=10,
    )
    requested_batch_send_enabled = any(
        _truthy(authoritative_inputs.get(key))
        for key in (
            "batch_send_enabled",
            "bulk_send_enabled",
            "mass_send_enabled",
            "group_send_enabled",
        )
    )
    scope_type = str(
        authoritative_inputs.get("pilot_scope")
        or authoritative_inputs.get("live_pilot_scope")
        or "small_sample"
    ).strip().lower().replace("-", "_").replace(" ", "_")
    small_sample = (
        scope_type == "small_sample"
        and approved_sample_size > 0
        and requested_sample_size > 0
        and requested_sample_size <= approved_sample_size
        and approved_sample_size <= max_sample_size
        and not requested_batch_send_enabled
    )
    return {
        "pilot_scope": "small_sample",
        "scope_type": scope_type,
        "approved_sample_size": approved_sample_size,
        "requested_sample_size": requested_sample_size,
        "max_small_sample_size": max_sample_size,
        "small_sample": small_sample,
        "batch_send_enabled": False,
        "bulk_send_enabled": False,
        "requested_batch_send_enabled": requested_batch_send_enabled,
    }


def _sandbox_pass_state(
    authoritative_inputs: Mapping[str, Any],
    sandbox_execution_state: str,
) -> str:
    explicit = _state_token(authoritative_inputs.get("sandbox_pass_state"), default="")
    if explicit in _SANDBOX_PASS_STATES:
        return "PASSED"
    if explicit:
        return "BLOCKED"
    if sandbox_execution_state == "SANDBOX_RECORDED":
        return "PASSED"
    if sandbox_execution_state == "SUSPENDED":
        return "SUSPENDED"
    if sandbox_execution_state == "STOPPED":
        return "STOPPED"
    if sandbox_execution_state == "HELD":
        return "HELD"
    return "BLOCKED"


def _complaint_taxonomy(authoritative_inputs: Mapping[str, Any]) -> dict[str, Any]:
    state = _state_token(
        authoritative_inputs.get("complaint_state")
        or authoritative_inputs.get("provider_complaint_state"),
        default="NONE",
    )
    threshold_state = _state_token(
        authoritative_inputs.get("complaint_threshold_state")
        or authoritative_inputs.get("complaint_rate_state"),
        default="OK",
    )
    complaint_class = _state_token(authoritative_inputs.get("complaint_class"), default="NONE")
    suspended = state in _COMPLAINT_BLOCKING_STATES or threshold_state in _COMPLAINT_BLOCKING_STATES
    return {
        "state": state,
        "complaint_class": complaint_class,
        "threshold_state": threshold_state,
        "suspends_live_pilot": suspended,
        "fail_closed": suspended,
    }


def _failure_threshold_state(authoritative_inputs: Mapping[str, Any]) -> dict[str, Any]:
    threshold_state = _state_token(
        authoritative_inputs.get("failure_threshold_state")
        or authoritative_inputs.get("provider_failure_threshold_state"),
        default="OK",
    )
    suspended = threshold_state in _FAILURE_THRESHOLD_BLOCKING_STATES
    return {
        "state": threshold_state,
        "suspends_live_pilot": suspended,
        "fail_closed": suspended,
    }


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


def _provider_config_readiness(
    *,
    authoritative_inputs: Mapping[str, Any],
    provider_adapter_readiness_summary: Mapping[str, Any] | None,
    provider_readiness: Mapping[str, Any],
) -> tuple[str, dict[str, Any], list[str]]:
    summary = dict(provider_adapter_readiness_summary or {})
    explicit_missing = (
        authoritative_inputs.get("provider_config_present") is False
        or authoritative_inputs.get("provider_adapter_config_present") is False
    )
    provider_config_ref = {
        "provider_family": provider_readiness.get("family", "sales_outreach"),
        "provider_id": provider_readiness.get("provider_id"),
        "provider_env": provider_readiness.get("provider_env"),
        "config_source": summary.get("config_source"),
        "config_source_ref": summary.get("config_source_ref"),
        "mode": summary.get("mode") or provider_readiness.get("mode"),
    }
    configured = (
        not explicit_missing
        and bool(provider_readiness.get("provider_adapter_configured", False))
        and bool(provider_config_ref["provider_id"])
        and bool(provider_config_ref["config_source_ref"] or provider_config_ref["config_source"])
    )
    if configured:
        return "CONFIGURED", provider_config_ref, []
    return "MISSING", provider_config_ref, ["provider_config_missing"]


def _blocking_stop_reason(value: Any) -> bool:
    reason = _state_token(value, default="")
    if reason in _NO_STOP_VALUES:
        return False
    if "REVIEW_REQUIRED" in reason or "QUIET_HOURS" in reason or "FREQUENCY" in reason:
        return False
    return bool(reason)


def _approved_provider_execution_requested(
    authoritative_inputs: Mapping[str, Any],
    *,
    requested_live: bool,
) -> bool:
    return requested_live or any(
        _truthy(authoritative_inputs.get(field_name))
        for field_name in (
            "approved_provider_execution_requested",
            "approved_provider_send_requested",
            "provider_execution_requested",
            "controlled_provider_execution_requested",
        )
    )


def _provider_result_state_from_inputs(authoritative_inputs: Mapping[str, Any]) -> str:
    supplied = authoritative_inputs.get("provider_result_readback")
    supplied_payload = dict(supplied) if isinstance(supplied, Mapping) else {}
    return _state_token(
        supplied_payload.get("result_state")
        or supplied_payload.get("state")
        or authoritative_inputs.get("provider_result_state")
        or authoritative_inputs.get("controlled_provider_result_state"),
        default="",
    )


def _approved_provider_result_state(
    *,
    authoritative_inputs: Mapping[str, Any],
    enabled: bool,
    live_pilot_readiness_state: str,
    failure_state: Mapping[str, Any],
    bounce_state: str,
) -> str:
    supplied_state = _provider_result_state_from_inputs(authoritative_inputs)
    if supplied_state:
        if "COMPLAINT" in supplied_state:
            return "COMPLAINT"
        if "BOUNCE" in supplied_state:
            return "BOUNCE"
        if supplied_state in {"RETRY", "RETRYABLE", "RETRY_SCHEDULED"}:
            return "RETRY"
        if supplied_state in {"STOP", "STOPPED"}:
            return "STOPPED"
        if supplied_state in {"SUSPEND", "SUSPENDED"}:
            return "SUSPENDED"
        if supplied_state in {"FAIL", "FAILED", "FAILURE", "ERROR", "TIMEOUT", "RATE_LIMITED"}:
            return "FAILED"
        if supplied_state in {"SUCCESS", "SENT", "ACCEPTED", "DELIVERED", "OK"}:
            return "SUCCESS"
        return supplied_state
    if live_pilot_readiness_state == "SUSPENDED":
        return "SUSPENDED"
    if live_pilot_readiness_state == "STOPPED":
        return "STOPPED"
    if dict(failure_state).get("state") == "FAILED":
        return "FAILED"
    if bounce_state != "NONE":
        return "BOUNCE"
    if enabled:
        return "SUCCESS"
    return "NOT_DISPATCHED"


def _complaint_state(
    *,
    authoritative_inputs: Mapping[str, Any],
    complaint_taxonomy: Mapping[str, Any],
    result_state: str,
) -> str:
    explicit_state = _state_token(
        authoritative_inputs.get("complaint_state")
        or authoritative_inputs.get("provider_complaint_state"),
        default="",
    )
    if explicit_state:
        return explicit_state
    if result_state == "COMPLAINT":
        return "COMPLAINT_RECORDED"
    return _state_token(complaint_taxonomy.get("state"), default="NONE")


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


def _append_approved_provider_execution_timeline(
    *,
    timeline: list[dict[str, Any]],
    now: str,
    execution_request_state: str,
    provider_execution_state: str,
    provider_result_readback: Mapping[str, Any],
    blocked_reasons: list[str],
    suspension_reasons: list[str],
) -> list[dict[str, Any]]:
    result = list(timeline)
    result.append(
        {
            "event": "approved_provider_execution_request_evaluated",
            "at": now,
            "state": execution_request_state,
            "blocked_reasons": list(blocked_reasons),
            "suspension_reasons": list(suspension_reasons),
            "real_provider_call_enabled": False,
            "real_send_attempted": False,
        }
    )
    if execution_request_state == "APPROVED":
        result.append(
            {
                "event": "controlled_provider_adapter_invoked",
                "at": now,
                "state": provider_execution_state,
                "adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "real_send_attempted": False,
            }
        )
    result.append(
        {
            "event": "provider_result_readback_recorded",
            "at": now,
            "state": provider_result_readback.get("result_state"),
            "provider_execution_state": provider_execution_state,
            "replayable": True,
            "provider_call_executed": False,
            "controlled_provider_execution_executed": bool(
                provider_result_readback.get("controlled_provider_execution_executed", False)
            ),
            "real_send_attempted": False,
        }
    )
    return result


def _adapter_family_readiness(
    *,
    active_adapter_family: str,
    provider_readiness: Mapping[str, Any],
    live_pilot_readiness_state: str,
    live_execution_enabled: bool,
) -> dict[str, Any]:
    provider_suspended = bool(provider_readiness.get("provider_adapter_suspended", False))
    readiness: dict[str, Any] = {}
    for family in _ADAPTER_FAMILIES:
        active = family == active_adapter_family
        readiness[family] = {
            "adapter_family": family,
            "active_adapter_family": active,
            "provider_family": provider_readiness.get("family", "sales_outreach"),
            "provider_id": provider_readiness.get("provider_id"),
            "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
            "provider_adapter_suspended": provider_suspended,
            "live_pilot_supported": True,
            "live_pilot_readiness_state": live_pilot_readiness_state if active else "AVAILABLE_FOR_PILOT_RECORD",
            "live_execution_enabled": bool(live_execution_enabled and active),
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
            "real_send_attempted": False,
            "bulk_send_enabled": False,
        }
    return readiness


def _provider_result_readback(
    *,
    authoritative_inputs: Mapping[str, Any],
    adapter_family: str,
    provider_readiness: Mapping[str, Any],
    failure_state: Mapping[str, Any],
    bounce_state: str,
    complaint_taxonomy: Mapping[str, Any],
    live_pilot_readiness_state: str,
    live_execution_enabled: bool,
    approved_provider_execution_enabled: bool = False,
    execution_request_state: str = "NOT_REQUESTED",
    provider_execution_state: str | None = None,
) -> dict[str, Any]:
    supplied = authoritative_inputs.get("provider_result_readback")
    supplied_payload = dict(supplied) if isinstance(supplied, Mapping) else {}
    result_state = _approved_provider_result_state(
        authoritative_inputs=authoritative_inputs,
        enabled=approved_provider_execution_enabled,
        live_pilot_readiness_state=live_pilot_readiness_state,
        failure_state=failure_state,
        bounce_state=bounce_state,
    )
    if not result_state:
        if live_pilot_readiness_state == "SUSPENDED":
            result_state = "SUSPENDED"
        elif live_pilot_readiness_state == "STOPPED":
            result_state = "STOPPED"
        elif dict(failure_state).get("state") == "FAILED":
            result_state = "FAILED"
        elif live_execution_enabled:
            result_state = "READY_FOR_OPERATOR_DISPATCH"
        else:
            result_state = "NOT_DISPATCHED"
    effective_provider_execution_state = provider_execution_state or result_state
    effective_bounce_state = "BOUNCE" if result_state == "BOUNCE" and bounce_state == "NONE" else bounce_state
    effective_failure_state = dict(failure_state)
    if result_state in {"FAILED", "RETRY"} and effective_failure_state.get("state") == "NONE":
        effective_failure_state = {
            **effective_failure_state,
            "state": "FAILED" if result_state == "FAILED" else "RETRY",
            "failure_class": "PROVIDER_RESULT",
            "failure_reason": "provider_result_readback",
            "retryable": result_state == "RETRY",
        }
    effective_complaint_taxonomy = dict(complaint_taxonomy)
    if result_state == "COMPLAINT" and effective_complaint_taxonomy.get("state") in (None, "", "NONE"):
        effective_complaint_taxonomy = {
            **effective_complaint_taxonomy,
            "state": "COMPLAINT",
            "suspends_live_pilot": False,
            "fail_closed": False,
        }
    return {
        **supplied_payload,
        "result_state": result_state,
        "execution_request_state": execution_request_state,
        "provider_execution_state": effective_provider_execution_state,
        "adapter_family": adapter_family,
        "provider_family": provider_readiness.get("family", "sales_outreach"),
        "provider_id": provider_readiness.get("provider_id"),
        "provider_status_readback": dict(provider_readiness.get("provider_status_readback", {})),
        "provider_binding_mode": provider_readiness.get("provider_binding_matrix", {}).get(
            "binding_mode"
        ),
        "provider_binding_matrix": dict(provider_readiness.get("provider_binding_matrix", {})),
        "selected_provider_bindings": list(provider_readiness.get("selected_provider_bindings", [])),
        "bounce_taxonomy": {
            "state": effective_bounce_state,
            "failure_class": "BOUNCE" if effective_bounce_state != "NONE" else "NONE",
            "retryable": effective_bounce_state not in {"NONE", "HARD_BOUNCE", "INVALID_CONTACT_BOUNCE"},
        },
        "failure_taxonomy": effective_failure_state,
        "complaint_taxonomy": effective_complaint_taxonomy,
        "readback_only": True,
        "controlled_provider_adapter_enabled": bool(approved_provider_execution_enabled),
        "controlled_provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
        "controlled_provider_execution_executed": bool(approved_provider_execution_enabled),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "provider_call_executed": False,
        "real_send_attempted": False,
        "real_provider_receipt_generated": False,
    }


def _live_pilot_readiness(
    *,
    authoritative_inputs: Mapping[str, Any],
    execution_id: str,
    outbox_id: str,
    touch_record_id: str,
    contact_target: Mapping[str, Any],
    provider_readiness: Mapping[str, Any],
    adapter_family: str,
    sandbox_execution_state: str,
    provider_suspended: bool,
    live_execution_requested: bool,
    approval_state: str,
    audit_state: str,
    template_approval_state: str,
    contact_source_audit_state: str,
    frequency_control_state: str,
    quiet_hours_state: str,
    opt_out_state: str,
    unsubscribe_state: str,
    failure_state: Mapping[str, Any],
    bounce_state: str,
    stop_state: str,
    now: str,
) -> dict[str, Any]:
    pilot_id = str(authoritative_inputs.get("pilot_id") or build_id("PILOT", outbox_id))
    pilot_scope = _pilot_scope(authoritative_inputs, live_execution_requested=live_execution_requested)
    operator_approval_state = _state_token(
        authoritative_inputs.get("operator_approval_state")
        or authoritative_inputs.get("live_pilot_operator_approval_state"),
        default="MISSING",
    )
    operator_action_audit_refs = _operator_action_audit_refs(authoritative_inputs)
    sandbox_pass_state = _sandbox_pass_state(authoritative_inputs, sandbox_execution_state)
    complaint_taxonomy = _complaint_taxonomy(authoritative_inputs)
    failure_threshold = _failure_threshold_state(authoritative_inputs)

    blocked_reasons: list[str] = []
    held_reasons: list[str] = []
    stopped_reasons: list[str] = []
    suspension_reasons: list[str] = []

    if not live_execution_requested:
        blocked_reasons.append("live_execution_not_requested")
    if approval_state not in _LIVE_APPROVED_STATES:
        blocked_reasons.append("live_pilot_approval_missing")
    if operator_approval_state not in _LIVE_APPROVED_STATES:
        blocked_reasons.append("operator_approval_missing")
    if not operator_action_audit_refs:
        blocked_reasons.append("operator_action_audit_missing")
    if sandbox_pass_state == "SUSPENDED":
        suspension_reasons.append("sandbox_pass_state=SUSPENDED")
    elif sandbox_pass_state == "STOPPED":
        stopped_reasons.append("sandbox_pass_state=STOPPED")
    elif sandbox_pass_state == "HELD":
        held_reasons.append("sandbox_pass_state=HELD")
    elif sandbox_pass_state != "PASSED":
        blocked_reasons.append(f"sandbox_pass_state={sandbox_pass_state}")
    if audit_state == "MISSING":
        blocked_reasons.append("audit_ref_missing")
    if template_approval_state not in _LIVE_TEMPLATE_APPROVED_STATES:
        blocked_reasons.append("template_approval_missing")
    if contact_source_audit_state != "AUDITED":
        blocked_reasons.append("contact_source_audit_missing")
    if str(contact_target.get("contact_target_status")) != "ELIGIBLE":
        blocked_reasons.append("contact_target_not_eligible")
    if not pilot_scope["small_sample"]:
        blocked_reasons.append("pilot_scope_not_approved_small_sample")
    if pilot_scope["requested_batch_send_enabled"]:
        blocked_reasons.append("batch_send_requested_but_disabled")

    if frequency_control_state == "HELD":
        held_reasons.append("frequency_control_held")
    elif frequency_control_state != "ALLOW":
        blocked_reasons.append("frequency_control_not_allow")
    if quiet_hours_state == "SCHEDULED":
        held_reasons.append("quiet_hours_scheduled")
    elif quiet_hours_state != "ALLOW":
        held_reasons.append("quiet_hours_not_allow")

    if opt_out_state in _OPT_OUT_BLOCKING_STATES:
        stopped_reasons.append("opt_out_blocked")
    if unsubscribe_state in _UNSUBSCRIBE_BLOCKING_STATES:
        stopped_reasons.append("unsubscribe_blocked")
    if stop_state == "STOPPED":
        stopped_reasons.append("stop_policy_stopped")
    if bounce_state in _BOUNCE_BLOCKING_STATES:
        stopped_reasons.append(f"bounce_state:{bounce_state}")

    if provider_suspended:
        suspension_reasons.append("provider_adapter_suspended_fail_closed")
    if complaint_taxonomy["suspends_live_pilot"]:
        suspension_reasons.append("complaint_threshold_suspended")
    if failure_threshold["suspends_live_pilot"]:
        suspension_reasons.append("failure_threshold_suspended")

    if suspension_reasons:
        readiness_state = "SUSPENDED"
    elif stopped_reasons:
        readiness_state = "STOPPED"
    elif blocked_reasons:
        readiness_state = "BLOCKED"
    elif held_reasons:
        readiness_state = "HELD"
    else:
        readiness_state = "LIVE_READY"
    live_execution_enabled = live_execution_requested and readiness_state == "LIVE_READY"

    provider_result = _provider_result_readback(
        authoritative_inputs=authoritative_inputs,
        adapter_family=adapter_family,
        provider_readiness=provider_readiness,
        failure_state=failure_state,
        bounce_state=bounce_state,
        complaint_taxonomy=complaint_taxonomy,
        live_pilot_readiness_state=readiness_state,
        live_execution_enabled=live_execution_enabled,
    )
    suspension_state = {
        "state": "SUSPENDED" if readiness_state == "SUSPENDED" else "ACTIVE",
        "reasons": _clean_list(suspension_reasons),
        "manual_resume_required": bool(suspension_reasons),
        "provider_adapter_suspended": provider_suspended,
        "complaint_threshold_suspended": complaint_taxonomy["suspends_live_pilot"],
        "failure_threshold_suspended": failure_threshold["suspends_live_pilot"],
    }
    retry_stop_suspension_state = {
        "retry_allowed_after_manual_review": readiness_state not in {"STOPPED", "SUSPENDED"},
        "stop_state": stop_state,
        "suspension_state": suspension_state["state"],
        "replay_required_before_resume": True,
        "real_retry_execution_enabled": False,
    }
    adapter_family_readiness = _adapter_family_readiness(
        active_adapter_family=adapter_family,
        provider_readiness=provider_readiness,
        live_pilot_readiness_state=readiness_state,
        live_execution_enabled=live_execution_enabled,
    )
    readiness_summary = {
        "pilot_id": pilot_id,
        "execution_id": execution_id,
        "outbox_id": outbox_id,
        "touch_record_id": touch_record_id,
        "contact_target_id": contact_target.get("contact_target_id"),
        "opportunity_id": contact_target.get("opportunity_id"),
        "adapter_family": adapter_family,
        "supported_adapter_families": list(_ADAPTER_FAMILIES),
        "pilot_scope": "small_sample",
        "approved_sample_size": pilot_scope["approved_sample_size"],
        "requested_sample_size": pilot_scope["requested_sample_size"],
        "batch_send_enabled": False,
        "bulk_send_enabled": False,
        "provider_adapter_readiness_summary": dict(provider_readiness),
        "sandbox_pass_state": sandbox_pass_state,
        "template_approval_state": template_approval_state,
        "contact_source_audit_state": contact_source_audit_state,
        "operator_approval_state": operator_approval_state,
        "operator_action_audit_refs": operator_action_audit_refs,
        "frequency_control_state": frequency_control_state,
        "quiet_hours_state": quiet_hours_state,
        "opt_out_state": opt_out_state,
        "unsubscribe_state": unsubscribe_state,
        "live_pilot_readiness_state": readiness_state,
        "live_execution_requested": live_execution_requested,
        "live_execution_enabled": live_execution_enabled,
        "real_send_attempted": False,
        "provider_result_readback": provider_result,
        "bounce_taxonomy": dict(provider_result["bounce_taxonomy"]),
        "failure_taxonomy": dict(provider_result["failure_taxonomy"]),
        "complaint_taxonomy": dict(complaint_taxonomy),
        "failure_threshold_state": dict(failure_threshold),
        "retry_stop_suspension_state": retry_stop_suspension_state,
        "suspension_state": suspension_state,
        "replay_state": {
            "state": "REPLAYABLE",
            "repository_backed": True,
            "live_pilot_record_replayable": True,
            "provider_result_readback_replayable": True,
            "real_provider_call_executed": False,
        },
        "adapter_family_readiness": adapter_family_readiness,
        "blocked_reasons": _clean_list(blocked_reasons),
        "held_reasons": _clean_list(held_reasons),
        "stopped_reasons": _clean_list(stopped_reasons),
        "suspension_reasons": _clean_list(suspension_reasons),
        "decided_at": now,
    }
    return {
        "pilot_id": pilot_id,
        "pilot_scope": "small_sample",
        "pilot_scope_details": pilot_scope,
        "approved_sample_size": pilot_scope["approved_sample_size"],
        "requested_sample_size": pilot_scope["requested_sample_size"],
        "batch_send_enabled": False,
        "bulk_send_enabled": False,
        "requested_batch_send_enabled": pilot_scope["requested_batch_send_enabled"],
        "sandbox_pass_state": sandbox_pass_state,
        "operator_approval_state": operator_approval_state,
        "operator_action_audit_refs": operator_action_audit_refs,
        "complaint_taxonomy": dict(complaint_taxonomy),
        "failure_threshold_state": dict(failure_threshold),
        "suspension_state": suspension_state,
        "retry_stop_suspension_state": retry_stop_suspension_state,
        "provider_result_readback": provider_result,
        "adapter_family_readiness": adapter_family_readiness,
        "live_pilot_readiness_state": readiness_state,
        "live_execution_requested": live_execution_requested,
        "live_execution_enabled": live_execution_enabled,
        "live_execution_record": {
            "pilot_id": pilot_id,
            "execution_id": execution_id,
            "outbox_id": outbox_id,
            "adapter_family": adapter_family,
            "execution_state": readiness_state,
            "live_execution_requested": live_execution_requested,
            "live_execution_enabled": live_execution_enabled,
            "real_send_attempted": False,
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
            "provider_result_readback": provider_result,
        },
        "live_pilot_readiness_summary": readiness_summary,
        "blocked_reasons": _clean_list(blocked_reasons),
        "held_reasons": _clean_list(held_reasons),
        "stopped_reasons": _clean_list(stopped_reasons),
        "suspension_reasons": _clean_list(suspension_reasons),
    }


def _approved_provider_execution_carrier(
    *,
    authoritative_inputs: Mapping[str, Any],
    execution_id: str,
    outbox_id: str,
    touch_record_id: str,
    contact_target: Mapping[str, Any],
    adapter_family: str,
    provider_config_state: str,
    provider_config_ref: Mapping[str, Any],
    provider_readiness: Mapping[str, Any],
    live_pilot: Mapping[str, Any],
    failure_state: Mapping[str, Any],
    bounce_state: str,
    now: str,
) -> dict[str, Any]:
    requested = _approved_provider_execution_requested(
        authoritative_inputs,
        requested_live=bool(live_pilot.get("live_execution_requested", False)),
    )
    blocked_reasons: list[str] = []
    held_reasons = _clean_list(ensure_list(live_pilot.get("held_reasons")))
    stopped_reasons = _clean_list(ensure_list(live_pilot.get("stopped_reasons")))
    suspension_reasons = _clean_list(ensure_list(live_pilot.get("suspension_reasons")))

    if not requested:
        blocked_reasons.append("approved_provider_execution_not_requested")
    if provider_config_state != "CONFIGURED":
        blocked_reasons.append("provider_config_missing")
    blocked_reasons.extend(ensure_list(live_pilot.get("blocked_reasons")))

    live_pilot_state = str(live_pilot.get("live_pilot_readiness_state") or "BLOCKED")
    if live_pilot_state == "SUSPENDED":
        execution_request_state = "SUSPENDED"
    elif live_pilot_state == "STOPPED":
        execution_request_state = "STOPPED"
    elif live_pilot_state == "HELD":
        execution_request_state = "HELD"
    elif blocked_reasons:
        execution_request_state = "BLOCKED"
    elif requested and live_pilot_state == "LIVE_READY":
        execution_request_state = "APPROVED"
    else:
        execution_request_state = "BLOCKED"

    enabled = execution_request_state == "APPROVED"
    result_state = _approved_provider_result_state(
        authoritative_inputs=authoritative_inputs,
        enabled=enabled,
        live_pilot_readiness_state=live_pilot_state,
        failure_state=failure_state,
        bounce_state=bounce_state,
    )
    provider_execution_state = result_state if enabled else execution_request_state
    complaint_taxonomy = dict(live_pilot.get("complaint_taxonomy", {}))
    complaint_state = _complaint_state(
        authoritative_inputs=authoritative_inputs,
        complaint_taxonomy=complaint_taxonomy,
        result_state=result_state,
    )
    provider_result = _provider_result_readback(
        authoritative_inputs=authoritative_inputs,
        adapter_family=adapter_family,
        provider_readiness=provider_readiness,
        failure_state=failure_state,
        bounce_state=bounce_state,
        complaint_taxonomy=complaint_taxonomy,
        live_pilot_readiness_state=live_pilot_state,
        live_execution_enabled=bool(live_pilot.get("live_execution_enabled", False)),
        approved_provider_execution_enabled=enabled,
        execution_request_state=execution_request_state,
        provider_execution_state=provider_execution_state,
    )
    provider_result["complaint_state"] = complaint_state
    provider_result["controlled_provider_execution_requested"] = requested
    complaint_taxonomy = dict(provider_result.get("complaint_taxonomy", complaint_taxonomy))

    gate_states = {
        "provider_config_state": provider_config_state,
        "sandbox_pass_state": live_pilot.get("sandbox_pass_state"),
        "template_approval_state": live_pilot.get("live_pilot_readiness_summary", {}).get(
            "template_approval_state"
        ),
        "contact_source_audit_state": live_pilot.get("live_pilot_readiness_summary", {}).get(
            "contact_source_audit_state"
        ),
        "operator_approval_state": live_pilot.get("operator_approval_state"),
        "operator_action_audit_refs": list(live_pilot.get("operator_action_audit_refs", [])),
        "frequency_control_state": live_pilot.get("live_pilot_readiness_summary", {}).get(
            "frequency_control_state"
        ),
        "quiet_hours_state": live_pilot.get("live_pilot_readiness_summary", {}).get("quiet_hours_state"),
        "opt_out_state": live_pilot.get("live_pilot_readiness_summary", {}).get("opt_out_state"),
        "unsubscribe_state": live_pilot.get("live_pilot_readiness_summary", {}).get(
            "unsubscribe_state"
        ),
        "complaint_state": complaint_state,
        "bounce_state": bounce_state,
        "failure_state": dict(failure_state),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": bool(provider_readiness.get("provider_adapter_suspended", False)),
    }
    replay_state = {
        "state": "REPLAYABLE",
        "repository_backed": True,
        "approved_provider_execution_record_replayable": True,
        "provider_result_readback_replayable": True,
        "execution_timeline_replayable": True,
        "provider_status_replayable": bool(
            dict(provider_readiness.get("provider_status_readback", {})).get("replayable", True)
        ),
        "controlled_provider_execution_replayable": True,
        "real_provider_call_executed": False,
    }
    summary = {
        "execution_id": execution_id,
        "outbox_id": outbox_id,
        "touch_record_id": touch_record_id,
        "contact_target_id": contact_target.get("contact_target_id"),
        "opportunity_id": contact_target.get("opportunity_id"),
        "adapter_family": adapter_family,
        "supported_adapter_families": list(_ADAPTER_FAMILIES),
        "provider_config_ref": dict(provider_config_ref),
        "provider_adapter_readiness_summary": dict(provider_readiness),
        "approved_provider_execution_requested": requested,
        "approved_provider_execution_enabled": enabled,
        "execution_request_state": execution_request_state,
        "provider_execution_state": provider_execution_state,
        "controlled_provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
        "controlled_provider_execution_executed": bool(
            provider_result.get("controlled_provider_execution_executed", False)
        ),
        "batch_send_enabled": False,
        "bulk_send_enabled": False,
        "real_send_attempted": False,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "gate_states": gate_states,
        "provider_result_readback": provider_result,
        "bounce_taxonomy": dict(provider_result.get("bounce_taxonomy", {})),
        "failure_taxonomy": dict(provider_result.get("failure_taxonomy", {})),
        "complaint_state": complaint_state,
        "complaint_taxonomy": complaint_taxonomy,
        "retry_state": "RETRY" if result_state == "RETRY" else "NOT_REQUESTED",
        "stop_state": "STOPPED" if execution_request_state == "STOPPED" else "ACTIVE",
        "suspension_state": dict(live_pilot.get("suspension_state", {})),
        "blocked_reasons": _clean_list(blocked_reasons),
        "held_reasons": held_reasons,
        "stopped_reasons": stopped_reasons,
        "suspension_reasons": suspension_reasons,
        "replay_state": replay_state,
        "decided_at": now,
    }
    return summary


def build_outbox_readiness_summary(outbox: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(outbox.get("blocked_reasons")))
    vendor_state = dict(outbox.get("vendor_adapter_state", {}))
    provider_readiness = dict(outbox.get("provider_adapter_readiness", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    retry_state = dict(outbox.get("retry_state", {}))
    stop_state = dict(outbox.get("stop_state", {}))
    live_pilot_summary = dict(outbox.get("live_pilot_readiness_summary", {}))
    approved_provider_summary = dict(outbox.get("approved_provider_execution_summary", {}))
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
        "pilot_id": outbox.get("pilot_id"),
        "pilot_scope": outbox.get("pilot_scope"),
        "approved_sample_size": outbox.get("approved_sample_size"),
        "requested_sample_size": outbox.get("requested_sample_size"),
        "batch_send_enabled": bool(outbox.get("batch_send_enabled", False)),
        "bulk_send_enabled": bool(outbox.get("bulk_send_enabled", False)),
        "provider_family": outbox.get("provider_family", "sales_outreach"),
        "sandbox_execution_state": sandbox_execution_state,
        "sandbox_pass_state": outbox.get("sandbox_pass_state"),
        "sandbox_execution_readiness": sandbox_execution_readiness,
        "sandbox_execution_record_ready": bool(outbox.get("execution_id")),
        "governed_execution_mode": outbox.get("governed_execution_mode", "INTERNAL_GOVERNED"),
        "readback_ready": bool(outbox.get("outbox_id")),
        "ready_for_real_send": False,
        "dry_run_ready": sandbox_ready,
        "live_pilot_readiness_state": outbox.get("live_pilot_readiness_state"),
        "live_pilot_execution_ready": bool(outbox.get("live_execution_enabled", False)),
        "live_execution_requested": bool(outbox.get("live_execution_requested", False)),
        "live_execution_enabled": bool(outbox.get("live_execution_enabled", False)),
        "approved_provider_execution_requested": bool(
            outbox.get("approved_provider_execution_requested", False)
        ),
        "approved_provider_execution_enabled": bool(
            outbox.get("approved_provider_execution_enabled", False)
        ),
        "approved_provider_execution_ready": bool(
            outbox.get("approved_provider_execution_enabled", False)
        ),
        "execution_request_state": outbox.get("execution_request_state"),
        "provider_execution_state": outbox.get("provider_execution_state"),
        "provider_config_ref": dict(outbox.get("provider_config_ref", {})),
        "provider_adapter_readiness_summary": dict(
            outbox.get("provider_adapter_readiness_summary", {})
        ),
        "approved_provider_execution_summary": approved_provider_summary,
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
        "operator_approval_state": outbox.get("operator_approval_state"),
        "operator_action_audit_refs": list(outbox.get("operator_action_audit_refs", [])),
        "bounce_state": outbox.get("bounce_state"),
        "failure_state": dict(outbox.get("failure_state", {})),
        "provider_result_readback": dict(outbox.get("provider_result_readback", {})),
        "provider_result_timeline": list(outbox.get("execution_timeline", [])),
        "complaint_state": outbox.get("complaint_state"),
        "complaint_taxonomy": dict(outbox.get("complaint_taxonomy", {})),
        "bounce_taxonomy": dict(outbox.get("bounce_taxonomy", {})),
        "failure_taxonomy": dict(outbox.get("failure_taxonomy", {})),
        "failure_threshold_state": dict(outbox.get("failure_threshold_state", {})),
        "suspension_state": dict(outbox.get("suspension_state", {})),
        "retry_state": retry_state.get("state"),
        "stop_state": stop_state.get("state"),
        "vendor_adapter_state": vendor_state.get("state"),
        "blocked_reason_count": len(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "execution_timeline": list(outbox.get("execution_timeline", [])),
        "replay_state": dict(outbox.get("replay_state", {})),
        "live_pilot_readiness_summary": live_pilot_summary,
        "adapter_family_readiness": dict(outbox.get("adapter_family_readiness", {})),
        "provider_adapter_config_source": outbox.get("provider_adapter_config_source"),
        "provider_adapter_mode": outbox.get("provider_adapter_mode"),
        "provider_adapter_readback_only": bool(provider_readiness.get("readback_only", True)),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": provider_suspended,
        "provider_circuit_breaker_state": provider_circuit_breaker.get("state"),
        "provider_failure_class": provider_failure_taxonomy.get("failure_class"),
        "provider_status_replayable": bool(provider_status_readback.get("replayable", True)),
        "controlled_provider_adapter_scope": outbox.get("controlled_provider_adapter_scope"),
        "controlled_provider_execution_executed": bool(
            outbox.get("controlled_provider_execution_executed", False)
        ),
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
    provider_config_state, provider_config_ref, provider_config_blocked_reasons = _provider_config_readiness(
        authoritative_inputs=authoritative_inputs,
        provider_adapter_readiness_summary=provider_adapter_readiness_summary,
        provider_readiness=provider_readiness,
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
        or _truthy(authoritative_inputs.get("live_execution_requested"))
        or _truthy(authoritative_inputs.get("live_pilot_execution_requested"))
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
        vendor_connection_requested
        or execution_decision == "BLOCK"
        or approval_missing
        or audit_state == "MISSING"
        or template_approval_blocked
        or contact_source_audit_state == "MISSING"
        or provider_config_state != "CONFIGURED"
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
    live_pilot = _live_pilot_readiness(
        authoritative_inputs=authoritative_inputs,
        execution_id=execution_id,
        outbox_id=outbox_id,
        touch_record_id=touch_record_id,
        contact_target=contact_target,
        provider_readiness=provider_readiness,
        adapter_family=adapter_family,
        sandbox_execution_state=sandbox_execution_state,
        provider_suspended=provider_suspended,
        live_execution_requested=requested_live,
        approval_state=approval_state,
        audit_state=audit_state,
        template_approval_state=template_approval_state,
        contact_source_audit_state=contact_source_audit_state,
        frequency_control_state=frequency_control_state,
        quiet_hours_state=quiet_hours_state,
        opt_out_state=opt_out_state,
        unsubscribe_state=unsubscribe_state,
        failure_state=failure_state,
        bounce_state=bounce_state,
        stop_state=stop_state,
        now=now,
    )
    approved_provider_execution = _approved_provider_execution_carrier(
        authoritative_inputs=authoritative_inputs,
        execution_id=execution_id,
        outbox_id=outbox_id,
        touch_record_id=touch_record_id,
        contact_target=contact_target,
        adapter_family=adapter_family,
        provider_config_state=provider_config_state,
        provider_config_ref=provider_config_ref,
        provider_readiness=provider_readiness,
        live_pilot=live_pilot,
        failure_state=failure_state,
        bounce_state=bounce_state,
        now=now,
    )
    live_pilot["provider_result_readback"] = approved_provider_execution["provider_result_readback"]
    live_pilot["live_execution_record"]["provider_result_readback"] = approved_provider_execution[
        "provider_result_readback"
    ]
    live_pilot["live_pilot_readiness_summary"]["provider_result_readback"] = approved_provider_execution[
        "provider_result_readback"
    ]
    execution_timeline = _append_approved_provider_execution_timeline(
        timeline=execution_timeline,
        now=now,
        execution_request_state=str(approved_provider_execution["execution_request_state"]),
        provider_execution_state=str(approved_provider_execution["provider_execution_state"]),
        provider_result_readback=approved_provider_execution["provider_result_readback"],
        blocked_reasons=list(approved_provider_execution["blocked_reasons"]),
        suspension_reasons=list(approved_provider_execution["suspension_reasons"]),
    ) if approved_provider_execution["approved_provider_execution_requested"] else execution_timeline

    blocked_reasons = []
    blocked_reasons.extend(ensure_list(contact_target.get("blocking_reasons")))
    blocked_reasons.extend(ensure_list(runtime_state.blocked_reasons))
    blocked_reasons.extend(ensure_list(runtime_state.permission_blocked_reasons))
    if requested_live and not live_pilot["live_execution_enabled"]:
        blocked_reasons.append("live_execution_requested_but_blocked")
    if (
        approved_provider_execution["approved_provider_execution_requested"]
        and not approved_provider_execution["approved_provider_execution_enabled"]
    ):
        blocked_reasons.append("approved_provider_execution_requested_but_blocked")
    if vendor_connection_requested:
        blocked_reasons.append("vendor_connection_enabled=false")
    if execution_decision == "BLOCK":
        blocked_reasons.append(
            execution_vendor_trace.get("unresolved_reason_optional")
            or "execution_vendor_resolution_blocked"
        )
    blocked_reasons.extend(provider_config_blocked_reasons)
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
    blocked_reasons.extend(live_pilot["blocked_reasons"])
    blocked_reasons.extend(live_pilot["held_reasons"])
    blocked_reasons.extend(live_pilot["stopped_reasons"])
    blocked_reasons.extend(live_pilot["suspension_reasons"])
    blocked_reasons.extend(approved_provider_execution["blocked_reasons"])
    blocked_reasons.extend(approved_provider_execution["held_reasons"])
    blocked_reasons.extend(approved_provider_execution["stopped_reasons"])
    blocked_reasons.extend(approved_provider_execution["suspension_reasons"])
    blocked_reasons.extend(
        [
            "internal_governed_outbox_only",
            "real_send_attempted=false",
            "external_vendor_connection_disabled",
        ]
    )
    if live_pilot["live_execution_enabled"]:
        blocked_reasons.append("real_provider_call_blocked_readback_only")
    else:
        blocked_reasons.append("live_execution_enabled=false")
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
        "supported_adapter_families": list(_ADAPTER_FAMILIES),
        "provider_config_ref": dict(provider_config_ref),
        "provider_config_state": provider_config_state,
        "provider_adapter_readiness_summary": dict(provider_readiness),
        "pilot_id": live_pilot["pilot_id"],
        "pilot_scope": live_pilot["pilot_scope"],
        "pilot_scope_details": live_pilot["pilot_scope_details"],
        "approved_sample_size": live_pilot["approved_sample_size"],
        "requested_sample_size": live_pilot["requested_sample_size"],
        "batch_send_enabled": False,
        "bulk_send_enabled": False,
        "requested_batch_send_enabled": live_pilot["requested_batch_send_enabled"],
        "sandbox_execution_state": sandbox_execution_state,
        "sandbox_pass_state": live_pilot["sandbox_pass_state"],
        "provider_family": provider_family,
        "template_approval_state": template_approval_state,
        "contact_source_audit_state": contact_source_audit_state,
        "frequency_control_state": frequency_control_state,
        "opt_out_state": opt_out_state,
        "unsubscribe_state": unsubscribe_state,
        "operator_approval_state": live_pilot["operator_approval_state"],
        "operator_action_audit_refs": live_pilot["operator_action_audit_refs"],
        "bounce_state": bounce_state,
        "failure_state": failure_state,
        "failure_threshold_state": live_pilot["failure_threshold_state"],
        "complaint_state": approved_provider_execution["complaint_state"],
        "complaint_taxonomy": live_pilot["complaint_taxonomy"],
        "provider_result_readback": approved_provider_execution["provider_result_readback"],
        "bounce_taxonomy": approved_provider_execution["bounce_taxonomy"],
        "failure_taxonomy": approved_provider_execution["failure_taxonomy"],
        "suspension_state": live_pilot["suspension_state"],
        "retry_stop_suspension_state": live_pilot["retry_stop_suspension_state"],
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
            "approved_provider_execution_enabled": approved_provider_execution[
                "approved_provider_execution_enabled"
            ],
            "execution_request_state": approved_provider_execution["execution_request_state"],
            "provider_execution_state": approved_provider_execution["provider_execution_state"],
            "controlled_provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
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
        "live_pilot_readiness_state": live_pilot["live_pilot_readiness_state"],
        "live_execution_requested": live_pilot["live_execution_requested"],
        "live_execution_enabled": live_pilot["live_execution_enabled"],
        "live_execution_record": live_pilot["live_execution_record"],
        "live_pilot_readiness_summary": live_pilot["live_pilot_readiness_summary"],
        "adapter_family_readiness": live_pilot["adapter_family_readiness"],
        "approved_provider_execution_requested": approved_provider_execution[
            "approved_provider_execution_requested"
        ],
        "approved_provider_execution_enabled": approved_provider_execution[
            "approved_provider_execution_enabled"
        ],
        "execution_request_state": approved_provider_execution["execution_request_state"],
        "provider_execution_state": approved_provider_execution["provider_execution_state"],
        "approved_provider_execution_summary": approved_provider_execution,
        "controlled_provider_adapter_scope": approved_provider_execution[
            "controlled_provider_adapter_scope"
        ],
        "controlled_provider_execution_executed": approved_provider_execution[
            "controlled_provider_execution_executed"
        ],
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
            "live_pilot_record_replayable": True,
            "approved_provider_execution_record_replayable": True,
            "execution_timeline_replayable": True,
            "provider_result_readback_replayable": True,
            "controlled_provider_execution_replayable": True,
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
            "controlled_provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
            "approved_provider_execution_enabled": approved_provider_execution[
                "approved_provider_execution_enabled"
            ],
            "pilot_scope": "small_sample",
            "batch_send_enabled": False,
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
