from __future__ import annotations

from typing import Any, Mapping


def _semantic_contact_target(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if context.get("upstream_saleability_status") == "BLOCKED":
        decision = "BLOCK"
        reasons.append("blocked saleability may not produce runnable contact_target")
    if payload.get("saleability_status") != context.get("upstream_saleability_status"):
        decision = "BLOCK"
        reasons.append("contact_target.saleability_status must stay aligned with upstream opportunity")
    if payload.get("auto_contact_allowed"):
        if payload.get("contact_legal_basis") not in (
            "PUBLIC_ROLE_CONTACT",
            "CUSTOMER_AUTHORIZED_CONTACT",
            "COMPLIANT_CRM_CONTACT",
        ):
            decision = "BLOCK"
            reasons.append("auto_contact_allowed requires compliant legal basis")
        if (
            payload.get("opt_out_state") != "ACTIVE"
            or payload.get("quiet_hours_policy_state") != "ALLOW"
            or payload.get("frequency_policy_state") != "ALLOW"
        ):
            decision = "BLOCK"
            reasons.append("auto_contact_allowed conflicts with opt-out/frequency/quiet-hours state")
    if payload.get("primary_contact_flag") and payload.get("contact_candidate_rank", 99) != 1:
        decision = "REVIEW"
        reasons.append("primary_contact_flag requires contact_candidate_rank=1")
    return decision, reasons, {"semantic_context_snapshot": context}


def _semantic_outreach_plan(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if payload.get("saleability_status") != context.get("upstream_saleability_status"):
        decision = "BLOCK"
        reasons.append("outreach_plan.saleability_status must stay aligned with upstream opportunity")
    if payload.get("plan_status") == "APPROVED":
        if payload.get("approval_state") != "APPROVED":
            decision = "BLOCK"
            reasons.append("APPROVED outreach_plan requires approval_state=APPROVED")
        if context.get("contact_target_status") != "ELIGIBLE":
            decision = "BLOCK"
            reasons.append("APPROVED outreach_plan requires ELIGIBLE contact_target")
    if context.get("upstream_saleability_status") == "BLOCKED" and payload.get("plan_status") in ("APPROVED", "SCHEDULED"):
        decision = "BLOCK"
        reasons.append("Stage8 may not recompute blocked saleability into runnable outreach plan")
    if payload.get("run_mode") == "DRY_RUN" and payload.get("projection_mode") == "REAL_EXECUTION_CONTROLLED_OPENING_REQUIRED":
        decision = "REVIEW"
        reasons.append("DRY_RUN plan should not project real execution mode")
    return decision, reasons, {"semantic_context_snapshot": context}


def _semantic_touch_record(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if payload.get("saleability_status") != context.get("upstream_saleability_status"):
        decision = "BLOCK"
        reasons.append("touch_record.saleability_status must stay aligned with upstream opportunity")
    if payload.get("touch_record_state") in ("SENT", "RESPONDED") and context.get("plan_status") != "APPROVED":
        decision = "BLOCK"
        reasons.append("touch_record SENT/RESPONDED requires approved plan")
    if context.get("upstream_saleability_status") == "BLOCKED" and payload.get("touch_record_state") != "CANCELLED":
        decision = "BLOCK"
        reasons.append("blocked saleability may not produce non-cancelled touch_record")
    if payload.get("response_status") in (
        "NO_RESPONSE",
        "DECLINED",
        "OPTED_OUT",
        "WRONG_ROLE",
        "INVALID_CONTACT",
        "OPPORTUNITY_CHANGED",
    ) and not payload.get("written_back_at_optional"):
        decision = "BLOCK"
        reasons.append("failed or negative touch_record requires written_back_at_optional")
    if not payload.get("writeback_targets"):
        decision = "BLOCK"
        reasons.append("touch_record requires writeback_targets")
    return decision, reasons, {"semantic_context_snapshot": context}


def _semantic_order_record(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if payload.get("governed_execution_mode") != "INTERNAL_GOVERNED":
        decision = "BLOCK"
        reasons.append("order_record must remain INTERNAL_GOVERNED only")
    if payload.get("saleability_status") != context.get("saleability_status"):
        decision = "BLOCK"
        reasons.append("order_record.saleability_status must stay aligned with upstream opportunity")
    if payload.get("crm_owner_state") != context.get("crm_owner_state"):
        decision = "BLOCK"
        reasons.append("order_record.crm_owner_state must stay aligned with upstream opportunity")
    if payload.get("plan_status") != context.get("plan_status"):
        decision = "BLOCK"
        reasons.append("order_record.plan_status must consume H-08 preview state")
    if payload.get("touch_record_state") != context.get("touch_record_state"):
        decision = "BLOCK"
        reasons.append("order_record.touch_record_state must consume H-08 writeback state")
    if payload.get("touch_record_state") == "CANCELLED" and payload.get("order_status") not in ("ON_HOLD", "PENDING_APPROVAL"):
        decision = "BLOCK"
        reasons.append("cancelled touch_record may not produce active order state")
    if context.get("saleability_status") == "BLOCKED" and payload.get("order_status") not in ("ON_HOLD", "PENDING_APPROVAL"):
        decision = "BLOCK"
        reasons.append("blocked upstream saleability may not produce ready order state")
    if context.get("governance_decision_state") == "BLOCK" and payload.get("order_status") not in ("ON_HOLD", "PENDING_APPROVAL"):
        decision = "BLOCK"
        reasons.append("blocked upstream governance may not produce ready order state")
    return decision, reasons, {"semantic_context_snapshot": context}


def _semantic_payment_record(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if payload.get("governed_execution_mode") != "INTERNAL_GOVERNED":
        decision = "BLOCK"
        reasons.append("payment_record must remain INTERNAL_GOVERNED only")
    if payload.get("payment_status") == "PAID" and payload.get("payment_proof_state") == "NOT_PROVIDED":
        decision = "BLOCK"
        reasons.append("PAID payment requires payment proof")
    if context.get("payer_mismatch_state") not in (None, "", "NO_MISMATCH") and payload.get("payment_status") == "PAID":
        decision = "BLOCK"
        reasons.append("payer mismatch conflicts with PAID payment state")
    if payload.get("payer_match_state") == "MISMATCHED" and payload.get("payment_status") in ("PAID", "PARTIALLY_PAID"):
        decision = "BLOCK"
        reasons.append("payer_match_state=MISMATCHED conflicts with paid payment state")
    if payload.get("amount_match_state") == "MISMATCHED" and payload.get("payment_status") == "PAID":
        decision = "BLOCK"
        reasons.append("amount_match_state=MISMATCHED conflicts with PAID payment state")
    if payload.get("refund_state") not in (None, "", "NOT_REQUESTED"):
        if not payload.get("refund_amount_band_optional"):
            decision = "BLOCK"
            reasons.append("refund workflow requires refund_amount_band_optional")
        if payload.get("refund_state") == "COMPLETED" and payload.get("payment_status") != "REFUNDED":
            decision = "BLOCK"
            reasons.append("completed refund requires REFUNDED payment_status")
    return decision, reasons, {"semantic_context_snapshot": context}


def _semantic_delivery_record(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if payload.get("governed_execution_mode") != "INTERNAL_GOVERNED":
        decision = "BLOCK"
        reasons.append("delivery_record must remain INTERNAL_GOVERNED only")
    if context.get("saleability_status") == "BLOCKED" and payload.get("delivery_status") != "RELEASE_BLOCKED":
        decision = "BLOCK"
        reasons.append("blocked upstream saleability requires RELEASE_BLOCKED delivery state")
    if context.get("plan_status") in ("BLOCKED", "CANCELLED", "REJECTED") and payload.get("delivery_status") not in ("RELEASE_BLOCKED", "NOT_READY"):
        decision = "BLOCK"
        reasons.append("blocked plan_status may not produce delivery-ready state")
    if context.get("touch_record_state") == "CANCELLED" and payload.get("delivery_status") not in ("RELEASE_BLOCKED", "NOT_READY"):
        decision = "BLOCK"
        reasons.append("cancelled touch_record may not produce delivery-ready state")
    if payload.get("delivery_status") == "DELIVERED" and payload.get("archival_status") != "ARCHIVED":
        decision = "REVIEW"
        reasons.append("DELIVERED without ARCHIVED requires review")
    if payload.get("delivery_status") == "DELIVERED" and payload.get("retrieval_status") == "FAILED":
        decision = "BLOCK"
        reasons.append("DELIVERED conflicts with retrieval failure")
    return decision, reasons, {"semantic_context_snapshot": context}


def _semantic_opportunity_outcome_event(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if payload.get("governed_execution_mode") != "INTERNAL_GOVERNED":
        decision = "BLOCK"
        reasons.append("outcome event must remain INTERNAL_GOVERNED only")
    if payload.get("outcome_family") == "WON" and context.get("delivery_status") == "RELEASE_BLOCKED":
        decision = "BLOCK"
        reasons.append("WON outcome conflicts with blocked delivery")
    if payload.get("feedback_reason") and payload.get("feedback_reason") not in payload.get("outcome_reason_tags", []):
        decision = "REVIEW"
        reasons.append("feedback_reason should be reflected in outcome_reason_tags when present")
    if context.get("governance_decision_state") == "BLOCK" and payload.get("outcome_family") == "WON":
        decision = "BLOCK"
        reasons.append("blocked governance may not emit WON outcome")
    if not payload.get("writeback_targets"):
        decision = "BLOCK"
        reasons.append("outcome event requires writeback targets")
    return decision, reasons, {"semantic_context_snapshot": context}


def _semantic_governance_feedback_event(payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    decision = "ALLOW"
    if payload.get("governed_execution_mode") != "INTERNAL_GOVERNED":
        decision = "BLOCK"
        reasons.append("governance feedback must remain INTERNAL_GOVERNED only")
    if not payload.get("trigger_type") or not payload.get("action_taken"):
        decision = "BLOCK"
        reasons.append("governance feedback requires trigger_type and action_taken")
    if not payload.get("writeback_targets"):
        decision = "BLOCK"
        reasons.append("governance feedback requires writeback_targets")
    return decision, reasons, {"semantic_context_snapshot": context}


__all__ = [
    "_semantic_contact_target",
    "_semantic_delivery_record",
    "_semantic_governance_feedback_event",
    "_semantic_opportunity_outcome_event",
    "_semantic_order_record",
    "_semantic_outreach_plan",
    "_semantic_payment_record",
    "_semantic_touch_record",
]
