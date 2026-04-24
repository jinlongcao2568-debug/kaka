from __future__ import annotations

from typing import Any, Mapping

from shared.utils import build_id, ensure_list


STAGE9_EXECUTION_LEDGER_OBJECT_TYPE = "stage9_execution_ledger"
STAGE9_EXECUTION_LEDGER_INPUT_KEY = "stage9_execution_ledger"
STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY = "stage9_execution_ledger_readiness"
STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY = "stage9_execution_ledger_id_optional"

_EMPTY_VALUES = {None, "", "UNKNOWN", "NOT_APPLICABLE"}


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
) -> dict[str, Any]:
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
    blocked_reasons.extend(
        [
            "internal_governed_execution_ledger_only",
            "real_payment_gateway_enabled=false",
            "real_charge_attempted=false",
            "real_refund_attempted=false",
            "automated_refund_enabled=false",
        ]
    )

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
        "payment_gateway_adapter_state": {
            "state": "BLOCKED",
            "adapter_scope": "NOT_CONNECTED_IN_110E",
            "real_payment_gateway_enabled": False,
            "real_charge_attempted": False,
        },
        "delivery_execution_adapter_state": {
            "state": "INTERNAL_LEDGER_ONLY",
            "real_delivery_attempted": False,
            "external_delivery_enabled": False,
            "customer_visible_delivery_enabled": False,
        },
        "refund_execution_boundary": {
            "state": "MANUAL_EXCEPTION_ONLY",
            "automated_refund_enabled": False,
            "real_refund_attempted": False,
            "operator_can_record_manual_exception": True,
            "operator_can_execute_automated_refund": False,
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
    "STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY",
    "STAGE9_EXECUTION_LEDGER_INPUT_KEY",
    "STAGE9_EXECUTION_LEDGER_OBJECT_TYPE",
    "STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY",
    "build_stage9_execution_ledger",
    "build_stage9_execution_ledger_readiness_summary",
    "stage9_execution_ledger_summary",
]
