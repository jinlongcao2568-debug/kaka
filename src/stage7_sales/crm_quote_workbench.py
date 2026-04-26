from __future__ import annotations

from typing import Any, Mapping

from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_readiness_for_family,
)
from shared.utils import build_id, ensure_list
from stage7_sales.runtime import build_stage7_crm_quote_governed_metadata, dedupe_strings


CRM_QUOTE_WORKBENCH_OBJECT_TYPE = "stage7_crm_quote_workbench"
CRM_QUOTE_WORKBENCH_INPUT_KEY = "crm_quote_workbench"
CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY = "crm_quote_workbench_readiness_summary"
CRM_ACTION_ID_INPUT_KEY = "crm_action_id_optional"
QUOTE_DRAFT_ID_INPUT_KEY = "quote_draft_id_optional"

_EMPTY_VALUES = {None, "", "UNKNOWN", "None"}
_INTERNAL_ONLY_VENDOR_IDS = {
    "INTERNAL_MANUAL_CRM",
    "INTERNAL_MANUAL_QUOTE",
    "INTERNAL_DRAFT_ONLY",
}
_AUDIT_REF_FIELDS = (
    "project_fact_audit_ref",
    "candidate_projection_audit_ref",
    "approval_chain_audit_ref",
    "trace_bundle_ref",
)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "live"}
    return bool(value)


def _clean_list(values: list[Any]) -> list[str]:
    return dedupe_strings([value for value in values if value not in _EMPTY_VALUES])


def _requested_external_quote(inputs: Mapping[str, Any]) -> bool:
    return any(
        _truthy(inputs.get(field_name))
        for field_name in (
            "external_quote_enabled",
            "external_quote_requested",
            "request_external_quote",
            "customer_quote_requested",
        )
    )


def _requested_live_crm(inputs: Mapping[str, Any]) -> bool:
    return any(
        _truthy(inputs.get(field_name))
        for field_name in (
            "crm_runtime_enabled",
            "live_crm_request",
            "live_crm_requested",
            "crm_live_execution_requested",
        )
    )


def _requested_vendor_connection(inputs: Mapping[str, Any]) -> bool:
    return any(
        _truthy(inputs.get(field_name))
        for field_name in (
            "vendor_connection_enabled",
            "direct_vendor_call_enabled",
            "external_vendor_connection_enabled",
            "vendor_direct_connection_requested",
        )
    )


def _requested_live_execution(inputs: Mapping[str, Any]) -> bool:
    return _truthy(inputs.get("live_execution_enabled")) or _truthy(
        inputs.get("external_live_execution_requested")
    )


def _vendor_id(inputs: Mapping[str, Any]) -> str:
    return str(
        inputs.get("crm_vendor_id_optional")
        or inputs.get("crm_vendor_id")
        or inputs.get("quote_vendor_id_optional")
        or inputs.get("quote_vendor_id")
        or ""
    ).strip()


def _audit_state(inputs: Mapping[str, Any], stage7_resolution_trace: Mapping[str, Any]) -> tuple[str, list[str]]:
    if inputs.get("audit_trail_present") is False:
        return "MISSING", list(_AUDIT_REF_FIELDS)
    present_refs = {
        field_name
        for field_name in _AUDIT_REF_FIELDS
        if inputs.get(field_name) not in _EMPTY_VALUES
    }
    if stage7_resolution_trace:
        present_refs.add("trace_bundle_ref")
    missing = [field_name for field_name in _AUDIT_REF_FIELDS if field_name not in present_refs]
    return ("MISSING" if missing else "PRESENT"), missing


def _owner_action_state(
    *,
    saleability_status: Any,
    offer_state: Any,
    requested_external_quote: bool,
    requested_live_crm: bool,
) -> str:
    if requested_external_quote or requested_live_crm:
        return "BLOCKED"
    if saleability_status != "QUALIFIED" or offer_state != "APPROVED":
        return "REVIEW_REQUIRED"
    return "DRAFT"


def _quote_surface_state(*, offer_state: Any, requested_external_quote: bool) -> str:
    if requested_external_quote:
        return "BLOCKED"
    if offer_state != "APPROVED":
        return "REVIEW_REQUIRED"
    return "DRAFT"


def build_crm_quote_workbench_readiness_summary(carrier: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(carrier.get("blocked_reasons")))
    provider_readiness = dict(carrier.get("provider_adapter_readiness", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    return {
        "opportunity_id": carrier.get("opportunity_id"),
        "crm_action_id": carrier.get("crm_action_id"),
        "quote_draft_id": carrier.get("quote_draft_id"),
        "governed_execution_mode": carrier.get("governed_execution_mode", "INTERNAL_GOVERNED"),
        "readback_ready": bool(carrier.get("crm_action_id") and carrier.get("quote_draft_id")),
        "owner_action_state": carrier.get("owner_action_state"),
        "approval_state": carrier.get("approval_state"),
        "audit_state": carrier.get("audit_state"),
        "vendor_adapter_state": dict(carrier.get("vendor_adapter_state", {})).get("state"),
        "quote_surface_state": carrier.get("quote_surface_state"),
        "dry_run_state": carrier.get("dry_run_state"),
        "ready_for_live_execution": False,
        "ready_for_external_quote": False,
        "live_execution_enabled": False,
        "real_external_quote_sent": False,
        "blocked_reason_count": len(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "provider_adapter_config_source": carrier.get("provider_adapter_config_source"),
        "provider_adapter_mode": carrier.get("provider_adapter_mode"),
        "provider_adapter_readback_only": bool(provider_readiness.get("readback_only", True)),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": bool(provider_readiness.get("provider_adapter_suspended", False)),
        "provider_circuit_breaker_state": provider_circuit_breaker.get("state"),
        "provider_failure_class": provider_failure_taxonomy.get("failure_class"),
        "provider_status_replayable": bool(provider_status_readback.get("replayable", True)),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
    }


def build_crm_quote_workbench_carrier(
    *,
    sales_lead: Mapping[str, Any],
    saleable_opportunity: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
    inputs: Mapping[str, Any],
    stage7_resolution_trace: Mapping[str, Any],
    now: str,
    provider_adapter_readiness_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    governed_metadata = build_stage7_crm_quote_governed_metadata()
    provider_readiness = provider_readiness_for_family(
        provider_adapter_readiness_summary,
        "crm_quote",
    )
    opportunity_id = str(saleable_opportunity.get("opportunity_id") or "")
    project_id = str(saleable_opportunity.get("project_id") or "")
    offer_id = offer_recommendation.get("offer_recommendation_id")
    lead_id = sales_lead.get("lead_id")
    crm_action_id = build_id("CRMACT", project_id, opportunity_id)
    quote_draft_id = build_id("QDRAFT", project_id, opportunity_id)
    approval_state = str(inputs.get("approval_state", "NOT_REQUIRED") or "NOT_REQUIRED")
    audit_state, missing_audit_refs = _audit_state(inputs, stage7_resolution_trace)
    requested_external_quote = _requested_external_quote(inputs)
    requested_live_crm = _requested_live_crm(inputs)
    requested_live_execution = _requested_live_execution(inputs)
    vendor_connection_requested = _requested_vendor_connection(inputs) or requested_live_crm or requested_external_quote
    requested_vendor_id = _vendor_id(inputs)
    unknown_vendor = bool(requested_vendor_id and requested_vendor_id not in _INTERNAL_ONLY_VENDOR_IDS)
    offer_state = offer_recommendation.get("offer_recommendation_state")
    saleability_status = saleable_opportunity.get("saleability_status")
    provider_suspended = bool(provider_readiness.get("provider_adapter_suspended", False))

    approval_missing = approval_state not in {"APPROVED", "NOT_REQUIRED"}
    if requested_external_quote or requested_live_crm or requested_live_execution:
        approval_missing = approval_state != "APPROVED"

    owner_action_state = _owner_action_state(
        saleability_status=saleability_status,
        offer_state=offer_state,
        requested_external_quote=requested_external_quote,
        requested_live_crm=requested_live_crm,
    )
    quote_surface_state = _quote_surface_state(
        offer_state=offer_state,
        requested_external_quote=requested_external_quote,
    )
    vendor_state = "BLOCKED" if unknown_vendor or vendor_connection_requested else "READY"
    if provider_suspended:
        owner_action_state = "BLOCKED"
        quote_surface_state = "BLOCKED"
        vendor_state = "BLOCKED"

    blocked_reasons: list[Any] = [
        "internal_governed_owner_operated_workbench_only",
        "crm_runtime_enabled=false",
        "external_quote_enabled=false",
        "live_execution_enabled=false",
        "real_external_quote_sent=false",
        "customer_facing_quote_not_generated",
        "customer_visible_delivery_package_not_generated",
        "real_crm_receipt_not_generated",
        "vendor_adapter_connection_disabled",
        "blocked_live_policy",
    ]
    blocked_reasons.extend(provider_readiness.get("blocked_reasons", []))
    if requested_live_execution:
        blocked_reasons.append("live_execution_requested_but_blocked")
    if requested_live_crm:
        blocked_reasons.append("live_crm_request_blocked")
    if requested_external_quote:
        blocked_reasons.append("external_quote_request_blocked")
    if vendor_connection_requested:
        blocked_reasons.append("vendor_connection_enabled=false")
    if unknown_vendor:
        blocked_reasons.append("crm_vendor_not_in_registry")
    if approval_missing:
        blocked_reasons.append(f"approval_state={approval_state}")
    if audit_state == "MISSING":
        blocked_reasons.append("audit_ref_missing")
    if saleability_status != "QUALIFIED":
        blocked_reasons.append(f"saleable_opportunity.saleability_status={saleability_status}")
    if offer_state != "APPROVED":
        blocked_reasons.append(f"offer_recommendation.offer_recommendation_state={offer_state}")

    carrier = {
        "opportunity_id": opportunity_id,
        "project_id": project_id,
        "crm_action_id": crm_action_id,
        "quote_draft_id": quote_draft_id,
        "owner_action_state": owner_action_state,
        "approval_state": approval_state,
        "audit_state": audit_state,
        "vendor_adapter_state": {
            "state": vendor_state,
            "crm_vendor_id_optional": requested_vendor_id or None,
            "resolved_from": "EXPLICIT_UNKNOWN_VENDOR" if unknown_vendor else "INTERNAL_MANUAL_CARRIER_DEFAULT",
            "adapter_boundary": "INTERNAL_OWNER_OPERATED_CARRIER_ONLY",
            "vendor_connection_enabled": False,
            "direct_vendor_call_enabled": False,
            "external_vendor_connection_enabled": False,
            "real_vendor_call_enabled": False,
            "real_vendor_receipt_allowed": False,
            "provider_adapter_family": "crm_quote",
            "provider_id": provider_readiness.get("provider_id"),
            "provider_mode": provider_readiness.get("mode"),
            "provider_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
            "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
            "provider_adapter_suspended": provider_suspended,
            "provider_circuit_breaker_state": dict(
                provider_readiness.get("provider_circuit_breaker", {})
            ).get("state"),
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
        },
        "quote_surface_state": quote_surface_state,
        "dry_run_state": "INTERNAL_DRY_RUN_CARRIER_ONLY",
        "live_execution_enabled": False,
        "real_external_quote_sent": False,
        "real_crm_receipt_generated": False,
        "customer_visible_quote_generated": False,
        "customer_visible_delivery_package_generated": False,
        "blocked_reasons": _clean_list(blocked_reasons),
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: dict(provider_adapter_readiness_summary or {}),
        "provider_adapter_readiness": provider_readiness,
        "provider_adapter_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
        "provider_adapter_mode": provider_readiness.get("mode"),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": provider_suspended,
        "provider_circuit_breaker_state": dict(provider_readiness.get("provider_circuit_breaker", {})).get("state"),
        "provider_failure_taxonomy": dict(provider_readiness.get("provider_failure_taxonomy", {})),
        "provider_status_readback": dict(provider_readiness.get("provider_status_readback", {})),
        "governed_execution_mode": governed_metadata["governed_execution_mode"],
        "readiness_only": True,
        "draft_only": True,
        "blocked_live": True,
        "crm_action": {
            "intent": "OWNER_OPERATED_INTERNAL_ACTION_DRAFT",
            "crm_receipt_id_optional": None,
            "real_crm_receipt_generated": False,
            "allowed_scope": "internal_action_intent_and_readiness_only",
        },
        "quote_draft": {
            "quote_draft_id": quote_draft_id,
            "offer_recommendation_id": offer_id,
            "recommended_quote_band": offer_recommendation.get("recommended_quote_band"),
            "state": quote_surface_state,
            "customer_visible_quote_sent": False,
            "customer_visible_delivery_package_generated": False,
            "allowed_scope": "internal_draft_review_blocked_live_only",
        },
        "approval_readiness_summary": {
            "state": "MISSING_OR_PENDING" if approval_missing else "SATISFIED_FOR_INTERNAL_DRAFT",
            "approval_state": approval_state,
            "approval_required_before_live": True,
            "ready_for_live_execution": False,
        },
        "audit_readiness_summary": {
            "state": audit_state,
            "required_audit_refs": list(_AUDIT_REF_FIELDS),
            "missing_audit_refs": list(missing_audit_refs),
            "ready_for_live_execution": False,
        },
        "source_object_refs": {
            "sales_lead": {"object_id": lead_id, "lead_status": sales_lead.get("lead_status")},
            "saleable_opportunity": {
                "object_id": opportunity_id,
                "saleability_status": saleability_status,
            },
            "offer_recommendation": {
                "object_id": offer_id,
                "offer_recommendation_state": offer_state,
            },
        },
        "requested_live_execution": requested_live_execution,
        "requested_live_crm": requested_live_crm,
        "requested_external_quote": requested_external_quote,
        "created_at": now,
    }
    carrier["readiness_summary"] = build_crm_quote_workbench_readiness_summary(carrier)
    return carrier


__all__ = [
    "CRM_ACTION_ID_INPUT_KEY",
    "CRM_QUOTE_WORKBENCH_INPUT_KEY",
    "CRM_QUOTE_WORKBENCH_OBJECT_TYPE",
    "CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY",
    "QUOTE_DRAFT_ID_INPUT_KEY",
    "build_crm_quote_workbench_carrier",
    "build_crm_quote_workbench_readiness_summary",
]
