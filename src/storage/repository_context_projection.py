from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import StageBundle

from storage.db import PersistedOperatorAction, PersistedWorkItem, build_persisted_at
from storage.operator_loop_contracts import build_work_item_key, list_pending_button_flows
from storage.repository_boundary import (
    STAGE_DEFAULT_MODES,
    STAGE_FORMAL_OBJECTS,
    STAGE_ROOT_OBJECTS,
    STAGE_SURFACE_IDS,
    SURFACE_OPERATIONAL_STATE_MAP,
    _approval_chain_status,
    _baseline_current_operational_state,
    _bundle_decision_states,
    _resolve_assignment_for_state,
    _surface_state_for_bundle,
)


def build_operational_context(
    work_item: PersistedWorkItem,
    actions: list[PersistedOperatorAction],
) -> dict[str, Any]:
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


def build_transient_preview_context(bundle: StageBundle) -> dict[str, Any]:
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
    trace_refs, audit_refs = bundle_trace_and_audit_refs(bundle)
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
        has_audit_trace=bool(audit_refs),
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
        "object_refs": bundle_object_refs(bundle),
        "pending_actions": [],
        "pending_button_flows": [flow.as_payload() for flow in pending_button_flows],
        "trace_refs": trace_refs,
        "audit_refs": audit_refs,
        "decision_states": _bundle_decision_states(bundle),
        "governed_context": bundle_governed_context(bundle),
        "preview_generated_at": build_persisted_at(),
    }


def bundle_object_refs(bundle: StageBundle) -> dict[str, str]:
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


def bundle_trace_and_audit_refs(bundle: StageBundle) -> tuple[dict[str, str], dict[str, str]]:
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


def bundle_governed_context(bundle: StageBundle) -> dict[str, Any]:
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
