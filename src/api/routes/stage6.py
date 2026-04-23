# Stage: api_stage6
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.projections import build_stage6_preview_surface, get_surface_runtime_defaults, register_route_table
from api.schemas.stage6 import (
    Stage6OperatorActionResponse,
    Stage6ReviewReportWorkbenchResponse,
    Stage6WorkItemListResponse,
)
from storage.repository_boundary import (
    OperationalContractError,
    list_stage_work_items,
    persist_stage_bundle,
    record_operator_action,
)


def preview_stage6_review_report_workbench(payload: Any) -> Stage6ReviewReportWorkbenchResponse:
    return build_stage6_preview_surface(payload)


def list_stage6_work_items(payload: Any) -> Stage6WorkItemListResponse:
    if not isinstance(payload, dict):
        persist_stage_bundle(payload)
    surface_defaults = get_surface_runtime_defaults("review_report_workbench")
    return {
        "work_items": list_stage_work_items(6, payload if isinstance(payload, dict) else None),
        "internal_only": bool(surface_defaults["internal_only"]),
        "live_execution_enabled": bool(surface_defaults["live_execution_enabled"]),
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
    }


def submit_stage6_operator_action(payload: Any) -> Stage6OperatorActionResponse:
    surface_defaults = get_surface_runtime_defaults("review_report_workbench")
    response: Stage6OperatorActionResponse = {
        "surface_id": "review_report_workbench",
        "surface_mode": str(surface_defaults["surface_mode"]),
        "internal_only": bool(surface_defaults["internal_only"]),
        "live_execution_enabled": bool(surface_defaults["live_execution_enabled"]),
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
    }
    try:
        action_result = record_operator_action(payload, stage_scope=6)
        response["operational_loop_persisted"] = True
        response["operational_context_status"] = "persisted"
        response["persisted_operational_context"] = action_result["work_item"]
        response["action_result"] = action_result["action_event"]
    except OperationalContractError as exc:
        response["error"] = exc.as_payload()
    return response


STAGE6_ROUTES = [
    {
        "operationId": "previewStage6ReviewReportWorkbench",
        "method": "GET",
        "path": "/review-report-workbench",
        "handler": preview_stage6_review_report_workbench,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
    },
    {
        "operationId": "listStage6WorkItems",
        "method": "GET",
        "path": "/review-report-work-items",
        "handler": list_stage6_work_items,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
    },
    {
        "operationId": "submitStage6OperatorAction",
        "method": "POST",
        "path": "/review-report-workbench/{project_fact_id}/operator-actions",
        "handler": submit_stage6_operator_action,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
    }
]


def register_stage6_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(STAGE6_ROUTES))


__all__ = [
    "STAGE6_ROUTES",
    "list_stage6_work_items",
    "preview_stage6_review_report_workbench",
    "register_stage6_routes",
    "submit_stage6_operator_action",
]
