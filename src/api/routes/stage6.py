# Stage: api_stage6
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.projections import build_stage6_preview_surface, register_route_table
from api.schemas.stage6 import Stage6ReviewReportWorkbenchResponse


def preview_stage6_review_report_workbench(payload: Any) -> Stage6ReviewReportWorkbenchResponse:
    return build_stage6_preview_surface(payload)


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
    }
]


def register_stage6_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(STAGE6_ROUTES))


__all__ = [
    "STAGE6_ROUTES",
    "preview_stage6_review_report_workbench",
    "register_stage6_routes",
]
