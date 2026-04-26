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
from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_adapter_bootstrap_payload,
    provider_readiness_for_family,
)


STAGE9_EXECUTION_LEDGER_ROUTE_READINESS = {
    "governed_execution_mode": "INTERNAL_GOVERNED",
    "repository_backed_readback": True,
    "payment_gateway_enabled": False,
    "real_payment_gateway_enabled": False,
    "real_charge_enabled": False,
    "real_delivery_enabled": False,
    "real_refund_enabled": False,
    "automated_refund_enabled": False,
    "stage9_execution_ledger_readiness": {
        "governed_execution_mode": "INTERNAL_GOVERNED",
        "owner_operable": True,
        "payment_recording_enabled": True,
        "delivery_recording_enabled": True,
        "manual_settlement_enabled": True,
        "refund_manual_exception_enabled": True,
        "ready_for_real_payment_gateway": False,
        "ready_for_real_charge": False,
        "ready_for_real_refund": False,
        "automated_refund_enabled": False,
        "blocked_reasons": [
            "real_payment_gateway_blocked_by_default",
            "automated_refund_program_out_of_scope",
        ],
    },
    "order_payment_delivery_execution_summary": {
        "real_payment_gateway_enabled": False,
        "real_charge_attempted": False,
        "real_refund_attempted": False,
        "automated_refund_enabled": False,
    },
    "payment_sandbox_provider_records": {
        "readback_ready": True,
        "gateway_record_enabled": True,
        "charge_status_callback_record_enabled": True,
        "receipt_record_enabled": True,
        "invoice_record_enabled": True,
        "real_charge_enabled": False,
        "payment_capture_enabled": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
    },
    "delivery_sandbox_provider_records": {
        "readback_ready": True,
        "provider_record_enabled": True,
        "artifact_download_record_enabled": True,
        "version_lock_enabled": True,
        "delivery_hash_enabled": True,
        "delivery_audit_enabled": True,
        "real_delivery_enabled": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
    },
    "manual_refund_exception_record": {
        "readback_ready": True,
        "manual_exception_enabled": True,
        "manual_approval_audit_enabled": True,
        "automated_refund_program_present": False,
        "automated_refund_enabled": False,
        "real_refund_enabled": False,
    },
}


def _provider_adapter_route_metadata(provider_adapter_readiness_summary: Any) -> dict[str, Any]:
    if not isinstance(provider_adapter_readiness_summary, dict):
        return {}
    bootstrap = provider_adapter_bootstrap_payload(provider_adapter_readiness_summary)
    return {
        **bootstrap,
        "payment_collection_provider_adapter_readiness": provider_readiness_for_family(
            provider_adapter_readiness_summary,
            "payment_collection",
        ),
        "leadpack_page_delivery_provider_adapter_readiness": provider_readiness_for_family(
            provider_adapter_readiness_summary,
            "leadpack_page_delivery",
        ),
        "provider_adapter_families_consumed": [
            "payment_collection",
            "leadpack_page_delivery",
        ],
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: dict(provider_adapter_readiness_summary),
    }


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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
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
        **STAGE9_EXECUTION_LEDGER_ROUTE_READINESS,
    },
]


def register_stage9_routes(
    router: object | None = None,
    *,
    provider_adapter_readiness_summary: Any = None,
) -> list[dict[str, Any]]:
    provider_metadata = _provider_adapter_route_metadata(provider_adapter_readiness_summary)
    routes = [
        {**route, **provider_metadata}
        for route in STAGE9_ROUTES
    ]
    return register_route_table(router, routes)


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
