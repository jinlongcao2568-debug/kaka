from __future__ import annotations

from typing import Any, Mapping

from shared.contract_loader import load_contract
from shared.contracts_runtime import ContractStore, StageBundle
from shared.provider_adapter_config import PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY

from stage7_sales.crm_quote_workbench import (
    CRM_ACTION_ID_INPUT_KEY,
    CRM_QUOTE_WORKBENCH_INPUT_KEY,
    CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY,
    QUOTE_DRAFT_ID_INPUT_KEY,
)
from stage7_sales.leadpack_delivery_package import (
    LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY,
    LEADPACK_DELIVERY_PACKAGE_INPUT_KEY,
    LEADPACK_DELIVERY_READINESS_INPUT_KEY,
    LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY,
    LEADPACK_PACKAGE_ID_INPUT_KEY,
    LEADPACK_PAGE_DRAFT_ID_INPUT_KEY,
    leadpack_delivery_package_summary,
)
from stage9_delivery.order_payment_delivery_execution import (
    DELIVERY_SANDBOX_RECORDS_INPUT_KEY,
    MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY,
    PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY,
    PAYMENT_SANDBOX_RECORDS_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY,
    stage9_execution_ledger_summary,
)
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
    ContactTargetRepository,
    OperatorActionRepository,
    OrderRecordRepository,
    OutreachPlanRepository,
    ProjectFactRepository,
    SaleableOpportunityRepository,
    TouchRecordRepository,
    WorkItemRepository,
)
from storage.repositories._base import PRIMARY_STATUS_FIELDS


STAGE6_PRODUCT_PACKAGE_READINESS_KEY = "stage6_product_package_readiness"

STAGE_SURFACE_IDS = {
    6: "review_report_workbench",
    7: "opportunity_pool",
    8: "outreach_workbench",
    9: "order_delivery_workbench",
}

STAGE_ROOT_OBJECTS = {
    6: ("project_fact", "project_fact_id"),
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
        "stage7_resolution_trace",
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
        "crm_quote_prerequisite_readiness",
        CRM_QUOTE_WORKBENCH_INPUT_KEY,
        CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY,
        "provider_execution_id",
        CRM_ACTION_ID_INPUT_KEY,
        QUOTE_DRAFT_ID_INPUT_KEY,
        LEADPACK_DELIVERY_PACKAGE_INPUT_KEY,
        LEADPACK_DELIVERY_READINESS_INPUT_KEY,
        LEADPACK_PACKAGE_ID_INPUT_KEY,
        LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY,
        LEADPACK_PAGE_DRAFT_ID_INPUT_KEY,
        LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY,
        "_stage7_handoff_snapshot",
        "_stage7_trace_rules_snapshot",
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
        "outbox_id_optional",
        "outreach_execution_outbox_id_optional",
        "outreach_execution_outbox_snapshot",
        "outbox_readiness_summary",
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
        "stage8_resolution_trace",
        "contact_candidate_collection_id_optional",
        "contact_selection_trace_id_optional",
        "winning_contact_candidate_id_optional",
        "reselect_reason_optional",
        "contact_candidate_collection_snapshot",
        "contact_selection_trace_snapshot",
        "_stage8_handoff_snapshot",
        "_stage8_trace_rules_snapshot",
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
        "upstream_feedback_contracts",
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
        "writeback_contract_summary",
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
        "h08_workflow_fallback_trace",
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
        STAGE9_EXECUTION_LEDGER_INPUT_KEY,
        STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY,
        STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY,
        PAYMENT_SANDBOX_RECORDS_INPUT_KEY,
        DELIVERY_SANDBOX_RECORDS_INPUT_KEY,
        MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY,
        PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY,
        "order_execution_id",
        "payment_execution_id",
        "delivery_execution_id",
        "_stage9_handoff_snapshot",
        "_stage9_trace_rules_snapshot",
    ),
}

STAGE_FORMAL_OBJECTS = {
    6: (
        "project_fact",
        "report_record",
        "review_queue_profile",
        "challenger_candidate_profile",
        "legal_action_recommendation",
    ),
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
    6: "preview-only",
    7: "preview-only",
    8: "draft-only",
    9: "draft-only",
}

STAGE_OPERATOR_OPERATION_IDS = {
    6: "submitStage6OperatorAction",
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


def persist_stage6_bundle(bundle: StageBundle) -> StageBundle:
    return _persist_stage6_bundle(bundle)


def persist_stage_bundle(payload: Any) -> Any:
    if not isinstance(payload, StageBundle):
        return payload
    if payload.stage == 6:
        return _persist_stage6_bundle(payload)
    if payload.stage == 7:
        return _persist_stage7_bundle(payload)
    if payload.stage == 8:
        return _persist_stage8_bundle(payload)
    if payload.stage == 9:
        return _persist_stage9_bundle(payload)
    return payload


def hydrate_stage6_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    return _hydrate_stage6_bundle(payload)


def hydrate_stage_bundle(stage_key: str, payload: Mapping[str, Any]) -> StageBundle | None:
    if stage_key == "stage6":
        return _hydrate_stage6_bundle(payload)
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
    if bundle is not None and stage_scope != 6:
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


def _repository_bundle_io_module() -> Any:
    # Keep repository_boundary.py as the public facade while allowing
    # persist/hydrate helpers to live in dedicated modules without eager cycles.
    from storage import repository_bundle_io

    return repository_bundle_io


def _persist_stage7_bundle(bundle: StageBundle) -> StageBundle:
    return _repository_bundle_io_module().persist_stage7_bundle(bundle)


def _persist_stage6_bundle(bundle: StageBundle) -> StageBundle:
    persisted_bundle = _repository_bundle_io_module().persist_stage6_bundle(bundle)
    _sync_stage_operational_loop(bundle)
    return persisted_bundle


def _persist_stage8_bundle(bundle: StageBundle) -> StageBundle:
    return _repository_bundle_io_module().persist_stage8_bundle(bundle)


def _persist_stage9_bundle(bundle: StageBundle) -> StageBundle:
    return _repository_bundle_io_module().persist_stage9_bundle(bundle)


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
    return _repository_bundle_io_module().hydrate_stage7_bundle(payload)


def _hydrate_stage6_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    return _repository_bundle_io_module().hydrate_stage6_bundle(payload)


def _hydrate_stage8_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    return _repository_bundle_io_module().hydrate_stage8_bundle(payload)


def _hydrate_stage9_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    return _repository_bundle_io_module().hydrate_stage9_bundle(payload)


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
    if touch_record_id and not touch_record:
        return None, None, None, stage_state
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
        return _get_stage_state(9, STAGE_SURFACE_IDS[9], order_id)

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
    if bundle.stage == 6:
        project_fact_status = (
            _record_status("project_fact", bundle.record("project_fact").data)
            if "project_fact" in bundle.records
            else "UNKNOWN"
        )
        report_status = (
            _record_status("report_record", bundle.record("report_record").data)
            if "report_record" in bundle.records
            else "UNKNOWN"
        )
        legal_window_status = (
            _record_status("legal_action_recommendation", bundle.record("legal_action_recommendation").data)
            if "legal_action_recommendation" in bundle.records
            else "UNKNOWN"
        )
        if "BLOCK" in decisions or project_fact_status == "BLOCK" or report_status == "REVOKED":
            return "blocked"
        if (
            "REVIEW" in decisions
            or project_fact_status == "REVIEW"
            or legal_window_status in {"REVIEW_REQUIRED", "MISSED"}
        ):
            return "review-required"
        if project_fact_status == "HOLD" or report_status in {"DRAFT", "READY"}:
            return "governed-hold"
        return "preview-ready"
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


def _repository_context_projection_module() -> Any:
    # Keep repository_boundary.py as the public facade while allowing
    # projection helpers to live in dedicated modules without eager cycles.
    from storage import repository_context_projection

    return repository_context_projection


def _build_operational_context(work_item: PersistedWorkItem, actions: list[PersistedOperatorAction]) -> dict[str, Any]:
    return _repository_context_projection_module().build_operational_context(work_item, actions)


def _build_transient_preview_context(bundle: StageBundle) -> dict[str, Any]:
    return _repository_context_projection_module().build_transient_preview_context(bundle)


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
    if stage_scope == 6:
        project_fact_id = str(payload.get("project_fact_id", "")).strip()
        project_fact = ProjectFactRepository().get_by_id(project_fact_id) if project_fact_id else None
        return ("project_fact", project_fact) if project_fact else None
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
        return ("order_record", order) if order else None
    return None


def _bundle_object_refs(bundle: StageBundle) -> dict[str, str]:
    if bundle.stage == 6:
        project_fact = bundle.record("project_fact").data
        report_record = bundle.record("report_record").data
        review_queue_profile = bundle.record("review_queue_profile").data
        challenger_candidate_profile = bundle.record("challenger_candidate_profile").data
        legal_action_recommendation = bundle.record("legal_action_recommendation").data
        refs = {
            "project_id": project_fact.get("project_id"),
            "project_fact_id": project_fact.get("project_fact_id"),
            "report_id": report_record.get("report_id"),
            "report_record_id": report_record.get("report_id"),
            "queue_profile_id": review_queue_profile.get("queue_profile_id"),
            "review_queue_profile_id": review_queue_profile.get("queue_profile_id"),
            "challenger_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
            "challenger_candidate_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
            "action_id": legal_action_recommendation.get("action_id"),
        }
        supplement = bundle.inputs.get("private_supplement_record_optional")
        if isinstance(supplement, Mapping):
            refs["private_supplement_record_id_optional"] = supplement.get("supplement_id")
        return {
            key: str(value)
            for key, value in refs.items()
            if value not in (None, "", "UNKNOWN")
        }
    refs = _repository_context_projection_module().bundle_object_refs(bundle)
    if bundle.stage == 7:
        workbench = bundle.inputs.get(CRM_QUOTE_WORKBENCH_INPUT_KEY)
        if isinstance(workbench, Mapping):
            crm_action_id = workbench.get("crm_action_id") or bundle.inputs.get(CRM_ACTION_ID_INPUT_KEY)
            quote_draft_id = workbench.get("quote_draft_id") or bundle.inputs.get(QUOTE_DRAFT_ID_INPUT_KEY)
            for key, value in {
                "provider_execution_id": workbench.get("provider_execution_id"),
                "crm_action_id": crm_action_id,
                CRM_ACTION_ID_INPUT_KEY: crm_action_id,
                "quote_draft_id": quote_draft_id,
                QUOTE_DRAFT_ID_INPUT_KEY: quote_draft_id,
            }.items():
                if value not in (None, "", "UNKNOWN"):
                    refs[key] = str(value)
        leadpack_package = bundle.inputs.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY)
        if isinstance(leadpack_package, Mapping):
            for key, value in {
                "package_id": leadpack_package.get("package_id"),
                LEADPACK_PACKAGE_ID_INPUT_KEY: leadpack_package.get("package_id"),
                "evidence_pack_id": leadpack_package.get("evidence_pack_id"),
                LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY: leadpack_package.get("evidence_pack_id"),
                "page_draft_id": leadpack_package.get("page_draft_id"),
                LEADPACK_PAGE_DRAFT_ID_INPUT_KEY: leadpack_package.get("page_draft_id"),
                "artifact_manifest_id": leadpack_package.get("artifact_manifest_id"),
                LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY: leadpack_package.get("artifact_manifest_id"),
            }.items():
                if value not in (None, "", "UNKNOWN"):
                    refs[key] = str(value)
    if bundle.stage == 8:
        refs.update(_stage8_carrier_refs(bundle))
    if bundle.stage == 9:
        execution_ledger = bundle.inputs.get(STAGE9_EXECUTION_LEDGER_INPUT_KEY)
        if isinstance(execution_ledger, Mapping):
            for key, value in {
                "execution_ledger_id": execution_ledger.get("execution_ledger_id"),
                STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY: execution_ledger.get("execution_ledger_id"),
                "order_execution_id": execution_ledger.get("order_execution_id"),
                "payment_execution_id": execution_ledger.get("payment_execution_id"),
                "delivery_execution_id": execution_ledger.get("delivery_execution_id"),
            }.items():
                if value not in (None, "", "UNKNOWN"):
                    refs[key] = str(value)
    return refs


def _stage8_carrier_payload(bundle: StageBundle, key: str) -> Mapping[str, Any]:
    value = bundle.inputs.get(key)
    return value if isinstance(value, Mapping) else {}


def _stage8_carrier_refs(bundle: StageBundle) -> dict[str, str]:
    collection = _stage8_carrier_payload(bundle, "contact_candidate_collection_snapshot")
    selection_trace = _stage8_carrier_payload(bundle, "contact_selection_trace_snapshot")
    outbox = _stage8_carrier_payload(bundle, "outreach_execution_outbox_snapshot")
    collection_id = (
        bundle.inputs.get("contact_candidate_collection_id_optional")
        or collection.get("contact_candidate_collection_id")
        or selection_trace.get("contact_candidate_collection_id")
    )
    selection_trace_id = (
        bundle.inputs.get("contact_selection_trace_id_optional")
        or selection_trace.get("contact_selection_trace_id")
        or collection.get("selection_trace_id")
    )
    winning_contact_candidate_id = (
        bundle.inputs.get("winning_contact_candidate_id_optional")
        or collection.get("winning_contact_candidate_id")
        or selection_trace.get("winning_contact_candidate_id")
    )
    refs = {
        "contact_candidate_collection_id": collection_id,
        "contact_candidate_collection_id_optional": collection_id,
        "contact_selection_trace_id": selection_trace_id,
        "contact_selection_trace_id_optional": selection_trace_id,
        "winning_contact_candidate_id_optional": winning_contact_candidate_id,
        "outbox_id": bundle.inputs.get("outbox_id_optional") or outbox.get("outbox_id"),
        "outbox_id_optional": bundle.inputs.get("outbox_id_optional") or outbox.get("outbox_id"),
        "outreach_execution_outbox_id_optional": (
            bundle.inputs.get("outreach_execution_outbox_id_optional")
            or outbox.get("outbox_id")
        ),
    }
    return {
        key: str(value)
        for key, value in refs.items()
        if value not in (None, "", "UNKNOWN")
    }


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
    return _repository_context_projection_module().bundle_trace_and_audit_refs(bundle)


def _bundle_decision_states(bundle: StageBundle) -> dict[str, str]:
    return {
        "permission_decision_state": str(bundle.inputs.get("permission_decision_state", "ALLOW")),
        "governance_decision_state": str(bundle.inputs.get("governance_decision_state", "ALLOW")),
        "semantic_decision_state": str(bundle.inputs.get("semantic_decision_state", "ALLOW")),
        "policy_decision_state": str(bundle.inputs.get("policy_decision_state", "ALLOW")),
    }


def _bundle_governed_context(bundle: StageBundle) -> dict[str, Any]:
    governed_context = _repository_context_projection_module().bundle_governed_context(bundle)
    provider_adapter_readiness = bundle.inputs.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY)
    if isinstance(provider_adapter_readiness, Mapping):
        governed_context[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY] = dict(provider_adapter_readiness)
        governed_context["provider_adapter_config_source"] = provider_adapter_readiness.get("config_source")
        governed_context["provider_adapter_mode"] = provider_adapter_readiness.get("mode")
        governed_context["provider_adapter_readback_only"] = bool(
            provider_adapter_readiness.get("readback_only", True)
        )
        governed_context["provider_adapter_real_provider_call_enabled"] = False
    if bundle.stage == 6:
        supplement_summary = bundle.inputs.get("private_supplement_carrier_summary")
        if isinstance(supplement_summary, Mapping):
            governed_context["private_supplement_carrier_summary"] = dict(supplement_summary)
        product_package_readiness = bundle.inputs.get(STAGE6_PRODUCT_PACKAGE_READINESS_KEY)
        if isinstance(product_package_readiness, Mapping):
            governed_context[STAGE6_PRODUCT_PACKAGE_READINESS_KEY] = dict(product_package_readiness)
    if bundle.stage == 7:
        workbench = bundle.inputs.get(CRM_QUOTE_WORKBENCH_INPUT_KEY)
        if isinstance(workbench, Mapping):
            governed_context["crm_quote_workbench_summary"] = {
                "crm_action_id": workbench.get("crm_action_id"),
                "quote_draft_id": workbench.get("quote_draft_id"),
                "owner_action_state": workbench.get("owner_action_state"),
                "approval_state": workbench.get("approval_state"),
                "audit_state": workbench.get("audit_state"),
                "quote_surface_state": workbench.get("quote_surface_state"),
                "dry_run_state": workbench.get("dry_run_state"),
                "live_execution_enabled": bool(workbench.get("live_execution_enabled", False)),
                "real_external_quote_sent": bool(workbench.get("real_external_quote_sent", False)),
                "external_quote_sent": bool(workbench.get("external_quote_sent", False)),
                "provider_execution_id": workbench.get("provider_execution_id"),
                "execution_request_state": workbench.get("execution_request_state"),
                "provider_execution_state": workbench.get("provider_execution_state"),
                "approved_crm_quote_execution_enabled": bool(
                    workbench.get("approved_crm_quote_execution_enabled", False)
                ),
                "controlled_provider_adapter_scope": workbench.get("controlled_provider_adapter_scope"),
                "controlled_provider_execution_executed": bool(
                    workbench.get("controlled_provider_execution_executed", False)
                ),
                "governed_execution_mode": workbench.get("governed_execution_mode"),
                "blocked_reasons": list(workbench.get("blocked_reasons", [])),
                "suspension_reasons": list(workbench.get("suspension_reasons", [])),
                "sandbox_adapter_execution": dict(workbench.get("sandbox_adapter_execution", {})),
                "provider_config_ref": dict(workbench.get("provider_config_ref", {})),
                "provider_result_readback": dict(workbench.get("provider_result_readback", {})),
                "approved_crm_quote_execution_summary": dict(
                    workbench.get("approved_crm_quote_execution_summary", {})
                ),
                "deal_tracking_timeline": list(workbench.get("deal_tracking_timeline", [])),
                "replay_state": dict(workbench.get("replay_state", {})),
                "crm_sandbox_sync_record_count": len(
                    dict(workbench.get("crm_sandbox_sync_records", {}))
                ),
                "quote_sandbox_record_id": dict(workbench.get("quote_sandbox_record", {})).get(
                    "quote_sandbox_record_id"
                ),
                "deal_tracking_record_id": dict(workbench.get("deal_tracking_record", {})).get(
                    "deal_tracking_record_id"
                ),
                "callback_task_id": dict(workbench.get("sales_followup_record", {})).get(
                    "callback_task_id"
                ),
            }
            readiness = bundle.inputs.get(CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY)
            if isinstance(readiness, Mapping):
                governed_context["crm_quote_workbench_readiness_summary"] = dict(readiness)
        leadpack_package = bundle.inputs.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY)
        if isinstance(leadpack_package, Mapping):
            governed_context["leadpack_delivery_package_summary"] = leadpack_delivery_package_summary(
                leadpack_package
            )
            governed_context["leadpack_customer_artifact_candidate_summary"] = {
                "artifact_version_hash": leadpack_package.get("artifact_version_hash"),
                "customer_visible_artifact_candidate_state": dict(
                    leadpack_package.get("customer_visible_artifact_candidate", {})
                ).get("candidate_state"),
                "page_export_candidate_state": dict(
                    leadpack_package.get("page_export_candidate", {})
                ).get("candidate_state"),
                "download_audit_id": dict(leadpack_package.get("download_audit", {})).get(
                    "download_audit_id"
                ),
                "export_page_replay_id": dict(leadpack_package.get("export_page_replay", {})).get(
                    "replay_id"
                ),
                "customer_visible_enabled": False,
                "external_delivery_enabled": False,
            }
            readiness = bundle.inputs.get(LEADPACK_DELIVERY_READINESS_INPUT_KEY)
            if isinstance(readiness, Mapping):
                governed_context["leadpack_delivery_readiness_summary"] = dict(readiness)
    if bundle.stage == 8:
        collection = _stage8_carrier_payload(bundle, "contact_candidate_collection_snapshot")
        selection_trace = _stage8_carrier_payload(bundle, "contact_selection_trace_snapshot")
        outbox = _stage8_carrier_payload(bundle, "outreach_execution_outbox_snapshot")
        refs = _stage8_carrier_refs(bundle)
        if collection:
            governed_context["contact_candidate_collection_summary"] = {
                "contact_candidate_collection_id": refs.get("contact_candidate_collection_id"),
                "winning_contact_candidate_id": refs.get("winning_contact_candidate_id_optional"),
                "candidate_count": len(collection.get("candidate_list", []))
                if isinstance(collection.get("candidate_list"), list)
                else 0,
                "source_conflict_candidate_count": collection.get("source_conflict_candidate_count", 0),
                "source_merge_review_required_count": collection.get(
                    "source_merge_review_required_count",
                    0,
                ),
                "reselect_reason_optional": collection.get("reselect_reason_optional"),
                "reselect_history_count": len(collection.get("reselect_history", []))
                if isinstance(collection.get("reselect_history"), list)
                else 0,
            }
        if selection_trace:
            governed_context["contact_selection_trace_summary"] = {
                "contact_selection_trace_id": refs.get("contact_selection_trace_id"),
                "contact_candidate_collection_id": refs.get("contact_candidate_collection_id"),
                "winning_contact_candidate_id": refs.get("winning_contact_candidate_id_optional"),
                "winning_selection_reason": selection_trace.get("winning_selection_reason"),
                "conflict_flag": selection_trace.get("conflict_flag"),
                "conflict_reason_optional": selection_trace.get("conflict_reason_optional"),
                "source_conflict_candidate_count": selection_trace.get("source_conflict_candidate_count", 0),
                "source_merge_review_required_count": selection_trace.get(
                    "source_merge_review_required_count",
                    0,
                ),
                "reselect_reason_optional": selection_trace.get("reselect_reason_optional"),
            }
        if outbox:
            governed_context["outbox_readiness_summary"] = dict(
                bundle.inputs.get("outbox_readiness_summary")
                if isinstance(bundle.inputs.get("outbox_readiness_summary"), Mapping)
                else outbox.get("outbox_readiness_summary", {})
            )
            governed_context["sandbox_execution_record_summary"] = {
                "execution_id": outbox.get("execution_id"),
                "outbox_id": refs.get("outbox_id"),
                "adapter_family": outbox.get("adapter_family"),
                "sandbox_execution_state": outbox.get("sandbox_execution_state"),
                "sandbox_pass_state": outbox.get("sandbox_pass_state"),
                "provider_family": outbox.get("provider_family"),
                "provider_adapter_suspended": bool(outbox.get("provider_adapter_suspended", False)),
                "live_execution_enabled": bool(outbox.get("live_execution_enabled", False)),
                "approved_provider_execution_enabled": bool(
                    outbox.get("approved_provider_execution_enabled", False)
                ),
                "provider_execution_state": outbox.get("provider_execution_state"),
                "real_send_attempted": bool(outbox.get("real_send_attempted", False)),
                "external_delivery_enabled": bool(outbox.get("external_delivery_enabled", False)),
                "replay_state": dict(outbox.get("replay_state", {})),
            }
            governed_context["live_pilot_readiness_summary"] = dict(
                outbox.get("live_pilot_readiness_summary", {})
            )
            governed_context["live_pilot_execution_summary"] = {
                "pilot_id": outbox.get("pilot_id"),
                "execution_id": outbox.get("execution_id"),
                "outbox_id": refs.get("outbox_id"),
                "adapter_family": outbox.get("adapter_family"),
                "pilot_scope": outbox.get("pilot_scope"),
                "approved_sample_size": outbox.get("approved_sample_size"),
                "batch_send_enabled": bool(outbox.get("batch_send_enabled", False)),
                "live_pilot_readiness_state": outbox.get("live_pilot_readiness_state"),
                "live_execution_requested": bool(outbox.get("live_execution_requested", False)),
                "live_execution_enabled": bool(outbox.get("live_execution_enabled", False)),
                "real_send_attempted": bool(outbox.get("real_send_attempted", False)),
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "provider_result_readback": dict(outbox.get("provider_result_readback", {})),
                "suspension_state": dict(outbox.get("suspension_state", {})),
            }
            governed_context["approved_provider_execution_summary"] = dict(
                outbox.get("approved_provider_execution_summary", {})
            )
            governed_context["provider_execution_timeline"] = list(
                outbox.get("execution_timeline", [])
            )
            governed_context["sandbox_execution_timeline"] = list(outbox.get("execution_timeline", []))
            governed_context["outbox_id"] = refs.get("outbox_id")
            governed_context["governed_execution_mode"] = outbox.get("governed_execution_mode")
            governed_context["live_execution_enabled"] = bool(outbox.get("live_execution_enabled", False))
            governed_context["approved_provider_execution_enabled"] = bool(
                outbox.get("approved_provider_execution_enabled", False)
            )
            governed_context["provider_execution_state"] = outbox.get("provider_execution_state")
            governed_context["real_send_attempted"] = bool(outbox.get("real_send_attempted", False))
    if bundle.stage == 9:
        execution_ledger = bundle.inputs.get(STAGE9_EXECUTION_LEDGER_INPUT_KEY)
        if isinstance(execution_ledger, Mapping):
            governed_context["stage9_execution_ledger_summary"] = stage9_execution_ledger_summary(
                execution_ledger
            )
            readiness = bundle.inputs.get(STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY)
            if isinstance(readiness, Mapping):
                governed_context["stage9_execution_ledger_readiness"] = dict(readiness)
            live_pilot_carrier = execution_ledger.get(PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY)
            if isinstance(live_pilot_carrier, Mapping):
                governed_context[PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY] = dict(live_pilot_carrier)
                governed_context["payment_delivery_live_pilot_summary"] = {
                    "pilot_id": live_pilot_carrier.get("pilot_id"),
                    "payment_live_pilot_readiness_state": live_pilot_carrier.get(
                        "payment_live_pilot_readiness_state"
                    ),
                    "delivery_live_pilot_readiness_state": live_pilot_carrier.get(
                        "delivery_live_pilot_readiness_state"
                    ),
                    "live_payment_enabled": bool(live_pilot_carrier.get("live_payment_enabled", False)),
                    "live_delivery_enabled": bool(live_pilot_carrier.get("live_delivery_enabled", False)),
                    "real_charge_attempted": False,
                    "real_delivery_fulfillment_attempted": False,
                    "real_refund_attempted": False,
                    "automated_refund_enabled": False,
                }
    return governed_context


def _project_id_for_bundle(bundle: StageBundle) -> str:
    root_object_type, _ = STAGE_ROOT_OBJECTS[bundle.stage]
    return str(bundle.record(root_object_type).data["project_id"])


def _record_status(object_type: str, record: Mapping[str, Any]) -> str:
    fallback_status_fields = {
        "report_record": ("report_status", "review_task_status"),
        "review_queue_profile": ("review_lane", "review_queue_bucket"),
        "challenger_candidate_profile": ("candidate_position_label",),
    }
    for field_name in (
        *PRIMARY_STATUS_FIELDS.get(object_type, ()),
        *fallback_status_fields.get(object_type, ()),
    ):
        value = record.get(field_name)
        if value not in (None, ""):
            return str(value)
    return "UNKNOWN"


__all__ = [
    "OperationalContractError",
    "get_operational_context",
    "get_transient_preview_context",
    "hydrate_stage6_bundle",
    "hydrate_stage_bundle",
    "list_stage_work_items",
    "persist_stage6_bundle",
    "persist_stage_bundle",
    "reopen_default_storage",
    "record_operator_action",
    "reset_default_storage",
]
