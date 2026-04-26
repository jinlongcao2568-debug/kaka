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

_EMPTY_VALUES = {None, "", "UNKNOWN", "NOT_APPLICABLE"}
_SUSPENDED_STATES = {"SUSPENDED"}
_CIRCUIT_OPEN_STATES = {"OPEN", "HALF_OPEN", "FORCED_OPEN"}
_PROVIDER_FAILURE_BLOCKING_CLASSES = {"UNHEALTHY", "RATE_LIMITED", "TIMEOUT", "CIRCUIT_OPEN"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "live", "enabled"}
    return bool(value)


def _has_value(value: Any) -> bool:
    return value not in _EMPTY_VALUES


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
    }


def stage9_execution_ledger_summary(ledger: Mapping[str, Any]) -> dict[str, Any]:
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
    "DELIVERY_SANDBOX_RECORDS_INPUT_KEY",
    "MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY",
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
