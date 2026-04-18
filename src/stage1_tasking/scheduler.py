# Stage: stage1_tasking
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json


from typing import Any

class Stage1Scheduler:
    def __init__(self) -> None:
        pass

    def next_window(self, context: Any) -> Any:
        raise NotImplementedError("stage1 scheduler is skeleton-only")
