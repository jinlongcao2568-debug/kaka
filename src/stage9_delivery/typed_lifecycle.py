from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shared.contracts_runtime import ContractStore
from shared.utils import build_id, ensure_enum, ensure_list


INTERNAL_WRITEBACK_GATE_IDS = (
    "internal_review_release",
    "sales_consumption_release",
)


@dataclass(frozen=True)
class GuardSpec:
    requested_gate_ids: tuple[str, ...]
    gate_conditions: dict[str, Any]


@dataclass(frozen=True)
class SemanticSpec:
    context: dict[str, Any]


@dataclass(frozen=True)
class LifecycleRecordSpec:
    object_type: str
    payload: dict[str, Any]
    guard: GuardSpec
    semantic: SemanticSpec


@dataclass(frozen=True)
class PaymentLifecycleState:
    payment_status: str
    payment_exception_family: str | None
    payment_exception_tags: list[str]
    payment_exception_reason: str | None
    amount_mismatch_state: str | None
    refund_amount_band_optional: str | None
    written_back_at: str
    payer_match_state: str
    amount_match_state: str
    refund_state: str


@dataclass(frozen=True)
class DeliveryLifecycleState:
    delivery_status: str
    delivery_exception_family: str | None
    delivery_exception_tags: list[str]
    delivery_exception_reason: str | None
    customer_ack_state_optional: str


def governed_fields(
    *,
    governed_execution_mode: str,
    permission_decision_state: str,
    governance_decision_state: str,
    semantic_decision_state: str,
    governed_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "governed_execution_mode": governed_execution_mode,
        "permission_decision_state": permission_decision_state,
        "governance_decision_state": governance_decision_state,
        "semantic_decision_state": semantic_decision_state,
        "governed_metadata": governed_metadata,
    }


def resolve_order_approval_state(*, approval_state: str, order_status: str) -> str:
    if approval_state == "NOT_REQUIRED" and order_status == "PENDING_APPROVAL":
        return "PENDING"
    return approval_state


def match_state_from_mismatch(mismatch_state: str | None) -> str:
    if mismatch_state in (None, "", "NO_MISMATCH"):
        return "MATCHED"
    if mismatch_state == "CONFIRMED":
        return "MISMATCHED"
    return "REVIEW_REQUIRED"


def resolve_payment_lifecycle_state(
    *,
    runtime_state: Any,
    runtime_inputs: Mapping[str, Any],
    written_back_at_optional: str | None,
    now: str,
) -> PaymentLifecycleState:
    refund_state = runtime_state.resolve(
        "refund_state",
        runtime_inputs.get("refund_state", "NOT_REQUESTED"),
    )
    payment_status = runtime_state.resolve(
        "payment_status",
        runtime_inputs.get("payment_status", "NOT_STARTED"),
    )
    if payment_status == "NOT_STARTED":
        if refund_state == "COMPLETED":
            payment_status = "REFUNDED"
        elif refund_state in ("REQUESTED", "APPROVED"):
            payment_status = "REFUND_PENDING"

    payment_exception_family = runtime_state.resolve("payment_exception_family_optional")
    payment_exception_tags = ensure_list(
        runtime_state.resolve("payment_exception_reason_tags_optional")
    )
    payment_exception_reason = runtime_state.resolve(
        "payment_exception_reason_optional",
        payment_exception_tags[0] if payment_exception_tags else payment_exception_family,
    )
    amount_mismatch_state = runtime_state.resolve(
        "amount_mismatch_state_optional",
        runtime_inputs.get("amount_mismatch_state_optional"),
    )
    refund_amount_band_optional = runtime_inputs.get("refund_amount_band_optional")
    if refund_state not in (None, "", "NOT_REQUESTED") and refund_amount_band_optional in (None, ""):
        refund_amount_band_optional = runtime_inputs["amount_band"]

    return PaymentLifecycleState(
        payment_status=payment_status,
        payment_exception_family=payment_exception_family,
        payment_exception_tags=payment_exception_tags,
        payment_exception_reason=payment_exception_reason,
        amount_mismatch_state=amount_mismatch_state,
        refund_amount_band_optional=refund_amount_band_optional,
        written_back_at=written_back_at_optional or now,
        payer_match_state=runtime_state.resolve(
            "payer_match_state",
            match_state_from_mismatch(runtime_inputs.get("payer_mismatch_state", "NO_MISMATCH")),
        ),
        amount_match_state=runtime_state.resolve(
            "amount_match_state",
            match_state_from_mismatch(amount_mismatch_state),
        ),
        refund_state=refund_state,
    )


def resolve_delivery_lifecycle_state(
    *,
    runtime_state: Any,
    runtime_inputs: Mapping[str, Any],
) -> DeliveryLifecycleState:
    delivery_status = runtime_state.resolve("delivery_status", runtime_inputs["delivery_status"])
    delivery_exception_family = runtime_state.resolve("delivery_exception_family_optional")
    delivery_exception_tags = ensure_list(
        runtime_state.resolve("delivery_exception_reason_tags_optional")
    )
    delivery_exception_reason = runtime_state.resolve(
        "delivery_exception_reason_optional",
        delivery_exception_tags[0] if delivery_exception_tags else delivery_exception_family,
    )
    customer_ack_state_optional = runtime_state.resolve(
        "customer_ack_state_optional",
        runtime_inputs.get("customer_ack_state_optional"),
    )
    if customer_ack_state_optional in (None, ""):
        if delivery_status == "ACKNOWLEDGED":
            customer_ack_state_optional = "ACKNOWLEDGED"
        elif delivery_status in ("DELIVERED", "ACK_PENDING"):
            customer_ack_state_optional = "PENDING"
        else:
            customer_ack_state_optional = "NOT_REQUESTED"

    return DeliveryLifecycleState(
        delivery_status=delivery_status,
        delivery_exception_family=delivery_exception_family,
        delivery_exception_tags=delivery_exception_tags,
        delivery_exception_reason=delivery_exception_reason,
        customer_ack_state_optional=customer_ack_state_optional,
    )


def build_order_record_spec(
    *,
    store: ContractStore,
    project_id: str,
    h08_payload: Mapping[str, Any],
    response_status: str,
    saleability_status: str,
    crm_owner_state: str,
    runtime_inputs: Mapping[str, Any],
    order_approval_state: str,
    order_archival_status: str,
    plan_status: str,
    touch_record_state: str,
    governed_execution_mode: str,
    permission_effective_state: str,
    governance_effective_state: str,
    semantic_effective_state: str,
    governed_metadata: Mapping[str, Any],
    now: str,
    approval_chain_present: bool,
    audit_trail_present: bool,
    feedback_reason: str,
    upstream_governance_decision_state: str,
) -> LifecycleRecordSpec:
    payload = {
        "order_id": build_id("ORDER", project_id),
        "project_id": project_id,
        "opportunity_id": h08_payload["opportunity_id"],
        "touch_record_id": h08_payload["touch_record_id"],
        "response_status": response_status,
        "saleability_status": saleability_status,
        "crm_owner_state": crm_owner_state,
        "commercial_status": ensure_enum(
            store,
            "commercial_status",
            runtime_inputs["commercial_status"],
        ),
        "order_status": ensure_enum(
            store,
            "order_status",
            runtime_inputs["order_status"],
        ),
        "approval_state": ensure_enum(
            store,
            "approval_state",
            order_approval_state,
        ),
        "archival_status": ensure_enum(
            store,
            "archival_status",
            order_archival_status,
        ),
        "amount_band": ensure_enum(
            store,
            "amount_band",
            runtime_inputs["amount_band"],
        ),
        "plan_status": ensure_enum(
            store,
            "plan_status",
            plan_status,
        ),
        "touch_record_state": ensure_enum(
            store,
            "touch_record_state",
            touch_record_state,
        ),
        **governed_fields(
            governed_execution_mode=governed_execution_mode,
            permission_decision_state=permission_effective_state,
            governance_decision_state=governance_effective_state,
            semantic_decision_state=semantic_effective_state,
            governed_metadata=governed_metadata,
        ),
        "created_at": now,
    }
    return LifecycleRecordSpec(
        object_type="order_record",
        payload=payload,
        guard=GuardSpec(
            requested_gate_ids=INTERNAL_WRITEBACK_GATE_IDS,
            gate_conditions={
                "approval chain present": approval_chain_present,
                "audit trail present": audit_trail_present,
            },
        ),
        semantic=SemanticSpec(
            context={
                "saleability_status": saleability_status,
                "crm_owner_state": crm_owner_state,
                "plan_status": plan_status,
                "touch_record_state": touch_record_state,
                "feedback_reason": feedback_reason,
                "governance_decision_state": upstream_governance_decision_state,
            }
        ),
    )


def apply_order_decision_projection(payload: dict[str, Any], decision_state: str | None) -> None:
    if decision_state == "BLOCK":
        payload["commercial_status"] = "ON_HOLD"
        payload["order_status"] = "ON_HOLD"
    elif decision_state == "REVIEW" and payload["order_status"] == "DRAFT":
        payload["order_status"] = "PENDING_APPROVAL"
        if payload["approval_state"] == "NOT_REQUIRED":
            payload["approval_state"] = "PENDING"


def build_payment_record_spec(
    *,
    store: ContractStore,
    project_id: str,
    order_record: Mapping[str, Any],
    runtime_inputs: Mapping[str, Any],
    payment_state: PaymentLifecycleState,
    governed_execution_mode: str,
    permission_effective_state: str,
    governance_effective_state: str,
    semantic_effective_state: str,
    governed_metadata: Mapping[str, Any],
    audit_trail_present: bool,
    feedback_reason: str,
) -> LifecycleRecordSpec:
    payload = {
        "payment_id": build_id("PAY", project_id),
        "project_id": project_id,
        "order_id": order_record.get("order_id"),
        "payment_status": ensure_enum(
            store,
            "payment_status",
            payment_state.payment_status,
        ),
        "payment_proof_state": runtime_inputs.get("payment_proof_state", "NOT_PROVIDED"),
        "amount_band": order_record.get("amount_band"),
        "payer_match_state": payment_state.payer_match_state,
        "amount_match_state": payment_state.amount_match_state,
        "payment_exception_family_optional": payment_state.payment_exception_family or "NO_EXCEPTION",
        "payment_exception_reason_optional": payment_state.payment_exception_reason or "NO_EXCEPTION",
        "payment_exception_reason_tags_optional": payment_state.payment_exception_tags,
        "amount_mismatch_state_optional": payment_state.amount_mismatch_state or "NO_MISMATCH",
        "refund_state": payment_state.refund_state,
        "refund_amount_band_optional": payment_state.refund_amount_band_optional or "NOT_APPLICABLE",
        "paid_at_optional": runtime_inputs.get("paid_at_optional", "NOT_PAID"),
        "written_back_at_optional": payment_state.written_back_at,
        **governed_fields(
            governed_execution_mode=governed_execution_mode,
            permission_decision_state=permission_effective_state,
            governance_decision_state=governance_effective_state,
            semantic_decision_state=semantic_effective_state,
            governed_metadata=governed_metadata,
        ),
    }
    return LifecycleRecordSpec(
        object_type="payment_record",
        payload=payload,
        guard=GuardSpec(
            requested_gate_ids=INTERNAL_WRITEBACK_GATE_IDS,
            gate_conditions={
                "payment proof or audit present for received state": payload["payment_status"] != "PAID"
                or payload["payment_proof_state"] != "NOT_PROVIDED"
                or audit_trail_present,
                "no payer mismatch block": runtime_inputs.get("payer_mismatch_state", "NO_MISMATCH") == "NO_MISMATCH",
                "audit trail present": audit_trail_present,
            },
        ),
        semantic=SemanticSpec(
            context={
                "payer_mismatch_state": runtime_inputs.get("payer_mismatch_state", "NO_MISMATCH"),
                "feedback_reason": feedback_reason,
            }
        ),
    )


def apply_payment_decision_projection(payload: dict[str, Any], decision_state: str | None) -> None:
    if decision_state == "BLOCK" and payload["payment_status"] == "PAID":
        payload["payment_status"] = "PAYMENT_EXCEPTION"
    elif decision_state == "REVIEW" and payload["payment_status"] == "NOT_STARTED":
        payload["payment_status"] = "PENDING_PAYMENT"


def build_delivery_record_spec(
    *,
    store: ContractStore,
    project_id: str,
    order_record: Mapping[str, Any],
    payment_record: Mapping[str, Any],
    runtime_inputs: Mapping[str, Any],
    delivery_state: DeliveryLifecycleState,
    written_back_at_optional: str | None,
    now: str,
    governed_execution_mode: str,
    permission_effective_state: str,
    governance_effective_state: str,
    semantic_effective_state: str,
    governed_metadata: Mapping[str, Any],
    approval_chain_present: bool,
    audit_trail_present: bool,
    saleability_status: str,
    plan_status: str,
    touch_record_state: str,
    runtime_state: Any,
) -> LifecycleRecordSpec:
    payload = {
        "delivery_id": build_id("DELIVERY", project_id),
        "project_id": project_id,
        "order_id": order_record.get("order_id"),
        "payment_id_optional": payment_record.get("payment_id"),
        "delivery_form": ensure_enum(
            store,
            "delivery_form",
            runtime_inputs.get("delivery_form", "INTERNAL_REVIEW"),
        ),
        "delivery_status": ensure_enum(
            store,
            "delivery_status",
            delivery_state.delivery_status,
        ),
        "delivered_at_optional": runtime_inputs.get("delivered_at_optional", "NOT_DELIVERED"),
        "customer_ack_state_optional": delivery_state.customer_ack_state_optional,
        "delivery_exception_family_optional": delivery_state.delivery_exception_family or "NO_EXCEPTION",
        "delivery_exception_reason_optional": delivery_state.delivery_exception_reason or "NO_EXCEPTION",
        "delivery_exception_reason_tags_optional": delivery_state.delivery_exception_tags,
        "partial_delivery_state_optional": runtime_state.resolve("partial_delivery_state_optional", "NOT_PARTIAL"),
        "resend_required_optional": bool(runtime_state.resolve("resend_required_optional", False)),
        "redeliver_required_optional": bool(runtime_state.resolve("redeliver_required_optional", False)),
        "archival_status": ensure_enum(
            store,
            "archival_status",
            runtime_state.resolve(
                "archival_status",
                runtime_inputs.get("archival_status", "NOT_ARCHIVED"),
            ),
        ),
        "retention_until": runtime_inputs.get("retention_until", now),
        "retrieval_status": ensure_enum(
            store,
            "retrieval_status",
            runtime_state.resolve(
                "retrieval_status",
                runtime_inputs.get("retrieval_status", "NOT_AVAILABLE"),
            ),
        ),
        "written_back_at_optional": written_back_at_optional or now,
        **governed_fields(
            governed_execution_mode=governed_execution_mode,
            permission_decision_state=permission_effective_state,
            governance_decision_state=governance_effective_state,
            semantic_decision_state=semantic_effective_state,
            governed_metadata=governed_metadata,
        ),
    }
    package_template_code = str(runtime_inputs.get("package_template_code") or "").strip()
    if package_template_code:
        payload["package_template_code"] = ensure_enum(
            store,
            "package_template_code",
            package_template_code,
        )
    return LifecycleRecordSpec(
        object_type="delivery_record",
        payload=payload,
        guard=GuardSpec(
            requested_gate_ids=INTERNAL_WRITEBACK_GATE_IDS,
            gate_conditions={
                "release gate present": True,
                "approval chain present": approval_chain_present,
                "audit trail present": audit_trail_present,
                "archival or retrieval not failed": payload["archival_status"] != "ARCHIVE_EXCEPTION"
                and payload["retrieval_status"] != "FAILED",
            },
        ),
        semantic=SemanticSpec(
            context={
                "saleability_status": saleability_status,
                "plan_status": plan_status,
                "touch_record_state": touch_record_state,
            }
        ),
    )


def apply_delivery_decision_projection(payload: dict[str, Any], decision_state: str | None) -> None:
    if decision_state == "BLOCK":
        payload["delivery_status"] = "RELEASE_BLOCKED"


__all__ = [
    "LifecycleRecordSpec",
    "PaymentLifecycleState",
    "DeliveryLifecycleState",
    "apply_delivery_decision_projection",
    "apply_order_decision_projection",
    "apply_payment_decision_projection",
    "build_delivery_record_spec",
    "build_order_record_spec",
    "build_payment_record_spec",
    "match_state_from_mismatch",
    "resolve_delivery_lifecycle_state",
    "resolve_order_approval_state",
    "resolve_payment_lifecycle_state",
]
