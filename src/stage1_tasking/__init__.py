# Stage: stage1_tasking
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

# Keep package init side-effect free. Scheduler and repository modules import each
# other through storage readback paths, so public symbols should be imported from
# their concrete submodules rather than eagerly from the package root.

__all__ = []
