from __future__ import annotations

from typing import Any, Mapping


_LIVE_ACTION_KEYWORDS = (
    "real_outreach",
    "live_outreach",
    "customer_outreach",
    "leadpack_send",
    "external_send",
    "real_payment",
    "live_payment",
    "charge",
    "delivery_fulfillment",
    "customer_download",
    "real_delivery",
    "real_refund",
    "automatic_refund",
    "auto_refund",
)


class TransitionGuard:
    def safety_envelope(self) -> dict[str, bool]:
        return {
            "external_customer_action_enabled": False,
            "customer_visible_download_enabled": False,
            "real_outreach_enabled": False,
            "real_payment_enabled": False,
            "real_delivery_enabled": False,
            "real_refund_enabled": False,
            "automatic_refund_enabled": False,
        }

    def controlled_boundary_projection(self) -> dict[str, Any]:
        safety = self.safety_envelope()
        return {
            "stage8_outreach_boundary_state": "CONTROLLED_OPENING_PREREQUISITES_ONLY",
            "stage9_payment_delivery_refund_boundary_state": "CONTROLLED_OPENING_PREREQUISITES_ONLY",
            "automatic_refund_policy_state": "EXCLUDED",
            "required_before_live_execution": [
                "release_checklist_passed",
                "approval_chain_passed",
                "audit_chain_ready",
                "operator_action_confirmed",
            ],
            "blocked_action_families": [
                "real_outreach",
                "real_payment",
                "real_delivery",
                "real_refund",
                "automatic_refund",
            ],
            "operator_next_action": "complete_release_approval_audit_and_operator_action_before_live_execution",
            "external_customer_action_enabled": safety["external_customer_action_enabled"],
            "real_outreach_enabled": safety["real_outreach_enabled"],
            "real_payment_enabled": safety["real_payment_enabled"],
            "real_delivery_enabled": safety["real_delivery_enabled"],
            "real_refund_enabled": safety["real_refund_enabled"],
            "automatic_refund_enabled": safety["automatic_refund_enabled"],
            "customer_visible_allowed": False,
        }

    def guarded_next_action(self, raw_action: Any) -> dict[str, Any]:
        if isinstance(raw_action, Mapping):
            return self._guard_action_mapping(raw_action)
        text = str(raw_action or "").strip()
        if not text:
            return {"action_type": "REVIEW", "entrypoint_id": "", "reason": "next_action_missing"}
        if text.startswith("run_"):
            return self._guard_entrypoint(entrypoint_id=text[4:], reason=text)
        return self._guard_entrypoint(entrypoint_id=text, reason=text)

    def _guard_action_mapping(self, raw_action: Mapping[str, Any]) -> dict[str, Any]:
        action = dict(raw_action)
        entrypoint_id = str(action.get("entrypoint_id") or "").strip()
        reason = str(action.get("reason") or entrypoint_id or action.get("action_type") or "").strip()
        if entrypoint_id:
            guarded = self._guard_entrypoint(entrypoint_id=entrypoint_id, reason=reason)
            if guarded.get("action_type") != "ENTRYPOINT":
                return {**action, **guarded}
        action["external_customer_action_enabled"] = False
        return action

    def _guard_entrypoint(self, *, entrypoint_id: str, reason: str) -> dict[str, Any]:
        normalized_entrypoint = str(entrypoint_id or "").strip()
        if _looks_like_live_external_action(normalized_entrypoint) or _looks_like_live_external_action(reason):
            return {
                "action_type": "OPERATOR_ACTION",
                "entrypoint_id": "",
                "reason": reason or normalized_entrypoint,
                "review_family": "controlled_live_boundary_review",
                "review_state": "BLOCKED_UNTIL_RELEASE_APPROVAL_AUDIT_AND_OPERATOR_ACTION",
                "blocking_reasons": ["live_external_action_not_gated"],
                "operator_next_action": "complete_release_approval_audit_and_operator_action_before_live_execution",
                "external_customer_action_enabled": False,
                "customer_visible_allowed": False,
            }
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": normalized_entrypoint,
            "reason": reason,
            "external_customer_action_enabled": False,
        }


def _looks_like_live_external_action(value: str) -> bool:
    text = str(value or "").lower()
    return any(keyword in text for keyword in _LIVE_ACTION_KEYWORDS)
