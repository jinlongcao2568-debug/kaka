# Stage: api_stage9
# Consumes formal objects: order_record, payment_record, delivery_record, governance_feedback_event, opportunity_outcome_event
# Dependent handoff: H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any, TypedDict

from api.schemas.common import ErrorEnvelope


class Stage9Request(TypedDict, total=False):
    opportunity_id: str
    crm_owner_state: str
    requested_surface_state: str
    include_formal_objects: bool


class FormalObjectRef(TypedDict, total=False):
    object_type: str
    object_id: str
    primary_status: str
    decision_states: dict[str, str]
    governed_metadata: dict[str, Any]
    trace_refs: dict[str, Any]


class Stage9PreviewProjection(TypedDict, total=False):
    order_draft_preview: dict[str, Any]
    payment_draft_preview: dict[str, Any]
    delivery_preview: dict[str, Any]
    outcome_writeback_preview: dict[str, Any]
    governance_feedback_preview: dict[str, Any]
    execution_ledger_preview: dict[str, Any]
    order_payment_delivery_execution_summary: dict[str, Any]
    payment_sandbox_records: dict[str, Any]
    delivery_sandbox_records: dict[str, Any]
    settlement_reconciliation_preview: dict[str, Any]
    manual_refund_exception_preview: dict[str, Any]
    payment_delivery_live_pilot_preview: dict[str, Any]
    approved_payment_delivery_execution_preview: dict[str, Any]


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


class Stage9Response(TypedDict, total=False):
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
    preview_projection: Stage9PreviewProjection
    stage9_execution_ledger: dict[str, Any]
    stage9_execution_ledger_readiness: dict[str, Any]
    order_payment_delivery_execution_summary: dict[str, Any]
    payment_sandbox_provider_records: dict[str, Any]
    delivery_sandbox_provider_records: dict[str, Any]
    manual_refund_exception_record: dict[str, Any]
    payment_delivery_live_pilot: dict[str, Any]
    approved_payment_delivery_execution: dict[str, Any]
    provider_adapter_readiness_summary: dict[str, Any]
    provider_adapter_config_source: str
    provider_adapter_mode: str
    provider_adapter_blocked_reasons: list[str]
    provider_adapter_approval_audit_prerequisites: dict[str, Any]
    trace_refs: dict[str, Any]
    operational_loop_persisted: bool
    operational_context_status: str
    persisted_operational_context: OperationalContext
    transient_preview_context: TransientPreviewContext
    action_result: OperatorActionResult
    error: ErrorEnvelope


class OrdersListRequest(Stage9Request, total=False):
    pass


class OrderCreateRequest(Stage9Request, total=False):
    order_status: str


class PaymentCreateRequest(Stage9Request, total=False):
    payment_status: str


class DeliveryCreateRequest(Stage9Request, total=False):
    delivery_status: str


class OpportunityOutcomeCreateRequest(Stage9Request, total=False):
    outcome_family: str


class GovernanceFeedbackListRequest(Stage9Request, total=False):
    trigger_type: str


class GovernanceFeedbackCreateRequest(Stage9Request, total=False):
    trigger_type: str
    action_taken: str


class OrdersListResponse(Stage9Response, total=False):
    pass


class OrderCreateResponse(Stage9Response, total=False):
    draft_created: bool


class PaymentCreateResponse(Stage9Response, total=False):
    draft_created: bool


class DeliveryCreateResponse(Stage9Response, total=False):
    preview_generated: bool


class OpportunityOutcomeListResponse(Stage9Response, total=False):
    pass


class OpportunityOutcomeCreateResponse(Stage9Response, total=False):
    writeback_ready: bool


class GovernanceFeedbackListResponse(Stage9Response, total=False):
    pass


class GovernanceFeedbackCreateResponse(Stage9Response, total=False):
    writeback_ready: bool


class Stage9WorkItemListRequest(Stage9Request, total=False):
    assigned_owner: str


class Stage9WorkItemListResponse(TypedDict, total=False):
    work_items: list[OperationalContext]
    internal_only: bool
    live_execution_enabled: bool
    blocked_by_default: bool


class Stage9OperatorActionRequest(Stage9Request, total=False):
    order_id: str
    action_id: str
    button_flow_id: str
    reason: str
    requested_by_role: str
    requested_by: str


class Stage9OperatorActionResponse(Stage9Response, total=False):
    action_result: OperatorActionResult


__all__ = [
    "DeliveryCreateRequest",
    "DeliveryCreateResponse",
    "FormalObjectRef",
    "OperationalAssignment",
    "OperationalContext",
    "OperatorActionResult",
    "GovernanceFeedbackCreateRequest",
    "GovernanceFeedbackCreateResponse",
    "GovernanceFeedbackListRequest",
    "GovernanceFeedbackListResponse",
    "OpportunityOutcomeCreateRequest",
    "OpportunityOutcomeCreateResponse",
    "OpportunityOutcomeListResponse",
    "OrderCreateRequest",
    "OrderCreateResponse",
    "OrdersListRequest",
    "OrdersListResponse",
    "PendingButtonFlow",
    "PaymentCreateRequest",
    "PaymentCreateResponse",
    "Stage9PreviewProjection",
    "Stage9OperatorActionRequest",
    "Stage9OperatorActionResponse",
    "Stage9Request",
    "Stage9Response",
    "Stage9WorkItemListRequest",
    "Stage9WorkItemListResponse",
    "TransientPreviewContext",
]
