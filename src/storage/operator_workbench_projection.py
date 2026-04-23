from __future__ import annotations

from typing import Any, Mapping


TRANSIENT_PREVIEW_HIDDEN_FIELDS = (
    "work_item_id",
    "pending_actions",
    "pending_button_flows",
    "last_action",
    "action_history",
)


def sanitize_transient_preview_context(context: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = _clone_context(context)
    for field_name in TRANSIENT_PREVIEW_HIDDEN_FIELDS:
        sanitized.pop(field_name, None)
    return sanitized


def build_operator_context_projection(
    *,
    operational_context_status: str,
    persisted_context: Mapping[str, Any] | None = None,
    transient_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context_key = _context_key(persisted_context=persisted_context, transient_context=transient_context)
    context = persisted_context or transient_context or {}
    assignment_payload = _assignment_payload(context)
    queue_materialized = persisted_context is not None
    pending_actions = _context_list(context, "pending_actions", queue_materialized=queue_materialized)
    pending_button_flows = _context_list(context, "pending_button_flows", queue_materialized=queue_materialized)
    action_history = _context_list(context, "action_history", queue_materialized=queue_materialized)
    return {
        "context_status": operational_context_status,
        "context_key": context_key,
        "context_source": str(context.get("context_source", "unavailable")),
        "workbench_replay_source": _workbench_replay_source(context, queue_materialized=queue_materialized),
        "queue_materialized": queue_materialized,
        "work_item_key": context.get("work_item_key"),
        "work_item_id": context.get("work_item_id") if queue_materialized else None,
        "primary_object_type": context.get("primary_object_type"),
        "primary_record_id": context.get("primary_record_id"),
        "surface_operational_state": context.get("surface_operational_state"),
        "current_operational_state": context.get("current_operational_state"),
        "assignment_lifecycle_state": assignment_payload.get("assignment_lifecycle_state"),
        "action_history_count": len(action_history),
        "pending_action_count": len(pending_actions),
        "pending_button_flow_count": len(pending_button_flows),
        "action_controls_source": (
            "persisted_operational_context.pending_actions"
            if queue_materialized
            else "governance_envelope.action_availability"
        ),
        "display_contract": {
            "work_item_id_visible": queue_materialized,
            "action_history_visible": queue_materialized,
            "pending_actions_visible": queue_materialized,
            "pending_button_flows_visible": queue_materialized,
            "work_item_key_visible": bool(context.get("work_item_key")),
            "assignment_visible": bool(assignment_payload),
        },
    }


def build_workbench_replay_projection(
    *,
    persisted_context: Mapping[str, Any] | None = None,
    transient_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context_key = _context_key(persisted_context=persisted_context, transient_context=transient_context)
    context = persisted_context or transient_context or {}
    assignment_payload = _assignment_payload(context)
    queue_materialized = persisted_context is not None
    return {
        "context_key": context_key,
        "replay_source": _workbench_replay_source(context, queue_materialized=queue_materialized),
        "queue_materialized": queue_materialized,
        "work_item_key": context.get("work_item_key"),
        "work_item_id": context.get("work_item_id") if queue_materialized else None,
        "primary_object_type": context.get("primary_object_type"),
        "primary_record_id": context.get("primary_record_id"),
        "surface_operational_state": context.get("surface_operational_state"),
        "current_operational_state": context.get("current_operational_state"),
        "assignment_lifecycle_state": assignment_payload.get("assignment_lifecycle_state"),
    }


def _assignment_payload(context: Mapping[str, Any]) -> dict[str, Any]:
    assignment = context.get("assignment", {})
    return dict(assignment) if isinstance(assignment, Mapping) else {}


def _context_key(
    *,
    persisted_context: Mapping[str, Any] | None,
    transient_context: Mapping[str, Any] | None,
) -> str:
    if persisted_context is not None:
        return "persisted_operational_context"
    if transient_context is not None:
        return "transient_preview_context"
    return "unavailable"


def _context_list(
    context: Mapping[str, Any],
    field_name: str,
    *,
    queue_materialized: bool,
) -> list[Any]:
    if not queue_materialized:
        return []
    value = context.get(field_name, [])
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _workbench_replay_source(context: Mapping[str, Any], *, queue_materialized: bool) -> str:
    if queue_materialized:
        return "repository_readback"
    if context:
        return "projection_only"
    return "unavailable"


def _clone_context(context: Mapping[str, Any]) -> dict[str, Any]:
    cloned: dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, Mapping):
            cloned[key] = dict(value)
        elif isinstance(value, list):
            cloned[key] = [dict(item) if isinstance(item, Mapping) else item for item in value]
        else:
            cloned[key] = value
    return cloned
