# Stage: api_stage9
# Consumes formal objects: order_record, payment_record, delivery_record, governance_feedback_event, opportunity_outcome_event
# Dependent handoff: H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.projections import build_stage9_preview_surface, get_surface_runtime_defaults, register_route_table
from api.schemas.stage9 import (
    DeliveryCreateResponse,
    GovernanceFeedbackCreateResponse,
    GovernanceFeedbackListResponse,
    OpportunityOutcomeCreateResponse,
    OpportunityOutcomeListResponse,
    OrderCreateResponse,
    OrdersListResponse,
    PaymentCreateResponse,
    Stage9OperatorActionResponse,
    Stage9WorkItemListResponse,
)
from storage.repository_boundary import (
    OperationalContractError,
    list_stage_work_items,
    persist_stage_bundle,
    record_operator_action,
)


def list_orders(payload: Any) -> OrdersListResponse:
    return build_stage9_preview_surface(payload)


def create_order(payload: Any) -> OrderCreateResponse:
    persist_stage_bundle(payload)
    response = build_stage9_preview_surface(payload)
    response["draft_created"] = response["governance_envelope"]["action_availability"]["createOrder"]["allowed"]
    return response


def create_payment_record(payload: Any) -> PaymentCreateResponse:
    persist_stage_bundle(payload)
    response = build_stage9_preview_surface(payload)
    response["draft_created"] = response["governance_envelope"]["action_availability"]["createPaymentRecord"]["allowed"]
    return response


def create_delivery_record(payload: Any) -> DeliveryCreateResponse:
    persist_stage_bundle(payload)
    response = build_stage9_preview_surface(payload)
    response["preview_generated"] = response["governance_envelope"]["action_availability"]["createDeliveryRecord"]["allowed"]
    return response


def list_opportunity_outcomes(payload: Any) -> OpportunityOutcomeListResponse:
    return build_stage9_preview_surface(payload)


def create_opportunity_outcome_event(payload: Any) -> OpportunityOutcomeCreateResponse:
    persist_stage_bundle(payload)
    response = build_stage9_preview_surface(payload)
    response["writeback_ready"] = response["governance_envelope"]["action_availability"]["createOpportunityOutcomeEvent"]["allowed"]
    return response


def list_governance_feedback_events(payload: Any) -> GovernanceFeedbackListResponse:
    return build_stage9_preview_surface(payload)


def create_governance_feedback_event(payload: Any) -> GovernanceFeedbackCreateResponse:
    persist_stage_bundle(payload)
    response = build_stage9_preview_surface(payload)
    response["writeback_ready"] = response["governance_envelope"]["action_availability"]["createGovernanceFeedbackEvent"]["allowed"]
    return response


def list_stage9_work_items(payload: Any) -> Stage9WorkItemListResponse:
    if not isinstance(payload, dict):
        persist_stage_bundle(payload)
    surface_defaults = get_surface_runtime_defaults("order_delivery_workbench")
    return {
        "work_items": list_stage_work_items(9, payload if isinstance(payload, dict) else None),
        "internal_only": bool(surface_defaults["internal_only"]),
        "live_execution_enabled": bool(surface_defaults["live_execution_enabled"]),
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
    }


def submit_stage9_operator_action(payload: Any) -> Stage9OperatorActionResponse:
    try:
        action_result = record_operator_action(payload, stage_scope=9)
        response = build_stage9_preview_surface(payload)
        response["operational_loop_persisted"] = True
        response["operational_context_status"] = "persisted"
        response["persisted_operational_context"] = action_result["work_item"]
        response["action_result"] = action_result["action_event"]
    except OperationalContractError as exc:
        try:
            response = build_stage9_preview_surface(payload)
        except Exception:
            response = {
                "surface_id": "order_delivery_workbench",
                "internal_only": True,
                "live_execution_enabled": False,
                "blocked_by_default": True,
            }
        response["error"] = exc.as_payload()
    return response


STAGE9_ROUTES = [
    {
        "operationId": "listOrders",
        "method": "GET",
        "path": "/orders",
        "handler": list_orders,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "createOrder",
        "method": "POST",
        "path": "/orders",
        "handler": create_order,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "createPaymentRecord",
        "method": "POST",
        "path": "/payments",
        "handler": create_payment_record,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "createDeliveryRecord",
        "method": "POST",
        "path": "/deliveries",
        "handler": create_delivery_record,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "listOpportunityOutcomes",
        "method": "GET",
        "path": "/projects/{project_id}/opportunity-outcomes",
        "handler": list_opportunity_outcomes,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "createOpportunityOutcomeEvent",
        "method": "POST",
        "path": "/opportunity-outcomes",
        "handler": create_opportunity_outcome_event,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "listGovernanceFeedbackEvents",
        "method": "GET",
        "path": "/governance-feedback-events",
        "handler": list_governance_feedback_events,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "createGovernanceFeedbackEvent",
        "method": "POST",
        "path": "/governance-feedback-events",
        "handler": create_governance_feedback_event,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "listStage9WorkItems",
        "method": "GET",
        "path": "/order-delivery-work-items",
        "handler": list_stage9_work_items,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
    {
        "operationId": "submitStage9OperatorAction",
        "method": "POST",
        "path": "/order-delivery-workbench/{opportunity_id}/operator-actions",
        "handler": submit_stage9_operator_action,
        "surface_mode": "draft-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": True,
    },
]


def register_stage9_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(STAGE9_ROUTES))


__all__ = [
    "STAGE9_ROUTES",
    "create_delivery_record",
    "create_governance_feedback_event",
    "create_opportunity_outcome_event",
    "create_order",
    "create_payment_record",
    "list_governance_feedback_events",
    "list_opportunity_outcomes",
    "list_orders",
    "list_stage9_work_items",
    "register_stage9_routes",
    "submit_stage9_operator_action",
]
