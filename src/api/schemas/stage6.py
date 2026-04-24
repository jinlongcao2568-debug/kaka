# Stage: api_stage6
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any, TypedDict

from api.schemas.common import ErrorEnvelope


class Stage6Request(TypedDict, total=False):
    project_id: str
    project_fact_id: str
    report_record_id: str
    review_queue_profile_id: str
    challenger_candidate_profile_id: str
    action_id: str
    requested_surface_state: str
    include_formal_objects: bool


class FormalObjectRef(TypedDict, total=False):
    object_type: str
    object_id: str
    primary_status: str
    decision_states: dict[str, str]
    governed_metadata: dict[str, Any]
    trace_refs: dict[str, Any]


class Stage6PreviewProjection(TypedDict, total=False):
    project_fact_summary: dict[str, Any]
    report_status_summary: dict[str, Any]
    review_queue_summary: dict[str, Any]
    challenger_summary: dict[str, Any]
    legal_action_summary: dict[str, Any]


class OperationalAssignment(TypedDict, total=False):
    assignment_profile_id: str
    assignment_lifecycle_state: str
    assigned_owner_role: str
    assigned_owner: str
    reviewer_role: str
    reviewer: str
    resolved_from: str
    simplified_boundary: list[str]


class PendingButtonFlow(TypedDict, total=False):
    button_flow_id: str
    action_id: str
    button_type: str


class OperatorActionResult(TypedDict, total=False):
    action_event_id: str
    work_item_id: str
    stage_scope: int
    action_id: str
    button_flow_id: str | None
    action_state: str
    resulting_assignment_lifecycle_state: str | None
    requested_by_role: str
    requested_by: str
    reason: str
    requested_at: str
    completed_at: str | None


class OperationalContext(TypedDict, total=False):
    context_source: str
    persistence_backend: str
    work_item_id: str
    work_item_key: str
    stage_scope: int
    surface_id: str
    primary_object_type: str
    primary_record_id: str
    surface_operational_state: str
    current_operational_state: str
    ready_for_internal_operator_action: bool
    assignment: OperationalAssignment
    object_refs: dict[str, str]
    pending_actions: list[str]
    pending_button_flows: list[PendingButtonFlow]
    last_action: dict[str, Any] | None
    action_history: list[dict[str, Any]]
    trace_refs: dict[str, Any]
    audit_refs: dict[str, Any]
    decision_states: dict[str, str]
    governed_context: dict[str, Any]
    created_at: str
    updated_at: str


class TransientPreviewContext(TypedDict, total=False):
    context_source: str
    persistence_backend: str
    work_item_key: str
    stage_scope: int
    surface_id: str
    primary_object_type: str
    primary_record_id: str
    surface_operational_state: str
    current_operational_state: str
    ready_for_internal_operator_action: bool
    assignment: OperationalAssignment
    object_refs: dict[str, str]
    pending_actions: list[str]
    pending_button_flows: list[PendingButtonFlow]
    trace_refs: dict[str, Any]
    audit_refs: dict[str, Any]
    decision_states: dict[str, str]
    governed_context: dict[str, Any]
    preview_generated_at: str


class Stage6Response(TypedDict, total=False):
    surface_id: str
    surface_state: str
    surface_mode: str
    surface_access: str
    internal_only: bool
    preview_only: bool
    draft_only: bool
    live_execution_enabled: bool
    blocked_by_default: bool
    formalization_scope: str
    release_layer: str
    decision_states: dict[str, str]
    formal_object_refs: dict[str, FormalObjectRef]
    preview_projection: Stage6PreviewProjection
    capability_envelope: dict[str, Any]
    governance_envelope: dict[str, Any]
    semantic_envelope: dict[str, Any]
    trace_refs: dict[str, Any]
    operational_loop_persisted: bool
    operational_context_status: str
    persisted_operational_context: OperationalContext
    transient_preview_context: TransientPreviewContext
    action_result: OperatorActionResult
    error: ErrorEnvelope


class Stage6ReviewReportWorkbenchRequest(Stage6Request, total=False):
    pass


class Stage6ReviewReportWorkbenchResponse(Stage6Response, total=False):
    pass


class Stage6WorkItemListRequest(Stage6Request, total=False):
    assigned_owner: str


class Stage6WorkItemListResponse(TypedDict, total=False):
    work_items: list[OperationalContext]
    internal_only: bool
    live_execution_enabled: bool
    blocked_by_default: bool


class Stage6OperatorActionRequest(Stage6Request, total=False):
    action_id: str
    button_flow_id: str
    reason: str
    requested_by_role: str
    requested_by: str


class Stage6OperatorActionResponse(Stage6Response, total=False):
    action_result: OperatorActionResult


class Stage1ToStage6InternalOrchestrationResponse(TypedDict, total=False):
    operation_id: str
    orchestration_scope: str
    payload_boundary: str
    source_mode: str
    run_mode: str
    internal_only: bool
    live_execution_enabled: bool
    external_live_transport_enabled: bool
    stage1_to_stage5_transport_state: str
    stage1_to_stage5_http_entry_enabled: bool
    stage1_to_stage5_real_transport_enabled: bool
    stage1_to_stage5_external_live_transport_enabled: bool
    stage6_repository_backed_preview: bool
    stage6_persisted: bool
    stage6_project_id: str
    stage6_project_fact_id: str
    stage6_readback: Stage6ReviewReportWorkbenchResponse


__all__ = [
    "FormalObjectRef",
    "OperationalAssignment",
    "OperationalContext",
    "OperatorActionResult",
    "PendingButtonFlow",
    "Stage1ToStage6InternalOrchestrationResponse",
    "Stage6PreviewProjection",
    "Stage6OperatorActionRequest",
    "Stage6OperatorActionResponse",
    "Stage6Request",
    "Stage6Response",
    "Stage6ReviewReportWorkbenchRequest",
    "Stage6ReviewReportWorkbenchResponse",
    "Stage6WorkItemListRequest",
    "Stage6WorkItemListResponse",
    "TransientPreviewContext",
]
