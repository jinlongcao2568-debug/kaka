# Stage: api_stage8
# Consumes formal objects: contact_target, outreach_plan, touch_record
# Dependent handoff: H-07-STAGE7-TO-STAGE8, H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any, TypedDict

from api.schemas.common import ErrorEnvelope


class Stage8Request(TypedDict, total=False):
    opportunity_id: str
    touch_record_id: str
    requested_surface_state: str
    include_formal_objects: bool


class FormalObjectRef(TypedDict, total=False):
    object_type: str
    object_id: str
    primary_status: str
    decision_states: dict[str, str]
    governed_metadata: dict[str, Any]
    trace_refs: dict[str, Any]


class Stage8PreviewProjection(TypedDict, total=False):
    contact_target_preview: dict[str, Any]
    outreach_plan_preview: dict[str, Any]
    touch_record_preview: dict[str, Any]
    outreach_execution_outbox_preview: dict[str, Any]
    outbox_readiness_summary: dict[str, Any]


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


class Stage8Response(TypedDict, total=False):
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
    preview_projection: Stage8PreviewProjection
    trace_refs: dict[str, Any]
    outreach_execution_outbox: dict[str, Any]
    outbox_readiness_summary: dict[str, Any]
    provider_adapter_readiness_summary: dict[str, Any]
    provider_adapter_config_source: str
    provider_adapter_mode: str
    provider_adapter_blocked_reasons: list[str]
    provider_adapter_approval_audit_prerequisites: dict[str, Any]
    operational_loop_persisted: bool
    operational_context_status: str
    persisted_operational_context: OperationalContext
    transient_preview_context: TransientPreviewContext
    action_result: OperatorActionResult
    error: ErrorEnvelope


class ContactTargetsListRequest(Stage8Request, total=False):
    pass


class ContactComplianceCheckRequest(Stage8Request, total=False):
    contact_target_id: str


class OutreachPlanCreateRequest(Stage8Request, total=False):
    plan_status: str


class TouchRecordCreateRequest(Stage8Request, total=False):
    response_status: str


class ContactTargetsListResponse(Stage8Response, total=False):
    pass


class ContactComplianceCheckResponse(Stage8Response, total=False):
    compliance_result: str


class OutreachPlanCreateResponse(Stage8Response, total=False):
    draft_created: bool


class TouchRecordCreateResponse(Stage8Response, total=False):
    writeback_ready: bool


class Stage8WorkItemListRequest(Stage8Request, total=False):
    assigned_owner: str


class Stage8WorkItemListResponse(TypedDict, total=False):
    work_items: list[OperationalContext]
    internal_only: bool
    live_execution_enabled: bool
    blocked_by_default: bool


class Stage8OperatorActionRequest(Stage8Request, total=False):
    action_id: str
    button_flow_id: str
    reason: str
    requested_by_role: str
    requested_by: str


class Stage8OperatorActionResponse(Stage8Response, total=False):
    action_result: OperatorActionResult


__all__ = [
    "ContactComplianceCheckRequest",
    "ContactComplianceCheckResponse",
    "ContactTargetsListRequest",
    "ContactTargetsListResponse",
    "FormalObjectRef",
    "OperationalAssignment",
    "OperationalContext",
    "OperatorActionResult",
    "OutreachPlanCreateRequest",
    "OutreachPlanCreateResponse",
    "PendingButtonFlow",
    "Stage8PreviewProjection",
    "Stage8OperatorActionRequest",
    "Stage8OperatorActionResponse",
    "Stage8Request",
    "Stage8Response",
    "Stage8WorkItemListRequest",
    "Stage8WorkItemListResponse",
    "TransientPreviewContext",
    "TouchRecordCreateRequest",
    "TouchRecordCreateResponse",
]
