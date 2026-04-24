# Stage: api_stage7
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from collections.abc import Mapping
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
    hydrate_stage_bundle,
    list_stage_work_items,
    persist_stage_bundle,
    record_operator_action,
)
from shared.contracts_runtime import StageBundle
from shared.utils import resolve_bundle
from stage7_sales.recommendation import build_crm_quote_prerequisite_readiness_carrier


CRM_QUOTE_PREREQUISITE_ROUTE_METADATA = {
    "readiness_only": True,
    "governed_execution_mode": "INTERNAL_GOVERNED",
    "crm_runtime_enabled": False,
    "external_quote_enabled": False,
    "external_delivery_enabled": False,
    "crm_quote_prerequisite_readiness": {
        "readiness_only": True,
        "prerequisite_only": True,
        "blocked_by_default": True,
        "crm_runtime_enabled": False,
        "external_quote_enabled": False,
        "external_delivery_enabled": False,
        "governed_execution_mode": "INTERNAL_GOVERNED",
        "surface": "opportunity_pool",
    },
}

LEADPACK_CANDIDATE_ROUTE_METADATA = {
    "readiness_only": True,
    "review_only": True,
    "governed_execution_mode": "INTERNAL_GOVERNED",
    "candidate_only": True,
    "external_delivery_enabled": False,
    "direct_export_enabled": False,
    "external_ready_direct_export": False,
    "customer_visible_export_enabled": False,
    "page_layer_release_enabled": False,
    "requires_review": True,
    "live_execution_enabled": False,
    "leadpack_external_delivery_candidate_readiness": {
        "readiness_only": True,
        "approval_audit_readiness_only": True,
        "candidate_only": True,
        "review_only": True,
        "external_delivery_enabled": False,
        "direct_export_enabled": False,
        "external_ready_direct_export": False,
        "customer_visible_export_enabled": False,
        "page_layer_release_enabled": False,
        "surface": "review_report_workbench",
    },
}


def _resolve_stage7_bundle_for_readiness(payload: Any) -> StageBundle | None:
    if isinstance(payload, Mapping):
        candidate = payload.get("stage7")
        if isinstance(candidate, StageBundle):
            return candidate
    try:
        bundle = resolve_bundle(payload)
    except TypeError:
        bundle = None
    if bundle is not None and bundle.stage == 7:
        return bundle
    if isinstance(payload, Mapping):
        return hydrate_stage_bundle("stage7", payload)
    return None


def _stage7_record_payload(bundle: StageBundle, record_name: str) -> dict[str, Any]:
    record = bundle.records.get(record_name)
    if record is None:
        return {}
    return dict(record.data)


def _stage7_trace_payload(bundle: StageBundle) -> dict[str, Any]:
    trace = bundle.inputs.get("stage7_resolution_trace")
    return dict(trace) if isinstance(trace, Mapping) else {}


def _attach_crm_quote_prerequisite_readback(response: dict[str, Any], payload: Any) -> dict[str, Any]:
    bundle = _resolve_stage7_bundle_for_readiness(payload)
    if bundle is None:
        return response
    carrier = bundle.inputs.get("crm_quote_prerequisite_readiness")
    if not isinstance(carrier, Mapping):
        semantic_additions = bundle.inputs.get("semantic_additions")
        if isinstance(semantic_additions, Mapping):
            carrier = semantic_additions.get("crm_quote_prerequisite_readiness")
    if not isinstance(carrier, Mapping):
        carrier = build_crm_quote_prerequisite_readiness_carrier(
            sales_lead=_stage7_record_payload(bundle, "sales_lead"),
            saleable_opportunity=_stage7_record_payload(bundle, "saleable_opportunity"),
            offer_recommendation=_stage7_record_payload(bundle, "offer_recommendation"),
            stage7_resolution_trace=_stage7_trace_payload(bundle),
        )
    response["crm_quote_prerequisite_readiness"] = dict(carrier)
    return response


def list_saleable_opportunities(payload: Any) -> SaleableOpportunityListResponse:
    return _attach_crm_quote_prerequisite_readback(build_stage7_preview_surface(payload), payload)


def refresh_saleable_opportunity(payload: Any) -> SaleableOpportunityRefreshResponse:
    persist_stage_bundle(payload)
    response = build_stage7_preview_surface(payload)
    response["refresh_requested"] = True
    return _attach_crm_quote_prerequisite_readback(response, payload)


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
    return _attach_crm_quote_prerequisite_readback(response, payload)


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
        **CRM_QUOTE_PREREQUISITE_ROUTE_METADATA,
    },
    {
        "operationId": "refreshSaleableOpportunity",
        "method": "POST",
        "path": "/saleable-opportunities/{opportunity_id}/refresh",
        "handler": refresh_saleable_opportunity,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        **CRM_QUOTE_PREREQUISITE_ROUTE_METADATA,
    },
    {
        "operationId": "listStage7WorkItems",
        "method": "GET",
        "path": "/saleable-opportunity-work-items",
        "handler": list_stage7_work_items,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        **CRM_QUOTE_PREREQUISITE_ROUTE_METADATA,
    },
    {
        "operationId": "submitStage7OperatorAction",
        "method": "POST",
        "path": "/saleable-opportunities/{opportunity_id}/operator-actions",
        "handler": submit_stage7_operator_action,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        **CRM_QUOTE_PREREQUISITE_ROUTE_METADATA,
    },
    {
        "operationId": "previewLeadpackExternalDeliveryCandidate",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}",
        "handler": preview_leadpack_external_delivery_candidate,
        "surface_mode": "preview-only",
        "internal_only": True,
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
    },
    {
        "operationId": "requestLeadpackExternalDeliveryCandidateReview",
        "method": "POST",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/review-requests",
        "handler": request_leadpack_external_delivery_candidate_review,
        "surface_mode": "preview-only",
        "internal_only": True,
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
    },
    {
        "operationId": "simulateLeadpackExternalDeliveryExport",
        "method": "POST",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/export-simulations",
        "handler": simulate_leadpack_external_delivery_export,
        "surface_mode": "preview-only",
        "internal_only": True,
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
    },
    {
        "operationId": "previewLeadpackActivationPrepPacket",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/activation-prep-packet",
        "handler": preview_leadpack_activation_prep_packet,
        "surface_mode": "preview-only",
        "internal_only": True,
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
    },
    {
        "operationId": "requestLeadpackActivationPrepReview",
        "method": "POST",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/activation-prep-review-requests",
        "handler": request_leadpack_activation_prep_review,
        "surface_mode": "preview-only",
        "internal_only": True,
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
    },
    {
        "operationId": "previewLeadpackActivationDesignImplementationPrepPacket",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/activation-design-implementation-prep-packet",
        "handler": preview_leadpack_activation_design_implementation_prep_packet,
        "surface_mode": "preview-only",
        "internal_only": True,
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
    },
    {
        "operationId": "previewLeadpackImplementationDecisionReadinessPacket",
        "method": "GET",
        "path": "/leadpack-external-delivery-candidates/{opportunity_id}/implementation-decision-readiness-packet",
        "handler": preview_leadpack_implementation_decision_readiness_packet,
        "surface_mode": "preview-only",
        "internal_only": True,
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
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
        **LEADPACK_CANDIDATE_ROUTE_METADATA,
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
