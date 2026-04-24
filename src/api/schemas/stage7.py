# Stage: api_stage7
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any, TypedDict

from api.schemas.common import ErrorEnvelope


class Stage7Request(TypedDict, total=False):
    opportunity_id: str
    saleability_status: str
    requested_surface_state: str
    include_formal_objects: bool


class FormalObjectRef(TypedDict, total=False):
    object_type: str
    object_id: str
    primary_status: str
    decision_states: dict[str, str]
    governed_metadata: dict[str, Any]
    trace_refs: dict[str, Any]


class Stage7PreviewProjection(TypedDict, total=False):
    opportunity_summary: dict[str, Any]
    offer_summary: dict[str, Any]
    buyer_fit_summary: dict[str, Any]
    actor_preview: list[dict[str, Any]]


class Stage7CrmQuotePrerequisiteReadiness(TypedDict, total=False):
    crm_prerequisite_state: str
    quote_prerequisite_state: str
    governed_execution_mode: str
    readiness_only: bool
    prerequisite_only: bool
    crm_runtime_enabled: bool
    external_quote_enabled: bool
    external_delivery_enabled: bool
    source_object_refs: dict[str, Any]
    blocked_reasons: list[str]
    required_approvals: list[str]
    required_audit_refs: list[str]
    audit_readiness_summary: dict[str, Any]
    operator_readback_summary: dict[str, Any]


class Stage7CrmQuoteWorkbenchCarrier(TypedDict, total=False):
    opportunity_id: str
    project_id: str
    crm_action_id: str
    quote_draft_id: str
    owner_action_state: str
    approval_state: str
    audit_state: str
    vendor_adapter_state: dict[str, Any]
    quote_surface_state: str
    dry_run_state: str
    live_execution_enabled: bool
    real_external_quote_sent: bool
    real_crm_receipt_generated: bool
    customer_visible_quote_generated: bool
    customer_visible_delivery_package_generated: bool
    blocked_reasons: list[str]
    governed_execution_mode: str
    readiness_summary: dict[str, Any]


class LeadpackDeliveryPackageCarrier(TypedDict, total=False):
    package_id: str
    opportunity_id: str
    evidence_pack_id: str
    page_draft_id: str
    artifact_manifest_id: str
    masking_state: str
    approval_state: str
    audit_state: str
    package_state: str
    page_state: str
    delivery_state: str
    customer_visible_enabled: bool
    external_delivery_enabled: bool
    package_manifest: dict[str, Any]
    evidence_item_manifest: dict[str, Any]
    field_masking_summary: dict[str, Any]
    page_draft: dict[str, Any]
    delivery_readiness_summary: dict[str, Any]


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


class LeadpackCandidateProjection(TypedDict, total=False):
    allowed_projection: dict[str, dict[str, Any]]
    masked_projection: dict[str, dict[str, Any]]
    summary_only: dict[str, dict[str, Any]]
    forbidden: list[dict[str, Any]]


class Stage7Response(TypedDict, total=False):
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
    preview_projection: Stage7PreviewProjection
    crm_quote_prerequisite_readiness: Stage7CrmQuotePrerequisiteReadiness
    crm_quote_workbench: Stage7CrmQuoteWorkbenchCarrier
    crm_quote_workbench_readiness_summary: dict[str, Any]
    leadpack_delivery_package: LeadpackDeliveryPackageCarrier
    leadpack_delivery_readiness_summary: dict[str, Any]
    package_page_delivery_summary: dict[str, Any]
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


class LeadpackExternalDeliveryCandidateRequest(TypedDict, total=False):
    opportunity_id: str
    touch_record_id: str
    requested_surface_state: str
    include_formal_objects: bool


class LeadpackActivationPrepRequest(LeadpackExternalDeliveryCandidateRequest, total=False):
    pass


class LeadpackActivationDesignImplementationPrepRequest(LeadpackActivationPrepRequest, total=False):
    pass


class LeadpackImplementationDecisionReadinessPacketRequest(LeadpackActivationDesignImplementationPrepRequest, total=False):
    pass


class FormalClientExportPageLayerReadinessResponse(TypedDict, total=False):
    surface_id: str
    surface_state: str
    surface_mode: str
    surface_access: str
    internal_only: bool
    readiness_only: bool
    projection_only: bool
    review_only: bool
    non_live: bool
    release_blocked: bool
    customer_visible_export_enabled: bool
    client_page_release_enabled: bool
    external_release_enabled: bool
    external_delivery_enabled: bool
    direct_export_enabled: bool
    export_artifact_generation_enabled: bool
    page_publication_enabled: bool
    readiness_state: str
    release_layer: str
    blocked_reasons: list[str]
    why_not_live: list[str]
    missing_prerequisites: list[str]
    source_readiness_refs: dict[str, Any]
    operator_readback_summary: dict[str, Any]
    leadpack_delivery_package: LeadpackDeliveryPackageCarrier
    package_manifest: dict[str, Any]
    evidence_item_manifest: dict[str, Any]
    field_masking_summary: dict[str, Any]
    page_draft: dict[str, Any]
    delivery_readiness_summary: dict[str, Any]
    package_page_delivery_summary: dict[str, Any]
    trace_refs: dict[str, Any]


class LeadpackExternalDeliveryCandidateResponse(TypedDict, total=False):
    surface_id: str
    surface_state: str
    surface_mode: str
    surface_access: str
    internal_only: bool
    candidate_only: bool
    readiness_only: bool
    review_only: bool
    external_delivery_enabled: bool
    requires_review: bool
    approval_prerequisites_met: bool
    review_gate_prerequisites_met: bool
    export_simulation_allowed: bool
    export_simulation_mode: str
    direct_export_enabled: bool
    external_ready_direct_export: bool
    review_requested: bool
    export_simulation_requested: bool
    release_layer: str
    candidate_status: str
    candidate_scope: dict[str, Any]
    formal_object_refs: dict[str, FormalObjectRef]
    candidate_projection: LeadpackCandidateProjection
    leadpack_delivery_package: LeadpackDeliveryPackageCarrier
    leadpack_delivery_readiness_summary: dict[str, Any]
    package_page_delivery_summary: dict[str, Any]
    required_approvals: list[str]
    required_review_gates: list[str]
    required_audit_refs: list[str]
    required_boundary_checks: list[str]
    required_masking_or_summary_rules: list[str]
    missing_approvals: list[str]
    missing_review_gates: list[str]
    missing_audit_refs: list[str]
    actual_approval_states: list[dict[str, Any]]
    actual_review_gate_states: list[dict[str, Any]]
    actual_audit_ref_states: list[dict[str, Any]]
    approval_readiness_summary: dict[str, Any]
    review_gate_readiness_summary: dict[str, Any]
    audit_readiness_summary: dict[str, Any]
    candidate_readback_summary: dict[str, Any]
    operator_readback_summary: dict[str, Any]
    denial_conditions: list[str]
    blocked_reasons: list[str]
    hold_reasons: list[str]
    why_not_live: list[str]
    why_not_now: list[str]
    future_activation_prereqs_remaining: list[str]
    trace_refs: dict[str, Any]
    error: ErrorEnvelope


class LeadpackActivationPrepEvidenceItem(TypedDict, total=False):
    item_id: str
    evidence_type: str
    required_for_review: bool
    present: bool
    status: str
    source_refs: list[str]
    freshness_policy: str


class LeadpackActivationPrepEvidencePack(TypedDict, total=False):
    evidence_pack_status: str
    required_evidence_items: list[LeadpackActivationPrepEvidenceItem]
    evidence_item_sources: dict[str, list[str]]
    evidence_item_freshness: dict[str, str]
    simulation_replay_required: bool
    approval_trace_required: bool
    audit_trace_required: bool
    projection_boundary_check_required: bool
    coverage_boundary_check_required: bool
    delivery_matrix_check_required: bool
    activation_denial_conditions: list[str]
    activation_blockers_remaining: list[str]


class LeadpackActivationPrepSimulationReplay(TypedDict, total=False):
    artifact_id: str
    replay_status: str
    source_operation_id: str
    candidate_matrix_ref: str
    boundary_check_results: dict[str, str]
    projection_component_counts: dict[str, int]
    forbidden_component_ids: list[str]
    missing_approvals: list[str]
    missing_review_gates: list[str]
    missing_audit_refs: list[str]
    trace_refs: dict[str, Any]


class LeadpackActivationPrepSignoffEntry(TypedDict, total=False):
    owner_role: str
    mandatory: bool
    status: str
    declared: bool
    state_source_ref: str


class LeadpackActivationPrepSignoffPacket(TypedDict, total=False):
    packet_id: str
    packet_status: str
    draft_packet_allowed: bool
    draft_packet_is_not_activation_ready: bool
    owner_signoff_state_source: dict[str, Any]
    actual_owner_signoff_states: list[dict[str, Any]]
    required_owner_signoffs: list[LeadpackActivationPrepSignoffEntry]
    required_release_checks: list[str]
    required_regression_suites: list[str]
    review_gate_ref: str


class LeadpackActivationPrepRunbookAction(TypedDict, total=False):
    runbook_action_id: str
    reviewActionId: str
    buttonFlowId: str
    trigger_conditions: list[str]
    resulting_prep_status: str


class LeadpackActivationPrepRunbook(TypedDict, total=False):
    prep_status_vocabulary: list[str]
    runbook_actions: list[LeadpackActivationPrepRunbookAction]
    strictness_rule: str
    external_delivery_enabled: bool
    direct_object_export_allowed: bool


class LeadpackActivationPrepTransition(TypedDict, total=False):
    prep_status_vocabulary: list[str]
    current_prep_status: str
    review_gate: dict[str, Any]
    transitions: list[dict[str, Any]]


class LeadpackActivationDesignImplementationPrepResponse(TypedDict, total=False):
    surface_id: str
    surface_state: str
    surface_mode: str
    surface_access: str
    internal_only: bool
    candidate_only: bool
    external_delivery_enabled: bool
    actual_activation_enabled: bool
    implementation_approved: bool
    activation_design_prep_review_requested: bool
    release_layer: str
    candidate_status: str
    activation_prep_status: str
    activation_design_prep_status: str
    owner_signoff_execution: dict[str, Any]
    approval_audit_prerequisites: dict[str, Any]
    state_layering: dict[str, Any]
    rollback_cancel_emergency_off: dict[str, Any]
    implementation_prep_readiness_gate: dict[str, Any]
    implementation_decision_readiness: dict[str, Any]
    design_prep_blockers: list[str]
    trace_refs: dict[str, Any]
    error: ErrorEnvelope


class LeadpackImplementationDecisionReadinessPacketResponse(TypedDict, total=False):
    surface_id: str
    surface_state: str
    surface_mode: str
    surface_access: str
    internal_only: bool
    candidate_only: bool
    external_delivery_enabled: bool
    actual_activation_enabled: bool
    implementation_decision_executed: bool
    implementation_approved: bool
    implementation_not_approved: bool
    actual_activation_not_approved: bool
    external_delivery_not_approved: bool
    implementation_decision_packet_status: str
    implementation_decision_ready: bool
    readiness_state: str
    decision_scope: dict[str, Any]
    hold_sources: list[dict[str, Any]]
    required_owner_signoffs: list[str]
    actual_owner_signoff_states: list[dict[str, Any]]
    owner_signoff_summary: dict[str, Any]
    required_approval_chains: list[str]
    actual_approval_states: list[dict[str, Any]]
    approval_readiness_summary: dict[str, Any]
    required_review_gates: list[str]
    actual_review_gate_states: list[dict[str, Any]]
    review_gate_readiness_summary: dict[str, Any]
    required_audit_refs: list[str]
    actual_audit_ref_states: list[dict[str, Any]]
    audit_readiness_summary: dict[str, Any]
    readiness_summaries: dict[str, Any]
    blocking_conditions: list[str]
    source_design_prep_packet: LeadpackActivationDesignImplementationPrepResponse
    formal_client_export_page_layer_readiness: FormalClientExportPageLayerReadinessResponse
    trace_refs: dict[str, Any]


class LeadpackActivationPrepResponse(TypedDict, total=False):
    surface_id: str
    surface_state: str
    surface_mode: str
    surface_access: str
    internal_only: bool
    candidate_only: bool
    external_delivery_enabled: bool
    activation_prep_review_requested: bool
    release_layer: str
    candidate_status: str
    formal_object_refs: dict[str, FormalObjectRef]
    candidate_projection: LeadpackCandidateProjection
    evidence_pack: LeadpackActivationPrepEvidencePack
    simulation_replay: LeadpackActivationPrepSimulationReplay
    signoff_packet: LeadpackActivationPrepSignoffPacket
    runbook: LeadpackActivationPrepRunbook
    readiness_transition: LeadpackActivationPrepTransition
    trace_refs: dict[str, Any]
    error: ErrorEnvelope


class SaleableOpportunityListRequest(Stage7Request, total=False):
    pass


class SaleableOpportunityRefreshRequest(Stage7Request, total=False):
    refresh_reason: str


class SaleableOpportunityListResponse(Stage7Response, total=False):
    pass


class SaleableOpportunityRefreshResponse(Stage7Response, total=False):
    refresh_requested: bool


class Stage7WorkItemListRequest(Stage7Request, total=False):
    assigned_owner: str


class Stage7WorkItemListResponse(TypedDict, total=False):
    work_items: list[OperationalContext]
    internal_only: bool
    live_execution_enabled: bool
    blocked_by_default: bool


class Stage7OperatorActionRequest(Stage7Request, total=False):
    action_id: str
    button_flow_id: str
    reason: str
    requested_by_role: str
    requested_by: str


class Stage7OperatorActionResponse(Stage7Response, total=False):
    action_result: OperatorActionResult


__all__ = [
    "FormalClientExportPageLayerReadinessResponse",
    "FormalObjectRef",
    "LeadpackCandidateProjection",
    "LeadpackDeliveryPackageCarrier",
    "LeadpackActivationDesignImplementationPrepRequest",
    "LeadpackActivationDesignImplementationPrepResponse",
    "LeadpackImplementationDecisionReadinessPacketRequest",
    "LeadpackImplementationDecisionReadinessPacketResponse",
    "LeadpackActivationPrepEvidenceItem",
    "LeadpackActivationPrepEvidencePack",
    "LeadpackActivationPrepRequest",
    "LeadpackActivationPrepRunbook",
    "LeadpackActivationPrepRunbookAction",
    "LeadpackActivationPrepSignoffEntry",
    "LeadpackActivationPrepSignoffPacket",
    "LeadpackActivationPrepSimulationReplay",
    "LeadpackActivationPrepTransition",
    "LeadpackActivationPrepResponse",
    "OperationalAssignment",
    "OperationalContext",
    "OperatorActionResult",
    "LeadpackExternalDeliveryCandidateRequest",
    "LeadpackExternalDeliveryCandidateResponse",
    "SaleableOpportunityListRequest",
    "SaleableOpportunityListResponse",
    "SaleableOpportunityRefreshRequest",
    "SaleableOpportunityRefreshResponse",
    "PendingButtonFlow",
    "Stage7CrmQuotePrerequisiteReadiness",
    "Stage7CrmQuoteWorkbenchCarrier",
    "Stage7OperatorActionRequest",
    "Stage7OperatorActionResponse",
    "Stage7PreviewProjection",
    "Stage7Request",
    "Stage7Response",
    "Stage7WorkItemListRequest",
    "Stage7WorkItemListResponse",
    "TransientPreviewContext",
]
