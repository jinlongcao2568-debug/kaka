# Stage: api_internal_write_contracts
# Consumes formal objects: internal request payloads only
# Dependent handoff: N/A
# Dependent schema/contracts: mounted internal write transports

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictInternalWriteRequest(BaseModel):
    """Network request base for internal writes.

    Authentication and actor identity are injected by the transport middleware and
    are intentionally absent from every public field set below.
    """

    model_config = ConfigDict(extra="forbid")


class SafePipelinePayloadFields(StrictInternalWriteRequest):
    now: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    project_root_id: str | None = None
    project_name: str | None = None
    document_kind: str | None = None
    guangzhou_flow_no: str | None = None
    region_code: str | None = None
    region_scope: str | None = None
    source_family: str | None = None
    platform_level: str | None = None
    coverage_tier: str | None = None
    default_route: str | None = None
    review_lane: str | None = None
    carrier_type: str | None = None
    announcement_url: str | None = None
    source_document_ref: str | None = None
    source_slice_ref: str | None = None
    normalization_rule_id: str | None = None
    parser_confidence_score: float | None = Field(default=None, ge=0, le=1)
    procurement_regime: str | None = None
    candidate_order_mode: str | None = None
    award_determination_mode: str | None = None
    channel_family: str | None = None
    contact_channel: str | None = None
    contact_validity_status: str | None = None
    contact_legal_basis: str | None = None
    reasonable_expectation_status: str | None = None
    channel_policy_status: str | None = None
    public_contact_source: str | None = None
    source_auditability_state: str | None = None
    source_vendor_role: str | None = None
    frequency_policy_state: str | None = None
    opt_out_state: str | None = None
    quiet_hours_policy_state: str | None = None
    response_status: str | None = None
    crm_owner_state: str | None = None
    automation_level: str | None = None
    approval_state: str | None = None
    flags: dict[str, Any] | None = None
    payload_boundary: str | None = None
    source_mode: str | None = None
    run_mode: Literal["DRY_RUN", "PREVIEW", "INTERNAL_PREVIEW", "OFFLINE_REPLAY"] | None = None
    transport_mode: Literal["DRY_RUN", "PREVIEW", "INTERNAL_PREVIEW", "OFFLINE_REPLAY"] | None = None
    execution_mode: Literal["DRY_RUN", "PREVIEW", "INTERNAL_PREVIEW", "OFFLINE_REPLAY"] | None = None
    live_execution_enabled: Literal[False] | None = None
    external_delivery_enabled: Literal[False] | None = None
    external_quote_enabled: Literal[False] | None = None
    external_release_enabled: Literal[False] | None = None
    live_source_enabled: Literal[False] | None = None
    real_transport_enabled: Literal[False] | None = None
    real_external_fetch_enabled: Literal[False] | None = None
    real_provider_call_enabled: Literal[False] | None = None


class Stage1ToStage6InternalOrchestrationRequest(SafePipelinePayloadFields):
    payload_boundary: Literal["SANITIZED_OFFLINE_INTERNAL"]
    source_mode: Literal["OFFLINE_FIXTURE", "OFFLINE_SANITIZED", "INTERNAL_OFFLINE_REPLAY"]
    run_mode: Literal["DRY_RUN", "PREVIEW", "INTERNAL_PREVIEW", "OFFLINE_REPLAY"]


class OperatorTaskCreateRequest(SafePipelinePayloadFields):
    task_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source_mode: Literal[
        "INTERNAL_OPERATOR_TASK",
        "OFFLINE_FIXTURE",
        "OFFLINE_SANITIZED",
        "INTERNAL_OFFLINE_REPLAY",
    ] | None = None


class ConversationalAgentTurnRequest(StrictInternalWriteRequest):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    project_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    opportunity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    queue_item_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    region_code: str | None = Field(
        default=None,
        min_length=5,
        max_length=32,
        pattern=r"^CN-[A-Z0-9-]+$",
    )
    confirm_internal_task: bool = False


class AgentToolCallRequest(StrictInternalWriteRequest):
    call_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    tool_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    arguments: dict[str, Any]


class AgentToolPlanRequest(StrictInternalWriteRequest):
    plan_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    proposal_source: Literal["DETERMINISTIC_REQUEST", "MODEL_SHADOW_PROPOSAL"]
    execute_read_only: bool = False
    calls: list[AgentToolCallRequest] = Field(min_length=1, max_length=8)


class AgentMemoryMutationRequest(StrictInternalWriteRequest):
    action: Literal["UPSERT", "CORRECT", "DELETE"]
    scope: Literal["PRINCIPAL", "PROJECT"]
    project_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    memory_key: Literal[
        "response_language",
        "response_detail",
        "preferred_output_format",
        "default_region_code",
        "project_workflow_note",
    ]
    value: str | None = Field(default=None, min_length=1, max_length=500)
    ttl_days: int | None = Field(default=None, ge=1, le=365)
    expected_version: int | None = Field(default=None, ge=1)


class ProductOnboardingBudgets(StrictInternalWriteRequest):
    discovery_candidate_limit: int = Field(ge=1, le=30)
    detail_capture_limit: int = Field(ge=0, le=10)
    attachment_capture_limit: int = Field(ge=0, le=20)
    job_time_budget_seconds: int = Field(ge=60, le=1800)


class ProductOnboardingConfigMutationRequest(StrictInternalWriteRequest):
    action: Literal["UPSERT_DRAFT", "ACTIVATE", "ROLLBACK"]
    profile_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    expected_version: int | None = Field(default=None, ge=1)
    target_version: int | None = Field(default=None, ge=1)
    profile_name: str | None = Field(default=None, min_length=1, max_length=100)
    region_codes: list[str] | None = Field(default=None, min_length=1, max_length=3)
    industry_code: Literal["CONSTRUCTION_PUBLIC_EVIDENCE"] | None = None
    evidence_template_id: Literal[
        "SKU_B_PUBLIC_SOURCE_FOUR_FIELD_RISK_REVIEW"
    ] | None = None
    source_profile_ids: list[str] | None = Field(default=None, min_length=1, max_length=8)
    budgets: ProductOnboardingBudgets | None = None


class ProductOnboardingConfigTestRequest(StrictInternalWriteRequest):
    profile_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    version: int | None = Field(default=None, ge=1)
    mode: Literal["OFFLINE_VALIDATION"] = "OFFLINE_VALIDATION"


class OperatorSupportTaskActionRequest(StrictInternalWriteRequest):
    action: Literal["RETRY"]
    queue_item_id: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    expected_status: Literal["failed", "dead-letter"]
    expected_updated_at: str = Field(min_length=1, max_length=64)
    confirmation: Literal["RETRY_FAILED_INTERNAL_TASK"]
    reason: str = Field(min_length=10, max_length=500)


class OperatorProjectImportRequest(SafePipelinePayloadFields):
    project_id: str = Field(min_length=1, max_length=128)
    source_mode: Literal[
        "INTERNAL_PROJECT_IMPORT",
        "OFFLINE_FIXTURE",
        "OFFLINE_SANITIZED",
        "INTERNAL_OFFLINE_REPLAY",
    ] | None = None


class OperatorAutonomousOpportunitySearchRequest(SafePipelinePayloadFields):
    async_execution: bool | None = None
    job_time_budget_seconds: int | None = Field(default=None, ge=1, le=86_400)
    job_priority: int | None = Field(default=None, ge=0, le=1_000)
    job_max_attempts: int | None = Field(default=None, ge=1, le=100)
    region_codes: list[str] | None = None
    project_type: str | None = None
    project_types: list[str] | None = None
    query: str | None = None
    keyword: str | None = None
    project_keyword: str | None = None
    amount: int | float | None = Field(default=None, ge=0)
    amount_min: int | float | None = Field(default=None, ge=0)
    amount_max: int | float | None = Field(default=None, ge=0)
    minimum_amount: int | float | None = Field(default=None, ge=0)
    maximum_amount: int | float | None = Field(default=None, ge=0)
    minimum_amount_optional: int | float | None = Field(default=None, ge=0)
    maximum_amount_optional: int | float | None = Field(default=None, ge=0)
    candidate_count: int | None = Field(default=None, ge=1, le=500)
    candidate_limit: int | None = Field(default=None, ge=1, le=500)
    discovery_candidate_limit: int | None = Field(default=None, ge=1, le=500)
    discovery_profile_limit_per_region: int | None = Field(default=None, ge=1, le=100)
    candidate_discovery_run_id: str | None = None
    selection_filters: list[str] | None = None
    source_profile_ids: list[str] | None = None
    evaluation_corpus_mode: bool | None = None
    evaluation_document_kind: str | None = None
    notice_candidates: list[dict[str, Any]] | None = None
    market_scan_candidates: list[dict[str, Any]] | None = None
    allow_offline_sample_candidates: bool | None = None
    offline_sample_candidates_enabled: bool | None = None
    exclude_project_ids: list[str] | None = None
    excluded_project_ids: list[str] | None = None
    stage1_6_exclude_project_ids: list[str] | None = None
    profile_id: str | None = None
    entry_profile_id: str | None = None
    disable_real_candidate_stage2_capture: bool | None = None
    detail_capture_limit: int | None = Field(default=None, ge=0, le=500)
    real_candidate_detail_capture_limit: int | None = Field(default=None, ge=0, le=500)
    attachment_capture_limit: int | None = Field(default=None, ge=0, le=500)
    real_candidate_attachment_capture_limit: int | None = Field(default=None, ge=0, le=500)
    detail_capture_time_budget_seconds: float | None = Field(default=None, gt=0, le=86_400)
    real_candidate_detail_capture_time_budget_seconds: float | None = Field(
        default=None,
        gt=0,
        le=86_400,
    )
    stage2_detail_capture_time_budget_seconds: float | None = Field(
        default=None,
        gt=0,
        le=86_400,
    )
    stage1_6_time_budget_seconds: float | None = Field(default=None, ge=0, le=86_400)
    stage1_6_loop_time_budget_seconds: float | None = Field(default=None, ge=0, le=86_400)
    attempt_all_stage1_6_candidates: bool | None = None
    attempt_all_candidates_for_stage1_6: bool | None = None
    attempt_all_real_public_candidates_for_stage1_6: bool | None = None
    analysis_score_threshold: int | None = Field(default=None, ge=0, le=100)
    scan_run_id: str | None = None
    source_blueprint_batch_id: str | None = None
    source_blueprint_plan_id: str | None = None
    notice_id: str | None = None
    notice_stage: str | None = None
    candidate_company: str | None = None
    objection_deadline_at_optional: str | None = None
    source_registry_id: str | None = None


class OperatorAutonomousSearchClearRequest(StrictInternalWriteRequest):
    clear_scope: Literal["local_test_autonomous_search_runs_only"] | None = None
    explicit_operator_action: Literal[True] | None = None
    now: str | None = None


class OwnerRealPublicSourceCaptureRequest(StrictInternalWriteRequest):
    capture_kind: Literal["entry", "attachment"]
    profile_id: str = Field(min_length=1, max_length=128)
    task_id: str | None = None
    project_id: str | None = None
    source_blueprint_batch_id: str | None = None
    async_execution: bool | None = None
    job_time_budget_seconds: int | None = Field(default=None, ge=1, le=86_400)
    job_priority: int | None = Field(default=None, ge=0, le=1_000)
    job_max_attempts: int | None = Field(default=None, ge=1, le=100)


class ControlledGrayPrepareRequest(StrictInternalWriteRequest):
    output_root: str | None = None
    source_targets_json: str | None = None
    per_target_sample_goal: int | None = Field(default=None, ge=1, le=10_000)
    per_target_candidate_limit: int | None = Field(default=None, ge=1, le=10_000)
    target_limit: int | None = Field(default=None, ge=0, le=10_000)
    group_by: Literal["target", "region", "source"] | None = None
    segment_timeout_seconds: int | None = Field(default=None, ge=1, le=86_400)
    execute: Literal[False] | None = None
    now: str | None = None


class ControlledGrayWorkerEnqueueRequest(ControlledGrayPrepareRequest):
    queue_item_id: str | None = None
    priority: int | None = Field(default=None, ge=0, le=1_000)
    max_attempts: int | None = Field(default=None, ge=1, le=100)
    next_run_at: str | None = None
    schedule_id: str | None = Field(default=None, min_length=1, max_length=128)
    recurring_interval_seconds: int | None = Field(
        default=None,
        ge=0,
        le=2_678_400,
    )
    time_budget_seconds: int | None = Field(default=None, ge=1, le=86_400)


class ControlledGrayWorkerCancelRequest(StrictInternalWriteRequest):
    queue_item_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="operator_requested_cancel", min_length=1, max_length=1024)
    now: str | None = None


class ControlledGrayWorkerRunOnceRequest(StrictInternalWriteRequest):
    execute: Literal[False] | None = None
    worker_id: str | None = None
    lease_id: str | None = None
    queue_item_id: str | None = None
    lease_seconds: int | None = Field(default=None, ge=1, le=86_400)
    now: str | None = None
    retryable: bool | None = None
    retry_delay_seconds: int | None = Field(default=None, ge=0, le=86_400)


__all__ = [
    "AgentMemoryMutationRequest",
    "AgentToolCallRequest",
    "AgentToolPlanRequest",
    "ConversationalAgentTurnRequest",
    "ControlledGrayPrepareRequest",
    "ControlledGrayWorkerCancelRequest",
    "ControlledGrayWorkerEnqueueRequest",
    "ControlledGrayWorkerRunOnceRequest",
    "OperatorAutonomousOpportunitySearchRequest",
    "OperatorAutonomousSearchClearRequest",
    "OperatorProjectImportRequest",
    "OperatorTaskCreateRequest",
    "OwnerRealPublicSourceCaptureRequest",
    "ProductOnboardingBudgets",
    "ProductOnboardingConfigMutationRequest",
    "ProductOnboardingConfigTestRequest",
    "OperatorSupportTaskActionRequest",
    "Stage1ToStage6InternalOrchestrationRequest",
    "StrictInternalWriteRequest",
]
