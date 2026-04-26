# Stage: api_stage8
# Consumes formal objects: contact_target, outreach_plan, touch_record
# Dependent handoff: H-07-STAGE7-TO-STAGE8, H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.projections import build_stage8_preview_surface, get_surface_runtime_defaults, register_route_table
from api.schemas.stage8 import (
    ContactComplianceCheckResponse,
    ContactTargetsListResponse,
    OutreachPlanCreateResponse,
    Stage8OperatorActionResponse,
    Stage8WorkItemListResponse,
    TouchRecordCreateResponse,
)
from storage.repository_boundary import (
    OperationalContractError,
    list_stage_work_items,
    persist_stage_bundle,
    record_operator_action,
)
from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_adapter_bootstrap_payload,
    provider_readiness_for_family,
)


STAGE8_OUTBOX_ROUTE_READINESS = {
    "governed_execution_mode": "INTERNAL_GOVERNED",
    "outbox_enabled": True,
    "repository_backed_readback": True,
    "real_send_enabled": False,
    "real_send_attempted": False,
    "vendor_connection_enabled": False,
    "stage8_execution_outbox_readiness": {
        "governed_execution_mode": "INTERNAL_GOVERNED",
        "sandbox_execution_record_enabled": True,
        "sandbox_adapter_families": ["email", "sms", "phone_call", "wecom_im"],
        "execution_timeline_visible": True,
        "live_execution_enabled": False,
        "real_send_attempted": False,
        "external_delivery_enabled": False,
        "ready_for_real_send": False,
        "blocked_reasons": [
            "stage8_real_execution_blocked_by_default",
            "internal_governed_outbox_only",
        ],
    },
}


def _provider_adapter_route_metadata(provider_adapter_readiness_summary: Any) -> dict[str, Any]:
    if not isinstance(provider_adapter_readiness_summary, dict):
        return {}
    bootstrap = provider_adapter_bootstrap_payload(provider_adapter_readiness_summary)
    return {
        **bootstrap,
        "sales_outreach_provider_adapter_readiness": provider_readiness_for_family(
            provider_adapter_readiness_summary,
            "sales_outreach",
        ),
        "provider_adapter_families_consumed": ["sales_outreach"],
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: dict(provider_adapter_readiness_summary),
    }


def list_contact_targets(payload: Any) -> ContactTargetsListResponse:
    return build_stage8_preview_surface(payload)


def check_contact_compliance(payload: Any) -> ContactComplianceCheckResponse:
    response = build_stage8_preview_surface(payload)
    response["compliance_result"] = response["semantic_envelope"]["surface_state"]
    return response


def create_outreach_plan(payload: Any) -> OutreachPlanCreateResponse:
    persist_stage_bundle(payload)
    response = build_stage8_preview_surface(payload)
    response["draft_created"] = response["governance_envelope"]["action_availability"]["createOutreachPlan"]["allowed"]
    return response


def create_touch_record(payload: Any) -> TouchRecordCreateResponse:
    persist_stage_bundle(payload)
    response = build_stage8_preview_surface(payload)
    response["writeback_ready"] = response["governance_envelope"]["action_availability"]["createTouchRecord"]["allowed"]
    return response


def list_stage8_work_items(payload: Any) -> Stage8WorkItemListResponse:
    if not isinstance(payload, dict):
        persist_stage_bundle(payload)
    surface_defaults = get_surface_runtime_defaults("outreach_workbench")
    return {
        "work_items": list_stage_work_items(8, payload if isinstance(payload, dict) else None),
        "internal_only": bool(surface_defaults["internal_only"]),
        "live_execution_enabled": bool(surface_defaults["live_execution_enabled"]),
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
    }


def submit_stage8_operator_action(payload: Any) -> Stage8OperatorActionResponse:
    try:
        action_result = record_operator_action(payload, stage_scope=8)
        response = build_stage8_preview_surface(payload)
        response["operational_loop_persisted"] = True
        response["operational_context_status"] = "persisted"
        response["persisted_operational_context"] = action_result["work_item"]
        response["action_result"] = action_result["action_event"]
    except OperationalContractError as exc:
        try:
            response = build_stage8_preview_surface(payload)
        except Exception:
            response = {
                "surface_id": "outreach_workbench",
                "internal_only": True,
                "live_execution_enabled": False,
                "blocked_by_default": True,
            }
        response["error"] = exc.as_payload()
    return response


STAGE8_ROUTES = [
    {
        "operationId": "listContactTargets",
        "method": "GET",
        "path": "/contact-targets",
        "handler": list_contact_targets,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        **STAGE8_OUTBOX_ROUTE_READINESS,
    },
    {
        "operationId": "checkContactCompliance",
        "method": "POST",
        "path": "/contact-targets/compliance-check",
        "handler": check_contact_compliance,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        **STAGE8_OUTBOX_ROUTE_READINESS,
    },
    {
        "operationId": "createOutreachPlan",
        "method": "POST",
        "path": "/outreach-plans",
        "handler": create_outreach_plan,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        **STAGE8_OUTBOX_ROUTE_READINESS,
    },
    {
        "operationId": "createTouchRecord",
        "method": "POST",
        "path": "/touch-records",
        "handler": create_touch_record,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        **STAGE8_OUTBOX_ROUTE_READINESS,
    },
    {
        "operationId": "listStage8WorkItems",
        "method": "GET",
        "path": "/outreach-work-items",
        "handler": list_stage8_work_items,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        **STAGE8_OUTBOX_ROUTE_READINESS,
    },
    {
        "operationId": "submitStage8OperatorAction",
        "method": "POST",
        "path": "/outreach-workbench/{opportunity_id}/operator-actions",
        "handler": submit_stage8_operator_action,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
        **STAGE8_OUTBOX_ROUTE_READINESS,
    },
]


def register_stage8_routes(
    router: object | None = None,
    *,
    provider_adapter_readiness_summary: Any = None,
) -> list[dict[str, Any]]:
    provider_metadata = _provider_adapter_route_metadata(provider_adapter_readiness_summary)
    routes = [
        {**route, **provider_metadata}
        for route in STAGE8_ROUTES
    ]
    return register_route_table(router, routes)


__all__ = [
    "STAGE8_ROUTES",
    "check_contact_compliance",
    "create_outreach_plan",
    "create_touch_record",
    "list_contact_targets",
    "list_stage8_work_items",
    "register_stage8_routes",
    "submit_stage8_operator_action",
]
