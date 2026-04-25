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
