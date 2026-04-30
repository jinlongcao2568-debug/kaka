# Stage: api_stage1
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json


from typing import Any, TypedDict

class Stage1Request(TypedDict, total=False):
    task_id: str
    project_id: str
    project_name: str
    region_code: str
    review_lane: str
    source_family: str
    platform_level: str
    region_scope: str
    coverage_tier: str
    carrier_type: str
    time_range_from: str
    time_range_until: str

class Stage1Response(TypedDict, total=False):
    status: str
    scheduler_task: dict[str, Any]
    stage2_handoff_intent: dict[str, Any]


class Stage1SchedulerReadback(TypedDict, total=False):
    readback_state: str
    repository_backed: bool
    replayable: bool
    scheduler_task: dict[str, Any]
    queue_item: dict[str, Any]
    stage2_handoff_intent: dict[str, Any]


class Stage1MarketScanRequest(TypedDict, total=False):
    scan_run_id: str
    task_id: str
    batch_id: str
    source_blueprint_batch_id: str
    minimum_amount: float
    analysis_score_threshold: int
    now: str
    notice_candidates: list[dict[str, Any]]


class Stage1OpportunityCandidate(TypedDict, total=False):
    opportunity_candidate_id: str
    notice_id: str
    project_id: str
    project_name: str
    region_code: str
    project_type: str
    notice_stage: str
    amount: float
    analysis_score: int
    analysis_decision: str
    analysis_priority: str
    why_analyze: list[str]
    why_skip: list[str]
    review_reasons: list[str]
    customer_visible: bool


class Stage1MarketScanResponse(TypedDict, total=False):
    scan_run_id: str
    capability_state: str
    internal_only: bool
    customer_visible: bool
    real_external_fetch_enabled: bool
    unregistered_capture_enabled: bool
    manual_url_picker_primary_flow: bool
    opportunity_candidates: list[Stage1OpportunityCandidate]
    review_candidates: list[Stage1OpportunityCandidate]
    skipped_candidates: list[Stage1OpportunityCandidate]
    run_controller: dict[str, Any]
    stage_state_machine: dict[str, Any]
    readback_summary: dict[str, Any]


class Stage1SourceBlueprintRequest(TypedDict, total=False):
    source_blueprint_plan_id: str
    scan_run_id: str
    market_scan_run_id: str
    source_blueprint_batch_id: str
    opportunity_candidate: Stage1OpportunityCandidate
    opportunity_candidates: list[Stage1OpportunityCandidate]
    coverage_gap_signals: list[str]
    now: str


class Stage1SourceDecision(TypedDict, total=False):
    surface_key: str
    source_role: str
    selected: bool
    selection_reason: str
    source_registry_id: str
    source_family: str
    adapter_id: str
    approved: bool
    approval_source: str
    triggered_by_coverage_gap: bool
    trigger_signals: list[str]


class Stage1SourceBlueprintResponse(TypedDict, total=False):
    source_blueprint_plan_id: str
    capability_state: str
    plan_state: str
    internal_only: bool
    customer_visible: bool
    capture_execution_enabled: bool
    stage2_fetch_executed: bool
    real_external_fetch_enabled: bool
    source_blueprint_auto_selection: bool
    stage2_capture_plan_generation: bool
    source_mix: list[Stage1SourceDecision]
    stage2_capture_plan: dict[str, Any]
    coverage_gap_policy: dict[str, Any]
    commercial_pilot_policy: dict[str, Any]
    pilot_province_portfolio: list[dict[str, Any]]
    readback_summary: dict[str, Any]
