from __future__ import annotations

from typing import Any, Mapping

from shared.utils import ensure_list
from stage7_sales.runtime import build_stage7_crm_quote_governed_metadata, dedupe_strings


STAGE7_CRM_QUOTE_REQUIRED_APPROVALS = [
    "internal_review_release",
    "client_report_release",
    "external_action_release",
]
STAGE7_CRM_QUOTE_REQUIRED_AUDIT_REFS = [
    "project_fact_audit_ref",
    "candidate_projection_audit_ref",
    "approval_chain_audit_ref",
    "trace_bundle_ref",
]


def build_stage7_restriction_reasons(
    *,
    saleability_status_seed: str,
    sale_gate_status: str,
    report_status: str,
    linked_review_request_id_optional: str | None,
    missing_condition_family_optional: str | None,
    offer_recommendation_state: Any,
) -> list[str]:
    reasons: list[str] = []
    if saleability_status_seed == "RESTRICTED":
        reasons.append("h06_saleability_status=RESTRICTED")
    if sale_gate_status in ("REVIEW", "HOLD", "BLOCK"):
        reasons.append(f"sale_gate_status={sale_gate_status}")
    if report_status not in ("READY", "ISSUED"):
        reasons.append(f"report_status={report_status}")
    if report_status == "READY":
        reasons.append("report_status=READY")
    if linked_review_request_id_optional:
        reasons.append(f"linked_review_request_id={linked_review_request_id_optional}")
    if missing_condition_family_optional:
        reasons.append(f"missing_condition_family={missing_condition_family_optional}")
    if offer_recommendation_state == "REVIEW_REQUIRED":
        reasons.append("offer_recommendation_state=REVIEW_REQUIRED")
    return reasons


def build_opportunity_blocking_reasons(
    *,
    inputs: Mapping[str, Any],
    runtime_state: Any,
    saleability_status: str,
    stage7_restriction_reasons: list[str],
) -> list[str]:
    blocking_reasons = ensure_list(inputs.get("blocking_reasons"))
    if saleability_status != "QUALIFIED":
        blocking_reasons.extend(
            ensure_list(runtime_state.resolve("offer_blocking_reasons_optional", ["stage7_review_required"]))
        )
        blocking_reasons.extend(stage7_restriction_reasons)
    return dedupe_strings(blocking_reasons)


def build_opportunity_policy_trace(
    runtime_state: Any,
    *,
    saleable_opportunity: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "opportunity_policy_trace": runtime_state.resolve("opportunity_policy_trace"),
        "why_recommended_template_id": runtime_state.resolve("why_recommended_template_id"),
        "why_recommended_rule_outputs": runtime_state.resolve("why_recommended_rule_outputs"),
        "expected_close_days_band": saleable_opportunity.get("expected_close_days_band"),
        "expected_delivery_cost_band": saleable_opportunity.get("expected_delivery_cost_band"),
        "why_recommended": offer_recommendation.get("why_recommended"),
    }


def build_crm_quote_prerequisite_readiness_carrier(
    *,
    sales_lead: Mapping[str, Any],
    saleable_opportunity: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
    stage7_resolution_trace: Mapping[str, Any],
) -> dict[str, Any]:
    governed_metadata = build_stage7_crm_quote_governed_metadata()
    source_trace_refs = [
        "stage7_resolution_trace.review_gate_report_constraints",
        "stage7_resolution_trace.opportunity_policy",
        "stage7_resolution_trace.price_resolution",
        "stage7_resolution_trace.formal_sink_projection",
    ]
    source_object_refs = {
        "sales_lead": {
            "object_id": sales_lead.get("lead_id"),
            "lead_status": sales_lead.get("lead_status"),
        },
        "saleable_opportunity": {
            "object_id": saleable_opportunity.get("opportunity_id"),
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "crm_owner_state": saleable_opportunity.get("crm_owner_state"),
        },
        "offer_recommendation": {
            "object_id": offer_recommendation.get("offer_recommendation_id"),
            "offer_recommendation_state": offer_recommendation.get("offer_recommendation_state"),
            "recommended_quote_band": offer_recommendation.get("recommended_quote_band"),
        },
        "stage7_resolution_trace": {
            "review_gate_report_constraints_present": bool(
                stage7_resolution_trace.get("review_gate_report_constraints")
            ),
            "opportunity_policy_present": bool(stage7_resolution_trace.get("opportunity_policy")),
            "price_resolution_present": bool(stage7_resolution_trace.get("price_resolution")),
            "formal_sink_projection_present": bool(stage7_resolution_trace.get("formal_sink_projection")),
            "source_trace_refs": source_trace_refs,
        },
    }
    internal_readback_ready = all(
        (
            source_object_refs["sales_lead"]["object_id"],
            source_object_refs["saleable_opportunity"]["object_id"],
            source_object_refs["offer_recommendation"]["object_id"],
            source_object_refs["stage7_resolution_trace"]["opportunity_policy_present"],
            source_object_refs["stage7_resolution_trace"]["price_resolution_present"],
        )
    )
    blocked_reasons = [
        "crm_runtime_enabled=false",
        "external_quote_enabled=false",
        "external_delivery_enabled=false",
        "customer_facing_quote_not_generated",
        "external_or_live_capability_reserved_not_live",
        "approval_and_audit_chain_required_before_external_or_live",
    ]
    crm_owner_state = saleable_opportunity.get("crm_owner_state")
    if crm_owner_state != "ASSIGNED":
        blocked_reasons.append(f"saleable_opportunity.crm_owner_state={crm_owner_state}")
    saleability_status = saleable_opportunity.get("saleability_status")
    if saleability_status != "QUALIFIED":
        blocked_reasons.append(f"saleable_opportunity.saleability_status={saleability_status}")
    offer_state = offer_recommendation.get("offer_recommendation_state")
    if offer_state != "APPROVED":
        blocked_reasons.append(f"offer_recommendation.offer_recommendation_state={offer_state}")

    return {
        "crm_prerequisite_state": "RESERVED_NOT_LIVE" if source_object_refs["saleable_opportunity"]["object_id"] else "BLOCKED_BY_GOVERNANCE",
        "quote_prerequisite_state": "RESERVED_NOT_LIVE" if source_object_refs["offer_recommendation"]["recommended_quote_band"] else "BLOCKED_BY_GOVERNANCE",
        "governed_execution_mode": governed_metadata["governed_execution_mode"],
        "readiness_only": governed_metadata["readiness_only"],
        "prerequisite_only": governed_metadata["prerequisite_only"],
        "crm_runtime_enabled": governed_metadata["crm_runtime_enabled"],
        "external_quote_enabled": governed_metadata["external_quote_enabled"],
        "external_delivery_enabled": governed_metadata["external_delivery_enabled"],
        "source_object_refs": source_object_refs,
        "blocked_reasons": dedupe_strings(blocked_reasons),
        "required_approvals": list(STAGE7_CRM_QUOTE_REQUIRED_APPROVALS),
        "required_audit_refs": list(STAGE7_CRM_QUOTE_REQUIRED_AUDIT_REFS),
        "governed_metadata": governed_metadata,
        "audit_readiness_summary": {
            "readback_trace_present": bool(stage7_resolution_trace),
            "crm_runtime_audit_ready": False,
            "external_quote_audit_ready": False,
            "external_delivery_audit_ready": False,
            "required_audit_refs": list(STAGE7_CRM_QUOTE_REQUIRED_AUDIT_REFS),
            "missing_audit_refs": list(STAGE7_CRM_QUOTE_REQUIRED_AUDIT_REFS),
            "source_trace_refs": source_trace_refs,
        },
        "operator_readback_summary": {
            "readback_ready": internal_readback_ready,
            "readback_surface": "opportunity_pool",
            "operator_can_read_prerequisites": True,
            "operator_can_enable_crm_runtime": False,
            "operator_can_generate_external_quote": False,
            "operator_can_deliver_external": False,
            "source_formal_object_types": [
                "sales_lead",
                "saleable_opportunity",
                "offer_recommendation",
            ],
        },
    }
