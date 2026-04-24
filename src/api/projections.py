from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from api.workbench_observability import (
    TRACE_FIELDS,
    collect_candidate_surface_block_reasons,
    collect_governed_context,
    collect_trace_refs,
    merge_trace_refs,
    missing_audit_refs,
)
from stage8_outreach.execution_outbox import (
    OUTBOX_READINESS_INPUT_KEY,
    OUTBOX_SNAPSHOT_INPUT_KEY,
    build_outbox_readiness_summary,
)
from shared.contract_loader import load_contract
from shared.contracts_runtime import ContractRecord, StageBundle
from storage.operator_loop_contracts import (
    build_operator_context_projection,
    build_workbench_replay_projection,
    sanitize_transient_preview_context,
)
from storage.repository_boundary import (
    _surface_state_for_bundle,
    get_operational_context,
    get_transient_preview_context,
    hydrate_stage_bundle,
)

_collect_governed_context = collect_governed_context
_collect_trace_refs = collect_trace_refs
_merge_trace_refs = merge_trace_refs
_missing_audit_refs = missing_audit_refs


BLOCKED_STATUSES = {
    "BLOCKED",
    "RELEASE_BLOCKED",
    "CANCELLED",
    "FAILED",
    "INVALID",
    "TERMINATED",
}
REVIEW_STATUSES = {
    "REVIEW_REQUIRED",
    "PENDING_APPROVAL",
    "APPROVAL_PENDING",
    "ACK_PENDING",
}
HOLD_STATUSES = {
    "ON_HOLD",
    "NOT_READY",
    "SCHEDULED",
    "PENDING_PAYMENT",
    "NOT_STARTED",
}
PRIMARY_STATUS_FIELD_MAP = {
    "project_fact": ("sale_gate_status", "competitor_quality_grade"),
    "report_record": ("report_status", "review_task_status"),
    "review_queue_profile": ("review_lane", "review_queue_bucket"),
    "challenger_candidate_profile": ("candidate_position_label",),
    "legal_action_recommendation": ("window_status", "action_family"),
    "saleable_opportunity": ("saleability_status", "opportunity_grade"),
    "offer_recommendation": ("offer_recommendation_state", "recommended_delivery_form"),
    "buyer_fit": ("buyer_type",),
    "legal_action_actor_profile": ("actionability_state",),
    "procurement_decision_actor_profile": ("reachable_state",),
    "contact_target": ("contact_target_status", "contact_validity_status"),
    "outreach_plan": ("plan_status", "approval_state"),
    "touch_record": ("touch_record_state", "response_status"),
    "order_record": ("order_status", "commercial_status"),
    "payment_record": ("payment_status", "refund_state"),
    "delivery_record": ("delivery_status", "archival_status"),
    "opportunity_outcome_event": ("outcome_family",),
    "governance_feedback_event": ("trigger_type",),
}
PRIMARY_ID_FIELD_MAP = {
    "project_fact": "project_fact_id",
    "report_record": "report_id",
    "review_queue_profile": "queue_profile_id",
    "challenger_candidate_profile": "challenger_profile_id",
    "legal_action_recommendation": "action_id",
    "saleable_opportunity": "opportunity_id",
    "offer_recommendation": "offer_recommendation_id",
    "buyer_fit": "buyer_fit_id",
    "legal_action_actor_profile": "actor_id",
    "procurement_decision_actor_profile": "actor_id",
    "contact_target": "contact_target_id",
    "outreach_plan": "outreach_plan_id",
    "touch_record": "touch_record_id",
    "order_record": "order_id",
    "payment_record": "payment_id",
    "delivery_record": "delivery_id",
    "opportunity_outcome_event": "outcome_event_id",
    "governance_feedback_event": "governance_feedback_event_id",
}
ID_FIELDS = (
    "project_fact_id",
    "report_id",
    "queue_profile_id",
    "challenger_profile_id",
    "action_id",
    "opportunity_id",
    "offer_recommendation_id",
    "buyer_fit_id",
    "actor_id",
    "contact_target_id",
    "outreach_plan_id",
    "touch_record_id",
    "order_id",
    "payment_id",
    "delivery_id",
    "outcome_event_id",
    "governance_feedback_event_id",
)
SURFACE_STATE_PROFILE_REFS = {
    "opportunity_pool": "stage7_internal_preview_surface",
    "outreach_workbench": "stage8_governed_preview_surface",
    "order_delivery_workbench": "stage9_internal_governed_surface",
}
SURFACE_CAPABILITY_MODES = {
    "review_report_workbench": "INTERNAL_ONLY",
    "opportunity_pool": "INTERNAL_ONLY",
    "outreach_workbench": "INTERNAL_GOVERNED",
    "order_delivery_workbench": "INTERNAL_GOVERNED",
}
SURFACE_CAPABILITY_FAMILIES = {
    "opportunity_pool": ("delivery_export_variants",),
    "outreach_workbench": ("stage8_execution", "contact_enrichment", "risky_automation"),
    "order_delivery_workbench": ("stage9_execution", "delivery_export_variants", "risky_automation"),
}
SURFACE_RUNTIME_DEFAULTS = {
    "review_report_workbench": {
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
        "release_layer": "INTERNAL_OPERABLE",
    },
    "opportunity_pool": {
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
        "release_layer": "INTERNAL_OPERABLE",
    },
    "outreach_workbench": {
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        "release_layer": "INTERNAL_OPERABLE",
    },
    "order_delivery_workbench": {
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        "release_layer": "INTERNAL_OPERABLE",
    },
}

STAGE6_TYPED_REF_KEYS = (
    "project_fact_id",
    "report_record_id",
    "review_queue_profile_id",
    "challenger_candidate_profile_id",
    "action_id",
)


def _resolve_bundle(payload: Any, stage_key: str) -> StageBundle:
    if isinstance(payload, StageBundle):
        return payload
    if isinstance(payload, Mapping):
        candidate = payload.get(stage_key)
        if isinstance(candidate, StageBundle):
            return candidate
        for value in payload.values():
            if isinstance(value, StageBundle):
                return value
        hydrated = hydrate_stage_bundle(stage_key, payload)
        if hydrated is not None:
            return hydrated
    raise TypeError(f"payload must include a StageBundle for {stage_key}")


def _record_data(record: ContractRecord | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, ContractRecord):
        return dict(record.data)
    return dict(record)


def _record_id(record: Mapping[str, Any], object_type: str) -> str:
    primary_id_field = PRIMARY_ID_FIELD_MAP.get(object_type)
    if primary_id_field:
        primary_value = record.get(primary_id_field)
        if primary_value:
            return str(primary_value)
    for field_name in ID_FIELDS:
        value = record.get(field_name)
        if value:
            return str(value)
    return "UNKNOWN"


def _record_status(record: Mapping[str, Any], object_type: str) -> str:
    for field_name in PRIMARY_STATUS_FIELD_MAP.get(object_type, ()):
        value = record.get(field_name)
        if value not in (None, ""):
            return str(value)
    return "UNKNOWN"


def get_surface_runtime_defaults(surface_id: str) -> dict[str, Any]:
    return dict(SURFACE_RUNTIME_DEFAULTS[surface_id])


@lru_cache
def _runtime_inventory() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    runtime_inventory_path = repo_root / "control" / "runtime_inventory.yaml"
    return yaml.safe_load(runtime_inventory_path.read_text(encoding="utf-8"))


def _decision_states(bundle: StageBundle, record: Mapping[str, Any] | None = None) -> dict[str, str]:
    source = record or {}
    return {
        "permission_decision_state": str(
            source.get("permission_decision_state", bundle.inputs.get("permission_decision_state", "ALLOW"))
        ),
        "governance_decision_state": str(
            source.get("governance_decision_state", bundle.inputs.get("governance_decision_state", "ALLOW"))
        ),
        "semantic_decision_state": str(
            source.get("semantic_decision_state", bundle.inputs.get("semantic_decision_state", "ALLOW"))
        ),
        "policy_decision_state": str(bundle.inputs.get("policy_decision_state", "ALLOW")),
    }


def _formal_object_ref(bundle: StageBundle, object_type: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "object_type": object_type,
        "object_id": _record_id(record, object_type),
        "primary_status": _record_status(record, object_type),
        "decision_states": _decision_states(bundle, record),
        "governed_metadata": dict(record.get("governed_metadata", {})),
        "trace_refs": {
            key: record.get(key)
            for key in TRACE_FIELDS
            if record.get(key) not in (None, "")
        },
    }


def _canonical_surface_state(bundle: StageBundle, *, default_mode: str) -> str:
    return _surface_state_for_bundle(bundle, default_mode=default_mode)


def _state_reasons_for_canonical_surface(
    *,
    surface_state: str,
    decision_states: Mapping[str, str],
    primary_statuses: Mapping[str, str],
) -> list[str]:
    reasons: list[str] = []

    for decision_name, decision_value in decision_states.items():
        if surface_state == "blocked" and decision_value == "BLOCK":
            reasons.append(f"decision_state:{decision_name}=BLOCK")
        elif surface_state == "review-required" and decision_value == "REVIEW":
            reasons.append(f"decision_state:{decision_name}=REVIEW")

    review_statuses = set(REVIEW_STATUSES)
    hold_statuses = set(HOLD_STATUSES)
    if surface_state == "governed-hold":
        hold_statuses.add("PENDING_APPROVAL")
        review_statuses.discard("PENDING_APPROVAL")

    for object_type, primary_status in primary_statuses.items():
        if surface_state == "blocked" and primary_status in BLOCKED_STATUSES:
            reasons.append(f"formal_status:{object_type}={primary_status}")
        elif surface_state == "review-required" and primary_status in review_statuses:
            reasons.append(f"formal_status:{object_type}={primary_status}")
        elif surface_state == "governed-hold" and primary_status in hold_statuses:
            reasons.append(f"formal_status:{object_type}={primary_status}")

    if reasons:
        return reasons
    return [f"canonical_surface_state={surface_state}"]


def _surface_access(surface_state: str) -> str:
    return "internal-readable" if surface_state in {"blocked", "review-required"} else "internal-operable"


def _capability_envelope(
    *,
    surface_id: str,
    default_mode: str,
    release_layer: str,
    blocked_by_default: bool,
) -> dict[str, Any]:
    family_projection_index = _runtime_inventory().get("capability_family_state_projection", {})
    capability_family_refs = []
    for capability_family in SURFACE_CAPABILITY_FAMILIES.get(surface_id, ()):
        projection = dict(family_projection_index.get(capability_family, {}))
        capability_family_refs.append(
            {
                "capability_family": capability_family,
                "projected_current_mode": projection.get("projected_current_mode"),
                "projected_release_layer_ceiling": projection.get("projected_release_layer_ceiling"),
                "projected_from": projection.get("projected_from"),
                "projection_only": bool(projection.get("projection_only", True)),
            }
        )

    return {
        "surface_state_profile_ref": SURFACE_STATE_PROFILE_REFS.get(surface_id, "UNKNOWN_SURFACE_PROFILE"),
        "surface_capability_mode": SURFACE_CAPABILITY_MODES.get(surface_id, "INTERNAL_ONLY"),
        "surface_mode": default_mode,
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": blocked_by_default,
        "formalization_scope": "INTERNAL_GOVERNED" if blocked_by_default else "INTERNAL_ONLY",
        "release_layer": release_layer,
        "capability_family_refs": capability_family_refs,
        "projection_source": "control/runtime_inventory.yaml#capability_family_state_projection",
    }


def _action_gate(
    *,
    allowed: bool,
    surface_state: str,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "allowed": allowed,
        "surface_state": surface_state,
        "blocked_reason": blocked_reason,
        "review_required": surface_state == "review-required",
    }


def _action_availability(
    *,
    surface_id: str,
    surface_state: str,
    primary_statuses: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    blocked = surface_state == "blocked"
    review_required = surface_state == "review-required"

    if surface_id == "review_report_workbench":
        return {
            "previewStage6ReviewReportWorkbench": _action_gate(
                allowed=True,
                surface_state=surface_state,
                blocked_reason=None,
            ),
            "listStage6WorkItems": _action_gate(
                allowed=True,
                surface_state=surface_state,
                blocked_reason=None,
            ),
        }

    if surface_id == "opportunity_pool":
        return {
            "listSaleableOpportunities": _action_gate(allowed=True, surface_state=surface_state),
            "refreshSaleableOpportunity": _action_gate(
                allowed=not blocked,
                surface_state=surface_state,
                blocked_reason="canonical_surface_blocked" if blocked else None,
            ),
        }

    if surface_id == "outreach_workbench":
        return {
            "listContactTargets": _action_gate(allowed=True, surface_state=surface_state),
            "checkContactCompliance": _action_gate(allowed=True, surface_state=surface_state),
            "createOutreachPlan": _action_gate(
                allowed=not blocked,
                surface_state=surface_state,
                blocked_reason="canonical_surface_blocked" if blocked else None,
            ),
            "createTouchRecord": _action_gate(
                allowed=not blocked and not review_required,
                surface_state=surface_state,
                blocked_reason=(
                    "canonical_surface_blocked"
                    if blocked
                    else "canonical_surface_review_required"
                    if review_required
                    else None
                ),
            ),
        }

    order_status = primary_statuses.get("order_record")
    payment_status = primary_statuses.get("payment_record")
    return {
        "listOrders": _action_gate(allowed=True, surface_state=surface_state),
        "createOrder": _action_gate(
            allowed=not blocked and order_status != "ON_HOLD",
            surface_state=surface_state,
            blocked_reason=(
                "formal_status:order_record=ON_HOLD"
                if order_status == "ON_HOLD"
                else "canonical_surface_blocked"
                if blocked
                else None
            ),
        ),
        "createPaymentRecord": _action_gate(
            allowed=not blocked and payment_status != "PAYMENT_EXCEPTION",
            surface_state=surface_state,
            blocked_reason=(
                "formal_status:payment_record=PAYMENT_EXCEPTION"
                if payment_status == "PAYMENT_EXCEPTION"
                else "canonical_surface_blocked"
                if blocked
                else None
            ),
        ),
        "createDeliveryRecord": _action_gate(allowed=True, surface_state=surface_state),
        "listOpportunityOutcomes": _action_gate(allowed=True, surface_state=surface_state),
        "createOpportunityOutcomeEvent": _action_gate(
            allowed=not blocked and not review_required,
            surface_state=surface_state,
            blocked_reason=(
                "canonical_surface_blocked"
                if blocked
                else "canonical_surface_review_required"
                if review_required
                else None
            ),
        ),
        "listGovernanceFeedbackEvents": _action_gate(allowed=True, surface_state=surface_state),
        "createGovernanceFeedbackEvent": _action_gate(
            allowed=not blocked and not review_required,
            surface_state=surface_state,
            blocked_reason=(
                "canonical_surface_blocked"
                if blocked
                else "canonical_surface_review_required"
                if review_required
                else None
            ),
        ),
    }


def _governance_envelope(
    *,
    decision_states: Mapping[str, str],
    governed_context: Mapping[str, Any],
    action_availability: Mapping[str, Mapping[str, Any]],
    surface_state: str,
) -> dict[str, Any]:
    return {
        "decision_states": dict(decision_states),
        "governed_context": dict(governed_context),
        "review_required": surface_state == "review-required",
        "blocked": surface_state == "blocked",
        "governed_hold": surface_state == "governed-hold",
        "action_availability": {key: dict(value) for key, value in action_availability.items()},
    }


def _semantic_envelope(
    *,
    surface_state: str,
    primary_statuses: Mapping[str, str],
    state_reasons: list[str],
) -> dict[str, Any]:
    return {
        "surface_state": surface_state,
        "surface_access": _surface_access(surface_state),
        "surface_state_source": "storage.repository_boundary._surface_state_for_bundle",
        "primary_statuses": dict(primary_statuses),
        "state_reasons": list(state_reasons),
    }


def _surface_envelope(
    *,
    bundle: StageBundle,
    surface_id: str,
    default_mode: str,
    formal_records: dict[str, Mapping[str, Any]],
    formal_objects: dict[str, dict[str, Any]],
    preview_projection: dict[str, Any],
    release_layer: str = "INTERNAL_OPERABLE",
    blocked_by_default: bool = False,
) -> dict[str, Any]:
    decision_states = _decision_states(bundle)
    primary_statuses = {
        object_type: formal_object["primary_status"]
        for object_type, formal_object in formal_objects.items()
    }
    governed_context = _collect_governed_context(formal_records, default_mode=default_mode)
    surface_state = _canonical_surface_state(bundle, default_mode=default_mode)
    state_reasons = _state_reasons_for_canonical_surface(
        surface_state=surface_state,
        decision_states=decision_states,
        primary_statuses=primary_statuses,
    )
    action_availability = _action_availability(
        surface_id=surface_id,
        surface_state=surface_state,
        primary_statuses=primary_statuses,
    )
    capability_envelope = _capability_envelope(
        surface_id=surface_id,
        default_mode=default_mode,
        release_layer=release_layer,
        blocked_by_default=blocked_by_default,
    )
    governance_envelope = _governance_envelope(
        decision_states=decision_states,
        governed_context=governed_context,
        action_availability=action_availability,
        surface_state=surface_state,
    )
    semantic_envelope = _semantic_envelope(
        surface_state=surface_state,
        primary_statuses=primary_statuses,
        state_reasons=state_reasons,
    )
    return {
        "surface_id": surface_id,
        "surface_state": semantic_envelope["surface_state"],
        "surface_mode": capability_envelope["surface_mode"],
        "surface_access": semantic_envelope["surface_access"],
        "internal_only": True,
        "preview_only": default_mode == "preview-only",
        "draft_only": default_mode == "draft-only",
        "live_execution_enabled": False,
        "blocked_by_default": blocked_by_default,
        "formalization_scope": capability_envelope["formalization_scope"],
        "release_layer": release_layer,
        "decision_states": dict(decision_states),
        "capability_envelope": capability_envelope,
        "governance_envelope": governance_envelope,
        "semantic_envelope": semantic_envelope,
        "formal_object_refs": formal_objects,
        "preview_projection": preview_projection,
        "trace_refs": _collect_trace_refs(bundle, list(preview_projection["_raw_records"])),
    }


def _attach_operational_context(envelope: dict[str, Any], bundle: StageBundle) -> dict[str, Any]:
    persisted = get_operational_context(bundle)
    if persisted is not None:
        envelope["operational_loop_persisted"] = True
        envelope["operational_context_status"] = "persisted"
        envelope["persisted_operational_context"] = persisted
        envelope["operator_loop_projection"] = build_operator_context_projection(
            operational_context_status="persisted",
            persisted_context=persisted,
        )
        envelope["workbench_replay"] = build_workbench_replay_projection(
            persisted_context=persisted,
        )
        return envelope
    transient = get_transient_preview_context(bundle)
    envelope["operational_loop_persisted"] = False
    operational_context_status = "transient_preview" if transient is not None else "unavailable"
    envelope["operational_context_status"] = operational_context_status
    if transient is not None:
        envelope["transient_preview_context"] = sanitize_transient_preview_context(transient)
    envelope["operator_loop_projection"] = build_operator_context_projection(
        operational_context_status=operational_context_status,
        transient_context=transient,
    )
    envelope["workbench_replay"] = build_workbench_replay_projection(
        transient_context=transient,
    )
    return envelope


def _stage6_locator_present(payload: Mapping[str, Any]) -> bool:
    return any(
        str(payload.get(key, "")).strip()
        for key in ("project_id", *STAGE6_TYPED_REF_KEYS)
    )


def _stage6_preview_projection(
    project_fact: Mapping[str, Any],
    report_record: Mapping[str, Any],
    review_queue_profile: Mapping[str, Any],
    challenger_candidate_profile: Mapping[str, Any],
    legal_action_recommendation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "project_fact_summary": {
            "project_fact_id": project_fact.get("project_fact_id"),
            "project_id": project_fact.get("project_id"),
            "sale_gate_status": project_fact.get("sale_gate_status"),
            "rule_gate_status": project_fact.get("rule_gate_status"),
            "evidence_gate_status": project_fact.get("evidence_gate_status"),
            "competitor_quality_grade": project_fact.get("competitor_quality_grade"),
            "real_competitor_count": project_fact.get("real_competitor_count"),
            "serviceable_competitor_count": project_fact.get("serviceable_competitor_count"),
        },
        "report_status_summary": {
            "report_id": report_record.get("report_id"),
            "report_status": report_record.get("report_status"),
            "review_task_status": report_record.get("review_task_status"),
            "review_lane": report_record.get("review_lane"),
            "minimum_release_level": report_record.get("minimum_release_level"),
            "review_sla_due_at": report_record.get("review_sla_due_at"),
        },
        "review_queue_summary": {
            "queue_profile_id": review_queue_profile.get("queue_profile_id"),
            "review_lane": review_queue_profile.get("review_lane"),
            "review_priority_score": review_queue_profile.get("review_priority_score"),
            "review_queue_bucket": review_queue_profile.get("review_queue_bucket"),
            "window_risk_level": review_queue_profile.get("window_risk_level"),
            "commercial_urgency_level": review_queue_profile.get("commercial_urgency_level"),
        },
        "challenger_summary": {
            "challenger_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
            "focus_bidder_id": challenger_candidate_profile.get("focus_bidder_id"),
            "challenger_bidder_id": challenger_candidate_profile.get("challenger_bidder_id"),
            "candidate_position_label": challenger_candidate_profile.get("candidate_position_label"),
            "challenge_actionability_score": challenger_candidate_profile.get("challenge_actionability_score"),
            "execution_readiness_score": challenger_candidate_profile.get("execution_readiness_score"),
        },
        "legal_action_summary": {
            "action_id": legal_action_recommendation.get("action_id"),
            "action_family": legal_action_recommendation.get("action_family"),
            "window_status": legal_action_recommendation.get("window_status"),
            "recommended_next_step": legal_action_recommendation.get("recommended_next_step"),
            "blocking_reasons": legal_action_recommendation.get("blocking_reasons"),
        },
        "_raw_records": [
            project_fact,
            report_record,
            review_queue_profile,
            challenger_candidate_profile,
            legal_action_recommendation,
        ],
    }


def _build_stage6_readback_failure_surface(
    payload: Mapping[str, Any],
    *,
    surface_state: str,
    reason: str,
) -> dict[str, Any]:
    surface_defaults = get_surface_runtime_defaults("review_report_workbench")
    decision_states = {
        "permission_decision_state": str(payload.get("permission_decision_state", "ALLOW")),
        "governance_decision_state": str(payload.get("governance_decision_state", "ALLOW")),
        "semantic_decision_state": "BLOCK" if surface_state == "blocked" else "REVIEW",
        "policy_decision_state": "BLOCK" if surface_state == "blocked" else "REVIEW",
    }
    capability_envelope = _capability_envelope(
        surface_id="review_report_workbench",
        default_mode=str(surface_defaults["surface_mode"]),
        release_layer=str(surface_defaults["release_layer"]),
        blocked_by_default=bool(surface_defaults["blocked_by_default"]),
    )
    governance_envelope = _governance_envelope(
        decision_states=decision_states,
        governed_context={
            "repository_readback_status": "failed",
            "repository_readback_reason": reason,
            "requested_project_id": str(payload.get("project_id", "")).strip(),
            "requested_typed_refs": {
                key: str(payload.get(key, "")).strip()
                for key in STAGE6_TYPED_REF_KEYS
                if str(payload.get(key, "")).strip()
            },
        },
        action_availability=_action_availability(
            surface_id="review_report_workbench",
            surface_state=surface_state,
            primary_statuses={},
        ),
        surface_state=surface_state,
    )
    semantic_envelope = _semantic_envelope(
        surface_state=surface_state,
        primary_statuses={},
        state_reasons=[reason],
    )
    return {
        "surface_id": "review_report_workbench",
        "surface_state": semantic_envelope["surface_state"],
        "surface_mode": capability_envelope["surface_mode"],
        "surface_access": semantic_envelope["surface_access"],
        "internal_only": True,
        "preview_only": True,
        "draft_only": False,
        "live_execution_enabled": False,
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
        "formalization_scope": capability_envelope["formalization_scope"],
        "release_layer": str(surface_defaults["release_layer"]),
        "decision_states": dict(decision_states),
        "capability_envelope": capability_envelope,
        "governance_envelope": governance_envelope,
        "semantic_envelope": semantic_envelope,
        "formal_object_refs": {},
        "preview_projection": {
            "project_fact_summary": {"repository_readback_status": "unavailable", "reason": reason},
            "report_status_summary": {"repository_readback_status": "unavailable", "reason": reason},
            "review_queue_summary": {"repository_readback_status": "unavailable", "reason": reason},
            "challenger_summary": {"repository_readback_status": "unavailable", "reason": reason},
            "legal_action_summary": {"repository_readback_status": "unavailable", "reason": reason},
        },
        "trace_refs": {
            "repository_readback_failed": True,
            "requested_project_id": str(payload.get("project_id", "")).strip(),
        },
        "error": {
            "error_code": "STAGE6-REPOSITORY-READBACK-FAILED",
            "message": reason,
            "meta": {
                "trace_id": "stage6_preview_readback_failed",
                "source_refs": ["storage.repository_boundary.hydrate_stage6_bundle"],
            },
        },
    }


def build_stage6_preview_surface(payload: Any) -> dict[str, Any]:
    bundle: StageBundle | None = None
    if isinstance(payload, StageBundle):
        bundle = payload
    elif isinstance(payload, Mapping):
        bundle = hydrate_stage_bundle("stage6", payload)
        if bundle is None and _stage6_locator_present(payload):
            typed_ref_failure = any(str(payload.get(key, "")).strip() for key in STAGE6_TYPED_REF_KEYS)
            return _build_stage6_readback_failure_surface(
                payload,
                surface_state="blocked" if typed_ref_failure else "review-required",
                reason=(
                    "stage6_repository_readback_failed:typed_refs_unresolved"
                    if typed_ref_failure
                    else "stage6_repository_readback_failed:project_not_persisted"
                ),
            )
        stage6_candidate = payload.get("stage6")
        if bundle is None and isinstance(stage6_candidate, StageBundle):
            bundle = stage6_candidate
        if bundle is None:
            for value in payload.values():
                if isinstance(value, StageBundle) and value.stage == 6:
                    bundle = value
                    break
    if bundle is None:
        raise TypeError("payload must include a StageBundle for stage6 or repository-backed stage6 refs")

    surface_defaults = get_surface_runtime_defaults("review_report_workbench")
    project_fact = _record_data(bundle.record("project_fact"))
    report_record = _record_data(bundle.record("report_record"))
    review_queue_profile = _record_data(bundle.record("review_queue_profile"))
    challenger_candidate_profile = _record_data(bundle.record("challenger_candidate_profile"))
    legal_action_recommendation = _record_data(bundle.record("legal_action_recommendation"))
    formal_records = {
        "project_fact": project_fact,
        "report_record": report_record,
        "review_queue_profile": review_queue_profile,
        "challenger_candidate_profile": challenger_candidate_profile,
        "legal_action_recommendation": legal_action_recommendation,
    }
    formal_objects = {
        "project_fact": _formal_object_ref(bundle, "project_fact", project_fact),
        "report_record": _formal_object_ref(bundle, "report_record", report_record),
        "review_queue_profile": _formal_object_ref(bundle, "review_queue_profile", review_queue_profile),
        "challenger_candidate_profile": _formal_object_ref(
            bundle,
            "challenger_candidate_profile",
            challenger_candidate_profile,
        ),
        "legal_action_recommendation": _formal_object_ref(
            bundle,
            "legal_action_recommendation",
            legal_action_recommendation,
        ),
    }
    preview_projection = _stage6_preview_projection(
        project_fact,
        report_record,
        review_queue_profile,
        challenger_candidate_profile,
        legal_action_recommendation,
    )
    envelope = _surface_envelope(
        bundle=bundle,
        surface_id="review_report_workbench",
        default_mode=str(surface_defaults["surface_mode"]),
        formal_records=formal_records,
        formal_objects=formal_objects,
        preview_projection=preview_projection,
        release_layer=str(surface_defaults["release_layer"]),
        blocked_by_default=bool(surface_defaults["blocked_by_default"]),
    )
    envelope["preview_projection"].pop("_raw_records", None)
    return _attach_operational_context(envelope, bundle)


def build_stage7_preview_surface(payload: Any) -> dict[str, Any]:
    bundle = _resolve_bundle(payload, "stage7")
    surface_defaults = get_surface_runtime_defaults("opportunity_pool")
    opportunity = _record_data(bundle.record("saleable_opportunity"))
    offer = _record_data(bundle.record("offer_recommendation"))
    buyer_fit = _record_data(bundle.record("buyer_fit"))
    legal_actor = _record_data(bundle.record("legal_action_actor_profile"))
    procurement_actor = _record_data(bundle.record("procurement_decision_actor_profile"))
    formal_records = {
        "saleable_opportunity": opportunity,
        "offer_recommendation": offer,
        "buyer_fit": buyer_fit,
        "legal_action_actor_profile": legal_actor,
        "procurement_decision_actor_profile": procurement_actor,
    }
    formal_objects = {
        "saleable_opportunity": _formal_object_ref(bundle, "saleable_opportunity", opportunity),
        "offer_recommendation": _formal_object_ref(bundle, "offer_recommendation", offer),
        "buyer_fit": _formal_object_ref(bundle, "buyer_fit", buyer_fit),
        "legal_action_actor_profile": _formal_object_ref(bundle, "legal_action_actor_profile", legal_actor),
        "procurement_decision_actor_profile": _formal_object_ref(bundle, "procurement_decision_actor_profile", procurement_actor),
    }
    preview_projection = {
        "opportunity_summary": {
            "opportunity_id": opportunity.get("opportunity_id"),
            "saleability_status": opportunity.get("saleability_status"),
            "opportunity_grade": opportunity.get("opportunity_grade"),
            "recommended_sku": opportunity.get("recommended_sku"),
            "crm_owner_state": opportunity.get("crm_owner_state"),
        },
        "offer_summary": {
            "offer_recommendation_state": offer.get("offer_recommendation_state"),
            "sku_code": offer.get("sku_code"),
            "recommended_delivery_form": offer.get("recommended_delivery_form"),
            "recommended_quote_band": offer.get("recommended_quote_band"),
        },
        "buyer_fit_summary": {
            "buyer_type": buyer_fit.get("buyer_type"),
            "fit_score": buyer_fit.get("fit_score"),
            "fit_reason_tags": buyer_fit.get("fit_reason_tags"),
        },
        "actor_preview": [
            {
                "actor_id": legal_actor.get("actor_id"),
                "actor_org_name": legal_actor.get("actor_org_name"),
                "actor_role_cluster": legal_actor.get("actor_role_cluster"),
                "actionability_state": legal_actor.get("actionability_state"),
            },
            {
                "actor_id": procurement_actor.get("actor_id"),
                "actor_org_name": procurement_actor.get("actor_org_name"),
                "actor_role_cluster": procurement_actor.get("actor_role_cluster"),
                "reachable_state": procurement_actor.get("reachable_state"),
            },
        ],
        "_raw_records": [opportunity, offer, buyer_fit, legal_actor, procurement_actor],
    }
    envelope = _surface_envelope(
        bundle=bundle,
        surface_id="opportunity_pool",
        default_mode=str(surface_defaults["surface_mode"]),
        formal_records=formal_records,
        formal_objects=formal_objects,
        preview_projection=preview_projection,
        release_layer=str(surface_defaults["release_layer"]),
        blocked_by_default=bool(surface_defaults["blocked_by_default"]),
    )
    envelope["preview_projection"].pop("_raw_records", None)
    return _attach_operational_context(envelope, bundle)


def build_stage8_preview_surface(payload: Any) -> dict[str, Any]:
    bundle = _resolve_bundle(payload, "stage8")
    surface_defaults = get_surface_runtime_defaults("outreach_workbench")
    contact = _record_data(bundle.record("contact_target"))
    outreach = _record_data(bundle.record("outreach_plan"))
    touch = _record_data(bundle.record("touch_record"))
    outbox = dict(bundle.inputs.get(OUTBOX_SNAPSHOT_INPUT_KEY, {}))
    outbox_summary = (
        dict(bundle.inputs.get(OUTBOX_READINESS_INPUT_KEY, {}))
        if isinstance(bundle.inputs.get(OUTBOX_READINESS_INPUT_KEY), Mapping)
        else build_outbox_readiness_summary(outbox)
        if outbox
        else {}
    )
    formal_records = {
        "contact_target": contact,
        "outreach_plan": outreach,
        "touch_record": touch,
    }
    formal_objects = {
        "contact_target": _formal_object_ref(bundle, "contact_target", contact),
        "outreach_plan": _formal_object_ref(bundle, "outreach_plan", outreach),
        "touch_record": _formal_object_ref(bundle, "touch_record", touch),
    }
    preview_projection = {
        "contact_target_preview": {
            "contact_target_id": contact.get("contact_target_id"),
            "contact_target_status": contact.get("contact_target_status"),
            "role_cluster": contact.get("role_cluster"),
            "contact_channel": contact.get("contact_channel"),
            "contact_validity_status": contact.get("contact_validity_status"),
            "contact_legal_basis": contact.get("contact_legal_basis"),
            "requires_manual_review": contact.get("requires_manual_review"),
            "blocking_reasons": contact.get("blocking_reasons"),
        },
        "outreach_plan_preview": {
            "outreach_plan_id": outreach.get("outreach_plan_id"),
            "plan_status": outreach.get("plan_status"),
            "approval_state": outreach.get("approval_state"),
            "projection_mode": outreach.get("projection_mode"),
            "run_mode": outreach.get("run_mode"),
            "requested_delivery_surface": outreach.get("requested_delivery_surface"),
            "retry_policy_id": outreach.get("retry_policy_id"),
            "stop_policy_id": outreach.get("stop_policy_id"),
            "governed_metadata": outreach.get("governed_metadata", {}),
        },
        "touch_record_preview": {
            "touch_record_id": touch.get("touch_record_id"),
            "touch_record_state": touch.get("touch_record_state"),
            "response_status": touch.get("response_status"),
            "feedback_reason": touch.get("feedback_reason"),
            "next_step_optional": touch.get("next_step_optional"),
            "written_back_at_optional": touch.get("written_back_at_optional"),
            "writeback_targets": touch.get("writeback_targets"),
            "governed_metadata": touch.get("governed_metadata", {}),
        },
        "outreach_execution_outbox_preview": {
            "outbox_id": outbox.get("outbox_id"),
            "outreach_plan_id": outbox.get("outreach_plan_id"),
            "touch_record_id": outbox.get("touch_record_id"),
            "contact_target_id": outbox.get("contact_target_id"),
            "opportunity_id": outbox.get("opportunity_id"),
            "channel": outbox.get("channel"),
            "governed_execution_mode": outbox.get("governed_execution_mode"),
            "vendor_adapter_state": outbox.get("vendor_adapter_state", {}),
            "approval_state": outbox.get("approval_state"),
            "audit_state": outbox.get("audit_state"),
            "quiet_hours_state": outbox.get("quiet_hours_state"),
            "retry_policy": outbox.get("retry_policy", {}),
            "retry_state": outbox.get("retry_state", {}),
            "stop_policy": outbox.get("stop_policy", {}),
            "stop_state": outbox.get("stop_state", {}),
            "dry_run_execution_state": outbox.get("dry_run_execution_state", {}),
            "live_execution_enabled": bool(outbox.get("live_execution_enabled", False)),
            "real_send_attempted": bool(outbox.get("real_send_attempted", False)),
            "blocked_reasons": list(outbox.get("blocked_reasons", [])),
        },
        "outbox_readiness_summary": outbox_summary,
        "_raw_records": [contact, outreach, touch],
    }
    envelope = _surface_envelope(
        bundle=bundle,
        surface_id="outreach_workbench",
        default_mode=str(surface_defaults["surface_mode"]),
        formal_records=formal_records,
        formal_objects=formal_objects,
        preview_projection=preview_projection,
        release_layer=str(surface_defaults["release_layer"]),
        blocked_by_default=bool(surface_defaults["blocked_by_default"]),
    )
    envelope["preview_projection"].pop("_raw_records", None)
    envelope["outreach_execution_outbox"] = preview_projection["outreach_execution_outbox_preview"]
    envelope["outbox_readiness_summary"] = outbox_summary
    return _attach_operational_context(envelope, bundle)


def build_stage9_preview_surface(payload: Any) -> dict[str, Any]:
    bundle = _resolve_bundle(payload, "stage9")
    surface_defaults = get_surface_runtime_defaults("order_delivery_workbench")
    order = _record_data(bundle.record("order_record"))
    payment = _record_data(bundle.record("payment_record"))
    delivery = _record_data(bundle.record("delivery_record"))
    outcome = _record_data(bundle.record("opportunity_outcome_event"))
    governance = _record_data(bundle.record("governance_feedback_event"))
    formal_records = {
        "order_record": order,
        "payment_record": payment,
        "delivery_record": delivery,
        "opportunity_outcome_event": outcome,
        "governance_feedback_event": governance,
    }
    formal_objects = {
        "order_record": _formal_object_ref(bundle, "order_record", order),
        "payment_record": _formal_object_ref(bundle, "payment_record", payment),
        "delivery_record": _formal_object_ref(bundle, "delivery_record", delivery),
        "opportunity_outcome_event": _formal_object_ref(bundle, "opportunity_outcome_event", outcome),
        "governance_feedback_event": _formal_object_ref(bundle, "governance_feedback_event", governance),
    }
    preview_projection = {
        "order_draft_preview": {
            "order_id": order.get("order_id"),
            "order_status": order.get("order_status"),
            "commercial_status": order.get("commercial_status"),
            "approval_state": order.get("approval_state"),
            "plan_status": order.get("plan_status"),
            "touch_record_state": order.get("touch_record_state"),
        },
        "payment_draft_preview": {
            "payment_id": payment.get("payment_id"),
            "payment_status": payment.get("payment_status"),
            "payment_proof_state": payment.get("payment_proof_state"),
            "payer_match_state": payment.get("payer_match_state"),
            "amount_match_state": payment.get("amount_match_state"),
            "refund_state": payment.get("refund_state"),
            "payment_exception_family_optional": payment.get("payment_exception_family_optional"),
        },
        "delivery_preview": {
            "delivery_id": delivery.get("delivery_id"),
            "delivery_status": delivery.get("delivery_status"),
            "delivery_form": delivery.get("delivery_form"),
            "customer_ack_state_optional": delivery.get("customer_ack_state_optional"),
            "delivery_exception_family_optional": delivery.get("delivery_exception_family_optional"),
            "archival_status": delivery.get("archival_status"),
            "retrieval_status": delivery.get("retrieval_status"),
        },
        "outcome_writeback_preview": {
            "outcome_event_id": outcome.get("outcome_event_id"),
            "outcome_family": outcome.get("outcome_family"),
            "outcome_reason_tags": outcome.get("outcome_reason_tags"),
            "feedback_reason": outcome.get("feedback_reason"),
            "writeback_targets": outcome.get("writeback_targets"),
        },
        "governance_feedback_preview": {
            "governance_feedback_event_id": governance.get("governance_feedback_event_id"),
            "trigger_type": governance.get("trigger_type"),
            "action_taken": governance.get("action_taken"),
            "impact_scope_optional": governance.get("impact_scope_optional"),
            "writeback_targets": governance.get("writeback_targets"),
        },
        "_raw_records": [order, payment, delivery, outcome, governance],
    }
    envelope = _surface_envelope(
        bundle=bundle,
        surface_id="order_delivery_workbench",
        default_mode=str(surface_defaults["surface_mode"]),
        formal_records=formal_records,
        formal_objects=formal_objects,
        preview_projection=preview_projection,
        release_layer=str(surface_defaults["release_layer"]),
        blocked_by_default=bool(surface_defaults["blocked_by_default"]),
    )
    envelope["preview_projection"].pop("_raw_records", None)
    return _attach_operational_context(envelope, bundle)


def _candidate_surface_state(surface_states: list[str]) -> str:
    if "blocked" in surface_states:
        return "blocked"
    if "review-required" in surface_states:
        return "review-required"
    if "governed-hold" in surface_states or "draft-only" in surface_states:
        return "governed-hold"
    return "preview-ready"


def _merge_formal_object_refs(*surfaces: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for surface in surfaces:
        merged.update(surface.get("formal_object_refs", {}))
    return merged


def _build_candidate_projection(
    candidate_matrix: Mapping[str, Any],
    source_projection_map: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    buckets = {
        "allowed_projection": {},
        "masked_projection": {},
        "summary_only": {},
        "forbidden": list(candidate_matrix.get("forbidden_components", [])),
    }
    for component in candidate_matrix.get("allowed_projection_components", []):
        source_object = str(component.get("source_object", ""))
        source_projection = dict(source_projection_map.get(source_object, {}))
        projected = {
            field_name: source_projection.get(field_name)
            for field_name in component.get("allowed_fields", [])
            if field_name in source_projection
        }
        for field_name in component.get("masked_fields", []):
            projected[field_name] = "[MASKED]"
        buckets[component["classification"]][component["component_id"]] = projected
    return buckets


def _dedupe_preserve_order(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _api_error_payload(code: str, *, meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    catalog = load_contract("contracts/api/error_code_catalog.json")
    for category in catalog.get("categories", []):
        for item in category.get("items", []):
            if item.get("code") == code:
                return {
                    "error_code": code,
                    "message": str(item.get("message", code)),
                    "meta": {
                        "http_status": int(item.get("httpStatus", 409)),
                        **dict(meta or {}),
                    },
                }
    return {
        "error_code": code,
        "message": code,
        "meta": {
            "http_status": 409,
            **dict(meta or {}),
        },
    }


def _leadpack_candidate_surface_core(
    payload: Any,
    *,
    requested_action: str = "preview",
) -> dict[str, Any]:
    if isinstance(payload, StageBundle):
        raise TypeError("leadpack candidate surface requires stage7/stage8/stage9 payload mapping or repository lookup payload")
    candidate_matrix = load_contract("contracts/release/leadpack_external_delivery_candidate_matrix.json")
    stage7_surface = build_stage7_preview_surface(payload)
    stage8_surface = build_stage8_preview_surface(payload)
    stage9_surface = build_stage9_preview_surface(payload)

    source_projection_map = {
        "saleable_opportunity": stage7_surface["preview_projection"]["opportunity_summary"],
        "offer_recommendation": stage7_surface["preview_projection"]["offer_summary"],
        "buyer_fit": stage7_surface["preview_projection"]["buyer_fit_summary"],
        "contact_target": stage8_surface["preview_projection"]["contact_target_preview"],
        "touch_record": stage8_surface["preview_projection"]["touch_record_preview"],
        "payment_record": stage9_surface["preview_projection"]["payment_draft_preview"],
        "delivery_record": stage9_surface["preview_projection"]["delivery_preview"],
        "opportunity_outcome_event": stage9_surface["preview_projection"]["outcome_writeback_preview"],
    }
    candidate_projection = _build_candidate_projection(candidate_matrix, source_projection_map)
    aggregated_trace_refs = _merge_trace_refs(stage7_surface, stage8_surface, stage9_surface)
    surface_state = _candidate_surface_state(
        [
            stage7_surface["surface_state"],
            stage8_surface["surface_state"],
            stage9_surface["surface_state"],
        ]
    )
    required_approvals = list(candidate_matrix.get("required_approvals", []))
    requested_approvals: list[str] = []
    required_review_gates = list(candidate_matrix.get("required_review_gates", []))
    requested_review_gates: list[str] = []
    if requested_action in {"review", "export_simulation"}:
        requested_review_gates.append("leadpack_candidate_review_gate")
    missing_approvals = [approval for approval in required_approvals if approval not in requested_approvals]
    satisfied_approvals = [approval for approval in required_approvals if approval not in missing_approvals]
    missing_review_gates = [gate for gate in required_review_gates if gate not in requested_review_gates]
    satisfied_review_gates = [gate for gate in required_review_gates if gate not in missing_review_gates]
    required_audit_refs = list(candidate_matrix.get("required_audit_refs", []))
    missing_audit_refs = _missing_audit_refs(required_audit_refs, aggregated_trace_refs)
    satisfied_audit_refs = [audit_ref for audit_ref in required_audit_refs if audit_ref not in missing_audit_refs]
    gate_reasons = collect_candidate_surface_block_reasons(
        stage8_surface_state=stage8_surface["surface_state"],
        stage9_surface_state=stage9_surface["surface_state"],
        surface_state=surface_state,
        missing_approvals=missing_approvals,
        missing_review_gates=missing_review_gates,
        missing_audit_refs=missing_audit_refs,
    )

    approval_prerequisites_met = not missing_approvals and not missing_audit_refs and surface_state == "preview-ready"
    review_gate_prerequisites_met = not missing_review_gates
    export_simulation_allowed = True
    approval_trace_present = bool(
        aggregated_trace_refs.get("permission_trace_present")
        or aggregated_trace_refs.get("governance_trace_present")
    )
    audit_trace_present = bool(
        aggregated_trace_refs.get("audit_refs")
        or aggregated_trace_refs.get("trace_refs")
    )
    non_live_blocked_reasons = [
        "external_delivery_enabled=false",
        "direct_export_enabled=false",
        "candidate_only_internal_preview",
        "customer_visible_formal_export_not_generated",
        "approval_and_audit_chain_required_before_external_delivery",
    ]
    blocked_reasons = _dedupe_preserve_order(gate_reasons["blocked_reasons"] + non_live_blocked_reasons)
    hold_reasons = _dedupe_preserve_order(gate_reasons["hold_reasons"])
    why_not_live = _dedupe_preserve_order(
        list(candidate_matrix.get("why_not_live", []))
        + [
            "external_delivery_enabled=false",
            "direct_export_enabled=false",
            "customer_visible_formal_export_not_generated",
        ]
    )
    approval_readiness_summary = {
        "ready": not missing_approvals,
        "required_count": len(required_approvals),
        "missing_count": len(missing_approvals),
        "required_approvals": required_approvals,
        "satisfied": satisfied_approvals,
        "missing_or_pending": sorted(missing_approvals),
        "approval_trace_present": approval_trace_present,
        "external_delivery_still_disabled": True,
    }
    review_gate_readiness_summary = {
        "ready": review_gate_prerequisites_met,
        "required_count": len(required_review_gates),
        "missing_count": len(missing_review_gates),
        "required_review_gates": required_review_gates,
        "satisfied": satisfied_review_gates,
        "missing_or_pending": sorted(missing_review_gates),
        "must_not_be_treated_as_approval": True,
    }
    audit_readiness_summary = {
        "ready": not missing_audit_refs,
        "required_count": len(required_audit_refs),
        "missing_count": len(missing_audit_refs),
        "required_audit_refs": required_audit_refs,
        "satisfied": satisfied_audit_refs,
        "missing_or_pending": sorted(missing_audit_refs),
        "missing_audit_refs": sorted(missing_audit_refs),
        "audit_trace_present": audit_trace_present,
        "trace_refs_present": bool(aggregated_trace_refs.get("trace_refs")),
        "audit_refs_present": bool(aggregated_trace_refs.get("audit_refs")),
        "policy_trace_present": bool(aggregated_trace_refs.get("policy_trace_present")),
        "permission_trace_present": bool(aggregated_trace_refs.get("permission_trace_present")),
        "governance_trace_present": bool(aggregated_trace_refs.get("governance_trace_present")),
        "semantic_trace_present": bool(aggregated_trace_refs.get("semantic_trace_present")),
        "external_delivery_still_disabled": True,
    }
    actual_approval_states = [
        {
            "approval_chain_id": approval,
            "current_status": "MISSING_OR_PENDING" if approval in missing_approvals else "PRESENT",
            "required_status": "APPROVED",
            "resulting_state_if_missing": "HOLD",
        }
        for approval in required_approvals
    ]
    actual_review_gate_states = [
        {
            "review_gate_id": gate,
            "current_status": "MISSING_OR_PENDING" if gate in missing_review_gates else "PRESENT",
            "required_status": "PASSED_OR_READY_FOR_REVIEW",
            "must_not_be_treated_as_approval": True,
            "resulting_state_if_missing": "HOLD",
        }
        for gate in required_review_gates
    ]
    actual_audit_ref_states = [
        {
            "audit_ref": audit_ref,
            "current_status": "MISSING" if audit_ref in missing_audit_refs else "PRESENT_OR_TRACE_BACKED",
            "resulting_state_if_missing": "HOLD",
        }
        for audit_ref in required_audit_refs
    ]
    source_formal_object_types = sorted(
        _merge_formal_object_refs(stage7_surface, stage8_surface, stage9_surface).keys()
    )
    candidate_readback_summary = {
        "readback_ready": True,
        "readback_surface": "review_report_workbench",
        "readiness_only": True,
        "candidate_only": True,
        "review_only": True,
        "projection_only": True,
        "approval_audit_readiness_only": True,
        "external_delivery_enabled": False,
        "direct_export_enabled": False,
        "customer_visible_export_enabled": False,
        "client_page_release_enabled": False,
        "blocked_reason_count": len(blocked_reasons),
        "hold_reason_count": len(hold_reasons),
        "why_not_live": why_not_live,
    }
    operator_readback_summary = {
        "readback_ready": True,
        "readback_surface": "review_report_workbench",
        "operator_can_read_candidate": True,
        "operator_can_request_review": True,
        "operator_can_run_export_simulation": True,
        "operator_can_direct_export": False,
        "operator_can_deliver_external": False,
        "operator_can_enable_external_delivery": False,
        "operator_can_publish_customer_page": False,
        "approval_ready": approval_readiness_summary["ready"],
        "audit_ready": audit_readiness_summary["ready"],
        "review_gate_ready": review_gate_readiness_summary["ready"],
        "missing_approvals": sorted(missing_approvals),
        "missing_audit_refs": sorted(missing_audit_refs),
        "missing_review_gates": sorted(missing_review_gates),
        "source_formal_object_types": source_formal_object_types,
    }
    return {
        "surface_id": "review_report_workbench",
        "surface_state": surface_state,
        "surface_mode": "preview-only",
        "surface_access": "internal-readable" if surface_state in {"blocked", "review-required"} else "internal-operable",
        "internal_only": True,
        "candidate_only": True,
        "readiness_only": True,
        "review_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "approval_prerequisites_met": approval_prerequisites_met,
        "review_gate_prerequisites_met": review_gate_prerequisites_met,
        "export_simulation_allowed": export_simulation_allowed,
        "export_simulation_mode": "simulation_only",
        "direct_export_enabled": False,
        "external_ready_direct_export": False,
        "review_requested": requested_action == "review",
        "export_simulation_requested": requested_action == "export_simulation",
        "release_layer": candidate_matrix["candidate_scope"]["minimum_release_level"],
        "candidate_status": candidate_matrix["candidate_status"],
        "candidate_scope": dict(candidate_matrix["candidate_scope"]),
        "formal_object_refs": _merge_formal_object_refs(stage7_surface, stage8_surface, stage9_surface),
        "candidate_projection": candidate_projection,
        "required_approvals": required_approvals,
        "required_review_gates": required_review_gates,
        "required_audit_refs": required_audit_refs,
        "required_boundary_checks": list(candidate_matrix.get("required_boundary_checks", [])),
        "required_masking_or_summary_rules": list(candidate_matrix.get("required_masking_or_summary_rules", [])),
        "missing_approvals": missing_approvals,
        "missing_review_gates": missing_review_gates,
        "missing_audit_refs": missing_audit_refs,
        "actual_approval_states": actual_approval_states,
        "actual_review_gate_states": actual_review_gate_states,
        "actual_audit_ref_states": actual_audit_ref_states,
        "approval_readiness_summary": approval_readiness_summary,
        "review_gate_readiness_summary": review_gate_readiness_summary,
        "audit_readiness_summary": audit_readiness_summary,
        "candidate_readback_summary": candidate_readback_summary,
        "operator_readback_summary": operator_readback_summary,
        "denial_conditions": list(candidate_matrix.get("denial_conditions", [])),
        "blocked_reasons": blocked_reasons,
        "hold_reasons": hold_reasons,
        "why_not_live": why_not_live,
        "why_not_now": list(candidate_matrix.get("why_not_now", [])),
        "future_activation_prereqs_remaining": list(candidate_matrix.get("future_activation_prereqs_remaining", [])),
        "trace_refs": {
            **aggregated_trace_refs,
            "requested_approvals": requested_approvals,
            "requested_review_gates": requested_review_gates,
            "source_surface_ids": [
                stage7_surface["surface_id"],
                stage8_surface["surface_id"],
                stage9_surface["surface_id"],
            ],
        },
    }


def build_leadpack_external_delivery_candidate_surface(
    payload: Any,
    *,
    requested_action: str = "preview",
) -> dict[str, Any]:
    return _leadpack_candidate_surface_core(payload, requested_action=requested_action)


def build_leadpack_activation_prep_surface(
    payload: Any,
    *,
    requested_action: str = "packet",
) -> dict[str, Any]:
    candidate_surface = _leadpack_candidate_surface_core(payload, requested_action="preview")
    evidence_pack_contract = load_contract("contracts/release/leadpack_activation_prep_evidence_pack.json")
    replay_contract = load_contract("contracts/release/leadpack_activation_prep_simulation_replay.json")
    runbook_contract = load_contract("contracts/release/leadpack_activation_prep_runbook.json")
    signoff_contract = load_contract("contracts/release/leadpack_activation_prep_signoff_packet.json")
    transition_contract = load_contract("contracts/release/leadpack_activation_prep_transition_matrix.json")
    delivery_matrix = load_contract("contracts/release/delivery_matrix.json")
    public_boundary = load_contract("contracts/governance/public_boundary_registry.json")
    coverage_registry = load_contract("contracts/governance/coverage_registry.json")
    release_checklist = load_contract("contracts/testing/release_checklist.json")
    regression_manifest = load_contract("contracts/testing/regression_manifest.json")

    opportunity_id = str(
        candidate_surface.get("formal_object_refs", {})
        .get("saleable_opportunity", {})
        .get("object_id", "UNKNOWN")
    )
    trace_refs = dict(candidate_surface.get("trace_refs", {}))
    candidate_scope = dict(candidate_surface.get("candidate_scope", {}))

    boundary_check_results = {
        "projection_boundary_check": "PASS"
        if candidate_surface.get("candidate_status") == "INTERNAL_ONLY_CANDIDATE_DEFINED"
        and bool(candidate_scope.get("internal_only"))
        and bool(candidate_scope.get("candidate_only"))
        and not candidate_surface.get("external_delivery_enabled", True)
        else "DENY",
        "coverage_boundary_check": "PASS"
        if bool(coverage_registry.get("future_unlock_constraints", {}).get("coverage_never_sufficient_alone"))
        else "HOLD",
        "delivery_matrix_check": "PASS"
        if bool(delivery_matrix.get("future_unlock_constraints", {}).get("candidate_package_must_not_override_object_surface_policy"))
        and bool(
            delivery_matrix.get("future_unlock_constraints", {}).get("direct_stage8_stage9_object_export_remains_blocked")
            or delivery_matrix.get("future_unlock_constraints", {}).get("direct_stage8_stage9_object_export_never_default_open")
        )
        else "DENY",
        "public_boundary_check": "PASS"
        if bool(public_boundary.get("future_unlock_guardrails", {}).get("leadpack_candidate_package_is_internal_only"))
        and bool(public_boundary.get("future_unlock_guardrails", {}).get("leadpack_external_delivery_requires_approval_and_audit"))
        else "DENY",
    }

    approval_trace_present = bool(
        trace_refs.get("permission_trace_present") or trace_refs.get("governance_trace_present")
    )
    audit_trace_present = bool(trace_refs.get("audit_refs") or trace_refs.get("trace_refs"))
    source_status_blocked = any(
        str(entry.get("primary_status", "")) in {"BLOCKED", "CANCELLED", "FAILED", "INVALID", "TERMINATED"}
        for entry in candidate_surface.get("formal_object_refs", {}).values()
    )
    replay_ready = bool(trace_refs.get("trace_refs")) and all(
        result == "PASS" for result in boundary_check_results.values()
    )

    simulation_replay = {
        "artifact_id": f"LPEXP-PREP-REPLAY-{opportunity_id}",
        "replay_status": "REPLAY_READY" if replay_ready else "REPLAY_HELD",
        "source_operation_id": replay_contract["source_operation_id"],
        "candidate_matrix_ref": replay_contract["metadata"]["candidate_matrix_ref"],
        "boundary_check_results": boundary_check_results,
        "projection_component_counts": {
            "allowed_projection": len(candidate_surface.get("candidate_projection", {}).get("allowed_projection", {})),
            "masked_projection": len(candidate_surface.get("candidate_projection", {}).get("masked_projection", {})),
            "summary_only": len(candidate_surface.get("candidate_projection", {}).get("summary_only", {})),
            "forbidden": len(candidate_surface.get("candidate_projection", {}).get("forbidden", [])),
        },
        "forbidden_component_ids": [
            str(entry.get("component_id", "UNKNOWN"))
            for entry in candidate_surface.get("candidate_projection", {}).get("forbidden", [])
        ],
        "missing_approvals": list(candidate_surface.get("missing_approvals", [])),
        "missing_review_gates": list(candidate_surface.get("missing_review_gates", [])),
        "missing_audit_refs": list(candidate_surface.get("missing_audit_refs", [])),
        "trace_refs": trace_refs,
    }

    release_item_ids = {
        item["itemId"]
        for section in release_checklist.get("sections", [])
        for item in section.get("items", [])
    }
    regression_suite_ids = {suite["suite_id"] for suite in regression_manifest.get("suites", [])}
    required_release_checks = list(transition_contract["review_gate"]["required_release_checks"])
    required_regression_suites = list(transition_contract["review_gate"]["required_regression_suites"])
    signoff_packet_ready = bool(signoff_contract.get("required_owner_signoffs")) and set(required_release_checks).issubset(
        release_item_ids
    ) and set(required_regression_suites).issubset(regression_suite_ids)
    runbook_ready = len(runbook_contract.get("runbook_actions", [])) >= 6

    evidence_items: list[dict[str, Any]] = []
    evidence_item_sources = dict(evidence_pack_contract.get("evidence_item_sources", {}))
    evidence_item_freshness = dict(evidence_pack_contract.get("evidence_item_freshness", {}))
    for entry in evidence_pack_contract.get("required_evidence_items", []):
        item_id = str(entry.get("item_id", "UNKNOWN"))
        status = "READY"
        present = True
        if item_id == "candidate_matrix_snapshot":
            present = candidate_surface.get("candidate_status") == "INTERNAL_ONLY_CANDIDATE_DEFINED"
            status = "READY" if present else "DENY"
        elif item_id == "projection_boundary_verdict":
            status = boundary_check_results["projection_boundary_check"]
        elif item_id == "coverage_boundary_verdict":
            status = boundary_check_results["coverage_boundary_check"]
        elif item_id == "delivery_matrix_verdict":
            status = boundary_check_results["delivery_matrix_check"]
        elif item_id == "public_boundary_verdict":
            status = boundary_check_results["public_boundary_check"]
        elif item_id == "export_simulation_replay_artifact":
            present = replay_ready
            status = "READY" if replay_ready else "HOLD"
        elif item_id == "approval_trace_snapshot":
            present = approval_trace_present
            status = "READY" if approval_trace_present else "HOLD"
        elif item_id == "audit_trace_snapshot":
            present = audit_trace_present
            status = "READY" if audit_trace_present else "HOLD"
        elif item_id == "signoff_packet_snapshot":
            present = signoff_packet_ready
            status = "READY" if signoff_packet_ready else "HOLD"
        elif item_id == "prep_runbook_snapshot":
            present = runbook_ready
            status = "READY" if runbook_ready else "HOLD"
        evidence_items.append(
            {
                "item_id": item_id,
                "evidence_type": str(entry.get("evidence_type", "unknown")),
                "required_for_review": bool(entry.get("required_for_review", False)),
                "present": present,
                "status": status,
                "source_refs": list(evidence_item_sources.get(item_id, [])),
                "freshness_policy": str(evidence_item_freshness.get(item_id, "unknown")),
            }
        )

    denial_conditions_triggered = [
        "projection_boundary_violation"
        for result in ("projection_boundary_check", "delivery_matrix_check", "public_boundary_check")
        if boundary_check_results[result] == "DENY"
    ]
    if candidate_surface.get("external_delivery_enabled"):
        denial_conditions_triggered.append("external_delivery_or_live_execution_requested")
    held_conditions_triggered = [
        item["item_id"] for item in evidence_items if item["status"] == "HOLD"
    ]
    if source_status_blocked:
        held_conditions_triggered.append("candidate_source_status_blocked")

    if denial_conditions_triggered:
        prep_status = "ACTIVATION_PREP_DENIED"
    elif held_conditions_triggered:
        prep_status = "ACTIVATION_PREP_HELD"
    else:
        prep_status = "ACTIVATION_PREP_READY_FOR_REVIEW"

    actual_signoff_state_by_role = {
        str(entry.get("owner_role")): dict(entry)
        for entry in signoff_contract.get("actual_owner_signoff_states", [])
    }
    signoff_packet = {
        "packet_id": f"LPEXP-PREP-SIGNOFF-{opportunity_id}",
        "packet_status": "PACKET_READY_FOR_REVIEW" if signoff_packet_ready else "PACKET_HELD",
        "draft_packet_allowed": bool(signoff_contract.get("draft_packet_allowed", False)),
        "draft_packet_is_not_activation_ready": bool(
            signoff_contract.get("draft_packet_is_not_activation_ready", True)
        ),
        "owner_signoff_state_source": dict(signoff_contract.get("owner_signoff_state_source", {})),
        "actual_owner_signoff_states": list(signoff_contract.get("actual_owner_signoff_states", [])),
        "required_owner_signoffs": [
            {
                "owner_role": entry["owner_role"],
                "mandatory": bool(entry.get("mandatory", False)),
                "status": str(
                    actual_signoff_state_by_role.get(str(entry["owner_role"]), {}).get(
                        "current_status",
                        entry.get("default_status", "PENDING_REQUEST"),
                    )
                ),
                "state_source_ref": str(
                    actual_signoff_state_by_role.get(str(entry["owner_role"]), {}).get(
                        "state_source_ref",
                        entry.get("actual_state_ref", ""),
                    )
                ),
            }
            for entry in signoff_contract.get("required_owner_signoffs", [])
        ],
        "required_release_checks": required_release_checks,
        "required_regression_suites": required_regression_suites,
        "review_gate_ref": signoff_contract["review_gate_ref"],
    }

    blockers_remaining = list(evidence_pack_contract.get("activation_blockers_remaining", []))
    blockers_remaining.extend(str(value) for value in candidate_surface.get("blocked_reasons", []))
    blockers_remaining.extend(str(value) for value in candidate_surface.get("hold_reasons", []))
    blockers_remaining.extend(denial_conditions_triggered)
    blockers_remaining.extend(held_conditions_triggered)
    blockers_remaining = sorted({entry for entry in blockers_remaining if entry})

    evidence_pack = {
        "evidence_pack_status": prep_status,
        "required_evidence_items": evidence_items,
        "evidence_item_sources": evidence_item_sources,
        "evidence_item_freshness": evidence_item_freshness,
        "simulation_replay_required": bool(evidence_pack_contract.get("simulation_replay_required", False)),
        "approval_trace_required": bool(evidence_pack_contract.get("approval_trace_required", False)),
        "audit_trace_required": bool(evidence_pack_contract.get("audit_trace_required", False)),
        "projection_boundary_check_required": bool(
            evidence_pack_contract.get("projection_boundary_check_required", False)
        ),
        "coverage_boundary_check_required": bool(
            evidence_pack_contract.get("coverage_boundary_check_required", False)
        ),
        "delivery_matrix_check_required": bool(
            evidence_pack_contract.get("delivery_matrix_check_required", False)
        ),
        "activation_denial_conditions": list(evidence_pack_contract.get("activation_denial_conditions", [])),
        "activation_blockers_remaining": blockers_remaining,
    }

    readiness_transition = {
        "prep_status_vocabulary": list(transition_contract.get("prep_status_vocabulary", [])),
        "current_prep_status": prep_status,
        "review_gate": dict(transition_contract.get("review_gate", {})),
        "transitions": list(transition_contract.get("transitions", [])),
    }

    response = {
        "surface_id": "review_report_workbench",
        "surface_state": candidate_surface.get("surface_state", "review-required"),
        "surface_mode": "preview-only",
        "surface_access": candidate_surface.get("surface_access", "internal-readable"),
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "activation_prep_review_requested": requested_action == "review",
        "release_layer": candidate_surface.get("release_layer", "INTERNAL_OPERABLE"),
        "candidate_status": candidate_surface.get("candidate_status", "UNKNOWN"),
        "formal_object_refs": dict(candidate_surface.get("formal_object_refs", {})),
        "candidate_projection": dict(candidate_surface.get("candidate_projection", {})),
        "evidence_pack": evidence_pack,
        "simulation_replay": simulation_replay,
        "signoff_packet": signoff_packet,
        "runbook": {
            "prep_status_vocabulary": list(runbook_contract.get("prep_status_vocabulary", [])),
            "runbook_actions": list(runbook_contract.get("runbook_actions", [])),
            "strictness_rule": str(runbook_contract.get("strictness_rule", "")),
            "external_delivery_enabled": bool(runbook_contract.get("external_delivery_enabled", False)),
            "direct_object_export_allowed": bool(runbook_contract.get("direct_object_export_allowed", False)),
        },
        "readiness_transition": readiness_transition,
        "trace_refs": {
            **trace_refs,
            "activation_prep_artifacts": {
                "evidence_pack_ref": evidence_pack_contract["metadata"]["machine_path"],
                "simulation_replay_ref": replay_contract["metadata"]["machine_path"],
                "signoff_packet_ref": signoff_contract["metadata"]["machine_path"],
                "runbook_ref": runbook_contract["metadata"]["machine_path"],
                "transition_matrix_ref": transition_contract["metadata"]["machine_path"],
            },
        },
    }

    if requested_action == "review" and prep_status != "ACTIVATION_PREP_READY_FOR_REVIEW":
        response["activation_prep_review_requested"] = False
        response["error"] = _api_error_payload(
            "LEADPACK-409-ACTIVATION_PREP_NOT_READY",
            meta={
                "candidate_domain_id": "leadpack_external_delivery",
                "activation_prep_status": prep_status,
                "missing_evidence_items": [
                    item["item_id"] for item in evidence_items if item["status"] != "READY"
                ],
                "activation_blockers_remaining": blockers_remaining,
            },
        )
    return response


def build_leadpack_activation_design_implementation_prep_surface(
    payload: Any,
    *,
    requested_action: str = "packet",
) -> dict[str, Any]:
    activation_prep = build_leadpack_activation_prep_surface(payload, requested_action="review")
    design_contract = load_contract("contracts/release/leadpack_activation_design_implementation_prep_matrix.json")
    release_checklist = load_contract("contracts/testing/release_checklist.json")
    regression_manifest = load_contract("contracts/testing/regression_manifest.json")

    formal_refs = dict(activation_prep.get("formal_object_refs", {}))
    opportunity_id = str(formal_refs.get("saleable_opportunity", {}).get("object_id", "UNKNOWN"))
    prep_status = str(
        activation_prep.get("readiness_transition", {}).get("current_prep_status", "ACTIVATION_PREP_HELD")
    )

    gate = dict(design_contract["implementation_prep_readiness_gate"])
    release_item_ids = {
        item["itemId"]
        for section in release_checklist.get("sections", [])
        for item in section.get("items", [])
    }
    regression_suite_ids = {suite["suite_id"] for suite in regression_manifest.get("suites", [])}
    required_release_checks = list(gate.get("required_release_checks", []))
    required_regression_suites = list(gate.get("required_regression_suites", []))
    missing_release_checks = sorted(set(required_release_checks) - release_item_ids)
    missing_regression_suites = sorted(set(required_regression_suites) - regression_suite_ids)

    owner_execution_contract = dict(design_contract.get("owner_signoff_execution", {}))
    actual_signoff_state_by_role = {
        str(entry.get("owner_role")): dict(entry)
        for entry in owner_execution_contract.get("actual_owner_signoff_states", [])
    }
    owner_signoffs = [
        {
            "owner_role": entry["owner_role"],
            "mandatory": bool(entry.get("mandatory", False)),
            "status": str(
                actual_signoff_state_by_role.get(str(entry["owner_role"]), {}).get(
                    "current_status",
                    entry.get("default_status", "REQUESTED"),
                )
            ),
            "declared": bool(actual_signoff_state_by_role.get(str(entry["owner_role"]), {}).get("declared", False)),
            "state_source_ref": str(
                actual_signoff_state_by_role.get(str(entry["owner_role"]), {}).get(
                    "state_source_ref",
                    entry.get("state_source_ref", ""),
                )
            ),
            "missing_or_pending_result": str(entry.get("missing_or_pending_result", "HOLD")),
            "denied_result": str(entry.get("denied_result", "NO_GO")),
        }
        for entry in owner_execution_contract.get("required_owner_signoffs", [])
    ]
    owner_roles = {entry["owner_role"] for entry in owner_signoffs}
    pending_owner_roles = [
        entry["owner_role"]
        for entry in owner_signoffs
        if entry["mandatory"] and entry["status"] != "APPROVED"
    ]
    owner_signoff_actual_state_ready = bool(actual_signoff_state_by_role) and all(
        entry.get("state_source_ref")
        for entry in owner_signoffs
        if entry["mandatory"]
    )
    owner_signoff_execution_ready = owner_roles == set(gate.get("required_owner_signoff_roles", [])) and owner_signoff_actual_state_ready

    replay = dict(activation_prep.get("simulation_replay", {}))
    missing_approvals = list(replay.get("missing_approvals", []))
    missing_review_gates = list(replay.get("missing_review_gates", []))
    missing_audit_refs = list(replay.get("missing_audit_refs", []))
    required_audit_refs = list(gate.get("required_audit_refs", []))
    design_decision_audit_ref = "activation_design_decision_audit_ref"
    implementation_decision_missing_audit_refs = sorted(
        set(missing_audit_refs + [design_decision_audit_ref])
        if design_decision_audit_ref in required_audit_refs
        else set(missing_audit_refs)
    )

    negative_controls = list(design_contract.get("rollback_cancel_emergency_off", {}).get("controls", []))
    negative_controls_ready = {entry.get("control_id") for entry in negative_controls} >= {
        "CANCEL_ACTIVATION_DESIGN_PREP",
        "ROLLBACK_ACTIVATION_DESIGN_PREP",
        "EMERGENCY_OFF_ACTIVATION_PREP",
    }
    state_layering = dict(design_contract.get("state_layering", {}))
    state_layering_ready = all(
        state_layering.get(key)
        for key in (
            "candidate_gap_states",
            "activation_prep_states",
            "activation_go_no_go_decision_states",
            "activation_design_prep_states",
            "implementation_decision_states",
        )
    ) and bool(state_layering.get("canonical_repo_readiness_must_not_change"))

    scope = dict(design_contract.get("scope", {}))
    scope_guard_ready = (
        bool(scope.get("design_prep_only"))
        and not bool(scope.get("actual_activation_enabled"))
        and not bool(scope.get("external_delivery_enabled"))
        and not bool(scope.get("external_software_release_enabled"))
        and not bool(scope.get("stage8_stage9_live_execution_enabled"))
        and not bool(scope.get("direct_stage8_stage9_object_export_allowed"))
        and not bool(scope.get("implementation_approved"))
    )

    design_blockers = []
    if prep_status != "ACTIVATION_PREP_READY_FOR_REVIEW":
        design_blockers.append("activation_prep_not_ready_for_review")
    design_blockers.extend(f"missing_release_check:{item}" for item in missing_release_checks)
    design_blockers.extend(f"missing_regression_suite:{item}" for item in missing_regression_suites)
    if not owner_signoff_execution_ready:
        design_blockers.append("owner_signoff_actual_state_source_not_aligned")
    if not negative_controls_ready:
        design_blockers.append("rollback_cancel_emergency_off_not_defined")
    if not state_layering_ready:
        design_blockers.append("state_layering_not_hardened")
    if not scope_guard_ready:
        design_blockers.append("scope_guard_violation")

    design_prep_ready_for_review = len(design_blockers) == 0
    if prep_status != "ACTIVATION_PREP_READY_FOR_REVIEW":
        design_prep_status = "ACTIVATION_DESIGN_PREP_HELD"
    elif design_prep_ready_for_review:
        design_prep_status = "ACTIVATION_DESIGN_PREP_READY_FOR_REVIEW"
    else:
        design_prep_status = "ACTIVATION_DESIGN_PREP_HELD"

    implementation_decision_blockers = []
    implementation_decision_hold_sources = []
    implementation_decision_hold_sources.extend(
        {
            "source_type": "owner_signoff",
            "source_id": role,
            "reason": f"owner_signoff_not_approved:{role}",
            "resulting_state": "IMPLEMENTATION_DECISION_HELD",
        }
        for role in pending_owner_roles
    )
    implementation_decision_hold_sources.extend(
        {
            "source_type": "approval_chain",
            "source_id": item,
            "reason": f"approval_missing_or_pending:{item}",
            "resulting_state": "IMPLEMENTATION_DECISION_HELD",
        }
        for item in missing_approvals
    )
    implementation_decision_hold_sources.extend(
        {
            "source_type": "review_gate",
            "source_id": item,
            "reason": f"review_gate_missing_or_pending:{item}",
            "resulting_state": "IMPLEMENTATION_DECISION_HELD",
        }
        for item in missing_review_gates
    )
    implementation_decision_hold_sources.extend(
        {
            "source_type": "audit_ref",
            "source_id": item,
            "reason": f"audit_ref_missing_or_pending:{item}",
            "resulting_state": "IMPLEMENTATION_DECISION_HELD",
        }
        for item in implementation_decision_missing_audit_refs
    )
    implementation_decision_blockers.extend(entry["reason"] for entry in implementation_decision_hold_sources)
    if design_prep_status != "ACTIVATION_DESIGN_PREP_READY_FOR_REVIEW":
        implementation_decision_blockers.append("activation_design_prep_not_ready_for_review")

    implementation_decision_state = (
        "IMPLEMENTATION_DECISION_READY_FOR_REVIEW"
        if design_prep_status == "ACTIVATION_DESIGN_PREP_READY_FOR_REVIEW"
        and not implementation_decision_blockers
        else "IMPLEMENTATION_DECISION_HELD"
    )

    response = {
        "surface_id": "review_report_workbench",
        "surface_state": "review-required",
        "surface_mode": "preview-only",
        "surface_access": "internal-readable",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "actual_activation_enabled": False,
        "implementation_approved": False,
        "activation_design_prep_review_requested": requested_action == "review",
        "release_layer": activation_prep.get("release_layer", "INTERNAL_OPERABLE"),
        "candidate_status": activation_prep.get("candidate_status", "UNKNOWN"),
        "activation_prep_status": prep_status,
        "activation_design_prep_status": design_prep_status,
        "owner_signoff_execution": {
            "owner_status_vocabulary": list(owner_execution_contract.get("owner_status_vocabulary", [])),
            "required_owner_signoffs": owner_signoffs,
            "actual_owner_signoff_states": list(owner_execution_contract.get("actual_owner_signoff_states", [])),
            "actual_state_source_refs": list(owner_execution_contract.get("actual_state_source_refs", [])),
            "pending_owner_roles": pending_owner_roles,
            "decision_mapping": dict(owner_execution_contract.get("decision_mapping", {})),
        },
        "approval_audit_prerequisites": {
            **dict(design_contract.get("approval_audit_prerequisites", {})),
            "missing_approvals": missing_approvals,
            "missing_review_gates": missing_review_gates,
            "missing_audit_refs": implementation_decision_missing_audit_refs,
        },
        "state_layering": state_layering,
        "rollback_cancel_emergency_off": dict(design_contract.get("rollback_cancel_emergency_off", {})),
        "implementation_prep_readiness_gate": gate,
        "implementation_decision_readiness": {
            "state": implementation_decision_state,
            "ready": implementation_decision_state == "IMPLEMENTATION_DECISION_READY_FOR_REVIEW",
            "blockers": sorted(implementation_decision_blockers),
            "hold_sources": sorted(implementation_decision_hold_sources, key=lambda entry: entry["reason"]),
        },
        "design_prep_blockers": sorted(design_blockers),
        "trace_refs": {
            **dict(activation_prep.get("trace_refs", {})),
            "activation_design_implementation_prep_ref": design_contract["metadata"]["machine_path"],
            "source_go_decision_ref": design_contract["metadata"]["source_go_decision_ref"],
        },
    }

    if requested_action == "review" and not design_prep_ready_for_review:
        response["activation_design_prep_review_requested"] = False
        response["error"] = _api_error_payload(
            "LEADPACK-410-ACTIVATION_DESIGN_PREP_NOT_READY",
            meta={
                "candidate_domain_id": "leadpack_external_delivery",
                "activation_design_prep_status": design_prep_status,
                "design_prep_blockers": sorted(design_blockers),
                "implementation_decision_blockers": sorted(implementation_decision_blockers),
            },
        )
    return response


def build_leadpack_implementation_decision_readiness_packet_surface(payload: Any) -> dict[str, Any]:
    readiness_contract = load_contract("contracts/release/leadpack_implementation_decision_readiness_packet.json")
    design_surface = build_leadpack_activation_design_implementation_prep_surface(payload, requested_action="packet")
    decision_readiness = dict(design_surface.get("implementation_decision_readiness", {}))
    hold_sources = list(decision_readiness.get("hold_sources", readiness_contract.get("hold_sources", [])))
    hold_source_ids_by_type: dict[str, list[str]] = {}
    for source in hold_sources:
        hold_source_ids_by_type.setdefault(str(source.get("source_type", "unknown")), []).append(
            str(source.get("source_id", "UNKNOWN"))
        )

    approval_prereqs = dict(design_surface.get("approval_audit_prerequisites", {}))
    owner_execution = dict(design_surface.get("owner_signoff_execution", {}))
    decision_scope = {
        **dict(readiness_contract.get("decision_scope", {})),
        "implementation_decision_ready": bool(decision_readiness.get("ready", False)),
        "implementation_approved": False,
        "actual_activation_not_approved": True,
        "external_delivery_not_approved": True,
    }
    packet_status = (
        "PACKET_READY_FOR_HUMAN_REVIEW"
        if decision_readiness.get("ready") and not hold_sources
        else "PACKET_HELD"
    )

    required_approval_chains = list(approval_prereqs.get("required_approval_chains_before_implementation_decision", []))
    missing_approvals = list(approval_prereqs.get("missing_approvals", []))
    required_review_gates = list(approval_prereqs.get("required_review_gates_before_implementation_decision", []))
    missing_review_gates = list(approval_prereqs.get("missing_review_gates", []))
    required_audit_refs = list(approval_prereqs.get("required_audit_refs_before_implementation_decision", []))
    missing_audit_refs = list(approval_prereqs.get("missing_audit_refs", []))
    actual_owner_states = list(owner_execution.get("actual_owner_signoff_states", []))

    response = {
        "surface_id": "review_report_workbench",
        "surface_state": "governed-hold" if hold_sources else "review-required",
        "surface_mode": "preview-only",
        "surface_access": "internal-readable",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "actual_activation_enabled": False,
        "implementation_decision_executed": False,
        "implementation_approved": False,
        "implementation_not_approved": True,
        "actual_activation_not_approved": True,
        "external_delivery_not_approved": True,
        "implementation_decision_packet_status": packet_status,
        "implementation_decision_ready": bool(decision_readiness.get("ready", False)),
        "readiness_state": str(decision_readiness.get("state", "IMPLEMENTATION_DECISION_HELD")),
        "decision_scope": decision_scope,
        "hold_sources": sorted(hold_sources, key=lambda entry: str(entry.get("reason", ""))),
        "required_owner_signoffs": list(readiness_contract.get("required_owner_signoffs", [])),
        "actual_owner_signoff_states": actual_owner_states,
        "owner_signoff_summary": {
            "ready": "owner_signoff" not in hold_source_ids_by_type,
            "missing_or_pending": sorted(hold_source_ids_by_type.get("owner_signoff", [])),
        },
        "required_approval_chains": required_approval_chains,
        "actual_approval_states": [
            {
                "approval_chain_id": approval,
                "current_status": "MISSING_OR_PENDING" if approval in missing_approvals else "PRESENT",
                "required_status": "APPROVED",
                "resulting_state": "IMPLEMENTATION_DECISION_HELD" if approval in missing_approvals else "SATISFIED_FOR_PACKET_REVIEW",
            }
            for approval in required_approval_chains
        ],
        "approval_readiness_summary": {
            "ready": not missing_approvals,
            "missing_or_pending": sorted(missing_approvals),
        },
        "required_review_gates": required_review_gates,
        "actual_review_gate_states": [
            {
                "review_gate_id": gate,
                "current_status": "MISSING_OR_PENDING" if gate in missing_review_gates else "PRESENT",
                "required_status": "PASSED_OR_READY_FOR_REVIEW",
                "must_not_be_treated_as_approval": True,
                "resulting_state": "IMPLEMENTATION_DECISION_HELD" if gate in missing_review_gates else "SATISFIED_FOR_PACKET_REVIEW",
            }
            for gate in required_review_gates
        ],
        "review_gate_readiness_summary": {
            "ready": not missing_review_gates,
            "missing_or_pending": sorted(missing_review_gates),
        },
        "required_audit_refs": required_audit_refs,
        "actual_audit_ref_states": [
            {
                "audit_ref": audit_ref,
                "current_status": "MISSING" if audit_ref in missing_audit_refs else "PRESENT_OR_TRACE_BACKED",
                "resulting_state_if_missing": "IMPLEMENTATION_DECISION_HELD",
            }
            for audit_ref in required_audit_refs
        ],
        "audit_readiness_summary": {
            "ready": not missing_audit_refs,
            "missing_or_pending": sorted(missing_audit_refs),
        },
        "readiness_summaries": {
            "owner_signoff": {
                "ready": "owner_signoff" not in hold_source_ids_by_type,
                "missing_or_pending": sorted(hold_source_ids_by_type.get("owner_signoff", [])),
            },
            "approval": {
                "ready": not missing_approvals,
                "missing_or_pending": sorted(missing_approvals),
            },
            "review_gate": {
                "ready": not missing_review_gates,
                "missing_or_pending": sorted(missing_review_gates),
            },
            "audit": {
                "ready": not missing_audit_refs,
                "missing_or_pending": sorted(missing_audit_refs),
            },
        },
        "blocking_conditions": list(readiness_contract.get("blocking_conditions", [])),
        "source_design_prep_packet": design_surface,
        "trace_refs": {
            **dict(design_surface.get("trace_refs", {})),
            "implementation_decision_readiness_packet_ref": readiness_contract["metadata"]["machine_path"],
        },
    }
    return response


def build_formal_client_export_page_layer_readiness_surface(
    payload: Any,
    *,
    source_implementation_decision_packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_surface = _leadpack_candidate_surface_core(payload, requested_action="preview")
    activation_prep = build_leadpack_activation_prep_surface(payload, requested_action="packet")
    implementation_packet = (
        dict(source_implementation_decision_packet)
        if source_implementation_decision_packet is not None
        else build_leadpack_implementation_decision_readiness_packet_surface(payload)
    )

    activation_evidence = dict(activation_prep.get("evidence_pack", {}))
    activation_replay = dict(activation_prep.get("simulation_replay", {}))
    implementation_decision = dict(implementation_packet.get("decision_scope", {}))
    hold_sources = list(implementation_packet.get("hold_sources", []))

    missing_approvals = _dedupe_preserve_order(
        list(candidate_surface.get("missing_approvals", []))
        + list(activation_replay.get("missing_approvals", []))
        + list(implementation_packet.get("approval_readiness_summary", {}).get("missing_or_pending", []))
    )
    missing_review_gates = _dedupe_preserve_order(
        list(candidate_surface.get("missing_review_gates", []))
        + list(activation_replay.get("missing_review_gates", []))
        + list(implementation_packet.get("review_gate_readiness_summary", {}).get("missing_or_pending", []))
    )
    missing_audit_refs = _dedupe_preserve_order(
        list(candidate_surface.get("missing_audit_refs", []))
        + list(activation_replay.get("missing_audit_refs", []))
        + list(implementation_packet.get("audit_readiness_summary", {}).get("missing_or_pending", []))
    )
    missing_owner_signoffs = _dedupe_preserve_order(
        list(implementation_packet.get("owner_signoff_summary", {}).get("missing_or_pending", []))
    )

    missing_prerequisites = _dedupe_preserve_order(
        [f"approval:{item}" for item in missing_approvals]
        + [f"review_gate:{item}" for item in missing_review_gates]
        + [f"audit_ref:{item}" for item in missing_audit_refs]
        + [f"owner_signoff:{item}" for item in missing_owner_signoffs]
        + [
            f"implementation_hold:{source.get('source_type', 'unknown')}:{source.get('source_id', 'UNKNOWN')}"
            for source in hold_sources
        ]
        + [
            "implementation_decision_not_approved",
            "external_release_not_approved",
            "client_visible_export_release_not_approved",
            "client_page_publication_not_approved",
        ]
    )

    disabled_capability_reasons = [
        "customer_visible_export_enabled=false",
        "client_page_release_enabled=false",
        "external_release_enabled=false",
        "external_delivery_enabled=false",
        "direct_export_enabled=false",
        "export_artifact_generation_enabled=false",
        "page_publication_enabled=false",
    ]
    blocked_reasons = _dedupe_preserve_order(
        list(candidate_surface.get("blocked_reasons", []))
        + list(activation_evidence.get("activation_blockers_remaining", []))
        + list(implementation_packet.get("blocking_conditions", []))
        + disabled_capability_reasons
        + [
            "internal_preview_readiness_only",
            "release_blocked_by_governance",
            "implementation_decision_not_approved",
        ]
    )
    why_not_live = _dedupe_preserve_order(
        list(candidate_surface.get("why_not_live", []))
        + disabled_capability_reasons
        + [
            "FORMAL_CLIENT_EXPORT_AND_PAGE_LAYER_RESERVED_NOT_LIVE",
            "approval_audit_and_implementation_decision_required_before_live",
        ]
    )

    source_formal_object_types = sorted(candidate_surface.get("formal_object_refs", {}).keys())
    source_readiness_refs = {
        "leadpack_candidate": {
            "surface_id": candidate_surface.get("surface_id"),
            "surface_state": candidate_surface.get("surface_state"),
            "candidate_status": candidate_surface.get("candidate_status"),
            "readiness_only": bool(candidate_surface.get("readiness_only", True)),
            "candidate_only": bool(candidate_surface.get("candidate_only", True)),
            "external_delivery_enabled": bool(candidate_surface.get("external_delivery_enabled", False)),
            "direct_export_enabled": bool(candidate_surface.get("direct_export_enabled", False)),
            "readback_summary": dict(candidate_surface.get("candidate_readback_summary", {})),
        },
        "activation_prep": {
            "surface_id": activation_prep.get("surface_id"),
            "activation_prep_status": activation_prep.get("readiness_transition", {}).get("current_prep_status"),
            "evidence_pack_status": activation_evidence.get("evidence_pack_status"),
            "simulation_replay_status": activation_replay.get("replay_status"),
            "external_delivery_enabled": bool(activation_prep.get("external_delivery_enabled", False)),
        },
        "implementation_decision": {
            "surface_id": implementation_packet.get("surface_id"),
            "readiness_state": implementation_packet.get("readiness_state"),
            "implementation_decision_packet_status": implementation_packet.get("implementation_decision_packet_status"),
            "implementation_decision_ready": bool(implementation_packet.get("implementation_decision_ready", False)),
            "implementation_decision_executed": bool(
                implementation_packet.get("implementation_decision_executed", False)
            ),
            "implementation_approved": bool(implementation_packet.get("implementation_approved", False)),
            "decision_scope": implementation_decision,
        },
    }
    operator_readback_summary = {
        "readback_ready": True,
        "readback_surface": "formal_client_export_page_layer_readiness",
        "operator_can_read_internal_preview": True,
        "operator_can_review_readiness": True,
        "operator_can_direct_export": False,
        "operator_can_deliver_external": False,
        "operator_can_enable_external_release": False,
        "operator_can_enable_customer_visible_export": False,
        "operator_can_generate_export_artifact": False,
        "operator_can_publish_customer_page": False,
        "missing_prerequisite_count": len(missing_prerequisites),
        "blocked_reason_count": len(blocked_reasons),
        "source_formal_object_types": source_formal_object_types,
        "source_readiness_surfaces": list(source_readiness_refs.keys()),
    }

    return {
        "surface_id": "formal_client_export_page_layer_readiness",
        "surface_state": "governed-hold",
        "surface_mode": "preview-only",
        "surface_access": "internal-readable",
        "internal_only": True,
        "readiness_only": True,
        "projection_only": True,
        "review_only": True,
        "non_live": True,
        "release_blocked": True,
        "customer_visible_export_enabled": False,
        "client_page_release_enabled": False,
        "external_release_enabled": False,
        "external_delivery_enabled": False,
        "direct_export_enabled": False,
        "export_artifact_generation_enabled": False,
        "page_publication_enabled": False,
        "readiness_state": "RESERVED_NOT_LIVE",
        "release_layer": "RESERVED_NOT_LIVE",
        "blocked_reasons": blocked_reasons,
        "why_not_live": why_not_live,
        "missing_prerequisites": missing_prerequisites,
        "source_readiness_refs": source_readiness_refs,
        "operator_readback_summary": operator_readback_summary,
        "trace_refs": {
            **dict(candidate_surface.get("trace_refs", {})),
            "source_readiness_surface_ids": [
                "leadpack_candidate",
                "activation_prep",
                "implementation_decision",
            ],
        },
    }


def register_route_table(router: object | None, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if router is None:
        return routes
    if hasattr(router, "extend"):
        router.extend(routes)
    elif hasattr(router, "append"):
        for route in routes:
            router.append(route)
    elif hasattr(router, "register"):
        for route in routes:
            router.register(route)
    elif hasattr(router, "add_api_route"):
        for route in routes:
            router.add_api_route(route["path"], route["handler"], methods=[route["method"]])
    return routes


__all__ = [
    "build_formal_client_export_page_layer_readiness_surface",
    "build_stage6_preview_surface",
    "build_leadpack_activation_design_implementation_prep_surface",
    "build_leadpack_activation_prep_surface",
    "build_leadpack_external_delivery_candidate_surface",
    "build_leadpack_implementation_decision_readiness_packet_surface",
    "build_stage7_preview_surface",
    "build_stage8_preview_surface",
    "build_stage9_preview_surface",
    "get_surface_runtime_defaults",
    "register_route_table",
]
