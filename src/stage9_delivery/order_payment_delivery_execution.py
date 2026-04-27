from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_readiness_for_family,
)
from shared.utils import build_id, ensure_list


STAGE9_EXECUTION_LEDGER_OBJECT_TYPE = "stage9_execution_ledger"
STAGE9_EXECUTION_LEDGER_INPUT_KEY = "stage9_execution_ledger"
STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY = "stage9_execution_ledger_readiness"
STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY = "stage9_execution_ledger_id_optional"
PAYMENT_SANDBOX_RECORDS_INPUT_KEY = "payment_sandbox_provider_records"
DELIVERY_SANDBOX_RECORDS_INPUT_KEY = "delivery_sandbox_provider_records"
MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY = "manual_refund_exception_record"
PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY = "payment_delivery_live_pilot"
APPROVED_PAYMENT_DELIVERY_EXECUTION_INPUT_KEY = "approved_payment_delivery_execution"

_EMPTY_VALUES = {None, "", "UNKNOWN", "NOT_APPLICABLE"}
_SUSPENDED_STATES = {"SUSPENDED"}
_CIRCUIT_OPEN_STATES = {"OPEN", "HALF_OPEN", "FORCED_OPEN"}
_PROVIDER_FAILURE_BLOCKING_CLASSES = {"UNHEALTHY", "RATE_LIMITED", "TIMEOUT", "CIRCUIT_OPEN"}
_LIVE_APPROVED_STATES = {"APPROVED", "APPROVED_FOR_LIVE_PILOT", "SATISFIED", "SATISFIED_FOR_LIVE_PILOT"}
_FINANCE_REVIEW_APPROVED_STATES = {"APPROVED", "APPROVED_FOR_LIVE_PILOT", "REVIEWED", "SATISFIED"}
_DOWNLOAD_AUTH_APPROVED_STATES = {"APPROVED", "AUTHORIZED", "APPROVED_FOR_LIVE_PILOT", "GRANTED"}
_CALLBACK_BLOCKING_STATES = {"MISMATCH", "MISMATCH_CONFIRMED", "BLOCKED", "FAILED"}
_CALLBACK_REVIEW_STATES = {"REVIEW", "REVIEW_REQUIRED", "MISMATCH_REVIEW", "MISMATCH_PENDING_REVIEW"}
_DELIVERY_FAILURE_STATES = {"RELEASE_BLOCKED", "FAILED", "CANCELLED", "FULFILLMENT_BLOCKED"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "live", "enabled"}
    return bool(value)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value not in _EMPTY_VALUES
    return True


def _clean_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        if value in _EMPTY_VALUES:
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _state_token(value: Any, *, default: str = "MISSING") -> str:
    if value in _EMPTY_VALUES:
        return default
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def _int_from_inputs(
    inputs: Mapping[str, Any],
    *field_names: str,
    default: int = 0,
) -> int:
    for field_name in field_names:
        value = inputs.get(field_name)
        if value in _EMPTY_VALUES:
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return default
    return default


def _requested_flag(inputs: Mapping[str, Any], *field_names: str) -> bool:
    return any(_truthy(inputs.get(field_name)) for field_name in field_names)


def _hash_payload(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(dict(payload), sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _provider_is_suspended(provider_readiness: Mapping[str, Any]) -> bool:
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_reliability = dict(provider_readiness.get("provider_reliability", {}))
    health_check = dict(provider_reliability.get("health_check", {}))
    rate_limit = dict(provider_reliability.get("rate_limit", {}))
    timeout = dict(provider_reliability.get("timeout", {}))
    failure_class = str(provider_failure_taxonomy.get("failure_class", "NONE")).upper()
    circuit_state = str(provider_circuit_breaker.get("state", "CLOSED")).upper()
    return bool(
        provider_readiness.get("provider_adapter_suspended", False)
        or str(provider_readiness.get("readiness_state", "")).upper() in _SUSPENDED_STATES
        or str(provider_readiness.get("provider_reliability_state", "")).upper() in _SUSPENDED_STATES
        or circuit_state in _CIRCUIT_OPEN_STATES
        or bool(provider_circuit_breaker.get("open", False))
        or failure_class in _PROVIDER_FAILURE_BLOCKING_CLASSES
        or str(health_check.get("status", "HEALTHY")).upper() == "UNHEALTHY"
        or bool(rate_limit.get("rate_limited", False))
        or bool(timeout.get("timeout_triggered", False))
    )


def _provider_sandbox_state(provider_readiness: Mapping[str, Any]) -> str:
    if not provider_readiness:
        return "BLOCKED"
    return "SUSPENDED" if _provider_is_suspended(provider_readiness) else "SANDBOX_RECORDED"


def _provider_blocked_reasons(provider_readiness: Mapping[str, Any], *extra: str) -> list[str]:
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    reasons = list(provider_readiness.get("blocked_reasons", [])) + list(extra)
    if _provider_is_suspended(provider_readiness):
        reasons.append("provider_suspended_fail_closed_no_live_fallback")
    if str(provider_failure_taxonomy.get("failure_class", "NONE")).upper() in _PROVIDER_FAILURE_BLOCKING_CLASSES:
        reasons.append("provider_failure_blocks_sandbox_execution")
    if str(provider_circuit_breaker.get("state", "CLOSED")).upper() in _CIRCUIT_OPEN_STATES:
        reasons.append("provider_circuit_open_fail_closed")
    return _clean_list(reasons)


def _operator_action_audit_refs(inputs: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for field_name in (
        "operator_action_audit_refs",
        "operator_action_audit_ref",
        "stage9_operator_action_audit_refs",
        "stage9_operator_action_audit_ref",
        "payment_delivery_live_pilot_operator_action_audit_refs",
        "payment_delivery_live_pilot_operator_action_audit_ref",
        "live_pilot_operator_action_audit_refs",
        "live_pilot_operator_action_audit_ref",
    ):
        value = inputs.get(field_name)
        if not _has_value(value):
            continue
        values.extend(ensure_list(value))
    expanded: list[str] = []
    for value in values:
        if isinstance(value, str) and "," in value:
            expanded.extend(part.strip() for part in value.split(","))
        else:
            expanded.append(str(value))
    return _clean_list(expanded)


def _live_pilot_scope(inputs: Mapping[str, Any], *, live_requested: bool) -> dict[str, Any]:
    approved_sample_size = _int_from_inputs(
        inputs,
        "approved_sample_size",
        "pilot_approved_sample_size",
        "live_pilot_approved_sample_size",
        "payment_delivery_live_pilot_approved_sample_size",
        default=0,
    )
    requested_sample_size = _int_from_inputs(
        inputs,
        "requested_sample_size",
        "pilot_requested_sample_size",
        "live_pilot_requested_sample_size",
        "payment_delivery_live_pilot_requested_sample_size",
        default=1 if live_requested else 0,
    )
    max_sample_size = _int_from_inputs(
        inputs,
        "max_small_sample_size",
        "live_pilot_max_sample_size",
        "payment_delivery_live_pilot_max_sample_size",
        default=10,
    )
    requested_batch_execution_enabled = any(
        _truthy(inputs.get(field_name))
        for field_name in (
            "batch_execution_enabled",
            "bulk_execution_enabled",
            "mass_execution_enabled",
            "batch_send_enabled",
            "bulk_send_enabled",
            "stage8_bulk_execution_enabled",
            "payment_delivery_batch_execution_enabled",
            "payment_delivery_live_pilot_batch_execution_enabled",
        )
    )
    scope_type = str(
        inputs.get("pilot_scope")
        or inputs.get("live_pilot_scope")
        or inputs.get("payment_delivery_live_pilot_scope")
        or "small_sample"
    ).strip().lower().replace("-", "_").replace(" ", "_")
    small_sample = (
        scope_type == "small_sample"
        and approved_sample_size > 0
        and requested_sample_size > 0
        and requested_sample_size <= approved_sample_size
        and approved_sample_size <= max_sample_size
        and not requested_batch_execution_enabled
    )
    return {
        "pilot_scope": "small_sample",
        "scope_type": scope_type,
        "approved_sample_size": approved_sample_size,
        "requested_sample_size": requested_sample_size,
        "max_small_sample_size": max_sample_size,
        "small_sample": small_sample,
        "batch_execution_enabled": False,
        "bulk_execution_enabled": False,
        "requested_batch_execution_enabled": requested_batch_execution_enabled,
    }


def _sandbox_payment_pass_state(
    inputs: Mapping[str, Any],
    payment_gateway_record: Mapping[str, Any],
    charge_record: Mapping[str, Any],
) -> str:
    explicit = _state_token(
        inputs.get("sandbox_payment_pass_state")
        or inputs.get("payment_sandbox_pass_state")
        or inputs.get("sandbox_pass_state"),
        default="",
    )
    if explicit in {"PASSED", "PASS", "SANDBOX_RECORDED"}:
        return "PASSED"
    if explicit:
        return "SUSPENDED" if explicit == "SUSPENDED" else "BLOCKED"
    gateway_state = str(payment_gateway_record.get("gateway_execution_state", "BLOCKED"))
    charge_state = str(charge_record.get("sandbox_execution_state", "BLOCKED"))
    if "SUSPENDED" in {gateway_state, charge_state}:
        return "SUSPENDED"
    if gateway_state == "SANDBOX_RECORDED" and charge_state == "SANDBOX_RECORDED":
        return "PASSED"
    return "BLOCKED"


def _provider_result_readback(
    *,
    family: str,
    provider_readiness: Mapping[str, Any],
    readiness_state: str,
    live_enabled: bool,
    records: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "provider_family": family,
        "provider_id": provider_readiness.get("provider_id"),
        "provider_mode": provider_readiness.get("mode"),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": _provider_is_suspended(provider_readiness),
        "provider_status_readback": dict(provider_readiness.get("provider_status_readback", {})),
        "readiness_state": readiness_state,
        "live_pilot_record_enabled": live_enabled,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "provider_call_executed": False,
        "real_charge_attempted": False,
        "real_delivery_fulfillment_attempted": False,
        "live_fallback_allowed": False,
        "readback_only": True,
        "records": dict(records),
    }


def _pilot_readiness_state(
    *,
    suspension_reasons: list[str],
    blocked_reasons: list[str],
    review_reasons: list[str],
) -> str:
    if suspension_reasons:
        return "SUSPENDED"
    if blocked_reasons:
        return "BLOCKED"
    if review_reasons:
        return "REVIEW"
    return "LIVE_READY"


def _build_payment_delivery_live_pilot_carrier(
    *,
    project_id: str,
    runtime_inputs: Mapping[str, Any],
    order_id: str,
    payment_id: str,
    delivery_id: str,
    opportunity_id: str,
    payment_gateway_record: Mapping[str, Any],
    charge_record: Mapping[str, Any],
    receipt_record: Mapping[str, Any],
    invoice_record: Mapping[str, Any],
    settlement_record: Mapping[str, Any],
    reconciliation_record: Mapping[str, Any],
    manual_refund_record: Mapping[str, Any],
    delivery_provider_record: Mapping[str, Any],
    delivery_artifact_record: Mapping[str, Any],
    delivery_version_lock_record: Mapping[str, Any],
    delivery_hash_record: Mapping[str, Any],
    delivery_audit_record: Mapping[str, Any],
    delivery_record: Mapping[str, Any],
    provider_summary: Mapping[str, Any],
    payment_provider_readiness: Mapping[str, Any],
    delivery_provider_readiness: Mapping[str, Any],
    audit_state: str,
    now: str,
) -> dict[str, Any]:
    live_payment_requested = _requested_flag(
        runtime_inputs,
        "live_payment_requested",
        "payment_live_pilot_requested",
        "payment_delivery_live_pilot_requested",
    )
    live_delivery_requested = _requested_flag(
        runtime_inputs,
        "live_delivery_requested",
        "delivery_live_pilot_requested",
        "payment_delivery_live_pilot_requested",
    )
    live_requested = live_payment_requested or live_delivery_requested
    pilot_scope = _live_pilot_scope(runtime_inputs, live_requested=live_requested)
    operator_action_audit_refs = _operator_action_audit_refs(runtime_inputs)
    sandbox_payment_pass_state = _sandbox_payment_pass_state(
        runtime_inputs,
        payment_gateway_record,
        charge_record,
    )
    payment_approval_state = _state_token(
        runtime_inputs.get("payment_approval_state")
        or runtime_inputs.get("live_payment_approval_state")
        or runtime_inputs.get("payment_live_pilot_approval_state"),
    )
    delivery_approval_state = _state_token(
        runtime_inputs.get("delivery_approval_state")
        or runtime_inputs.get("live_delivery_approval_state")
        or runtime_inputs.get("delivery_live_pilot_approval_state"),
    )
    finance_review_state = _state_token(
        runtime_inputs.get("finance_review_state")
        or runtime_inputs.get("finance_reconciliation_review_state")
        or runtime_inputs.get("payment_finance_review_state")
        or runtime_inputs.get("settlement_finance_review_state"),
    )
    download_auth_state = _state_token(
        runtime_inputs.get("download_auth_state")
        or runtime_inputs.get("customer_download_auth_state")
        or runtime_inputs.get("delivery_download_auth_state")
        or runtime_inputs.get("artifact_download_auth_state"),
    )
    callback_mismatch_state = _state_token(
        runtime_inputs.get("callback_mismatch_state")
        or runtime_inputs.get("payment_callback_mismatch_state"),
        default="NO_MISMATCH",
    )
    delivery_failure_state = _state_token(
        runtime_inputs.get("delivery_failure_state")
        or delivery_record.get("delivery_status")
        or delivery_provider_record.get("provider_execution_state"),
        default="NONE",
    )
    settlement_state = _state_token(settlement_record.get("settlement_state"), default="MISSING")
    reconciliation_state = _state_token(
        reconciliation_record.get("reconciliation_state"),
        default="MISSING",
    )
    artifact_version_locked = bool(delivery_version_lock_record.get("version_locked", False))
    payment_provider_suspended = _provider_is_suspended(payment_provider_readiness)
    delivery_provider_suspended = _provider_is_suspended(delivery_provider_readiness)
    delivery_failure = (
        delivery_failure_state in _DELIVERY_FAILURE_STATES
        or str(delivery_provider_record.get("provider_execution_state", "")).upper() in _DELIVERY_FAILURE_STATES
    )

    payment_blocked_reasons: list[str] = []
    delivery_blocked_reasons: list[str] = []
    payment_review_reasons: list[str] = []
    delivery_review_reasons: list[str] = []
    payment_suspension_reasons: list[str] = []
    delivery_suspension_reasons: list[str] = []

    if not live_payment_requested:
        payment_blocked_reasons.append("live_payment_not_requested")
    if not live_delivery_requested:
        delivery_blocked_reasons.append("live_delivery_not_requested")
    if not pilot_scope["small_sample"]:
        payment_blocked_reasons.append("pilot_scope_not_approved_small_sample")
        delivery_blocked_reasons.append("pilot_scope_not_approved_small_sample")
    if pilot_scope["requested_batch_execution_enabled"]:
        payment_blocked_reasons.append("batch_execution_requested_but_disabled")
        delivery_blocked_reasons.append("batch_execution_requested_but_disabled")
    if sandbox_payment_pass_state == "SUSPENDED":
        payment_suspension_reasons.append("sandbox_payment_pass_state=SUSPENDED")
    elif sandbox_payment_pass_state != "PASSED":
        payment_blocked_reasons.append(f"sandbox_payment_pass_state={sandbox_payment_pass_state}")
    if payment_approval_state not in _LIVE_APPROVED_STATES:
        payment_blocked_reasons.append("payment_approval_missing")
    if delivery_approval_state not in _LIVE_APPROVED_STATES:
        delivery_blocked_reasons.append("delivery_approval_missing")
    if finance_review_state not in _FINANCE_REVIEW_APPROVED_STATES:
        payment_blocked_reasons.append("finance_review_missing")
        delivery_blocked_reasons.append("finance_review_missing")
    if not operator_action_audit_refs:
        payment_blocked_reasons.append("operator_action_audit_missing")
        delivery_blocked_reasons.append("operator_action_audit_missing")
    if audit_state == "MISSING":
        payment_blocked_reasons.append("audit_ref_missing")
        delivery_blocked_reasons.append("audit_ref_missing")
    if payment_provider_suspended:
        payment_suspension_reasons.append("payment_provider_suspended_fail_closed")
    if delivery_provider_suspended:
        delivery_suspension_reasons.append("delivery_provider_suspended_fail_closed")
    if callback_mismatch_state in _CALLBACK_BLOCKING_STATES:
        payment_blocked_reasons.append(f"callback_mismatch_state={callback_mismatch_state}")
    elif callback_mismatch_state in _CALLBACK_REVIEW_STATES:
        payment_review_reasons.append(f"callback_mismatch_state={callback_mismatch_state}")
    if settlement_state not in {"RECORDED", "SETTLED", "MATCHED"}:
        payment_review_reasons.append(f"settlement_state={settlement_state}")
        delivery_review_reasons.append(f"settlement_state={settlement_state}")
    if reconciliation_state != "MATCHED":
        payment_review_reasons.append(f"reconciliation_state={reconciliation_state}")
        delivery_review_reasons.append(f"reconciliation_state={reconciliation_state}")
    if not artifact_version_locked:
        delivery_blocked_reasons.append("artifact_version_not_locked")
    if download_auth_state not in _DOWNLOAD_AUTH_APPROVED_STATES:
        delivery_blocked_reasons.append("download_auth_missing")
    if delivery_failure:
        delivery_suspension_reasons.append("delivery_failure_rollback_required")
    if payment_blocked_reasons or payment_suspension_reasons:
        delivery_blocked_reasons.append("payment_live_pilot_not_ready")
    elif payment_review_reasons:
        delivery_review_reasons.append("payment_live_pilot_review_required")

    payment_readiness_state = _pilot_readiness_state(
        suspension_reasons=payment_suspension_reasons,
        blocked_reasons=payment_blocked_reasons,
        review_reasons=payment_review_reasons,
    )
    delivery_readiness_state = _pilot_readiness_state(
        suspension_reasons=delivery_suspension_reasons,
        blocked_reasons=delivery_blocked_reasons,
        review_reasons=delivery_review_reasons,
    )
    live_payment_enabled = live_payment_requested and payment_readiness_state == "LIVE_READY"
    live_delivery_enabled = live_delivery_requested and delivery_readiness_state == "LIVE_READY"
    callback_record = {
        "charge_status_callback_sandbox_record": dict(charge_record),
        "callback_mismatch_state": callback_mismatch_state,
        "status_readback_state": charge_record.get("status_readback_state"),
        "callback_readback_state": charge_record.get("callback_readback_state"),
        "real_callback_received": False,
        "replayable": bool(charge_record.get("replayable", False)),
    }
    rollback_readiness = {
        "state": "ROLLBACK_REQUIRED" if delivery_failure else "READY_FOR_MANUAL_REVIEW",
        "rollback_required": delivery_failure,
        "manual_approval_required": True,
        "audit_required": True,
        "rollback_execution_enabled": False,
        "destructive_rollback_enabled": False,
        "external_provider_rollback_enabled": False,
        "replayable": True,
        "blocked_reasons": ["rollback_execution_enabled=false"],
    }
    payment_provider_result = _provider_result_readback(
        family="payment_collection",
        provider_readiness=payment_provider_readiness,
        readiness_state=payment_readiness_state,
        live_enabled=live_payment_enabled,
        records={
            "payment_gateway_sandbox_record": dict(payment_gateway_record),
            "charge_status_callback_sandbox_record": dict(charge_record),
            "receipt_record": dict(receipt_record),
            "invoice_record": dict(invoice_record),
            "settlement_record": dict(settlement_record),
            "finance_reconciliation_record": dict(reconciliation_record),
        },
    )
    delivery_provider_result = _provider_result_readback(
        family="leadpack_page_delivery",
        provider_readiness=delivery_provider_readiness,
        readiness_state=delivery_readiness_state,
        live_enabled=live_delivery_enabled,
        records={
            "delivery_provider_sandbox_record": dict(delivery_provider_record),
            "delivery_artifact_download_record": dict(delivery_artifact_record),
            "delivery_version_lock_record": dict(delivery_version_lock_record),
            "delivery_hash_record": dict(delivery_hash_record),
            "delivery_audit_record": dict(delivery_audit_record),
        },
    )
    blocked_reasons = _clean_list(payment_blocked_reasons + delivery_blocked_reasons)
    review_reasons = _clean_list(payment_review_reasons + delivery_review_reasons)
    suspension_reasons = _clean_list(payment_suspension_reasons + delivery_suspension_reasons)
    overall_state = _pilot_readiness_state(
        suspension_reasons=suspension_reasons,
        blocked_reasons=blocked_reasons,
        review_reasons=review_reasons,
    )

    return {
        "pilot_id": str(runtime_inputs.get("payment_delivery_live_pilot_id") or build_id("S9PILOT", project_id, order_id)),
        "order_id": order_id,
        "payment_id": payment_id,
        "delivery_id": delivery_id,
        "opportunity_id": opportunity_id,
        "pilot_scope": "small_sample",
        "approved_sample_size": pilot_scope["approved_sample_size"],
        "requested_sample_size": pilot_scope["requested_sample_size"],
        "batch_execution_enabled": False,
        "bulk_execution_enabled": False,
        "requested_batch_execution_enabled": pilot_scope["requested_batch_execution_enabled"],
        "provider_adapter_readiness_summary": dict(provider_summary),
        "payment_provider_adapter_readiness": dict(payment_provider_readiness),
        "delivery_provider_adapter_readiness": dict(delivery_provider_readiness),
        "sandbox_payment_pass_state": sandbox_payment_pass_state,
        "payment_approval_state": payment_approval_state,
        "delivery_approval_state": delivery_approval_state,
        "operator_action_audit_refs": operator_action_audit_refs,
        "finance_review_state": finance_review_state,
        "download_auth_state": download_auth_state,
        "payment_live_pilot_readiness_state": payment_readiness_state,
        "delivery_live_pilot_readiness_state": delivery_readiness_state,
        "overall_live_pilot_readiness_state": overall_state,
        "live_payment_requested": live_payment_requested,
        "live_delivery_requested": live_delivery_requested,
        "live_payment_enabled": live_payment_enabled,
        "live_delivery_enabled": live_delivery_enabled,
        "real_payment_capture_attempted": False,
        "real_charge_attempted": False,
        "real_delivery_fulfillment_attempted": False,
        "real_customer_download_attempted": False,
        "real_refund_attempted": False,
        "automated_refund_program": {
            "present": False,
            "enabled": False,
            "state": "ABSENT_BLOCKED",
        },
        "payment_provider_result_readback": payment_provider_result,
        "delivery_provider_result_readback": delivery_provider_result,
        "callback_record": callback_record,
        "callback_mismatch_state": callback_mismatch_state,
        "receipt_record": dict(receipt_record),
        "invoice_record": dict(invoice_record),
        "delivery_unlock_record": {
            "delivery_id": delivery_id,
            "approval_state": delivery_approval_state,
            "unlock_state": "APPROVED_FOR_LIVE_PILOT" if live_delivery_enabled else delivery_readiness_state,
            "customer_visible_unlock_enabled": live_delivery_enabled,
            "real_delivery_fulfillment_attempted": False,
            "external_delivery_enabled": False,
            "audit_refs": operator_action_audit_refs,
        },
        "delivery_artifact_version_lock": dict(delivery_version_lock_record),
        "delivery_hash_record": dict(delivery_hash_record),
        "customer_download_audit_record": {
            "delivery_artifact_download_record": dict(delivery_artifact_record),
            "delivery_audit_record": dict(delivery_audit_record),
            "download_auth_state": download_auth_state,
            "customer_download_authorized": download_auth_state in _DOWNLOAD_AUTH_APPROVED_STATES,
            "customer_download_enabled": live_delivery_enabled,
            "real_customer_download_attempted": False,
            "audit_refs": operator_action_audit_refs,
            "replayable": bool(delivery_artifact_record.get("replayable", False))
            and bool(delivery_audit_record.get("replayable", False)),
        },
        "settlement_record": dict(settlement_record),
        "finance_reconciliation_record": dict(reconciliation_record),
        "settlement_reconciliation_readback": {
            "settlement_state": settlement_state,
            "reconciliation_state": reconciliation_state,
            "readiness_state": "LIVE_READY"
            if settlement_state in {"RECORDED", "SETTLED", "MATCHED"} and reconciliation_state == "MATCHED"
            else "REVIEW",
            "real_finance_posting_enabled": False,
            "replayable": bool(settlement_record.get("replayable", False))
            and bool(reconciliation_record.get("replayable", False)),
        },
        "rollback_readiness": rollback_readiness,
        "manual_refund_exception_record": dict(manual_refund_record),
        "manual_refund_governance": {
            "manual_refund_exception_state": manual_refund_record.get("manual_refund_exception_state"),
            "manual_approval_state": dict(manual_refund_record.get("approval_record", {})).get("approval_state"),
            "manual_audit_state": dict(manual_refund_record.get("audit_record", {})).get("audit_state"),
            "governed_review_required": bool(
                manual_refund_record.get("manual_refund_exception_required", False)
            ),
            "automatic_approval_enabled": False,
            "automated_refund_enabled": False,
            "real_refund_attempted": False,
        },
        "suspension_state": {
            "state": "SUSPENDED" if suspension_reasons else "ACTIVE",
            "reasons": suspension_reasons,
            "manual_resume_required": bool(suspension_reasons),
            "payment_provider_suspended": payment_provider_suspended,
            "delivery_provider_suspended": delivery_provider_suspended,
            "delivery_failure_rollback_required": delivery_failure,
        },
        "replay_state": {
            "state": "REPLAYABLE",
            "repository_backed": True,
            "live_pilot_record_replayable": True,
            "payment_provider_result_readback_replayable": True,
            "delivery_provider_result_readback_replayable": True,
            "callback_record_replayable": True,
            "receipt_invoice_replayable": True,
            "settlement_reconciliation_replayable": True,
            "delivery_artifact_readback_replayable": True,
            "manual_refund_exception_replayable": True,
            "real_provider_call_executed": False,
        },
        "blocked_reasons": blocked_reasons,
        "review_reasons": review_reasons,
        "suspension_reasons": suspension_reasons,
        "decided_at": now,
    }


def _build_approved_payment_delivery_execution_carrier(
    *,
    project_id: str,
    runtime_inputs: Mapping[str, Any],
    order_id: str,
    payment_id: str,
    delivery_id: str,
    opportunity_id: str,
    live_pilot_carrier: Mapping[str, Any],
    payment_provider_readiness: Mapping[str, Any],
    delivery_provider_readiness: Mapping[str, Any],
    now: str,
) -> dict[str, Any]:
    payment_requested = _requested_flag(
        runtime_inputs,
        "approved_payment_delivery_execution_requested",
        "approved_payment_capture_requested",
        "approved_charge_execution_requested",
    )
    delivery_requested = _requested_flag(
        runtime_inputs,
        "approved_payment_delivery_execution_requested",
        "approved_delivery_fulfillment_requested",
        "approved_customer_download_requested",
    )
    requested = payment_requested or delivery_requested
    payment_provider_suspended = _provider_is_suspended(payment_provider_readiness)
    delivery_provider_suspended = _provider_is_suspended(delivery_provider_readiness)
    settlement_readback = dict(live_pilot_carrier.get("settlement_reconciliation_readback", {}))
    callback_record = dict(live_pilot_carrier.get("callback_record", {}))
    download_audit = dict(live_pilot_carrier.get("customer_download_audit_record", {}))
    rollback_readiness = dict(live_pilot_carrier.get("rollback_readiness", {}))
    manual_refund_record = dict(live_pilot_carrier.get(MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY, {}))
    manual_refund_governance = dict(live_pilot_carrier.get("manual_refund_governance", {}))

    payment_blocked: list[str] = []
    delivery_blocked: list[str] = []
    payment_suspended: list[str] = []
    delivery_suspended: list[str] = []
    if payment_requested and live_pilot_carrier.get("payment_live_pilot_readiness_state") != "LIVE_READY":
        payment_blocked.append("payment_live_pilot_not_ready")
    if delivery_requested and live_pilot_carrier.get("delivery_live_pilot_readiness_state") != "LIVE_READY":
        delivery_blocked.append("delivery_live_pilot_not_ready")
    if payment_requested and payment_provider_suspended:
        payment_suspended.append("payment_provider_suspended_fail_closed")
    if delivery_requested and delivery_provider_suspended:
        delivery_suspended.append("delivery_provider_suspended_fail_closed")
    if payment_requested and str(callback_record.get("callback_mismatch_state", "NO_MISMATCH")) != "NO_MISMATCH":
        payment_blocked.append("callback_verification_not_clear")
    if payment_requested and settlement_readback.get("readiness_state") != "LIVE_READY":
        payment_blocked.append("settlement_reconciliation_not_matched")
    if delivery_requested and not dict(live_pilot_carrier.get("delivery_artifact_version_lock", {})).get(
        "version_locked",
        False,
    ):
        delivery_blocked.append("artifact_version_not_locked")
    if delivery_requested and not download_audit.get("customer_download_authorized", False):
        delivery_blocked.append("download_auth_missing")
    if delivery_requested and not rollback_readiness:
        delivery_blocked.append("rollback_readiness_missing")

    payment_enabled = bool(payment_requested and not payment_blocked and not payment_suspended)
    delivery_enabled = bool(delivery_requested and not delivery_blocked and not delivery_suspended)
    blocked_reasons = _clean_list(payment_blocked + delivery_blocked)
    suspension_reasons = _clean_list(payment_suspended + delivery_suspended)
    not_requested_reasons = _clean_list(
        ([] if payment_requested else ["approved_payment_execution_not_requested"])
        + ([] if delivery_requested else ["approved_delivery_execution_not_requested"])
    )
    request_state = (
        "NOT_REQUESTED"
        if not requested
        else "SUSPENDED"
        if suspension_reasons
        else "BLOCKED"
        if blocked_reasons
        else "APPROVED"
    )
    provider_execution_state = (
        "NOT_REQUESTED"
        if not requested
        else "SUSPENDED"
        if suspension_reasons
        else "BLOCKED"
        if blocked_reasons
        else "APPROVED_CONTROLLED_FAKE_PROVIDER_RECORDED"
    )
    controlled_execution_executed = bool(payment_enabled or delivery_enabled)
    payment_capture_record = {
        "payment_capture_execution_id": build_id("APAYCAP", project_id, payment_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "approved_payment_capture_requested": payment_requested,
        "approved_payment_capture_enabled": payment_enabled,
        "approved_charge_execution_enabled": payment_enabled,
        "controlled_fake_payment_capture_recorded": payment_enabled,
        "controlled_fake_charge_recorded": payment_enabled,
        "provider_result_state": "CONTROLLED_FAKE_CAPTURE_RECORDED" if payment_enabled else provider_execution_state,
        "provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
        "provider_family": "payment_collection",
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "provider_call_executed": False,
        "real_payment_capture_attempted": False,
        "real_charge_attempted": False,
        "live_fallback_allowed": False,
        "callback_verification": callback_record,
        "receipt_record": dict(live_pilot_carrier.get("receipt_record", {})),
        "invoice_record": dict(live_pilot_carrier.get("invoice_record", {})),
        "settlement_reconciliation_readback": settlement_readback,
        "audit_refs": list(live_pilot_carrier.get("operator_action_audit_refs", [])),
        "recorded_at": now,
    }
    delivery_fulfillment_record = {
        "delivery_fulfillment_execution_id": build_id("ADELIVER", project_id, delivery_id),
        "delivery_id": delivery_id,
        "order_id": order_id,
        "payment_id": payment_id,
        "approved_delivery_fulfillment_requested": delivery_requested,
        "approved_delivery_fulfillment_enabled": delivery_enabled,
        "approved_customer_download_enabled": delivery_enabled
        and bool(download_audit.get("customer_download_authorized", False)),
        "controlled_fake_delivery_fulfillment_recorded": delivery_enabled,
        "controlled_fake_customer_download_recorded": delivery_enabled
        and bool(download_audit.get("customer_download_authorized", False)),
        "provider_result_state": "CONTROLLED_FAKE_DELIVERY_RECORDED" if delivery_enabled else provider_execution_state,
        "provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
        "provider_family": "leadpack_page_delivery",
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "provider_call_executed": False,
        "real_delivery_fulfillment_attempted": False,
        "real_customer_download_attempted": False,
        "live_fallback_allowed": False,
        "delivery_artifact_version_lock": dict(live_pilot_carrier.get("delivery_artifact_version_lock", {})),
        "delivery_hash_record": dict(live_pilot_carrier.get("delivery_hash_record", {})),
        "customer_download_audit_record": download_audit,
        "rollback_readiness": rollback_readiness,
        "audit_refs": list(live_pilot_carrier.get("operator_action_audit_refs", [])),
        "recorded_at": now,
    }
    timeline = [
        {
            "step": "provider_config_and_reliability_checked",
            "state": "SUSPENDED" if payment_provider_suspended or delivery_provider_suspended else "SATISFIED",
            "recorded_at": now,
        },
        {
            "step": "sandbox_payment_and_approval_gates_checked",
            "state": "SATISFIED" if live_pilot_carrier.get("overall_live_pilot_readiness_state") == "LIVE_READY" else "BLOCKED",
            "recorded_at": now,
        },
        {
            "step": "controlled_fake_provider_execution_recorded",
            "state": "RECORDED" if controlled_execution_executed else provider_execution_state,
            "recorded_at": now,
        },
    ]
    return {
        "execution_id": build_id(
            "APAYDELIV",
            f"{project_id}:{order_id}:{payment_id}:{delivery_id}",
        ),
        "order_id": order_id,
        "payment_id": payment_id,
        "delivery_id": delivery_id,
        "opportunity_id": opportunity_id,
        "approved_payment_delivery_execution_requested": requested,
        "approved_payment_execution_requested": payment_requested,
        "approved_delivery_execution_requested": delivery_requested,
        "approved_payment_delivery_execution_enabled": bool(payment_enabled and delivery_enabled),
        "approved_payment_capture_enabled": payment_enabled,
        "approved_charge_execution_enabled": payment_enabled,
        "approved_delivery_fulfillment_enabled": delivery_enabled,
        "approved_customer_download_enabled": bool(delivery_fulfillment_record["approved_customer_download_enabled"]),
        "execution_request_state": request_state,
        "provider_execution_state": provider_execution_state,
        "controlled_provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
        "controlled_provider_execution_executed": controlled_execution_executed,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "provider_call_executed": False,
        "real_payment_capture_attempted": False,
        "real_charge_attempted": False,
        "real_delivery_fulfillment_attempted": False,
        "real_customer_download_attempted": False,
        "real_refund_attempted": False,
        "automated_refund_program": {
            "present": False,
            "enabled": False,
            "state": "ABSENT_BLOCKED",
        },
        "payment_provider_adapter_readiness": dict(payment_provider_readiness),
        "delivery_provider_adapter_readiness": dict(delivery_provider_readiness),
        "payment_capture_execution_record": payment_capture_record,
        "delivery_fulfillment_execution_record": delivery_fulfillment_record,
        "callback_verification": callback_record,
        "settlement_reconciliation_readback": settlement_readback,
        "manual_refund_exception_record": manual_refund_record,
        "manual_refund_governance": {
            **manual_refund_governance,
            "automated_refund_enabled": False,
            "real_refund_attempted": False,
        },
        "execution_timeline": timeline,
        "blocked_reasons": blocked_reasons,
        "suspension_reasons": suspension_reasons,
        "not_requested_reasons": not_requested_reasons,
        "replay_state": {
            "state": "REPLAYABLE",
            "repository_backed": True,
            "controlled_fake_provider_execution_replayable": True,
            "real_provider_call_executed": False,
        },
        "decided_at": now,
    }


def _provider_snapshot(
    provider_readiness: Mapping[str, Any],
    *,
    family: str,
) -> dict[str, Any]:
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    return {
        "provider_family": family,
        "provider_id": provider_readiness.get("provider_id"),
        "provider_mode": provider_readiness.get("mode"),
        "sandbox_enabled": bool(provider_readiness.get("sandbox_enabled", True)),
        "dry_run_enabled": bool(provider_readiness.get("dry_run_enabled", True)),
        "readback_only": bool(provider_readiness.get("readback_only", True)),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": _provider_is_suspended(provider_readiness),
        "provider_circuit_breaker_state": provider_circuit_breaker.get("state"),
        "provider_failure_class": provider_failure_taxonomy.get("failure_class"),
        "provider_status_readback": provider_status_readback,
        "provider_status_replayable": bool(provider_status_readback.get("replayable", True)),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
        "blocked_reasons": _provider_blocked_reasons(provider_readiness),
    }


def _payment_collection_state(payment_record: Mapping[str, Any]) -> str:
    payment_status = str(payment_record.get("payment_status", "NOT_STARTED"))
    refund_state = str(payment_record.get("refund_state", "NOT_REQUESTED"))
    if refund_state not in {"NOT_REQUESTED", "NO_EXCEPTION"}:
        return "REFUND_MANUAL_EXCEPTION_REVIEW"
    if payment_status == "PAID":
        return "MANUAL_COLLECTION_RECORDED"
    if payment_status in {"PENDING_PAYMENT", "NOT_STARTED"}:
        return "PENDING_COLLECTION"
    if payment_status in {"PAYMENT_EXCEPTION", "REFUND_PENDING"}:
        return "COLLECTION_EXCEPTION_REVIEW"
    return "INTERNAL_COLLECTION_REVIEW"


def _manual_settlement_state(payment_record: Mapping[str, Any], inputs: Mapping[str, Any]) -> str:
    explicit = inputs.get("manual_settlement_state")
    if explicit not in (None, ""):
        return str(explicit)
    if _has_value(inputs.get("manual_settlement_note_optional")):
        return "RECORDED"
    if payment_record.get("payment_proof_state") != "NOT_PROVIDED":
        return "RECORDED"
    if payment_record.get("paid_at_optional") != "NOT_PAID":
        return "RECORDED"
    if payment_record.get("payment_status") == "PAID":
        return "REQUIRES_PROOF_REVIEW"
    return "NOT_RECORDED"


def _delivery_fulfillment_state(delivery_record: Mapping[str, Any]) -> str:
    delivery_status = str(delivery_record.get("delivery_status", "NOT_READY"))
    if delivery_status in {"DELIVERED", "ACKNOWLEDGED"}:
        return "INTERNAL_DELIVERY_RECORDED"
    if delivery_status in {"RELEASE_BLOCKED", "FAILED", "CANCELLED"}:
        return "FULFILLMENT_BLOCKED"
    if delivery_status in {"READY", "ACK_PENDING"}:
        return "READY_FOR_INTERNAL_FULFILLMENT"
    return "NOT_READY"


def attach_order_lifecycle_record(
    order_payload: dict[str, Any],
    *,
    runtime_inputs: Mapping[str, Any],
    now: str,
) -> None:
    project_id = str(order_payload.get("project_id") or "UNKNOWN")
    order_id = str(order_payload.get("order_id") or build_id("ORDER", project_id))
    order_payload["order_lifecycle_record"] = {
        "order_lifecycle_record_id": build_id("OLIFE", project_id, order_id),
        "order_id": order_id,
        "commercial_status": order_payload.get("commercial_status"),
        "order_status": order_payload.get("order_status"),
        "approval_state": order_payload.get("approval_state"),
        "lifecycle_state": "ORDER_RECORDED_FOR_INTERNAL_GOVERNED_EXECUTION",
        "settlement_required": True,
        "delivery_requires_payment_readback": True,
        "real_payment_enabled": False,
        "real_delivery_enabled": False,
        "real_refund_enabled": False,
        "automated_refund_enabled": False,
        "governed_execution_mode": order_payload.get("governed_execution_mode"),
        "source_touch_record_id": order_payload.get("touch_record_id"),
        "source_opportunity_id": order_payload.get("opportunity_id"),
        "operator_action_required": runtime_inputs.get("approval_state") not in {"APPROVED", "NOT_REQUIRED"},
        "replayable": True,
        "audit_record_id": build_id("OLIFEAUDIT", project_id, order_id),
        "created_at": now,
    }


def attach_payment_sandbox_records(
    payment_payload: dict[str, Any],
    *,
    runtime_inputs: Mapping[str, Any],
    provider_adapter_readiness_summary: Mapping[str, Any] | None,
    now: str,
) -> None:
    provider_readiness = provider_readiness_for_family(
        provider_adapter_readiness_summary,
        "payment_collection",
    )
    project_id = str(payment_payload.get("project_id") or "UNKNOWN")
    payment_id = str(payment_payload.get("payment_id") or build_id("PAY", project_id))
    order_id = str(payment_payload.get("order_id") or "UNKNOWN")
    sandbox_state = _provider_sandbox_state(provider_readiness)
    provider_snapshot = _provider_snapshot(provider_readiness, family="payment_collection")
    payment_status = str(payment_payload.get("payment_status", "NOT_STARTED"))
    refund_state = str(payment_payload.get("refund_state", "NOT_REQUESTED"))
    manual_refund_required = refund_state not in {"NOT_REQUESTED", "NO_EXCEPTION"}
    manual_settlement_state = _manual_settlement_state(payment_payload, runtime_inputs)

    gateway_record = {
        "payment_gateway_sandbox_record_id": build_id("PGSANDBOX", project_id, payment_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "gateway_execution_state": sandbox_state,
        "adapter_scope": "SANDBOX_DRY_RUN_READBACK_ONLY",
        "gateway_provider": provider_snapshot,
        "gateway_request_recorded": True,
        "gateway_status_recorded": True,
        "gateway_callback_recorded": True,
        "real_payment_gateway_enabled": False,
        "payment_capture_enabled": False,
        "payment_capture_attempted": False,
        "real_charge_attempted": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
        "replayable": True,
        "audit_record_id": build_id("PGAUDIT", project_id, payment_id),
        "created_at": now,
        "blocked_reasons": _provider_blocked_reasons(
            provider_readiness,
            "real_payment_gateway_enabled=false",
            "payment_capture_attempted=false",
        ),
    }
    charge_status_callback_record = {
        "charge_status_callback_sandbox_record_id": build_id("CHARGESANDBOX", project_id, payment_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "charge_record_id": build_id("CHARGE", project_id, payment_id),
        "status_record_id": build_id("CHARGESTATUS", project_id, payment_id),
        "callback_record_id": build_id("CHARGECB", project_id, payment_id),
        "sandbox_execution_state": sandbox_state,
        "charge_requested": _requested_flag(runtime_inputs, "real_charge_requested", "charge_execution_requested"),
        "status_readback_state": "REPLAYABLE",
        "callback_readback_state": "REPLAYABLE",
        "payment_status": payment_status,
        "charge_capture_enabled": False,
        "payment_capture_enabled": False,
        "real_charge_attempted": False,
        "real_payment_gateway_enabled": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
        "replayable": True,
        "audit_record_id": build_id("CHARGEAUDIT", project_id, payment_id),
        "created_at": now,
    }
    receipt_record = {
        "receipt_record_id": build_id("RECEIPT", project_id, payment_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "receipt_state": "SANDBOX_RECEIPT_RECORDED" if payment_status == "PAID" else "PENDING_PAYMENT",
        "payment_status": payment_status,
        "amount_band": payment_payload.get("amount_band"),
        "real_receipt_issued": False,
        "sandbox_receipt_readback_only": True,
        "replayable": True,
        "audit_record_id": build_id("RECEIPTAUDIT", project_id, payment_id),
        "created_at": now,
    }
    invoice_record = {
        "invoice_record_id": build_id("INVOICE", project_id, order_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "invoice_state": "SANDBOX_INVOICE_DRAFT_RECORDED",
        "amount_band": payment_payload.get("amount_band"),
        "real_invoice_issued": False,
        "sandbox_invoice_readback_only": True,
        "replayable": True,
        "audit_record_id": build_id("INVOICEAUDIT", project_id, order_id),
        "created_at": now,
    }
    settlement_record = {
        "settlement_record_id": build_id("SETTLEMENT", project_id, payment_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "settlement_state": manual_settlement_state,
        "manual_settlement_state": manual_settlement_state,
        "manual_settlement_note_optional": runtime_inputs.get("manual_settlement_note_optional"),
        "settlement_readback_only": True,
        "real_settlement_execution_enabled": False,
        "replayable": True,
        "audit_record_id": build_id("SETTLEMENTAUDIT", project_id, payment_id),
        "created_at": now,
    }
    finance_reconciliation_record = {
        "finance_reconciliation_record_id": build_id("FINRECON", project_id, payment_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "reconciliation_state": (
            "MATCHED"
            if payment_payload.get("payer_match_state") == "MATCHED"
            and payment_payload.get("amount_match_state") == "MATCHED"
            else "REVIEW_REQUIRED"
        ),
        "payer_match_state": payment_payload.get("payer_match_state"),
        "amount_match_state": payment_payload.get("amount_match_state"),
        "payment_status": payment_status,
        "refund_state": refund_state,
        "real_finance_posting_enabled": False,
        "sandbox_reconciliation_readback_only": True,
        "replayable": True,
        "audit_record_id": build_id("FINRECONAUDIT", project_id, payment_id),
        "created_at": now,
    }
    manual_refund_exception_record = {
        "manual_refund_exception_record_id": build_id("MANUALREFUND", project_id, payment_id),
        "payment_id": payment_id,
        "order_id": order_id,
        "refund_state": refund_state,
        "manual_refund_exception_required": manual_refund_required,
        "manual_refund_exception_state": "MANUAL_REVIEW_REQUIRED" if manual_refund_required else "NOT_REQUESTED",
        "approval_record": {
            "approval_record_id": build_id("MANUALREFUNDAPPROVAL", project_id, payment_id),
            "approval_required": manual_refund_required,
            "approval_state": "PENDING_MANUAL_APPROVAL" if manual_refund_required else "NOT_REQUIRED",
            "automatic_approval_enabled": False,
        },
        "audit_record": {
            "audit_record_id": build_id("MANUALREFUNDAUDIT", project_id, payment_id),
            "audit_state": "RECORDED",
            "audit_required": True,
            "replayable": True,
        },
        "automated_refund_program": {
            "present": False,
            "enabled": False,
            "state": "ABSENT_BLOCKED",
        },
        "automated_refund_enabled": False,
        "real_refund_attempted": False,
        "real_refund_enabled": False,
        "operator_can_record_manual_exception": True,
        "operator_can_execute_automated_refund": False,
        "blocked_reasons": [
            "automated_refund_program_absent_blocked",
            "real_refund_attempted=false",
        ],
        "created_at": now,
    }

    payment_payload["payment_gateway_sandbox_record"] = gateway_record
    payment_payload["charge_status_callback_sandbox_record"] = charge_status_callback_record
    payment_payload["receipt_record"] = receipt_record
    payment_payload["invoice_record"] = invoice_record
    payment_payload["settlement_record"] = settlement_record
    payment_payload["finance_reconciliation_record"] = finance_reconciliation_record
    payment_payload[MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY] = manual_refund_exception_record
    payment_payload[PAYMENT_SANDBOX_RECORDS_INPUT_KEY] = {
        "payment_gateway_sandbox_record": gateway_record,
        "charge_status_callback_sandbox_record": charge_status_callback_record,
        "receipt_record": receipt_record,
        "invoice_record": invoice_record,
        "settlement_record": settlement_record,
        "finance_reconciliation_record": finance_reconciliation_record,
        MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY: manual_refund_exception_record,
    }


def attach_delivery_sandbox_records(
    delivery_payload: dict[str, Any],
    *,
    provider_adapter_readiness_summary: Mapping[str, Any] | None,
    now: str,
) -> None:
    provider_readiness = provider_readiness_for_family(
        provider_adapter_readiness_summary,
        "leadpack_page_delivery",
    )
    project_id = str(delivery_payload.get("project_id") or "UNKNOWN")
    delivery_id = str(delivery_payload.get("delivery_id") or build_id("DELIVERY", project_id))
    order_id = str(delivery_payload.get("order_id") or "UNKNOWN")
    payment_id = str(delivery_payload.get("payment_id_optional") or "UNKNOWN")
    sandbox_state = _provider_sandbox_state(provider_readiness)
    provider_snapshot = _provider_snapshot(provider_readiness, family="leadpack_page_delivery")
    version_lock_id = build_id("DVERLOCK", project_id, delivery_id)
    artifact_id = build_id("DARTIFACT", project_id, delivery_id)
    download_record_id = build_id("DDOWNLOAD", project_id, delivery_id)
    version_token = str(delivery_payload.get("delivery_version_optional") or version_lock_id)
    delivery_hash = _hash_payload(
        {
            "delivery_id": delivery_id,
            "order_id": order_id,
            "payment_id": payment_id,
            "artifact_id": artifact_id,
            "version": version_token,
        }
    )

    provider_record = {
        "delivery_provider_sandbox_record_id": build_id("DPROVIDERSANDBOX", project_id, delivery_id),
        "delivery_id": delivery_id,
        "order_id": order_id,
        "payment_id": payment_id,
        "provider_execution_state": sandbox_state,
        "adapter_scope": "SANDBOX_DRY_RUN_READBACK_ONLY",
        "delivery_provider": provider_snapshot,
        "real_delivery_fulfillment_enabled": False,
        "real_delivery_fulfillment_attempted": False,
        "external_delivery_enabled": False,
        "customer_visible_delivery_enabled": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
        "replayable": True,
        "audit_record_id": build_id("DPROVIDERAUDIT", project_id, delivery_id),
        "created_at": now,
        "blocked_reasons": _provider_blocked_reasons(
            provider_readiness,
            "real_delivery_fulfillment_attempted=false",
            "external_delivery_enabled=false",
        ),
    }
    artifact_download_record = {
        "delivery_artifact_download_record_id": build_id("DARTDOWNLOAD", project_id, delivery_id),
        "delivery_id": delivery_id,
        "order_id": order_id,
        "payment_id": payment_id,
        "artifact_id": artifact_id,
        "download_record_id": download_record_id,
        "artifact_state": "SANDBOX_ARTIFACT_RECORDED",
        "download_state": sandbox_state,
        "download_token_state": "SANDBOX_PLACEHOLDER",
        "real_download_enabled": False,
        "external_download_enabled": False,
        "customer_visible_download_enabled": False,
        "replayable": True,
        "audit_record_id": build_id("DDOWNLOADAUDIT", project_id, delivery_id),
        "created_at": now,
    }
    version_lock_record = {
        "delivery_version_lock_id": version_lock_id,
        "delivery_id": delivery_id,
        "artifact_id": artifact_id,
        "version_token": version_token,
        "version_locked": True,
        "lock_state": "LOCKED_FOR_SANDBOX_READBACK",
        "real_delivery_unlock_enabled": False,
        "replayable": True,
        "audit_record_id": build_id("DVERLOCKAUDIT", project_id, delivery_id),
        "created_at": now,
    }
    hash_record = {
        "delivery_hash_record_id": build_id("DHASH", project_id, delivery_id),
        "delivery_id": delivery_id,
        "artifact_id": artifact_id,
        "delivery_hash": delivery_hash,
        "hash_algorithm": "sha256",
        "hash_scope": "sandbox_delivery_artifact_version_lock",
        "replayable": True,
        "audit_record_id": build_id("DHASHAUDIT", project_id, delivery_id),
        "created_at": now,
    }
    audit_record = {
        "delivery_audit_record_id": build_id("DAUDIT", project_id, delivery_id),
        "delivery_id": delivery_id,
        "order_id": order_id,
        "payment_id": payment_id,
        "audit_state": "RECORDED",
        "delivery_status": delivery_payload.get("delivery_status"),
        "provider_execution_state": sandbox_state,
        "real_delivery_fulfillment_enabled": False,
        "real_delivery_fulfillment_attempted": False,
        "external_delivery_enabled": False,
        "customer_visible_delivery_enabled": False,
        "provider_adapter_suspended": _provider_is_suspended(provider_readiness),
        "provider_circuit_breaker_state": dict(provider_readiness.get("provider_circuit_breaker", {})).get("state"),
        "replayable": True,
        "created_at": now,
    }

    delivery_payload["delivery_provider_sandbox_record"] = provider_record
    delivery_payload["delivery_artifact_download_record"] = artifact_download_record
    delivery_payload["delivery_version_lock_record"] = version_lock_record
    delivery_payload["delivery_hash_record"] = hash_record
    delivery_payload[DELIVERY_SANDBOX_RECORDS_INPUT_KEY] = {
        "delivery_provider_sandbox_record": provider_record,
        "delivery_artifact_download_record": artifact_download_record,
        "delivery_version_lock_record": version_lock_record,
        "delivery_hash_record": hash_record,
        "delivery_audit_record": audit_record,
    }


def _approval_audit_state(
    *,
    approval_state: str,
    audit_trail_present: bool,
    order_record: Mapping[str, Any],
    payment_record: Mapping[str, Any],
    delivery_record: Mapping[str, Any],
) -> tuple[str, str]:
    record_decisions = {
        str(order_record.get("governance_decision_state", "ALLOW")),
        str(payment_record.get("governance_decision_state", "ALLOW")),
        str(delivery_record.get("governance_decision_state", "ALLOW")),
        str(order_record.get("semantic_decision_state", "ALLOW")),
        str(payment_record.get("semantic_decision_state", "ALLOW")),
        str(delivery_record.get("semantic_decision_state", "ALLOW")),
    }
    if "BLOCK" in record_decisions:
        return "BLOCKED", "PRESENT" if audit_trail_present else "MISSING"
    if approval_state not in {"APPROVED", "NOT_REQUIRED"} or "REVIEW" in record_decisions:
        return "REVIEW_REQUIRED", "PRESENT" if audit_trail_present else "MISSING"
    return "SATISFIED_FOR_INTERNAL_LEDGER", "PRESENT" if audit_trail_present else "MISSING"


def build_stage9_execution_ledger_readiness_summary(ledger: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(ledger.get("blocked_reasons")))
    provider_readiness = dict(ledger.get("provider_adapter_readiness", {}))
    delivery_provider_readiness = dict(ledger.get("delivery_provider_adapter_readiness", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    payment_gateway_record = dict(ledger.get("payment_gateway_sandbox_record", {}))
    charge_record = dict(ledger.get("charge_status_callback_sandbox_record", {}))
    delivery_provider_record = dict(ledger.get("delivery_provider_sandbox_record", {}))
    delivery_artifact_record = dict(ledger.get("delivery_artifact_download_record", {}))
    settlement_record = dict(ledger.get("settlement_record", {}))
    reconciliation_record = dict(ledger.get("finance_reconciliation_record", {}))
    manual_refund_record = dict(ledger.get(MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY, {}))
    live_pilot_carrier = dict(ledger.get(PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY, {}))
    approved_execution_carrier = dict(
        ledger.get(
            APPROVED_PAYMENT_DELIVERY_EXECUTION_INPUT_KEY,
            live_pilot_carrier.get("approved_payment_delivery_execution_summary", {}),
        )
        or {}
    )
    return {
        "execution_ledger_id": ledger.get("execution_ledger_id"),
        "order_execution_id": ledger.get("order_execution_id"),
        "payment_execution_id": ledger.get("payment_execution_id"),
        "delivery_execution_id": ledger.get("delivery_execution_id"),
        "governed_execution_mode": ledger.get("governed_execution_mode", "INTERNAL_GOVERNED"),
        "readback_ready": bool(ledger.get("execution_ledger_id")),
        "owner_operable": True,
        "payment_recording_enabled": True,
        "delivery_recording_enabled": True,
        "manual_settlement_enabled": True,
        "refund_manual_exception_enabled": True,
        "ready_for_real_payment_gateway": False,
        "ready_for_real_charge": False,
        "ready_for_real_refund": False,
        "automated_refund_enabled": False,
        "payment_collection_state": ledger.get("payment_collection_state"),
        "delivery_fulfillment_state": ledger.get("delivery_fulfillment_state"),
        "manual_settlement_state": ledger.get("manual_settlement_state"),
        "refund_execution_state": ledger.get("refund_execution_state"),
        "approval_state": ledger.get("approval_state"),
        "audit_state": ledger.get("audit_state"),
        "blocked_reason_count": len(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "provider_adapter_config_source": ledger.get("provider_adapter_config_source"),
        "provider_adapter_mode": ledger.get("provider_adapter_mode"),
        "provider_adapter_readback_only": bool(provider_readiness.get("readback_only", True)),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": bool(provider_readiness.get("provider_adapter_suspended", False)),
        "provider_circuit_breaker_state": provider_circuit_breaker.get("state"),
        "provider_failure_class": provider_failure_taxonomy.get("failure_class"),
        "provider_status_replayable": bool(provider_status_readback.get("replayable", True)),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "payment_gateway_sandbox_state": payment_gateway_record.get("gateway_execution_state"),
        "charge_status_callback_sandbox_state": charge_record.get("sandbox_execution_state"),
        "delivery_provider_sandbox_state": delivery_provider_record.get("provider_execution_state"),
        "delivery_artifact_download_state": delivery_artifact_record.get("download_state"),
        "delivery_provider_reliability_state": delivery_provider_readiness.get("provider_reliability_state"),
        "delivery_provider_adapter_suspended": _provider_is_suspended(delivery_provider_readiness),
        "receipt_replayable": bool(dict(ledger.get("receipt_record", {})).get("replayable", False)),
        "invoice_replayable": bool(dict(ledger.get("invoice_record", {})).get("replayable", False)),
        "settlement_reconciliation_readiness": {
            "settlement_state": settlement_record.get("settlement_state"),
            "reconciliation_state": reconciliation_record.get("reconciliation_state"),
            "real_finance_posting_enabled": False,
            "replayable": bool(settlement_record.get("replayable", False))
            and bool(reconciliation_record.get("replayable", False)),
        },
        "manual_refund_exception_readiness": {
            "manual_refund_exception_state": manual_refund_record.get("manual_refund_exception_state"),
            "approval_state": dict(manual_refund_record.get("approval_record", {})).get("approval_state"),
            "audit_state": dict(manual_refund_record.get("audit_record", {})).get("audit_state"),
            "automated_refund_program_present": False,
            "automated_refund_enabled": False,
            "real_refund_attempted": False,
            "replayable": bool(dict(manual_refund_record.get("audit_record", {})).get("replayable", False)),
        },
        PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY: live_pilot_carrier,
        "payment_live_pilot_readiness_state": live_pilot_carrier.get("payment_live_pilot_readiness_state"),
        "delivery_live_pilot_readiness_state": live_pilot_carrier.get("delivery_live_pilot_readiness_state"),
        "overall_live_pilot_readiness_state": live_pilot_carrier.get("overall_live_pilot_readiness_state"),
        "live_payment_requested": bool(live_pilot_carrier.get("live_payment_requested", False)),
        "live_delivery_requested": bool(live_pilot_carrier.get("live_delivery_requested", False)),
        "live_payment_enabled": bool(live_pilot_carrier.get("live_payment_enabled", False)),
        "live_delivery_enabled": bool(live_pilot_carrier.get("live_delivery_enabled", False)),
        APPROVED_PAYMENT_DELIVERY_EXECUTION_INPUT_KEY: approved_execution_carrier,
        "approved_payment_delivery_execution_state": approved_execution_carrier.get(
            "provider_execution_state"
        ),
        "approved_payment_delivery_execution_enabled": bool(
            approved_execution_carrier.get("approved_payment_delivery_execution_enabled", False)
        ),
        "approved_payment_capture_enabled": bool(
            approved_execution_carrier.get("approved_payment_capture_enabled", False)
        ),
        "approved_charge_execution_enabled": bool(
            approved_execution_carrier.get("approved_charge_execution_enabled", False)
        ),
        "approved_delivery_fulfillment_enabled": bool(
            approved_execution_carrier.get("approved_delivery_fulfillment_enabled", False)
        ),
        "approved_customer_download_enabled": bool(
            approved_execution_carrier.get("approved_customer_download_enabled", False)
        ),
        "real_payment_capture_attempted": False,
        "real_delivery_fulfillment_attempted": False,
        "real_customer_download_attempted": False,
        "automated_refund_program": {
            "present": False,
            "enabled": False,
            "state": "ABSENT_BLOCKED",
        },
    }


def stage9_execution_ledger_summary(ledger: Mapping[str, Any]) -> dict[str, Any]:
    live_pilot_carrier = dict(ledger.get(PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY, {}))
    approved_execution_carrier = dict(
        ledger.get(
            APPROVED_PAYMENT_DELIVERY_EXECUTION_INPUT_KEY,
            live_pilot_carrier.get("approved_payment_delivery_execution_summary", {}),
        )
        or {}
    )
    return {
        "execution_ledger_id": ledger.get("execution_ledger_id"),
        "order_execution_id": ledger.get("order_execution_id"),
        "payment_execution_id": ledger.get("payment_execution_id"),
        "delivery_execution_id": ledger.get("delivery_execution_id"),
        "order_id": ledger.get("order_id"),
        "payment_id": ledger.get("payment_id"),
        "delivery_id": ledger.get("delivery_id"),
        "opportunity_id": ledger.get("opportunity_id"),
        "payment_collection_state": ledger.get("payment_collection_state"),
        "delivery_fulfillment_state": ledger.get("delivery_fulfillment_state"),
        "manual_settlement_state": ledger.get("manual_settlement_state"),
        "refund_execution_state": ledger.get("refund_execution_state"),
        "automated_refund_enabled": bool(ledger.get("automated_refund_enabled", False)),
        "real_payment_gateway_enabled": bool(ledger.get("real_payment_gateway_enabled", False)),
        "real_charge_attempted": bool(ledger.get("real_charge_attempted", False)),
        "real_delivery_attempted": bool(ledger.get("real_delivery_attempted", False)),
        "real_refund_attempted": bool(ledger.get("real_refund_attempted", False)),
        "governed_execution_mode": ledger.get("governed_execution_mode", "INTERNAL_GOVERNED"),
        "payment_gateway_sandbox_state": dict(ledger.get("payment_gateway_sandbox_record", {})).get(
            "gateway_execution_state"
        ),
        "charge_status_callback_sandbox_state": dict(
            ledger.get("charge_status_callback_sandbox_record", {})
        ).get("sandbox_execution_state"),
        "receipt_state": dict(ledger.get("receipt_record", {})).get("receipt_state"),
        "invoice_state": dict(ledger.get("invoice_record", {})).get("invoice_state"),
        "delivery_provider_sandbox_state": dict(ledger.get("delivery_provider_sandbox_record", {})).get(
            "provider_execution_state"
        ),
        "delivery_artifact_download_state": dict(ledger.get("delivery_artifact_download_record", {})).get(
            "download_state"
        ),
        "delivery_version_lock_state": dict(ledger.get("delivery_version_lock_record", {})).get("lock_state"),
        "settlement_reconciliation_state": dict(ledger.get("finance_reconciliation_record", {})).get(
            "reconciliation_state"
        ),
        "manual_refund_exception_state": dict(ledger.get(MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY, {})).get(
            "manual_refund_exception_state"
        ),
        PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY: live_pilot_carrier,
        "payment_live_pilot_readiness_state": live_pilot_carrier.get("payment_live_pilot_readiness_state"),
        "delivery_live_pilot_readiness_state": live_pilot_carrier.get("delivery_live_pilot_readiness_state"),
        "overall_live_pilot_readiness_state": live_pilot_carrier.get("overall_live_pilot_readiness_state"),
        "live_payment_enabled": bool(live_pilot_carrier.get("live_payment_enabled", False)),
        "live_delivery_enabled": bool(live_pilot_carrier.get("live_delivery_enabled", False)),
        APPROVED_PAYMENT_DELIVERY_EXECUTION_INPUT_KEY: approved_execution_carrier,
        "approved_payment_delivery_execution_enabled": bool(
            approved_execution_carrier.get("approved_payment_delivery_execution_enabled", False)
        ),
        "approved_payment_capture_enabled": bool(
            approved_execution_carrier.get("approved_payment_capture_enabled", False)
        ),
        "approved_delivery_fulfillment_enabled": bool(
            approved_execution_carrier.get("approved_delivery_fulfillment_enabled", False)
        ),
    }


def build_stage9_execution_ledger(
    *,
    project_id: str,
    runtime_inputs: Mapping[str, Any],
    order_record: Mapping[str, Any],
    payment_record: Mapping[str, Any],
    delivery_record: Mapping[str, Any],
    approval_state: str,
    audit_trail_present: bool,
    now: str,
    provider_adapter_readiness_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider_summary = dict(provider_adapter_readiness_summary or {})
    provider_readiness = provider_readiness_for_family(
        provider_adapter_readiness_summary,
        "payment_collection",
    )
    delivery_provider_readiness = provider_readiness_for_family(
        provider_adapter_readiness_summary,
        "leadpack_page_delivery",
    )
    provider_suspended = bool(
        provider_summary.get("provider_adapter_suspended", False)
        or _provider_is_suspended(provider_readiness)
        or _provider_is_suspended(delivery_provider_readiness)
    )
    order_id = str(order_record.get("order_id"))
    payment_id = str(payment_record.get("payment_id"))
    delivery_id = str(delivery_record.get("delivery_id"))
    opportunity_id = str(order_record.get("opportunity_id") or runtime_inputs.get("opportunity_id") or "")
    ledger_id = build_id("S9LEDGER", project_id, order_id)
    order_execution_id = build_id("OEXEC", project_id, order_id)
    payment_execution_id = build_id("PEXEC", project_id, payment_id)
    delivery_execution_id = build_id("DEXEC", project_id, delivery_id)

    requested_real_payment_gateway = _requested_flag(
        runtime_inputs,
        "real_payment_gateway_enabled",
        "payment_gateway_enabled",
        "payment_gateway_connection_requested",
        "direct_payment_gateway_call_enabled",
        "external_payment_gateway_enabled",
    )
    requested_real_charge = _requested_flag(
        runtime_inputs,
        "real_charge_requested",
        "real_charge_attempted",
        "charge_execution_requested",
        "payment_live_execution_requested",
        "live_payment_execution_requested",
    )
    requested_real_delivery = _requested_flag(
        runtime_inputs,
        "real_delivery_requested",
        "real_delivery_attempted",
        "delivery_live_execution_requested",
        "live_delivery_execution_requested",
        "external_delivery_enabled",
    )
    requested_automated_refund = _requested_flag(
        runtime_inputs,
        "automated_refund_enabled",
        "auto_refund_enabled",
        "automated_refund_requested",
        "refund_automation_requested",
    )
    requested_real_refund = _requested_flag(
        runtime_inputs,
        "real_refund_requested",
        "real_refund_attempted",
        "refund_live_execution_requested",
        "live_refund_execution_requested",
    )
    requested_live = _requested_flag(
        runtime_inputs,
        "live_execution_enabled",
        "external_live_execution",
        "external_live_execution_requested",
    )

    approval_execution_state, audit_state = _approval_audit_state(
        approval_state=approval_state,
        audit_trail_present=audit_trail_present,
        order_record=order_record,
        payment_record=payment_record,
        delivery_record=delivery_record,
    )
    manual_settlement_state = _manual_settlement_state(payment_record, runtime_inputs)
    payment_collection_state = _payment_collection_state(payment_record)
    delivery_fulfillment_state = _delivery_fulfillment_state(delivery_record)
    refund_state = str(payment_record.get("refund_state", "NOT_REQUESTED"))
    refund_execution_state = (
        "MANUAL_EXCEPTION_REVIEW"
        if refund_state not in {"NOT_REQUESTED", "NO_EXCEPTION"}
        else "MANUAL_EXCEPTION_ONLY"
    )

    blocked_reasons: list[str] = []
    if requested_live:
        blocked_reasons.append("live_execution_requested_but_blocked")
    if requested_real_payment_gateway:
        blocked_reasons.append("real_payment_gateway_requested_but_blocked")
    if requested_real_charge:
        blocked_reasons.append("real_charge_requested_but_blocked")
    if requested_real_delivery:
        blocked_reasons.append("real_delivery_requested_but_blocked")
    if requested_automated_refund:
        blocked_reasons.append("automated_refund_requested_but_blocked")
    if requested_real_refund:
        blocked_reasons.append("real_refund_requested_but_blocked")
    if audit_state == "MISSING":
        blocked_reasons.append("audit_trail_missing_for_live_execution")
    if provider_suspended:
        blocked_reasons.append("provider_suspended_fail_closed_no_live_fallback")
    blocked_reasons.extend(
        [
            "internal_governed_execution_ledger_only",
            "real_payment_gateway_enabled=false",
            "real_charge_attempted=false",
            "real_refund_attempted=false",
            "automated_refund_enabled=false",
            "real_delivery_attempted=false",
        ]
    )
    blocked_reasons.extend(provider_readiness.get("blocked_reasons", []))
    blocked_reasons.extend(delivery_provider_readiness.get("blocked_reasons", []))

    payment_gateway_record = dict(payment_record.get("payment_gateway_sandbox_record", {}))
    charge_record = dict(payment_record.get("charge_status_callback_sandbox_record", {}))
    receipt_record = dict(payment_record.get("receipt_record", {}))
    invoice_record = dict(payment_record.get("invoice_record", {}))
    settlement_record = dict(payment_record.get("settlement_record", {}))
    reconciliation_record = dict(payment_record.get("finance_reconciliation_record", {}))
    manual_refund_record = dict(payment_record.get(MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY, {}))
    delivery_sandbox_records = dict(delivery_record.get(DELIVERY_SANDBOX_RECORDS_INPUT_KEY, {}))
    delivery_provider_record = dict(delivery_record.get("delivery_provider_sandbox_record", {}))
    delivery_artifact_record = dict(delivery_record.get("delivery_artifact_download_record", {}))
    delivery_version_lock_record = dict(delivery_record.get("delivery_version_lock_record", {}))
    delivery_hash_record = dict(delivery_record.get("delivery_hash_record", {}))
    delivery_audit_record = dict(delivery_sandbox_records.get("delivery_audit_record", {}))
    live_pilot_carrier = _build_payment_delivery_live_pilot_carrier(
        project_id=project_id,
        runtime_inputs=runtime_inputs,
        order_id=order_id,
        payment_id=payment_id,
        delivery_id=delivery_id,
        opportunity_id=opportunity_id,
        payment_gateway_record=payment_gateway_record,
        charge_record=charge_record,
        receipt_record=receipt_record,
        invoice_record=invoice_record,
        settlement_record=settlement_record,
        reconciliation_record=reconciliation_record,
        manual_refund_record=manual_refund_record,
        delivery_provider_record=delivery_provider_record,
        delivery_artifact_record=delivery_artifact_record,
        delivery_version_lock_record=delivery_version_lock_record,
        delivery_hash_record=delivery_hash_record,
        delivery_audit_record=delivery_audit_record,
        delivery_record=delivery_record,
        provider_summary=provider_summary,
        payment_provider_readiness=provider_readiness,
        delivery_provider_readiness=delivery_provider_readiness,
        audit_state=audit_state,
        now=now,
    )
    approved_execution_carrier = _build_approved_payment_delivery_execution_carrier(
        project_id=project_id,
        runtime_inputs=runtime_inputs,
        order_id=order_id,
        payment_id=payment_id,
        delivery_id=delivery_id,
        opportunity_id=opportunity_id,
        live_pilot_carrier=live_pilot_carrier,
        payment_provider_readiness=provider_readiness,
        delivery_provider_readiness=delivery_provider_readiness,
        now=now,
    )
    live_pilot_carrier["approved_payment_delivery_execution_summary"] = approved_execution_carrier
    live_pilot_carrier["approved_payment_delivery_execution_enabled"] = bool(
        approved_execution_carrier.get("approved_payment_delivery_execution_enabled", False)
    )
    blocked_reasons.extend(live_pilot_carrier.get("blocked_reasons", []))
    blocked_reasons.extend(live_pilot_carrier.get("review_reasons", []))
    blocked_reasons.extend(live_pilot_carrier.get("suspension_reasons", []))
    if approved_execution_carrier.get("approved_payment_delivery_execution_requested"):
        blocked_reasons.extend(approved_execution_carrier.get("blocked_reasons", []))
        blocked_reasons.extend(approved_execution_carrier.get("suspension_reasons", []))

    ledger = {
        "execution_ledger_id": ledger_id,
        "order_execution_id": order_execution_id,
        "payment_execution_id": payment_execution_id,
        "delivery_execution_id": delivery_execution_id,
        "order_id": order_id,
        "payment_id": payment_id,
        "delivery_id": delivery_id,
        "opportunity_id": opportunity_id,
        "project_id": project_id,
        "payment_collection_state": payment_collection_state,
        "delivery_fulfillment_state": delivery_fulfillment_state,
        "manual_settlement_state": manual_settlement_state,
        "manual_settlement_note_optional": runtime_inputs.get("manual_settlement_note_optional"),
        "refund_execution_state": refund_execution_state,
        "refund_state": refund_state,
        "automated_refund_enabled": False,
        "refund_manual_exception_required": refund_state not in {"NOT_REQUESTED", "NO_EXCEPTION"},
        "real_payment_gateway_enabled": False,
        "real_charge_attempted": False,
        "real_delivery_attempted": False,
        "real_refund_attempted": False,
        "real_payment_capture_attempted": False,
        "real_delivery_fulfillment_attempted": False,
        "real_customer_download_attempted": False,
        "live_payment_requested": bool(live_pilot_carrier.get("live_payment_requested", False)),
        "live_delivery_requested": bool(live_pilot_carrier.get("live_delivery_requested", False)),
        "live_payment_enabled": bool(live_pilot_carrier.get("live_payment_enabled", False)),
        "live_delivery_enabled": bool(live_pilot_carrier.get("live_delivery_enabled", False)),
        "payment_live_pilot_readiness_state": live_pilot_carrier.get("payment_live_pilot_readiness_state"),
        "delivery_live_pilot_readiness_state": live_pilot_carrier.get("delivery_live_pilot_readiness_state"),
        "overall_live_pilot_readiness_state": live_pilot_carrier.get("overall_live_pilot_readiness_state"),
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: provider_summary,
        "provider_adapter_readiness": provider_readiness,
        "delivery_provider_adapter_readiness": delivery_provider_readiness,
        "provider_adapter_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
        "provider_adapter_mode": provider_readiness.get("mode"),
        "provider_reliability_state": provider_summary.get(
            "provider_reliability_state",
            provider_readiness.get("provider_reliability_state"),
        ),
        "provider_adapter_suspended": provider_suspended,
        "provider_circuit_breaker_state": provider_summary.get(
            "provider_circuit_breaker_state",
            dict(provider_readiness.get("provider_circuit_breaker", {})).get("state"),
        ),
        "provider_failure_taxonomy": dict(provider_readiness.get("provider_failure_taxonomy", {})),
        "provider_status_readback": dict(provider_readiness.get("provider_status_readback", {})),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "payment_gateway_sandbox_record": payment_gateway_record,
        "charge_status_callback_sandbox_record": charge_record,
        "receipt_record": receipt_record,
        "invoice_record": invoice_record,
        "settlement_record": settlement_record,
        "finance_reconciliation_record": reconciliation_record,
        MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY: manual_refund_record,
        PAYMENT_SANDBOX_RECORDS_INPUT_KEY: dict(payment_record.get(PAYMENT_SANDBOX_RECORDS_INPUT_KEY, {})),
        "delivery_provider_sandbox_record": delivery_provider_record,
        "delivery_artifact_download_record": delivery_artifact_record,
        "delivery_version_lock_record": delivery_version_lock_record,
        "delivery_hash_record": delivery_hash_record,
        "delivery_audit_record": delivery_audit_record,
        DELIVERY_SANDBOX_RECORDS_INPUT_KEY: delivery_sandbox_records,
        PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY: live_pilot_carrier,
        APPROVED_PAYMENT_DELIVERY_EXECUTION_INPUT_KEY: approved_execution_carrier,
        "approved_payment_delivery_execution_enabled": bool(
            approved_execution_carrier.get("approved_payment_delivery_execution_enabled", False)
        ),
        "approved_payment_capture_enabled": bool(
            approved_execution_carrier.get("approved_payment_capture_enabled", False)
        ),
        "approved_charge_execution_enabled": bool(
            approved_execution_carrier.get("approved_charge_execution_enabled", False)
        ),
        "approved_delivery_fulfillment_enabled": bool(
            approved_execution_carrier.get("approved_delivery_fulfillment_enabled", False)
        ),
        "approved_customer_download_enabled": bool(
            approved_execution_carrier.get("approved_customer_download_enabled", False)
        ),
        "approved_payment_delivery_execution_state": approved_execution_carrier.get(
            "provider_execution_state"
        ),
        "payment_gateway_adapter_state": {
            "state": _provider_sandbox_state(provider_readiness),
            "adapter_scope": "SANDBOX_DRY_RUN_READBACK_ONLY",
            "real_payment_gateway_enabled": False,
            "real_charge_attempted": False,
            "provider_adapter_family": "payment_collection",
            "provider_id": provider_readiness.get("provider_id"),
            "provider_mode": provider_readiness.get("mode"),
            "provider_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
            "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
            "provider_adapter_suspended": provider_suspended,
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
            "sandbox_record_id": payment_gateway_record.get("payment_gateway_sandbox_record_id"),
        },
        "delivery_execution_adapter_state": {
            "state": _provider_sandbox_state(delivery_provider_readiness),
            "adapter_scope": "SANDBOX_DRY_RUN_READBACK_ONLY",
            "provider_adapter_family": "leadpack_page_delivery",
            "provider_id": delivery_provider_readiness.get("provider_id"),
            "provider_mode": delivery_provider_readiness.get("mode"),
            "provider_reliability_state": delivery_provider_readiness.get("provider_reliability_state"),
            "provider_adapter_suspended": _provider_is_suspended(delivery_provider_readiness),
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
            "real_delivery_attempted": False,
            "external_delivery_enabled": False,
            "customer_visible_delivery_enabled": False,
            "sandbox_record_id": delivery_provider_record.get("delivery_provider_sandbox_record_id"),
        },
        "refund_execution_boundary": {
            "state": "MANUAL_EXCEPTION_ONLY",
            "automated_refund_enabled": False,
            "real_refund_attempted": False,
            "operator_can_record_manual_exception": True,
            "operator_can_execute_automated_refund": False,
            MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY: manual_refund_record,
        },
        "approval_state": approval_execution_state,
        "source_approval_state": approval_state,
        "audit_state": audit_state,
        "governed_execution_mode": str(runtime_inputs.get("governed_execution_mode", "INTERNAL_GOVERNED")),
        "payment_recording_enabled": True,
        "delivery_recording_enabled": True,
        "manual_settlement_enabled": True,
        "operator_readback_summary": {
            "operator_can_record_order_execution": True,
            "operator_can_record_payment_collection": True,
            "operator_can_record_delivery_fulfillment": True,
            "operator_can_record_manual_settlement": True,
            "operator_can_record_refund_manual_exception": True,
            "operator_can_connect_payment_gateway": False,
            "operator_can_attempt_real_charge": False,
            "operator_can_attempt_real_refund": False,
            "operator_can_execute_automated_refund": False,
            "readback_ready": True,
        },
        "blocked_reasons": _clean_list(blocked_reasons),
        "created_at": now,
    }
    ledger["readiness_summary"] = build_stage9_execution_ledger_readiness_summary(ledger)
    return ledger


__all__ = [
    "APPROVED_PAYMENT_DELIVERY_EXECUTION_INPUT_KEY",
    "DELIVERY_SANDBOX_RECORDS_INPUT_KEY",
    "MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY",
    "PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY",
    "PAYMENT_SANDBOX_RECORDS_INPUT_KEY",
    "STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY",
    "STAGE9_EXECUTION_LEDGER_INPUT_KEY",
    "STAGE9_EXECUTION_LEDGER_OBJECT_TYPE",
    "STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY",
    "attach_delivery_sandbox_records",
    "attach_order_lifecycle_record",
    "attach_payment_sandbox_records",
    "build_stage9_execution_ledger",
    "build_stage9_execution_ledger_readiness_summary",
    "stage9_execution_ledger_summary",
]
