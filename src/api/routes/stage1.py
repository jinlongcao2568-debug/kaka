# Stage: api_stage1
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from stage1_tasking.market_scan import Stage1MarketScanEngine
from stage1_tasking.scheduler import Stage1Scheduler
from stage1_tasking.source_blueprint import Stage1SourceBlueprintOrchestrator
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


def create_stage1_scheduler_task(payload: dict[str, Any]) -> dict[str, Any]:
    task = Stage1Scheduler().create_task(payload)
    return {
        "status": task.status,
        "scheduler_task": task.as_payload(),
        "stage2_handoff_intent": task.stage2_handoff_intent.as_payload(),
        "real_external_fetch_enabled": False,
        "unregistered_capture_enabled": False,
    }


def read_stage1_scheduler_task(payload: dict[str, Any]) -> dict[str, Any]:
    queue_item_id = payload.get("queue_item_id")
    if not queue_item_id:
        raise ValueError("queue_item_id is required for stage1 scheduler readback")
    return Stage1Scheduler().readback(str(queue_item_id))


def create_stage1_market_scan(payload: dict[str, Any]) -> dict[str, Any]:
    return Stage1MarketScanEngine().run(payload)


def read_stage1_market_scan(payload: dict[str, Any]) -> dict[str, Any]:
    scan_run_id = payload.get("scan_run_id") or payload.get("market_scan_run_id")
    if not scan_run_id:
        raise ValueError("scan_run_id is required for stage1 market scan readback")
    return Stage1MarketScanEngine().readback(str(scan_run_id))


def create_stage1_source_blueprint_plan(payload: dict[str, Any]) -> dict[str, Any]:
    return Stage1SourceBlueprintOrchestrator().build(payload)


def read_stage1_source_blueprint_plan(payload: dict[str, Any]) -> dict[str, Any]:
    plan_id = payload.get("source_blueprint_plan_id")
    if not plan_id:
        raise ValueError("source_blueprint_plan_id is required for stage1 source blueprint readback")
    return Stage1SourceBlueprintOrchestrator().readback(str(plan_id))


__all__ = [
    "STAGE1_TRANSPORT_UNAVAILABLE",
    "create_stage1_market_scan",
    "create_stage1_scheduler_task",
    "create_stage1_source_blueprint_plan",
    "read_stage1_market_scan",
    "read_stage1_scheduler_task",
    "read_stage1_source_blueprint_plan",
    "register_stage1_routes",
]
