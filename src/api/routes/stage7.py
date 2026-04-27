# Stage: api_stage7
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from api.projections import (
    build_formal_client_export_page_layer_readiness_surface,
    build_leadpack_activation_design_implementation_prep_surface,
    build_leadpack_activation_prep_surface,
    build_leadpack_external_delivery_candidate_surface,
    build_leadpack_implementation_decision_readiness_packet_surface,
    build_stage7_preview_surface,
    get_surface_runtime_defaults,
    register_route_table,
)
from api.schemas.stage7 import (
    FormalClientExportPageLayerReadinessResponse,
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
from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_adapter_bootstrap_payload,
    provider_readiness_for_family,
)
from shared.contracts_runtime import StageBundle
from shared.utils import resolve_bundle
from stage7_sales.crm_quote_workbench import (
    CRM_QUOTE_WORKBENCH_INPUT_KEY,
    CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY,
    build_crm_quote_workbench_carrier,
    build_crm_quote_workbench_readiness_summary,
)
from stage7_sales.leadpack_delivery_package import (
    LEADPACK_DELIVERY_PACKAGE_INPUT_KEY,
    LEADPACK_DELIVERY_READINESS_INPUT_KEY,
    build_leadpack_delivery_package_carrier,
    build_leadpack_delivery_readiness_summary,
    leadpack_delivery_package_summary,
)
from stage7_sales.recommendation import build_crm_quote_prerequisite_readiness_carrier


LEADPACK_DELIVERY_PACKAGE_ROUTE_METADATA = {
    "repository_backed_readback": True,
    "leadpack_delivery_package_readiness": {
        "readiness_only": False,
        "internal_only": True,
        "repository_backed_readback": True,
        "owner_operated_workbench": True,
        "package_manifest_visible": True,
        "evidence_item_manifest_visible": True,
        "field_masking_summary_visible": True,
        "field_allowlist_blacklist_visible": True,
        "customer_visible_artifact_candidate_visible": True,
        "watermark_visible": True,
        "artifact_version_hash_visible": True,
        "download_audit_visible": True,
        "export_page_replay_visible": True,
        "page_draft_visible": True,
        "delivery_readiness_visible": True,
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "external_release_enabled": False,
        "page_publication_enabled": False,
        "surface": "opportunity_pool",
    },
    "package_page_delivery_summary": {
        "package_summary_visible": True,
        "page_summary_visible": True,
        "delivery_summary_visible": True,
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "page_publication_enabled": False,
    },
}


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
    "crm_quote_workbench_readiness": {
        "readiness_only": True,
        "draft_only": True,
        "blocked_live": True,
        "repository_backed_readback": True,
        "crm_account_sandbox_sync_record_visible": True,
        "crm_opportunity_sandbox_sync_record_visible": True,
        "crm_activity_sandbox_sync_record_visible": True,
        "quote_sandbox_record_visible": True,
        "deal_tracking_record_visible": True,
        "sales_note_callback_record_visible": True,
        "governed_execution_mode": "INTERNAL_GOVERNED",
        "live_execution_enabled": False,
        "real_external_quote_sent": False,
        "crm_runtime_enabled": False,
        "external_quote_enabled": False,
        "surface": "opportunity_pool",
    },
    "stage7_approved_crm_quote_provider_execution_readiness": {
        "capability_state": "LIVE_READY",
        "readiness_scope": "approved_crm_quote_provider_execution_readback",
        "provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER",
        "supported_actions": [
            "crm_account_sync",
            "crm_opportunity_sync",
            "crm_activity_sync",
            "quote_send",
            "quote_version",
            "quote_approval",
            "quote_expiration",
            "discount_approval",
            "quote_audit",
        ],
        "requires_provider_config": True,
        "requires_sandbox_pass": True,
        "requires_crm_approval": True,
        "requires_quote_approval": True,
        "requires_quote_audit": True,
        "requires_operator_action_audit": True,
        "requires_quote_version_policy": True,
        "requires_quote_expiration_policy": True,
        "requires_discount_approval_policy": True,
        "requires_provider_reliability": True,
        "provider_unhealthy_rate_limited_timeout_circuit_open_suspended_fail_closed": True,
        "repository_backed_readback": True,
        "replayable": True,
        "provider_result_readback_visible": True,
        "deal_tracking_timeline_visible": True,
        "sales_note_callback_readback_visible": True,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "real_crm_sync_enabled": False,
        "external_quote_sent": False,
        "real_external_quote_sent": False,
        "stage8_outreach_enabled": False,
        "stage9_payment_delivery_refund_enabled": False,
        "automated_refund_enabled": False,
        "surface": "opportunity_pool",
    },
    **LEADPACK_DELIVERY_PACKAGE_ROUTE_METADATA,
}

FORMAL_CLIENT_EXPORT_PAGE_LAYER_ROUTE_METADATA = {
    "projection_only": True,
    "non_live": True,
    "release_blocked": True,
    "customer_visible_export_enabled": False,
    "client_page_release_enabled": False,
    "page_layer_release_enabled": False,
    "external_release_enabled": False,
    "external_delivery_enabled": False,
    "direct_export_enabled": False,
    "export_artifact_generation_enabled": False,
    "page_publication_enabled": False,
    "formal_client_export_page_layer_readiness": {
        "surface_id": "formal_client_export_page_layer_readiness",
        "internal_only": True,
        "readiness_only": True,
        "projection_only": True,
        "review_only": True,
        "non_live": True,
        "release_blocked": True,
        "customer_visible_export_enabled": False,
        "client_page_release_enabled": False,
        "external_release_enabled": False,
        "external_delivery_enabled": False,
        "direct_export_enabled": False,
        "export_artifact_generation_enabled": False,
        "page_publication_enabled": False,
        "source_surface": "leadpack_implementation_decision_readiness_packet",
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
    "client_page_release_enabled": False,
    "page_layer_release_enabled": False,
    "requires_review": True,
    "live_execution_enabled": False,
    **FORMAL_CLIENT_EXPORT_PAGE_LAYER_ROUTE_METADATA,
    "leadpack_external_delivery_candidate_readiness": {
        "readiness_only": True,
        "approval_audit_readiness_only": True,
        "candidate_only": True,
        "review_only": True,
        "external_delivery_enabled": False,
        "direct_export_enabled": False,
        "external_ready_direct_export": False,
        "customer_visible_export_enabled": False,
        "client_page_release_enabled": False,
        "page_layer_release_enabled": False,
        "surface": "review_report_workbench",
    },
    **LEADPACK_DELIVERY_PACKAGE_ROUTE_METADATA,
}


def _provider_adapter_route_metadata(
    provider_adapter_readiness_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(provider_adapter_readiness_summary, Mapping):
        return {}
    bootstrap = provider_adapter_bootstrap_payload(provider_adapter_readiness_summary)
    return {
        **bootstrap,
        "crm_quote_provider_adapter_readiness": provider_readiness_for_family(
            provider_adapter_readiness_summary,
            "crm_quote",
        ),
        "leadpack_page_delivery_provider_adapter_readiness": provider_readiness_for_family(
            provider_adapter_readiness_summary,
            "leadpack_page_delivery",
        ),
        "provider_adapter_families_consumed": [
            "crm_quote",
            "leadpack_page_delivery",
        ],
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: dict(provider_adapter_readiness_summary),
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
        provider_summary = bundle.inputs.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY)
        carrier = build_crm_quote_prerequisite_readiness_carrier(
            sales_lead=_stage7_record_payload(bundle, "sales_lead"),
            saleable_opportunity=_stage7_record_payload(bundle, "saleable_opportunity"),
            offer_recommendation=_stage7_record_payload(bundle, "offer_recommendation"),
            stage7_resolution_trace=_stage7_trace_payload(bundle),
        )
    carrier_payload = dict(carrier)
    provider_summary = bundle.inputs.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY)
    if isinstance(provider_summary, Mapping):
        carrier_payload.setdefault(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY, dict(provider_summary))
        carrier_payload.setdefault(
            "provider_adapter_readiness",
            provider_readiness_for_family(provider_summary, "crm_quote"),
        )
        carrier_payload.setdefault("provider_adapter_config_source", provider_summary.get("config_source"))
        carrier_payload.setdefault("provider_adapter_mode", provider_summary.get("mode"))
    response["crm_quote_prerequisite_readiness"] = carrier_payload
    workbench = bundle.inputs.get(CRM_QUOTE_WORKBENCH_INPUT_KEY)
    if not isinstance(workbench, Mapping):
        semantic_additions = bundle.inputs.get("semantic_additions")
        if isinstance(semantic_additions, Mapping):
            workbench = semantic_additions.get(CRM_QUOTE_WORKBENCH_INPUT_KEY)
    if not isinstance(workbench, Mapping):
        provider_summary = bundle.inputs.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY)
        workbench = build_crm_quote_workbench_carrier(
            sales_lead=_stage7_record_payload(bundle, "sales_lead"),
            saleable_opportunity=_stage7_record_payload(bundle, "saleable_opportunity"),
            offer_recommendation=_stage7_record_payload(bundle, "offer_recommendation"),
            inputs=bundle.inputs,
            stage7_resolution_trace=_stage7_trace_payload(bundle),
            now=str(bundle.inputs.get("now") or ""),
            provider_adapter_readiness_summary=provider_summary if isinstance(provider_summary, Mapping) else None,
        )
    response[CRM_QUOTE_WORKBENCH_INPUT_KEY] = dict(workbench)
    readiness_summary = bundle.inputs.get(CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY)
    response[CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY] = (
        dict(readiness_summary)
        if isinstance(readiness_summary, Mapping)
        else build_crm_quote_workbench_readiness_summary(workbench)
    )
    return response


def _attach_leadpack_delivery_package_readback(response: dict[str, Any], payload: Any) -> dict[str, Any]:
    bundle = _resolve_stage7_bundle_for_readiness(payload)
    if bundle is None:
        return response
    carrier = bundle.inputs.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY)
    if not isinstance(carrier, Mapping):
        semantic_additions = bundle.inputs.get("semantic_additions")
        if isinstance(semantic_additions, Mapping):
            carrier = semantic_additions.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY)
    if not isinstance(carrier, Mapping):
        provider_summary = bundle.inputs.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY)
        carrier = build_leadpack_delivery_package_carrier(
            sales_lead=_stage7_record_payload(bundle, "sales_lead"),
            saleable_opportunity=_stage7_record_payload(bundle, "saleable_opportunity"),
            offer_recommendation=_stage7_record_payload(bundle, "offer_recommendation"),
            buyer_fit=_stage7_record_payload(bundle, "buyer_fit"),
            legal_action_actor_profile=_stage7_record_payload(bundle, "legal_action_actor_profile"),
            procurement_decision_actor_profile=_stage7_record_payload(
                bundle,
                "procurement_decision_actor_profile",
            ),
            inputs=bundle.inputs,
            stage7_resolution_trace=_stage7_trace_payload(bundle),
            now=str(bundle.inputs.get("now") or ""),
            provider_adapter_readiness_summary=provider_summary if isinstance(provider_summary, Mapping) else None,
        )
    carrier_payload = dict(carrier)
    response[LEADPACK_DELIVERY_PACKAGE_INPUT_KEY] = carrier_payload
    readiness_summary = bundle.inputs.get(LEADPACK_DELIVERY_READINESS_INPUT_KEY)
    readiness = (
        dict(readiness_summary)
        if isinstance(readiness_summary, Mapping)
        else build_leadpack_delivery_readiness_summary(carrier)
    )
    response[LEADPACK_DELIVERY_READINESS_INPUT_KEY] = readiness
    response["package_page_delivery_summary"] = {
        "package": leadpack_delivery_package_summary(carrier),
        "readiness": readiness,
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "page_publication_enabled": False,
        "customer_visible_artifact_candidate": dict(
            carrier_payload.get("customer_visible_artifact_candidate", {})
        ),
        "page_export_candidate": dict(carrier_payload.get("page_export_candidate", {})),
        "download_audit": dict(carrier_payload.get("download_audit", {})),
        "export_page_replay": dict(carrier_payload.get("export_page_replay", {})),
    }
    return response


def list_saleable_opportunities(payload: Any) -> SaleableOpportunityListResponse:
    response = _attach_crm_quote_prerequisite_readback(build_stage7_preview_surface(payload), payload)
    return _attach_leadpack_delivery_package_readback(response, payload)


def refresh_saleable_opportunity(payload: Any) -> SaleableOpportunityRefreshResponse:
    persist_stage_bundle(payload)
    response = build_stage7_preview_surface(payload)
    response["refresh_requested"] = True
    response = _attach_crm_quote_prerequisite_readback(response, payload)
    return _attach_leadpack_delivery_package_readback(response, payload)


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
    response = _attach_crm_quote_prerequisite_readback(response, payload)
    return _attach_leadpack_delivery_package_readback(response, payload)


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
    response = build_leadpack_implementation_decision_readiness_packet_surface(payload)
    response["formal_client_export_page_layer_readiness"] = (
        build_formal_client_export_page_layer_readiness_surface(
            payload,
            source_implementation_decision_packet=response,
        )
    )
    return response


def preview_formal_client_export_page_layer_readiness(
    payload: Any,
) -> FormalClientExportPageLayerReadinessResponse:
    return build_formal_client_export_page_layer_readiness_surface(payload)


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


def register_stage7_routes(
    router: object | None = None,
    *,
    provider_adapter_readiness_summary: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    provider_metadata = _provider_adapter_route_metadata(provider_adapter_readiness_summary)
    routes = [
        {**route, **provider_metadata}
        for route in STAGE7_ROUTES
    ]
    return register_route_table(router, routes)


__all__ = [
    "STAGE7_ROUTES",
    "list_saleable_opportunities",
    "list_stage7_work_items",
    "preview_leadpack_activation_design_implementation_prep_packet",
    "preview_leadpack_activation_prep_packet",
    "preview_formal_client_export_page_layer_readiness",
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
