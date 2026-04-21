from __future__ import annotations

from typing import Any, Mapping

from shared.contract_loader import load_contract
from shared.contracts_runtime import ContractRecord, ContractStore, StageBundle

from storage.db import (
    DatabaseSession,
    PersistedOperatorAction,
    PersistedRecord,
    PersistedStageState,
    PersistedWorkItem,
    build_persisted_at,
)
from storage.operator_loop_contracts import (
    action_is_currently_allowed,
    build_work_item_key,
    list_pending_button_flows,
    resolve_assignment,
    resolve_button_flow,
    review_action_spec,
)
from storage.repositories import (
    BuyerFitRepository,
    ContactTargetRepository,
    DeliveryRecordRepository,
    GovernanceFeedbackEventRepository,
    LegalActionActorProfileRepository,
    OfferRecommendationRepository,
    OperatorActionRepository,
    OpportunityOutcomeEventRepository,
    OrderRecordRepository,
    OutreachPlanRepository,
    PaymentRecordRepository,
    ProcurementDecisionActorProfileRepository,
    SaleableOpportunityRepository,
    TouchRecordRepository,
    WorkItemRepository,
)
from storage.repositories._base import PRIMARY_STATUS_FIELDS


STAGE_SURFACE_IDS = {
    7: "opportunity_pool",
    8: "outreach_workbench",
    9: "order_delivery_workbench",
}

STAGE_ROOT_OBJECTS = {
    7: ("saleable_opportunity", "opportunity_id"),
    8: ("touch_record", "touch_record_id"),
    9: ("order_record", "order_id"),
}

STAGE_INPUT_FIELDS = {
    7: (
        "policy_trace",
        "policy_decision_state",
        "semantic_trace",
        "semantic_decision_state",
        "semantic_additions",
        "buyer_fit_id",
        "offer_recommendation_id",
        "legal_action_actor_id",
        "procurement_decision_actor_id",
        "multi_competitor_collection_id_optional",
        "winning_competitor_candidate_id_optional",
        "winning_challenger_profile_id_optional",
    ),
    8: (
        "policy_trace",
        "policy_decision_state",
        "permission_trace",
        "permission_decision_state",
        "permission_governance",
        "governance_trace",
        "governance_decision_state",
        "governance_additions",
        "semantic_trace",
        "semantic_decision_state",
        "semantic_additions",
        "feedback_reason",
        "next_step_optional",
        "written_back_at_optional",
        "stop_reason_optional",
        "retry_scheduled_optional",
        "writeback_targets",
        "writeback_target_optional",
        "failure_reason_tag_optional",
        "human_handoff_policy_id_optional",
        "human_handoff_next_owner_role_optional",
        "human_handoff_sla_hours_optional",
        "human_handoff_sla_due_at_optional",
        "human_handoff_reason_optional",
        "next_touch_due_at_optional",
        "retry_count",
        "max_retry_count",
        "attempt_index",
        "cadence_profile_id",
        "retry_policy_id",
        "stop_policy_id",
    ),
    9: (
        "policy_trace",
        "policy_decision_state",
        "permission_trace",
        "permission_decision_state",
        "permission_governance",
        "governance_trace",
        "governance_decision_state",
        "governance_additions",
        "semantic_trace",
        "semantic_decision_state",
        "semantic_additions",
        "outcome_writeback_targets",
        "outcome_authoritative_base_targets",
        "upstream_feedback_projected_targets",
        "upstream_feedback_advisory_targets",
        "governance_writeback_targets_optional",
        "governance_legacy_writeback_targets",
        "governance_owned_self_target",
        "payment_exception_writeback_targets_optional",
        "delivery_exception_writeback_targets_optional",
        "effective_writeback_targets",
        "resolved_effective_writeback_targets",
        "writeback_contract_state",
        "writeback_contract_semantics",
        "writeback_source_contracts",
        "writeback_target_sources",
        "writeback_target_contracts",
        "writeback_persistence_targets",
        "writeback_projected_targets",
        "writeback_advisory_targets",
        "writeback_trace_only_targets",
        "impact_executor_state",
        "impact_runtime_executor_enabled",
        "impact_mutation_mode",
        "impact_formal_targets",
        "impact_targets_projected",
        "impact_targets_projected_contract_only",
        "impact_targets_advisory",
        "impact_mutations",
        "impact_projected_contracts",
        "impact_advisories",
        "impact_trace",
    ),
}

STAGE_FORMAL_OBJECTS = {
    7: (
        "saleable_opportunity",
        "offer_recommendation",
        "buyer_fit",
        "legal_action_actor_profile",
        "procurement_decision_actor_profile",
    ),
    8: (
        "contact_target",
        "outreach_plan",
        "touch_record",
    ),
    9: (
        "order_record",
        "payment_record",
        "delivery_record",
        "opportunity_outcome_event",
        "governance_feedback_event",
    ),
}

STAGE_DEFAULT_MODES = {
    7: "preview-only",
    8: "draft-only",
    9: "draft-only",
}

STAGE_OPERATOR_OPERATION_IDS = {
    7: "submitStage7OperatorAction",
    8: "submitStage8OperatorAction",
    9: "submitStage9OperatorAction",
}

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

SURFACE_OPERATIONAL_STATE_MAP = {
    "preview-ready": "preview_ready",
    "draft-only": "draft_only",
    "review-required": "review_required",
    "governed-hold": "governed_hold",
    "blocked": "governed_hold",
}


class OperationalContractError(Exception):
    def __init__(self, code: str, *, meta: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.meta = dict(meta or {})
        spec = _error_catalog().get(code, {})
        self.http_status = int(spec.get("httpStatus", 409))
        self.message = str(spec.get("message", code))
        super().__init__(self.message)

    def as_payload(self) -> dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
            "meta": {
                "http_status": self.http_status,
                **self.meta,
            },
        }


def _error_catalog() -> dict[str, dict[str, Any]]:
    catalog = load_contract("contracts/api/error_code_catalog.json")
    items = {}
    for category in catalog["categories"]:
        for entry in category["items"]:
            items[str(entry["code"])] = dict(entry)
    return items


def _approval_chain_status(
    *,
    reviewer_role: str,
    reviewer: str,
    assignment_resolved_from: str,
    governed_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reviewer_role = str(reviewer_role or "").strip()
    reviewer = str(reviewer or "").strip()
    assignment_resolved_from = str(assignment_resolved_from or "").strip()
    approval_state = ""
    if governed_context is not None:
        approval_state = str(governed_context.get("approval_state", "") or "").strip()

    missing_fields: list[str] = []
    if not reviewer_role:
        missing_fields.append("reviewer_role")
    if not reviewer:
        missing_fields.append("reviewer")
    if assignment_resolved_from in {"", "unassigned"}:
        missing_fields.append("assignment_resolution")

    return {
        "available": not missing_fields,
        "requirement_mode": "resolved_reviewer_chain",
        "reviewer_role": reviewer_role,
        "reviewer": reviewer,
        "assignment_resolved_from": assignment_resolved_from or "unassigned",
        "approval_state": approval_state or "UNKNOWN",
        "missing_fields": missing_fields,
    }


def reset_default_storage() -> None:
    DatabaseSession.default().clear()


def reopen_default_storage() -> None:
    DatabaseSession.default(reload_from_disk=True)


def persist_stage_bundle(payload: Any) -> Any:
    if not isinstance(payload, StageBundle):
        return payload
    if payload.stage == 7:
        return _persist_stage7_bundle(payload)
    if payload.stage == 8:
        return _persist_stage8_bundle(payload)
    if payload.stage == 9:
        return _persist_stage9_bundle(payload)
    return payload


def hydrate_stage_bundle(stage_key: str, payload: Mapping[str, Any]) -> StageBundle | None:
    if stage_key == "stage7":
        return _hydrate_stage7_bundle(payload)
    if stage_key == "stage8":
        return _hydrate_stage8_bundle(payload)
    if stage_key == "stage9":
        return _hydrate_stage9_bundle(payload)
    return None


def get_operational_context(payload: Any, *, stage_scope: int | None = None) -> dict[str, Any] | None:
    bundle = _resolve_bundle_for_stage(payload, stage_scope)
    if bundle is None:
        return None
    work_item = _get_persisted_work_item(bundle)
    if work_item is None:
        return None
    actions = OperatorActionRepository().list(work_item_id=work_item.work_item_id)
    return _build_operational_context(_work_item_with_refreshed_pending_actions(work_item), actions)


def get_transient_preview_context(payload: Any, *, stage_scope: int | None = None) -> dict[str, Any] | None:
    bundle = _resolve_bundle_for_stage(payload, stage_scope)
    if bundle is None:
        return None
    return _build_transient_preview_context(bundle)


def list_stage_work_items(stage_scope: int, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    items = WorkItemRepository().list(stage_scope=stage_scope)
    if payload:
        filters = {
            key: str(value)
            for key, value in payload.items()
            if key.endswith("_id") and value not in (None, "", "UNKNOWN")
        }
        if filters:
            items = [
                item
                for item in items
                if all(item.object_refs.get(key) == value for key, value in filters.items())
            ]
    action_repo = OperatorActionRepository()
    return [
        _build_operational_context(
            _work_item_with_refreshed_pending_actions(item),
            action_repo.list(work_item_id=item.work_item_id),
        )
        for item in items
    ]


def record_operator_action(payload: Any, *, stage_scope: int) -> dict[str, Any]:
    bundle = _resolve_bundle_for_stage(payload, stage_scope)
    if bundle is not None:
        persist_stage_bundle(bundle)

    action_payload = dict(payload.inputs) if isinstance(payload, StageBundle) else dict(payload)
    action_id = str(action_payload.get("action_id", "")).strip()
    button_flow_id = str(action_payload.get("button_flow_id", "")).strip() or None
    try:
        action_spec = review_action_spec(action_id)
    except KeyError as exc:
        raise OperationalContractError(
            "ACTION-409-NOT_PENDING",
            meta={
                "stage_scope": stage_scope,
                "action_id": action_id,
                "reason": "unsupported_action_id",
            },
        ) from exc

    work_item = _resolve_work_item(stage_scope, action_payload, bundle)
    if work_item is None:
        raise OperationalContractError(
            "WORKITEM-404-NOT_FOUND",
            meta={
                "stage_scope": stage_scope,
                "action_id": action_id,
                "button_flow_id": button_flow_id,
            },
        )

    approval_chain = _approval_chain_status(
        reviewer_role=work_item.reviewer_role,
        reviewer=work_item.reviewer,
        assignment_resolved_from=work_item.assignment_resolved_from,
        governed_context=work_item.governed_context,
    )
    if action_spec.requires_approval_chain and not approval_chain["available"]:
        raise OperationalContractError(
            "ACTION-409-APPROVAL_REQUIRED",
            meta={
                "stage_scope": stage_scope,
                "action_id": action_id,
                "button_flow_id": button_flow_id,
                "work_item_id": work_item.work_item_id,
                "work_item_key": work_item.work_item_key,
                "review_requirement": action_spec.review_requirement,
                "approval_requirement_mode": approval_chain["requirement_mode"],
                "approval_state": approval_chain["approval_state"],
                "missing_approval_fields": list(approval_chain["missing_fields"]),
            },
        )

    try:
        _, flow = action_is_currently_allowed(
            action_id=action_id,
            surface_id=work_item.surface_id,
            surface_operational_state=work_item.surface_operational_state,
            current_operational_state=work_item.current_operational_state,
            assignment_lifecycle_state=work_item.assignment_lifecycle_state,
            button_flow_id=button_flow_id,
            has_repository_state=True,
            has_approval_chain=bool(approval_chain["available"]),
            has_audit_trace=bool(work_item.audit_refs),
            internal_only=True,
        )
    except KeyError as exc:
        reason = "button_flow_not_resolved" if str(exc) == "'button_flow_not_resolved'" else "action_not_pending"
        raise OperationalContractError(
            "ACTION-409-NOT_PENDING",
            meta={
                "stage_scope": stage_scope,
                "action_id": action_id,
                "button_flow_id": button_flow_id,
                "work_item_id": work_item.work_item_id,
                "work_item_key": work_item.work_item_key,
                "reason": reason,
            },
        ) from exc

    if flow and flow.api_operation_id != STAGE_OPERATOR_OPERATION_IDS[stage_scope]:
        raise OperationalContractError(
            "ACTION-409-NOT_PENDING",
            meta={
                "stage_scope": stage_scope,
                "action_id": action_id,
                "button_flow_id": button_flow_id,
                "work_item_id": work_item.work_item_id,
                "work_item_key": work_item.work_item_key,
                "reason": "button_flow_not_bound_to_operator_action_route",
            },
        )

    if action_spec.requires_audit_trace and not work_item.audit_refs:
        raise OperationalContractError(
            "ACTION-409-AUDIT_REQUIRED",
            meta={
                "stage_scope": stage_scope,
                "action_id": action_id,
                "button_flow_id": button_flow_id,
                "work_item_id": work_item.work_item_id,
                "work_item_key": work_item.work_item_key,
                "audit_requirement": action_spec.audit_requirement,
            },
        )

    now = build_persisted_at()
    next_state = str(action_spec.resulting_operational_state or work_item.current_operational_state)
    reason = str(action_payload.get("reason", "")).strip()
    requested_by_role = str(action_payload.get("requested_by_role", work_item.assigned_owner_role or "single_operator"))
    requested_by = str(action_payload.get("requested_by", work_item.assigned_owner or ""))
    effective_trace_refs = dict(work_item.trace_refs)
    if not effective_trace_refs:
        effective_trace_refs["operator_action_trace_ref"] = f"TRACE-S{stage_scope}-{work_item.primary_record_id}"
    effective_audit_refs = dict(work_item.audit_refs)

    action_repo = OperatorActionRepository()
    existing_actions = action_repo.list(work_item_id=work_item.work_item_id)
    action_event = PersistedOperatorAction(
        action_event_id=f"ACT-S{stage_scope}-{work_item.primary_record_id}-{len(existing_actions) + 1}",
        work_item_id=work_item.work_item_id,
        stage_scope=stage_scope,
        action_id=action_id,
        button_flow_id=flow.flow_id if flow else button_flow_id,
        action_state=next_state,
        resulting_assignment_lifecycle_state=action_spec.resulting_assignment_lifecycle_state,
        requested_by_role=requested_by_role,
        requested_by=requested_by,
        assigned_owner_role=work_item.assigned_owner_role,
        assigned_owner=work_item.assigned_owner,
        reviewer_role=work_item.reviewer_role,
        reviewer=work_item.reviewer,
        reason=reason,
        object_refs=dict(work_item.object_refs),
        trace_refs=effective_trace_refs,
        audit_refs=effective_audit_refs,
        requested_at=now,
        completed_at=now if next_state in {"action_completed", "action_denied", "action_returned_for_revision", "governed_hold"} else None,
    )
    action_repo.append(action_event)

    assignment = _resolve_assignment_for_state(
        stage_scope=stage_scope,
        current_operational_state=next_state,
        existing_work_item=work_item,
    )
    updated_work_item = PersistedWorkItem(
        work_item_id=work_item.work_item_id,
        work_item_key=work_item.work_item_key,
        stage_scope=work_item.stage_scope,
        project_id=work_item.project_id,
        surface_id=work_item.surface_id,
        primary_object_type=work_item.primary_object_type,
        primary_record_id=work_item.primary_record_id,
        assignment_profile_id=str(assignment["assignment_profile_id"]),
        assignment_lifecycle_state=str(
            action_spec.resulting_assignment_lifecycle_state or assignment["assignment_lifecycle_state"]
        ),
        object_refs=dict(work_item.object_refs),
        surface_operational_state=work_item.surface_operational_state,
        current_operational_state=next_state,
        assigned_owner_role=str(assignment["assigned_owner_role"]),
        assigned_owner=str(assignment["assigned_owner"]),
        reviewer_role=str(assignment["reviewer_role"]),
        reviewer=str(assignment["reviewer"]),
        assignment_resolved_from=str(assignment["resolved_from"]),
        assignment_simplified_boundary=list(assignment["simplified_boundary"]),
        pending_actions=[],
        pending_button_flows=[],
        last_action_id=action_id,
        last_action_state=next_state,
        last_action_at=now,
        trace_refs=effective_trace_refs,
        audit_refs=effective_audit_refs,
        decision_states=dict(work_item.decision_states),
        governed_context=dict(work_item.governed_context),
        created_at=work_item.created_at,
        updated_at=now,
    )
    pending_actions, pending_button_flows = _pending_operator_actions(updated_work_item)
    updated_work_item = PersistedWorkItem(
        work_item_id=updated_work_item.work_item_id,
        work_item_key=updated_work_item.work_item_key,
        stage_scope=updated_work_item.stage_scope,
        project_id=updated_work_item.project_id,
        surface_id=updated_work_item.surface_id,
        primary_object_type=updated_work_item.primary_object_type,
        primary_record_id=updated_work_item.primary_record_id,
        assignment_profile_id=updated_work_item.assignment_profile_id,
        assignment_lifecycle_state=updated_work_item.assignment_lifecycle_state,
        object_refs=dict(updated_work_item.object_refs),
        surface_operational_state=updated_work_item.surface_operational_state,
        current_operational_state=updated_work_item.current_operational_state,
        assigned_owner_role=updated_work_item.assigned_owner_role,
        assigned_owner=updated_work_item.assigned_owner,
        reviewer_role=updated_work_item.reviewer_role,
        reviewer=updated_work_item.reviewer,
        assignment_resolved_from=updated_work_item.assignment_resolved_from,
        assignment_simplified_boundary=list(updated_work_item.assignment_simplified_boundary),
        pending_actions=pending_actions,
        pending_button_flows=pending_button_flows,
        last_action_id=updated_work_item.last_action_id,
        last_action_state=updated_work_item.last_action_state,
        last_action_at=updated_work_item.last_action_at,
        trace_refs=dict(updated_work_item.trace_refs),
        audit_refs=dict(updated_work_item.audit_refs),
        decision_states=dict(updated_work_item.decision_states),
        governed_context=dict(updated_work_item.governed_context),
        created_at=updated_work_item.created_at,
        updated_at=updated_work_item.updated_at,
    )
    WorkItemRepository().save(updated_work_item)

    return {
        "action_event": action_event.as_payload(),
        "work_item": _build_operational_context(
            updated_work_item,
            action_repo.list(work_item_id=updated_work_item.work_item_id),
        ),
    }


def _persist_stage7_bundle(bundle: StageBundle) -> StageBundle:
    SaleableOpportunityRepository().save(bundle.record("saleable_opportunity").data)
    OfferRecommendationRepository().save(bundle.record("offer_recommendation").data)
    BuyerFitRepository().save(bundle.record("buyer_fit").data)
    LegalActionActorProfileRepository().save(bundle.record("legal_action_actor_profile").data)
    ProcurementDecisionActorProfileRepository().save(bundle.record("procurement_decision_actor_profile").data)
    _persist_auxiliary_record(
        object_type="multi_competitor_collection",
        id_field="multi_competitor_collection_id",
        stage_scope=7,
        payload=bundle.record("multi_competitor_collection").data,
    )
    _save_stage_state(bundle)
    _sync_stage_operational_loop(bundle)
    return bundle


def _persist_stage8_bundle(bundle: StageBundle) -> StageBundle:
    ContactTargetRepository().save(bundle.record("contact_target").data)
    OutreachPlanRepository().save(bundle.record("outreach_plan").data)
    TouchRecordRepository().save(bundle.record("touch_record").data)
    _save_stage_state(bundle)
    _sync_stage_operational_loop(bundle)
    return bundle


def _persist_stage9_bundle(bundle: StageBundle) -> StageBundle:
    OrderRecordRepository().save(bundle.record("order_record").data)
    PaymentRecordRepository().save(bundle.record("payment_record").data)
    DeliveryRecordRepository().save(bundle.record("delivery_record").data)
    OpportunityOutcomeEventRepository().save(bundle.record("opportunity_outcome_event").data)
    GovernanceFeedbackEventRepository().save(bundle.record("governance_feedback_event").data)
    _save_stage_state(bundle)
    _sync_stage_operational_loop(bundle)
    return bundle


def _save_stage_state(bundle: StageBundle) -> None:
    root_object_type, root_id_field = STAGE_ROOT_OBJECTS[bundle.stage]
    root_record = bundle.record(root_object_type).data
    project_id = str(root_record["project_id"])
    inputs_snapshot = {
        field_name: bundle.inputs.get(field_name)
        for field_name in STAGE_INPUT_FIELDS[bundle.stage]
        if bundle.inputs.get(field_name) not in (None, "")
    }
    DatabaseSession.default().upsert_stage_state(
        PersistedStageState(
            stage_scope=bundle.stage,
            project_id=project_id,
            surface_id=STAGE_SURFACE_IDS[bundle.stage],
            root_object_type=root_object_type,
            root_record_id=str(root_record[root_id_field]),
            inputs=inputs_snapshot,
            persisted_at=build_persisted_at(),
            typed_object_refs=_bundle_object_refs(bundle),
        )
    )


def _sync_stage_operational_loop(bundle: StageBundle) -> PersistedWorkItem:
    project_id = _project_id_for_bundle(bundle)
    surface_id = STAGE_SURFACE_IDS[bundle.stage]
    root_object_type, root_id_field = STAGE_ROOT_OBJECTS[bundle.stage]
    root_record = bundle.record(root_object_type).data
    primary_record_id = str(root_record[root_id_field])
    surface_state = _surface_state_for_bundle(bundle, default_mode=STAGE_DEFAULT_MODES[bundle.stage])
    surface_operational_state = SURFACE_OPERATIONAL_STATE_MAP[surface_state]
    existing = WorkItemRepository().get(
        stage_scope=bundle.stage,
        surface_id=surface_id,
        primary_object_type=root_object_type,
        primary_record_id=primary_record_id,
    )
    if existing and existing.current_operational_state in {
        "action_submitted",
        "action_completed",
        "action_denied",
        "action_returned_for_revision",
        "governed_hold",
    }:
        current_state = existing.current_operational_state
    elif surface_operational_state in {"review_required", "governed_hold"}:
        current_state = surface_operational_state
    else:
        current_state = _baseline_current_operational_state(surface_operational_state)

    assignment = _resolve_assignment_for_state(
        stage_scope=bundle.stage,
        current_operational_state=current_state,
        existing_work_item=existing,
    )
    trace_refs, audit_refs = _bundle_trace_and_audit_refs(bundle)
    if existing is not None:
        trace_refs = {**existing.trace_refs, **trace_refs}
        audit_refs = {**existing.audit_refs, **audit_refs}
    work_item = PersistedWorkItem(
        work_item_id=existing.work_item_id if existing else f"WI-S{bundle.stage}-{primary_record_id}",
        work_item_key=existing.work_item_key
        if existing
        else build_work_item_key(
            stage_scope=bundle.stage,
            surface_id=surface_id,
            primary_object_type=root_object_type,
            primary_record_id=primary_record_id,
        ),
        stage_scope=bundle.stage,
        project_id=project_id,
        surface_id=surface_id,
        primary_object_type=root_object_type,
        primary_record_id=primary_record_id,
        assignment_profile_id=str(assignment["assignment_profile_id"]),
        assignment_lifecycle_state=str(assignment["assignment_lifecycle_state"]),
        object_refs=_bundle_object_refs(bundle),
        surface_operational_state=surface_operational_state,
        current_operational_state=current_state,
        assigned_owner_role=str(assignment["assigned_owner_role"]),
        assigned_owner=str(assignment["assigned_owner"]),
        reviewer_role=str(assignment["reviewer_role"]),
        reviewer=str(assignment["reviewer"]),
        assignment_resolved_from=str(assignment["resolved_from"]),
        assignment_simplified_boundary=list(assignment["simplified_boundary"]),
        pending_actions=[],
        pending_button_flows=[],
        last_action_id=existing.last_action_id if existing else None,
        last_action_state=existing.last_action_state if existing else None,
        last_action_at=existing.last_action_at if existing else None,
        trace_refs=trace_refs,
        audit_refs=audit_refs,
        decision_states=_bundle_decision_states(bundle),
        governed_context=_bundle_governed_context(bundle),
        created_at=existing.created_at if existing else build_persisted_at(),
        updated_at=build_persisted_at(),
    )
    pending_actions, pending_button_flows = _pending_operator_actions(work_item)
    work_item = PersistedWorkItem(
        work_item_id=work_item.work_item_id,
        work_item_key=work_item.work_item_key,
        stage_scope=work_item.stage_scope,
        project_id=work_item.project_id,
        surface_id=work_item.surface_id,
        primary_object_type=work_item.primary_object_type,
        primary_record_id=work_item.primary_record_id,
        assignment_profile_id=work_item.assignment_profile_id,
        assignment_lifecycle_state=work_item.assignment_lifecycle_state,
        object_refs=dict(work_item.object_refs),
        surface_operational_state=work_item.surface_operational_state,
        current_operational_state=work_item.current_operational_state,
        assigned_owner_role=work_item.assigned_owner_role,
        assigned_owner=work_item.assigned_owner,
        reviewer_role=work_item.reviewer_role,
        reviewer=work_item.reviewer,
        assignment_resolved_from=work_item.assignment_resolved_from,
        assignment_simplified_boundary=list(work_item.assignment_simplified_boundary),
        pending_actions=pending_actions,
        pending_button_flows=pending_button_flows,
        last_action_id=work_item.last_action_id,
        last_action_state=work_item.last_action_state,
        last_action_at=work_item.last_action_at,
        trace_refs=dict(work_item.trace_refs),
        audit_refs=dict(work_item.audit_refs),
        decision_states=dict(work_item.decision_states),
        governed_context=dict(work_item.governed_context),
        created_at=work_item.created_at,
        updated_at=work_item.updated_at,
    )
    return WorkItemRepository().save(work_item)


def _get_stage_work_item(stage_scope: int, primary_object_type: str, primary_record_id: str) -> PersistedWorkItem | None:
    return WorkItemRepository().get(
        stage_scope=stage_scope,
        surface_id=STAGE_SURFACE_IDS[stage_scope],
        primary_object_type=primary_object_type,
        primary_record_id=primary_record_id,
    )


def _record_from_persisted_refs(
    repository: Any,
    *,
    ref_sources: tuple[Mapping[str, Any] | None, ...],
    ref_keys: tuple[str, ...],
    fallback_field: str,
    fallback_value: str,
) -> Any:
    record_id = _resolve_typed_ref(*ref_sources, keys=ref_keys)
    if record_id:
        record = repository.get_by_id(record_id)
        if record is not None:
            return record
        # Once a typed repository-backed ref is present, do not silently
        # broaden replay authority to coarse fallback fields.
        return None
    if fallback_value:
        return repository.find_one_by_field(fallback_field, fallback_value)
    return None


def _resolve_typed_ref(
    *sources: Mapping[str, Any] | None,
    keys: tuple[str, ...],
) -> str:
    for source in sources:
        if source is None:
            continue
        for key in keys:
            value = str(source.get(key, "")).strip()
            if value:
                return value
    return ""


def _latest_stage_state(
    *,
    stage_scope: int,
    surface_id: str,
    criteria: Mapping[str, str],
) -> PersistedStageState | None:
    if not criteria:
        return None
    rows = DatabaseSession.default().find_stage_states(
        stage_scope=stage_scope,
        surface_id=surface_id,
        **dict(criteria),
    )
    if not rows:
        return None
    rows.sort(
        key=lambda row: (
            str(row.persisted_at or ""),
            str(row.root_record_id or ""),
        ),
        reverse=True,
    )
    return rows[0]


def _hydrate_stage7_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    opportunity_id = str(payload.get("opportunity_id", "")).strip()
    if not opportunity_id:
        return None
    opportunity = SaleableOpportunityRepository().get_by_id(opportunity_id)
    if not opportunity:
        return None

    stage_state = _get_stage_state(7, STAGE_SURFACE_IDS[7], opportunity.record_id)
    work_item = _get_stage_work_item(7, "saleable_opportunity", opportunity.record_id)
    stage_inputs = dict(stage_state.inputs) if stage_state is not None else {}
    persisted_refs = stage_state.typed_object_refs if stage_state is not None else None
    buyer_fit_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("buyer_fit_id",),
    )
    buyer_fit = BuyerFitRepository().get_by_id(buyer_fit_id) if buyer_fit_id else None
    offer_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("offer_recommendation_id",),
    )
    offer = OfferRecommendationRepository().get_by_id(offer_id) if offer_id else None
    legal_actor_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("legal_action_actor_id",),
    )
    legal_actor = (
        LegalActionActorProfileRepository().get_by_id(legal_actor_id)
        if legal_actor_id
        else None
    )
    procurement_actor_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("procurement_decision_actor_id",),
    )
    procurement_actor = (
        ProcurementDecisionActorProfileRepository().get_by_id(procurement_actor_id)
        if procurement_actor_id
        else None
    )
    multi_competitor_collection_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("multi_competitor_collection_id_optional",),
    )
    multi_competitor_collection = (
        DatabaseSession.default().get_record("multi_competitor_collection", multi_competitor_collection_id)
        if multi_competitor_collection_id
        else None
    )
    if not all((buyer_fit, offer, legal_actor, procurement_actor, multi_competitor_collection, stage_state)):
        return None

    return StageBundle(
        stage=7,
        records={
            "saleable_opportunity": ContractRecord("saleable_opportunity", opportunity.as_payload()),
            "offer_recommendation": ContractRecord("offer_recommendation", offer.as_payload()),
            "buyer_fit": ContractRecord("buyer_fit", buyer_fit.as_payload()),
            "legal_action_actor_profile": ContractRecord("legal_action_actor_profile", legal_actor.as_payload()),
            "procurement_decision_actor_profile": ContractRecord("procurement_decision_actor_profile", procurement_actor.as_payload()),
            "multi_competitor_collection": ContractRecord(
                "multi_competitor_collection",
                multi_competitor_collection.as_payload(),
            ),
        },
        handoff={},
        inputs=stage_inputs,
    )


def _hydrate_stage8_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    contact_target, outreach_plan, touch_record, stage_state = _find_stage8_records(payload)
    if not all((contact_target, outreach_plan, touch_record, stage_state)):
        return None
    if stage_state.root_record_id != touch_record.record_id:
        stage_state = _get_stage_state(8, STAGE_SURFACE_IDS[8], touch_record.record_id)
    if not stage_state:
        return None

    return StageBundle(
        stage=8,
        records={
            "contact_target": ContractRecord("contact_target", contact_target.as_payload()),
            "outreach_plan": ContractRecord("outreach_plan", outreach_plan.as_payload()),
            "touch_record": ContractRecord("touch_record", touch_record.as_payload()),
        },
        handoff={},
        inputs=dict(stage_state.inputs),
    )


def _hydrate_stage9_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    opportunity_id = str(payload.get("opportunity_id", "")).strip()
    stage_state = _resolve_stage9_stage_state(payload)
    order_id = str(payload.get("order_id", "")).strip() or (
        stage_state.root_record_id if stage_state is not None else ""
    )
    order = OrderRecordRepository().get_by_id(order_id) if order_id else None
    if not order and opportunity_id:
        order = OrderRecordRepository().find_one_by_field("opportunity_id", opportunity_id)
    if not order:
        return None

    if stage_state is None or stage_state.root_record_id != order.record_id:
        stage_state = _get_stage_state(9, STAGE_SURFACE_IDS[9], order.record_id)
    work_item = _get_stage_work_item(9, "order_record", order.record_id)
    persisted_refs = stage_state.typed_object_refs if stage_state is not None else None
    work_item_refs = work_item.object_refs if work_item is not None else None
    payment = _record_from_persisted_refs(
        PaymentRecordRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("payment_id",),
        fallback_field="order_id",
        fallback_value=order.record_id,
    )
    delivery = _record_from_persisted_refs(
        DeliveryRecordRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("delivery_id",),
        fallback_field="order_id",
        fallback_value=order.record_id,
    )
    outcome = _record_from_persisted_refs(
        OpportunityOutcomeEventRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("outcome_event_id",),
        fallback_field="opportunity_id",
        fallback_value=opportunity_id or str(order.object_refs.get("opportunity_id", "")).strip(),
    )
    governance = _record_from_persisted_refs(
        GovernanceFeedbackEventRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("governance_feedback_event_id",),
        fallback_field="project_id",
        fallback_value=order.project_id or "",
    )
    if not all((payment, delivery, outcome, governance, stage_state)):
        return None

    return StageBundle(
        stage=9,
        records={
            "order_record": ContractRecord("order_record", order.as_payload()),
            "payment_record": ContractRecord("payment_record", payment.as_payload()),
            "delivery_record": ContractRecord("delivery_record", delivery.as_payload()),
            "opportunity_outcome_event": ContractRecord("opportunity_outcome_event", outcome.as_payload()),
            "governance_feedback_event": ContractRecord("governance_feedback_event", governance.as_payload()),
        },
        handoff={},
        inputs=dict(stage_state.inputs),
    )


def _resolve_stage8_stage_state(payload: Mapping[str, Any]) -> PersistedStageState | None:
    touch_record_id = str(payload.get("touch_record_id", "")).strip()
    if touch_record_id:
        stage_state = _get_stage_state(8, STAGE_SURFACE_IDS[8], touch_record_id)
        if stage_state is not None:
            return stage_state

    opportunity_id = str(payload.get("opportunity_id", "")).strip()
    if not opportunity_id:
        return None
    return _latest_stage_state(
        stage_scope=8,
        surface_id=STAGE_SURFACE_IDS[8],
        criteria={"opportunity_id": opportunity_id},
    )


def _find_stage8_work_item(
    payload: Mapping[str, Any],
    *,
    stage_state: PersistedStageState | None = None,
) -> PersistedWorkItem | None:
    touch_record_id = str(payload.get("touch_record_id", "")).strip()
    if touch_record_id:
        return _get_stage_work_item(8, "touch_record", touch_record_id)
    if stage_state is not None:
        work_item = _get_stage_work_item(8, "touch_record", stage_state.root_record_id)
        if work_item is not None:
            return work_item

    opportunity_id = str(payload.get("opportunity_id", "")).strip()
    if not opportunity_id:
        return None

    candidates = [
        item
        for item in WorkItemRepository().list(stage_scope=8)
        if item.surface_id == STAGE_SURFACE_IDS[8]
        and item.primary_object_type == "touch_record"
        and item.object_refs.get("opportunity_id") == opportunity_id
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            str(item.updated_at or ""),
            str(item.created_at or ""),
            str(item.primary_record_id or ""),
        ),
        reverse=True,
    )
    return candidates[0]


def _find_stage8_records(payload: Mapping[str, Any]) -> tuple[Any, Any, Any, PersistedStageState | None]:
    stage_state = _resolve_stage8_stage_state(payload)
    work_item = _find_stage8_work_item(payload, stage_state=stage_state)
    touch_record_id = str(payload.get("touch_record_id", "")).strip() or (
        stage_state.root_record_id if stage_state is not None else ""
    )
    if work_item is not None:
        touch_record_id = touch_record_id or str(work_item.primary_record_id or "")
    touch_record = TouchRecordRepository().get_by_id(touch_record_id) if touch_record_id else None
    if not touch_record:
        opportunity_id = str(payload.get("opportunity_id", "")).strip()
        touch_record = TouchRecordRepository().find_one_by_field("opportunity_id", opportunity_id) if opportunity_id else None
    if not touch_record:
        return None, None, None, stage_state

    if stage_state is None or stage_state.root_record_id != touch_record.record_id:
        stage_state = _get_stage_state(8, STAGE_SURFACE_IDS[8], touch_record.record_id)
    persisted_refs = stage_state.typed_object_refs if stage_state is not None else None
    work_item_refs = work_item.object_refs if work_item is not None else None

    contact_target = _record_from_persisted_refs(
        ContactTargetRepository(),
        ref_sources=(persisted_refs, touch_record.object_refs, work_item_refs),
        ref_keys=("contact_target_id",),
        fallback_field="contact_target_id",
        fallback_value="",
    )
    outreach_plan = _record_from_persisted_refs(
        OutreachPlanRepository(),
        ref_sources=(persisted_refs, touch_record.object_refs, work_item_refs),
        ref_keys=("outreach_plan_id",),
        fallback_field="outreach_plan_id",
        fallback_value="",
    )
    return contact_target, outreach_plan, touch_record, stage_state


def _get_stage_state(stage_scope: int, surface_id: str, root_record_id: str | None) -> PersistedStageState | None:
    if not root_record_id:
        return None
    return DatabaseSession.default().get_stage_state(stage_scope, surface_id, root_record_id)


def _resolve_stage9_stage_state(payload: Mapping[str, Any]) -> PersistedStageState | None:
    order_id = str(payload.get("order_id", "")).strip()
    if order_id:
        stage_state = _get_stage_state(9, STAGE_SURFACE_IDS[9], order_id)
        if stage_state is not None:
            return stage_state

    opportunity_id = str(payload.get("opportunity_id", "")).strip()
    if not opportunity_id:
        return None
    return _latest_stage_state(
        stage_scope=9,
        surface_id=STAGE_SURFACE_IDS[9],
        criteria={"opportunity_id": opportunity_id},
    )


def _resolve_bundle_for_stage(payload: Any, stage_scope: int | None) -> StageBundle | None:
    if isinstance(payload, StageBundle):
        return payload
    if not isinstance(payload, Mapping) or stage_scope is None:
        return None
    return hydrate_stage_bundle(f"stage{stage_scope}", payload)


def _resolve_work_item(stage_scope: int, payload: Mapping[str, Any], bundle: StageBundle | None) -> PersistedWorkItem | None:
    if bundle is not None:
        return _get_persisted_work_item(bundle)
    primary = _resolve_primary_record(stage_scope, payload)
    if primary is None:
        return None
    object_type, record = primary
    return WorkItemRepository().get(
        stage_scope=stage_scope,
        surface_id=STAGE_SURFACE_IDS[stage_scope],
        primary_object_type=object_type,
        primary_record_id=record.record_id,
    )


def _surface_state_for_bundle(bundle: StageBundle, *, default_mode: str) -> str:
    decisions = set(_bundle_decision_states(bundle).values())
    statuses = [
        _record_status(object_type, bundle.record(object_type).data)
        for object_type in STAGE_FORMAL_OBJECTS[bundle.stage]
        if object_type in bundle.records
    ]
    review_statuses = set(REVIEW_STATUSES)
    hold_statuses = set(HOLD_STATUSES)
    if bundle.stage == 9:
        review_statuses.discard("PENDING_APPROVAL")
        hold_statuses.add("PENDING_APPROVAL")
    if "BLOCK" in decisions or any(status in BLOCKED_STATUSES for status in statuses):
        return "blocked"
    if "REVIEW" in decisions or any(status in review_statuses for status in statuses):
        return "review-required"
    if any(status in hold_statuses for status in statuses):
        return "governed-hold"
    if default_mode == "draft-only":
        return "draft-only"
    return "preview-ready"


def _baseline_current_operational_state(surface_operational_state: str) -> str:
    if surface_operational_state in {"review_required", "governed_hold"}:
        return surface_operational_state
    return "ready_for_internal_operator_action"


def _build_operational_context(work_item: PersistedWorkItem, actions: list[PersistedOperatorAction]) -> dict[str, Any]:
    action_history = [entry.as_payload() for entry in actions]
    return {
        "context_source": "persisted",
        "persistence_backend": "local_file_backed_json_store",
        "work_item_id": work_item.work_item_id,
        "work_item_key": work_item.work_item_key,
        "stage_scope": work_item.stage_scope,
        "surface_id": work_item.surface_id,
        "primary_object_type": work_item.primary_object_type,
        "primary_record_id": work_item.primary_record_id,
        "surface_operational_state": work_item.surface_operational_state,
        "current_operational_state": work_item.current_operational_state,
        "ready_for_internal_operator_action": work_item.current_operational_state == "ready_for_internal_operator_action",
        "assignment": {
            "assignment_profile_id": work_item.assignment_profile_id,
            "assignment_lifecycle_state": work_item.assignment_lifecycle_state,
            "assigned_owner_role": work_item.assigned_owner_role,
            "assigned_owner": work_item.assigned_owner,
            "reviewer_role": work_item.reviewer_role,
            "reviewer": work_item.reviewer,
            "resolved_from": work_item.assignment_resolved_from,
            "simplified_boundary": list(work_item.assignment_simplified_boundary),
        },
        "object_refs": dict(work_item.object_refs),
        "pending_actions": list(work_item.pending_actions),
        "pending_button_flows": list(work_item.pending_button_flows),
        "last_action": action_history[-1] if action_history else None,
        "action_history": action_history,
        "trace_refs": dict(work_item.trace_refs),
        "audit_refs": dict(work_item.audit_refs),
        "decision_states": dict(work_item.decision_states),
        "governed_context": dict(work_item.governed_context),
        "created_at": work_item.created_at,
        "updated_at": work_item.updated_at,
    }


def _build_transient_preview_context(bundle: StageBundle) -> dict[str, Any]:
    surface_state = _surface_state_for_bundle(bundle, default_mode=STAGE_DEFAULT_MODES[bundle.stage])
    surface_operational_state = SURFACE_OPERATIONAL_STATE_MAP[surface_state]
    current_state = _baseline_current_operational_state(surface_operational_state)
    assignment = _resolve_assignment_for_state(stage_scope=bundle.stage, current_operational_state=current_state)
    approval_chain = _approval_chain_status(
        reviewer_role=str(assignment["reviewer_role"]),
        reviewer=str(assignment["reviewer"]),
        assignment_resolved_from=str(assignment["resolved_from"]),
    )
    root_object_type, root_id_field = STAGE_ROOT_OBJECTS[bundle.stage]
    root_record = bundle.record(root_object_type).data
    work_item_key = build_work_item_key(
        stage_scope=bundle.stage,
        surface_id=STAGE_SURFACE_IDS[bundle.stage],
        primary_object_type=root_object_type,
        primary_record_id=str(root_record[root_id_field]),
    )
    pending_button_flows = list_pending_button_flows(
        stage_scope=bundle.stage,
        surface_id=STAGE_SURFACE_IDS[bundle.stage],
        surface_operational_state=surface_operational_state,
        current_operational_state=current_state,
        assignment_lifecycle_state=str(assignment["assignment_lifecycle_state"]),
        has_repository_state=False,
        has_approval_chain=bool(approval_chain["available"]),
        has_audit_trace=bool(_bundle_trace_and_audit_refs(bundle)[1]),
        internal_only=True,
    )
    return {
        "context_source": "transient_preview",
        "persistence_backend": "local_file_backed_json_store",
        "work_item_key": work_item_key,
        "stage_scope": bundle.stage,
        "surface_id": STAGE_SURFACE_IDS[bundle.stage],
        "primary_object_type": root_object_type,
        "primary_record_id": str(root_record[root_id_field]),
        "surface_operational_state": surface_operational_state,
        "current_operational_state": current_state,
        "ready_for_internal_operator_action": current_state == "ready_for_internal_operator_action",
        "assignment": {
            "assignment_profile_id": assignment["assignment_profile_id"],
            "assignment_lifecycle_state": assignment["assignment_lifecycle_state"],
            "assigned_owner_role": assignment["assigned_owner_role"],
            "assigned_owner": assignment["assigned_owner"],
            "reviewer_role": assignment["reviewer_role"],
            "reviewer": assignment["reviewer"],
            "resolved_from": assignment["resolved_from"],
            "simplified_boundary": assignment["simplified_boundary"],
        },
        "object_refs": _bundle_object_refs(bundle),
        "pending_actions": [],
        "pending_button_flows": [flow.as_payload() for flow in pending_button_flows],
        "trace_refs": _bundle_trace_and_audit_refs(bundle)[0],
        "audit_refs": _bundle_trace_and_audit_refs(bundle)[1],
        "decision_states": _bundle_decision_states(bundle),
        "governed_context": _bundle_governed_context(bundle),
        "preview_generated_at": build_persisted_at(),
    }


def _get_persisted_work_item(bundle: StageBundle) -> PersistedWorkItem | None:
    root_object_type, root_id_field = STAGE_ROOT_OBJECTS[bundle.stage]
    root_record = bundle.record(root_object_type).data
    return WorkItemRepository().get(
        stage_scope=bundle.stage,
        surface_id=STAGE_SURFACE_IDS[bundle.stage],
        primary_object_type=root_object_type,
        primary_record_id=str(root_record[root_id_field]),
    )


def _pending_operator_actions(work_item: PersistedWorkItem) -> tuple[list[str], list[dict[str, str]]]:
    approval_chain = _approval_chain_status(
        reviewer_role=work_item.reviewer_role,
        reviewer=work_item.reviewer,
        assignment_resolved_from=work_item.assignment_resolved_from,
        governed_context=work_item.governed_context,
    )
    pending_flows = list_pending_button_flows(
        stage_scope=work_item.stage_scope,
        surface_id=work_item.surface_id,
        surface_operational_state=work_item.surface_operational_state,
        current_operational_state=work_item.current_operational_state,
        assignment_lifecycle_state=work_item.assignment_lifecycle_state,
        has_repository_state=True,
        has_approval_chain=bool(approval_chain["available"]),
        has_audit_trace=bool(work_item.audit_refs),
        internal_only=True,
    )
    pending_flows = [
        entry
        for entry in pending_flows
        if resolve_button_flow(
            surface_id=work_item.surface_id,
            action_id=entry.action_id,
            button_flow_id=entry.button_flow_id,
        )
        and resolve_button_flow(
            surface_id=work_item.surface_id,
            action_id=entry.action_id,
            button_flow_id=entry.button_flow_id,
        ).api_operation_id
        == STAGE_OPERATOR_OPERATION_IDS[work_item.stage_scope]
    ]
    pending_actions = sorted({entry.action_id for entry in pending_flows})
    return pending_actions, [entry.as_payload() for entry in pending_flows]


def _work_item_with_refreshed_pending_actions(work_item: PersistedWorkItem) -> PersistedWorkItem:
    pending_actions, pending_button_flows = _pending_operator_actions(work_item)
    return PersistedWorkItem(
        work_item_id=work_item.work_item_id,
        work_item_key=work_item.work_item_key,
        stage_scope=work_item.stage_scope,
        project_id=work_item.project_id,
        surface_id=work_item.surface_id,
        primary_object_type=work_item.primary_object_type,
        primary_record_id=work_item.primary_record_id,
        assignment_profile_id=work_item.assignment_profile_id,
        assignment_lifecycle_state=work_item.assignment_lifecycle_state,
        object_refs=dict(work_item.object_refs),
        surface_operational_state=work_item.surface_operational_state,
        current_operational_state=work_item.current_operational_state,
        assigned_owner_role=work_item.assigned_owner_role,
        assigned_owner=work_item.assigned_owner,
        reviewer_role=work_item.reviewer_role,
        reviewer=work_item.reviewer,
        assignment_resolved_from=work_item.assignment_resolved_from,
        assignment_simplified_boundary=list(work_item.assignment_simplified_boundary),
        pending_actions=pending_actions,
        pending_button_flows=pending_button_flows,
        last_action_id=work_item.last_action_id,
        last_action_state=work_item.last_action_state,
        last_action_at=work_item.last_action_at,
        trace_refs=dict(work_item.trace_refs),
        audit_refs=dict(work_item.audit_refs),
        decision_states=dict(work_item.decision_states),
        governed_context=dict(work_item.governed_context),
        created_at=work_item.created_at,
        updated_at=work_item.updated_at,
    )


def _resolve_assignment_for_state(
    *,
    stage_scope: int,
    current_operational_state: str,
    existing_work_item: PersistedWorkItem | None = None,
) -> dict[str, Any]:
    resolved = resolve_assignment(stage_scope=stage_scope, current_operational_state=current_operational_state)
    if existing_work_item is not None:
        # Existing work-item assignment is authoritative; do not silently
        # repopulate an emptied reviewer lane from the static roster.
        resolved["assigned_owner"] = existing_work_item.assigned_owner
        resolved["reviewer"] = existing_work_item.reviewer
        resolved["assigned_owner_role"] = existing_work_item.assigned_owner_role
        resolved["reviewer_role"] = existing_work_item.reviewer_role
        resolved["assignment_profile_id"] = existing_work_item.assignment_profile_id or resolved["assignment_profile_id"]
        resolved["resolved_from"] = existing_work_item.assignment_resolved_from or "unassigned"
        resolved["simplified_boundary"] = list(existing_work_item.assignment_simplified_boundary)
    return resolved


def _resolve_primary_record(stage_scope: int, payload: Mapping[str, Any]) -> tuple[str, Any] | None:
    if stage_scope == 7:
        opportunity_id = str(payload.get("opportunity_id", "")).strip()
        opportunity = SaleableOpportunityRepository().get_by_id(opportunity_id) if opportunity_id else None
        return ("saleable_opportunity", opportunity) if opportunity else None
    if stage_scope == 8:
        _, _, touch_record, _ = _find_stage8_records(payload)
        return ("touch_record", touch_record) if touch_record else None
    if stage_scope == 9:
        stage_state = _resolve_stage9_stage_state(payload)
        order_id = str(payload.get("order_id", "")).strip() or (
            stage_state.root_record_id if stage_state is not None else ""
        )
        order = OrderRecordRepository().get_by_id(order_id) if order_id else None
        if not order:
            opportunity_id = str(payload.get("opportunity_id", "")).strip()
            order = OrderRecordRepository().find_one_by_field("opportunity_id", opportunity_id) if opportunity_id else None
        return ("order_record", order) if order else None
    return None


def _bundle_object_refs(bundle: StageBundle) -> dict[str, str]:
    refs: dict[str, str] = {}
    for object_type in STAGE_FORMAL_OBJECTS[bundle.stage]:
        record = bundle.record(object_type).data
        for key, value in record.items():
            if key.endswith("_id") and value not in (None, "", "UNKNOWN"):
                refs[key] = str(value)
    if bundle.stage == 7:
        legal_actor = bundle.records.get("legal_action_actor_profile")
        if legal_actor is not None and legal_actor.data.get("actor_id") not in (None, "", "UNKNOWN"):
            refs["legal_action_actor_id"] = str(legal_actor.data["actor_id"])
        procurement_actor = bundle.records.get("procurement_decision_actor_profile")
        if procurement_actor is not None and procurement_actor.data.get("actor_id") not in (None, "", "UNKNOWN"):
            refs["procurement_decision_actor_id"] = str(procurement_actor.data["actor_id"])
        if bundle.inputs.get("multi_competitor_collection_id_optional") not in (None, "", "UNKNOWN"):
            refs["multi_competitor_collection_id_optional"] = str(
                bundle.inputs["multi_competitor_collection_id_optional"]
            )
        if bundle.inputs.get("winning_competitor_candidate_id_optional") not in (None, "", "UNKNOWN"):
            refs["winning_competitor_candidate_id_optional"] = str(
                bundle.inputs["winning_competitor_candidate_id_optional"]
            )
        if bundle.inputs.get("winning_challenger_profile_id_optional") not in (None, "", "UNKNOWN"):
            refs["winning_challenger_profile_id_optional"] = str(
                bundle.inputs["winning_challenger_profile_id_optional"]
            )
    return refs


def _persist_auxiliary_record(
    *,
    object_type: str,
    id_field: str,
    stage_scope: int,
    payload: Mapping[str, Any],
) -> PersistedRecord:
    payload_dict = dict(payload)
    ContractStore.default().validate_record(object_type, payload_dict)
    object_refs = {
        key: str(value)
        for key, value in payload_dict.items()
        if key != id_field
        and (key.endswith("_id") or key.endswith("_id_optional"))
        and value not in (None, "", "UNKNOWN")
    }
    trace_refs = {
        key: str(value)
        for key, value in payload_dict.items()
        if "trace" in key.lower() and value not in (None, "", "UNKNOWN")
    }
    audit_refs = {
        key: str(value)
        for key, value in payload_dict.items()
        if "audit" in key.lower() and value not in (None, "", "UNKNOWN")
    }
    project_id = payload_dict.get("project_id")
    return DatabaseSession.default().upsert_record(
        PersistedRecord(
            object_type=object_type,
            record_id=str(payload_dict[id_field]),
            stage_scope=stage_scope,
            project_id=str(project_id) if project_id not in (None, "", "UNKNOWN") else None,
            object_refs=object_refs,
            decision_states={},
            trace_refs=trace_refs,
            audit_refs=audit_refs,
            governed_state={},
            writeback_state={},
            payload=payload_dict,
            persisted_at=build_persisted_at(),
        )
    )


def _bundle_trace_and_audit_refs(bundle: StageBundle) -> tuple[dict[str, str], dict[str, str]]:
    trace_refs: dict[str, str] = {}
    audit_refs: dict[str, str] = {}
    for object_type in STAGE_FORMAL_OBJECTS[bundle.stage]:
        record = bundle.record(object_type).data
        for key, value in record.items():
            if value in (None, "", "UNKNOWN", "NOT_PAID", "NOT_DELIVERED"):
                continue
            if "trace" in key.lower():
                trace_refs[key] = str(value)
            if "audit" in key.lower():
                audit_refs[key] = str(value)
    return trace_refs, audit_refs


def _bundle_decision_states(bundle: StageBundle) -> dict[str, str]:
    return {
        "permission_decision_state": str(bundle.inputs.get("permission_decision_state", "ALLOW")),
        "governance_decision_state": str(bundle.inputs.get("governance_decision_state", "ALLOW")),
        "semantic_decision_state": str(bundle.inputs.get("semantic_decision_state", "ALLOW")),
        "policy_decision_state": str(bundle.inputs.get("policy_decision_state", "ALLOW")),
    }


def _bundle_governed_context(bundle: StageBundle) -> dict[str, Any]:
    governed_context: dict[str, Any] = {
        "surface_mode": STAGE_DEFAULT_MODES[bundle.stage],
    }
    for object_type in STAGE_FORMAL_OBJECTS[bundle.stage]:
        record = bundle.record(object_type).data
        for field_name in (
            "projection_mode",
            "run_mode",
            "governed_execution_mode",
            "approval_state",
            "plan_status",
            "touch_record_state",
            "response_status",
            "feedback_reason",
            "next_step_optional",
            "stop_reason_optional",
            "retry_scheduled_optional",
            "requested_delivery_surface",
            "writeback_required",
            "writeback_targets",
            "writeback_target_optional",
            "written_back_at_optional",
            "failure_reason_tag_optional",
            "retry_count",
            "max_retry_count",
            "attempt_index",
            "cadence_profile_id",
            "retry_policy_id",
            "stop_policy_id",
        ):
            if record.get(field_name) not in (None, ""):
                governed_context[field_name] = record.get(field_name)
    if bundle.stage == 8:
        human_handoff = bundle.record("touch_record").data.get("governed_metadata", {}).get("human_handoff", {})
        if isinstance(human_handoff, Mapping):
            optional_fields = {
                "human_handoff_policy_id_optional": human_handoff.get("policy_id"),
                "human_handoff_next_owner_role_optional": human_handoff.get("next_owner_role_optional"),
                "human_handoff_sla_hours_optional": human_handoff.get("sla_hours_optional"),
                "human_handoff_sla_due_at_optional": human_handoff.get("sla_due_at_optional"),
                "human_handoff_reason_optional": human_handoff.get("reason_optional"),
            }
            for field_name, field_value in optional_fields.items():
                if field_value not in (None, ""):
                    governed_context[field_name] = field_value
    return governed_context


def _project_id_for_bundle(bundle: StageBundle) -> str:
    root_object_type, _ = STAGE_ROOT_OBJECTS[bundle.stage]
    return str(bundle.record(root_object_type).data["project_id"])


def _record_status(object_type: str, record: Mapping[str, Any]) -> str:
    for field_name in PRIMARY_STATUS_FIELDS.get(object_type, ()):
        value = record.get(field_name)
        if value not in (None, ""):
            return str(value)
    return "UNKNOWN"


__all__ = [
    "OperationalContractError",
    "get_operational_context",
    "get_transient_preview_context",
    "hydrate_stage_bundle",
    "list_stage_work_items",
    "persist_stage_bundle",
    "reopen_default_storage",
    "record_operator_action",
    "reset_default_storage",
]
