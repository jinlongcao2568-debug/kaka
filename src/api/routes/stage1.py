# Stage: api_stage1
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.deps import build_transport_unavailable


STAGE1_TRANSPORT_UNAVAILABLE = {
    **build_transport_unavailable(
        1,
        reserved_operation_id="reservedStage1TaskingEntry",
        reserved_path="/reserved/stage1/tasking",
        reserved_method="POST",
        handoff_refs=("H-01-STAGE1-TO-STAGE2",),
    ),
    "route_registrar": "register_stage1_routes",
}


def register_stage1_routes(router: object | None = None) -> list[dict[str, Any]]:
    return [dict(STAGE1_TRANSPORT_UNAVAILABLE)]


__all__ = ["STAGE1_TRANSPORT_UNAVAILABLE", "register_stage1_routes"]
