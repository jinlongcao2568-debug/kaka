# Stage: api_stage7
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.projections import (
    build_leadpack_activation_design_implementation_prep_surface,
    build_leadpack_activation_prep_surface,
    build_leadpack_external_delivery_candidate_surface,
    build_leadpack_implementation_decision_readiness_packet_surface,
    build_stage7_preview_surface,
    get_surface_runtime_defaults,
    register_route_table,
)
from api.schemas.stage7 import (
    LeadpackActivationDesignImplementationPrepResponse,
    LeadpackActivationPrepResponse,
    LeadpackImplementationDecisionReadinessPacketResponse,
    LeadpackExternalDeliveryCandidateResponse,
    SaleableOpportunityListResponse,
    SaleableOpportunityRefreshResponse,
    Stage7OperatorActionResponse,
    Stage7WorkItemListResponse,
)
from storage.repository_boundary import (
    OperationalContractError,
    list_stage_work_items,
    persist_stage_bundle,
    record_operator_action,
)


def list_saleable_opportunities(payload: Any) -> SaleableOpportunityListResponse:
    return build_stage7_preview_surface(payload)


def refresh_saleable_opportunity(payload: Any) -> SaleableOpportunityRefreshResponse:
    persist_stage_bundle(payload)
    response = build_stage7_preview_surface(payload)
    response["refresh_requested"] = True
    return response


def list_stage7_work_items(payload: Any) -> Stage7WorkItemListResponse:
    if not isinstance(payload, dict):
        persist_stage_bundle(payload)
    surface_defaults = get_surface_runtime_defaults("opportunity_pool")
    return {
        "work_items": list_stage_work_items(7, payload if isinstance(payload, dict) else None),
        "internal_only": bool(surface_defaults["internal_only"]),
        "live_execution_enabled": bool(surface_defaults["live_execution_enabled"]),
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
    }


def submit_stage7_operator_action(payload: Any) -> Stage7OperatorActionResponse:
    try:
        action_result = record_operator_action(payload, stage_scope=7)
        response = build_stage7_preview_surface(payload)
        response["operational_loop_persisted"] = True
        response["operational_context_status"] = "persisted"
        response["persisted_operational_context"] = action_result["work_item"]
        response["action_result"] = action_result["action_event"]
    except OperationalContractError as exc:
        try:
            response = build_stage7_preview_surface(payload)
        except Exception:
            response = {
                "surface_id": "opportunity_pool",
                "internal_only": True,
                "live_execution_enabled": False,
            }
        response["error"] = exc.as_payload()
    return response


def preview_leadpack_external_delivery_candidate(payload: Any) -> LeadpackExternalDeliveryCandidateResponse:
    return build_leadpack_external_delivery_candidate_surface(payload, requested_action="preview")


def request_leadpack_external_delivery_candidate_review(payload: Any) -> LeadpackExternalDeliveryCandidateResponse:
    return build_leadpack_external_delivery_candidate_surface(payload, requested_action="review")


def simulate_leadpack_external_delivery_export(payload: Any) -> LeadpackExternalDeliveryCandidateResponse:
    return build_leadpack_external_delivery_candidate_surface(payload, requested_action="export_simulation")


def preview_leadpack_activation_prep_packet(payload: Any) -> LeadpackActivationPrepResponse:
    return build_leadpack_activation_prep_surface(payload, requested_action="packet")


def request_leadpack_activation_prep_review(payload: Any) -> LeadpackActivationPrepResponse:
    return build_leadpack_activation_prep_surface(payload, requested_action="review")


def preview_leadpack_activation_design_implementation_prep_packet(
    payload: Any,
) -> LeadpackActivationDesignImplementationPrepResponse:
    return build_leadpack_activation_design_implementation_prep_surface(payload, requested_action="packet")


def request_leadpack_activation_design_implementation_prep_review(
    payload: Any,
) -> LeadpackActivationDesignImplementationPrepResponse:
    return build_leadpack_activation_design_implementation_prep_surface(payload, requested_action="review")


def preview_leadpack_implementation_decision_readiness_packet(
    payload: Any,
) -> LeadpackImplementationDecisionReadinessPacketResponse:
    return build_leadpack_implementation_decision_readiness_packet_surface(payload)


STAGE7_ROUTES = [
    {
        "operationId": "listSaleableOpportunities",
        "method": "GET",
        "path": "/saleable-opportunities",
        "handler": list_saleable_opportunities,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "refreshSaleableOpportunity",
        "method": "POST",
        "path": "/saleable-opportunities/{opportunity_id}/refresh",
        "handler": refresh_saleable_opportunity,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "listStage7WorkItems",
        "method": "GET",
        "path": "/saleable-opportunity-work-items",
        "handler": list_stage7_work_items,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "submitStage7OperatorAction",
        "method": "POST",
        "path": "/saleable-opportunities/{opportunity_id}/operator-actions",
        "handler": submit_stage7_operator_action,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "previewLeadpackExternalDeliveryCandidate",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}",
        "handler": preview_leadpack_external_delivery_candidate,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "requestLeadpackExternalDeliveryCandidateReview",
        "method": "POST",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/review-requests",
        "handler": request_leadpack_external_delivery_candidate_review,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "simulateLeadpackExternalDeliveryExport",
        "method": "POST",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/export-simulations",
        "handler": simulate_leadpack_external_delivery_export,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "previewLeadpackActivationPrepPacket",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/activation-prep-packet",
        "handler": preview_leadpack_activation_prep_packet,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "requestLeadpackActivationPrepReview",
        "method": "POST",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/activation-prep-review-requests",
        "handler": request_leadpack_activation_prep_review,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "previewLeadpackActivationDesignImplementationPrepPacket",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/activation-design-implementation-prep-packet",
        "handler": preview_leadpack_activation_design_implementation_prep_packet,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
    },
    {
        "operationId": "previewLeadpackImplementationDecisionReadinessPacket",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/implementation-decision-readiness-packet",
        "handler": preview_leadpack_implementation_decision_readiness_packet,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
        "implementation_decision_executed": False,
        "implementation_approved": False,
    },
    {
        "operationId": "requestLeadpackActivationDesignImplementationPrepReview",
        "method": "POST",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/activation-design-implementation-prep-review-requests",
        "handler": request_leadpack_activation_design_implementation_prep_review,
        "surface_mode": "preview-only",
        "internal_only": True,
        "candidate_only": True,
        "external_delivery_enabled": False,
        "requires_review": True,
        "live_execution_enabled": False,
    },
]


def register_stage7_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(STAGE7_ROUTES))


__all__ = [
    "STAGE7_ROUTES",
    "list_saleable_opportunities",
    "list_stage7_work_items",
    "preview_leadpack_activation_design_implementation_prep_packet",
    "preview_leadpack_activation_prep_packet",
    "preview_leadpack_external_delivery_candidate",
    "preview_leadpack_implementation_decision_readiness_packet",
    "refresh_saleable_opportunity",
    "register_stage7_routes",
    "request_leadpack_activation_design_implementation_prep_review",
    "request_leadpack_activation_prep_review",
    "request_leadpack_external_delivery_candidate_review",
    "submit_stage7_operator_action",
    "simulate_leadpack_external_delivery_export",
]
