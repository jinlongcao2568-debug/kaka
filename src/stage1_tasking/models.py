# Stage: stage1_tasking
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskExecutionContext:
    task_id: str
    # TODO: align with contracts/schemas/schema_catalog.json

@dataclass(frozen=True)
class ProjectIdentityStrategy:
    strategy_id: str
    # TODO: align with contracts/schemas/schema_catalog.json

@dataclass(frozen=True)
class ClockStrategyProfile:
    clock_profile_id: str
    # TODO: align with contracts/schemas/schema_catalog.json
