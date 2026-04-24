from __future__ import annotations

from typing import Any, Mapping

from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_readiness_for_family,
)
from shared.utils import build_id, ensure_list
from stage7_sales.runtime import dedupe_strings


LEADPACK_DELIVERY_PACKAGE_OBJECT_TYPE = "stage7_leadpack_delivery_package"
LEADPACK_DELIVERY_PACKAGE_INPUT_KEY = "leadpack_delivery_package"
LEADPACK_DELIVERY_READINESS_INPUT_KEY = "leadpack_delivery_readiness_summary"
LEADPACK_PACKAGE_ID_INPUT_KEY = "leadpack_package_id_optional"
LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY = "leadpack_evidence_pack_id_optional"
LEADPACK_PAGE_DRAFT_ID_INPUT_KEY = "leadpack_page_draft_id_optional"
LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY = "leadpack_artifact_manifest_id_optional"

_EMPTY_VALUES = {None, "", "UNKNOWN", "None"}
_REQUIRED_APPROVALS = [
    "internal_review_release",
    "client_report_release",
    "external_action_release",
]
_REQUIRED_REVIEW_GATES = [
    "leadpack_candidate_review_gate",
    "leadpack_activation_prep_review_gate",
]
_REQUIRED_AUDIT_REFS = [
    "project_fact_audit_ref",
    "candidate_projection_audit_ref",
    "approval_chain_audit_ref",
    "trace_bundle_ref",
]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "live"}
    return bool(value)


def _clean_list(values: list[Any]) -> list[str]:
    return dedupe_strings([value for value in values if value not in _EMPTY_VALUES])


def _approval_state(inputs: Mapping[str, Any]) -> tuple[str, list[str]]:
    approval_state = str(inputs.get("approval_state", "") or "").strip()
    if approval_state == "APPROVED":
        return "APPROVED", []
    return "MISSING_OR_PENDING", list(_REQUIRED_APPROVALS)


def _audit_state(inputs: Mapping[str, Any], stage7_resolution_trace: Mapping[str, Any]) -> tuple[str, list[str]]:
    present_refs = {
        field_name
        for field_name in _REQUIRED_AUDIT_REFS
        if inputs.get(field_name) not in _EMPTY_VALUES
    }
    if stage7_resolution_trace:
        present_refs.add("trace_bundle_ref")
    missing_refs = [field_name for field_name in _REQUIRED_AUDIT_REFS if field_name not in present_refs]
    return ("MISSING" if missing_refs else "PRESENT"), missing_refs


def _package_state(*, approval_state: str, audit_state: str, saleability_status: Any, offer_state: Any) -> str:
    if saleability_status == "BLOCKED" or offer_state == "BLOCKED":
        return "PACKET_HELD"
    if approval_state != "APPROVED" or audit_state != "PRESENT":
        return "PACKET_HELD"
    if saleability_status != "QUALIFIED" or offer_state != "APPROVED":
        return "PACKET_HELD"
    return "PACKET_READY_FOR_REVIEW"


def _delivery_state(*, package_state: str) -> str:
    if package_state == "PACKET_READY_FOR_REVIEW":
        return "DELIVERY_REVIEW_REQUIRED"
    return "DELIVERY_BLOCKED"


def _source_object_ref(object_type: str, object_id: Any, state_key: str, state_value: Any) -> dict[str, Any]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        state_key: state_value,
    }


def _evidence_item(
    *,
    item_id: str,
    source_object: str,
    source_id: Any,
    state: Any,
    source_refs: list[str],
    masking_policy: str,
) -> dict[str, Any]:
    present = source_id not in _EMPTY_VALUES
    return {
        "item_id": item_id,
        "source_object": source_object,
        "source_id": source_id,
        "source_state": state,
        "present": present,
        "manifest_state": "READY" if present else "HELD",
        "source_refs": source_refs,
        "masking_policy": masking_policy,
    }


def build_leadpack_delivery_readiness_summary(carrier: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(carrier.get("blocked_reasons")))
    provider_readiness = dict(carrier.get("provider_adapter_readiness", {}))
    return {
        "package_id": carrier.get("package_id"),
        "opportunity_id": carrier.get("opportunity_id"),
        "evidence_pack_id": carrier.get("evidence_pack_id"),
        "page_draft_id": carrier.get("page_draft_id"),
        "artifact_manifest_id": carrier.get("artifact_manifest_id"),
        "masking_state": carrier.get("masking_state"),
        "approval_state": carrier.get("approval_state"),
        "audit_state": carrier.get("audit_state"),
        "package_state": carrier.get("package_state"),
        "page_state": carrier.get("page_state"),
        "delivery_state": carrier.get("delivery_state"),
        "readback_ready": bool(
            carrier.get("package_id")
            and carrier.get("evidence_pack_id")
            and carrier.get("page_draft_id")
            and carrier.get("artifact_manifest_id")
        ),
        "delivery_ready": False,
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "blocked_reason_count": len(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "provider_adapter_config_source": carrier.get("provider_adapter_config_source"),
        "provider_adapter_mode": carrier.get("provider_adapter_mode"),
        "provider_adapter_readback_only": bool(provider_readiness.get("readback_only", True)),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
    }


def build_leadpack_delivery_package_carrier(
    *,
    sales_lead: Mapping[str, Any],
    saleable_opportunity: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
    buyer_fit: Mapping[str, Any],
    legal_action_actor_profile: Mapping[str, Any],
    procurement_decision_actor_profile: Mapping[str, Any],
    inputs: Mapping[str, Any],
    stage7_resolution_trace: Mapping[str, Any],
    now: str,
    provider_adapter_readiness_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider_readiness = provider_readiness_for_family(
        provider_adapter_readiness_summary,
        "leadpack_page_delivery",
    )
    opportunity_id = str(saleable_opportunity.get("opportunity_id") or "")
    project_id = str(saleable_opportunity.get("project_id") or "")
    package_id = build_id("LPKG", project_id, opportunity_id)
    evidence_pack_id = build_id("EPACK", project_id, opportunity_id)
    page_draft_id = build_id("LPAGE", project_id, opportunity_id)
    artifact_manifest_id = build_id("LPMAN", project_id, opportunity_id)
    saleability_status = saleable_opportunity.get("saleability_status")
    offer_state = offer_recommendation.get("offer_recommendation_state")
    approval_state, missing_approvals = _approval_state(inputs)
    audit_state, missing_audit_refs = _audit_state(inputs, stage7_resolution_trace)
    masking_state = "MASKING_REQUIRED"
    package_state = _package_state(
        approval_state=approval_state,
        audit_state=audit_state,
        saleability_status=saleability_status,
        offer_state=offer_state,
    )
    page_state = "PAGE_DRAFT_ONLY"
    delivery_state = _delivery_state(package_state=package_state)

    evidence_items = [
        _evidence_item(
            item_id="saleable_opportunity_snapshot",
            source_object="saleable_opportunity",
            source_id=opportunity_id,
            state=saleability_status,
            source_refs=["stage7.saleable_opportunity"],
            masking_policy="allowed_projection",
        ),
        _evidence_item(
            item_id="offer_recommendation_snapshot",
            source_object="offer_recommendation",
            source_id=offer_recommendation.get("offer_recommendation_id"),
            state=offer_state,
            source_refs=["stage7.offer_recommendation"],
            masking_policy="allowed_projection",
        ),
        _evidence_item(
            item_id="buyer_fit_summary",
            source_object="buyer_fit",
            source_id=buyer_fit.get("buyer_fit_id"),
            state=buyer_fit.get("buyer_type"),
            source_refs=["stage7.buyer_fit"],
            masking_policy="summary_only",
        ),
        _evidence_item(
            item_id="actor_reachability_summary",
            source_object="stage7_actor_profiles",
            source_id=procurement_decision_actor_profile.get("actor_id"),
            state=procurement_decision_actor_profile.get("reachable_state"),
            source_refs=[
                "stage7.legal_action_actor_profile",
                "stage7.procurement_decision_actor_profile",
            ],
            masking_policy="masked_projection",
        ),
        _evidence_item(
            item_id="crm_quote_workbench_snapshot",
            source_object="crm_quote_workbench",
            source_id=inputs.get("crm_action_id_optional"),
            state=inputs.get("quote_draft_id_optional"),
            source_refs=["stage7.crm_quote_workbench"],
            masking_policy="internal_summary_only",
        ),
        _evidence_item(
            item_id="stage7_resolution_trace_snapshot",
            source_object="stage7_resolution_trace",
            source_id=stage7_resolution_trace.get("multi_competitor_collection", {}).get(
                "multi_competitor_collection_id"
            ),
            state="TRACE_PRESENT" if stage7_resolution_trace else "TRACE_MISSING",
            source_refs=[
                "stage7_resolution_trace.review_gate_report_constraints",
                "stage7_resolution_trace.opportunity_policy",
                "stage7_resolution_trace.price_resolution",
                "stage7_resolution_trace.formal_sink_projection",
            ],
            masking_policy="internal_trace_summary",
        ),
    ]
    evidence_item_manifest = {
        "manifest_id": f"{artifact_manifest_id}-EVIDENCE",
        "evidence_pack_id": evidence_pack_id,
        "item_count": len(evidence_items),
        "ready_count": sum(1 for item in evidence_items if item["manifest_state"] == "READY"),
        "held_count": sum(1 for item in evidence_items if item["manifest_state"] != "READY"),
        "items": evidence_items,
    }
    field_masking_summary = {
        "masking_state": masking_state,
        "masking_required": True,
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "allowed_projection_items": [
            item["item_id"] for item in evidence_items if item["masking_policy"] == "allowed_projection"
        ],
        "masked_projection_items": [
            item["item_id"] for item in evidence_items if item["masking_policy"] == "masked_projection"
        ],
        "summary_only_items": [
            item["item_id"]
            for item in evidence_items
            if item["masking_policy"] in {"summary_only", "internal_summary_only", "internal_trace_summary"}
        ],
        "forbidden_direct_export_families": [
            "outreach_plan",
            "payment_record",
            "delivery_record",
            "governance_feedback_event",
        ],
        "policy_summary": [
            "customer_visible_export_enabled=false",
            "page_publication_enabled=false",
            "direct_stage8_stage9_object_export_blocked",
            "high_restriction_fields_masked_or_summary_only",
        ],
    }
    operator_review_summary = {
        "manual_review_required": True,
        "review_state": "REVIEW_REQUIRED",
        "required_review_gates": list(_REQUIRED_REVIEW_GATES),
        "missing_review_gates": list(_REQUIRED_REVIEW_GATES),
        "operator_can_review_internal_package": True,
        "operator_can_publish_customer_page": False,
        "operator_can_deliver_external": False,
    }
    approval_audit_prerequisites = {
        "required_approvals": list(_REQUIRED_APPROVALS),
        "missing_approvals": missing_approvals,
        "approval_state": approval_state,
        "required_review_gates": list(_REQUIRED_REVIEW_GATES),
        "missing_review_gates": list(_REQUIRED_REVIEW_GATES),
        "required_audit_refs": list(_REQUIRED_AUDIT_REFS),
        "missing_audit_refs": missing_audit_refs,
        "audit_state": audit_state,
    }
    delivery_readiness_summary = {
        "delivery_ready": False,
        "package_state": package_state,
        "page_state": page_state,
        "delivery_state": delivery_state,
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "external_release_enabled": False,
        "page_publication_enabled": False,
        "blocked_by_default": True,
        "missing_approvals": missing_approvals,
        "missing_audit_refs": missing_audit_refs,
        "missing_review_gates": list(_REQUIRED_REVIEW_GATES),
    }
    blocked_reasons = [
        "owner_operated_internal_package_workbench_only",
        "customer_visible_enabled=false",
        "external_delivery_enabled=false",
        "external_release_enabled=false",
        "page_publication_enabled=false",
        "approval_and_audit_chain_required_before_external_delivery",
        "manual_review_required_before_customer_visible_page",
    ]
    blocked_reasons.extend(provider_readiness.get("blocked_reasons", []))
    if _truthy(inputs.get("customer_visible_enabled")) or _truthy(inputs.get("customer_visible_export_enabled")):
        blocked_reasons.append("customer_visible_request_blocked")
    if _truthy(inputs.get("external_delivery_enabled")) or _truthy(inputs.get("direct_export_enabled")):
        blocked_reasons.append("external_delivery_or_direct_export_request_blocked")
    if _truthy(inputs.get("page_publication_enabled")) or _truthy(inputs.get("client_page_release_enabled")):
        blocked_reasons.append("page_publication_request_blocked")
    if _truthy(inputs.get("external_release_enabled")) or _truthy(inputs.get("live_execution_enabled")):
        blocked_reasons.append("external_or_live_request_blocked")
    blocked_reasons.extend(f"missing_approval:{item}" for item in missing_approvals)
    blocked_reasons.extend(f"missing_audit_ref:{item}" for item in missing_audit_refs)
    if saleability_status != "QUALIFIED":
        blocked_reasons.append(f"saleable_opportunity.saleability_status={saleability_status}")
    if offer_state != "APPROVED":
        blocked_reasons.append(f"offer_recommendation.offer_recommendation_state={offer_state}")

    source_object_refs = {
        "sales_lead": _source_object_ref("sales_lead", sales_lead.get("lead_id"), "lead_status", sales_lead.get("lead_status")),
        "saleable_opportunity": _source_object_ref(
            "saleable_opportunity",
            opportunity_id,
            "saleability_status",
            saleability_status,
        ),
        "offer_recommendation": _source_object_ref(
            "offer_recommendation",
            offer_recommendation.get("offer_recommendation_id"),
            "offer_recommendation_state",
            offer_state,
        ),
        "buyer_fit": _source_object_ref("buyer_fit", buyer_fit.get("buyer_fit_id"), "buyer_type", buyer_fit.get("buyer_type")),
        "legal_action_actor_profile": _source_object_ref(
            "legal_action_actor_profile",
            legal_action_actor_profile.get("actor_id"),
            "actionability_state",
            legal_action_actor_profile.get("actionability_state"),
        ),
        "procurement_decision_actor_profile": _source_object_ref(
            "procurement_decision_actor_profile",
            procurement_decision_actor_profile.get("actor_id"),
            "reachable_state",
            procurement_decision_actor_profile.get("reachable_state"),
        ),
    }
    page_draft = {
        "page_draft_id": page_draft_id,
        "package_id": package_id,
        "page_state": page_state,
        "draft_only": True,
        "customer_visible_enabled": False,
        "page_publication_enabled": False,
        "public_url": None,
        "draft_sections": [
            "opportunity_summary",
            "offer_summary",
            "buyer_fit_summary",
            "masked_actor_summary",
            "evidence_manifest",
            "delivery_readiness",
        ],
    }
    package_manifest = {
        "package_manifest_id": artifact_manifest_id,
        "package_id": package_id,
        "evidence_pack_id": evidence_pack_id,
        "evidence_items": evidence_items,
        "source_refs": {
            "source_object_refs": source_object_refs,
            "trace_refs": [
                "stage7_resolution_trace",
                "crm_quote_workbench",
                "leadpack_delivery_package",
            ],
        },
        "masking_field_policy_summary": field_masking_summary,
        "operator_review_summary": operator_review_summary,
        "delivery_readiness_summary": delivery_readiness_summary,
    }
    carrier = {
        "package_id": package_id,
        "opportunity_id": opportunity_id,
        "project_id": project_id,
        "evidence_pack_id": evidence_pack_id,
        "page_draft_id": page_draft_id,
        "artifact_manifest_id": artifact_manifest_id,
        "masking_state": masking_state,
        "approval_state": approval_state,
        "audit_state": audit_state,
        "package_state": package_state,
        "page_state": page_state,
        "delivery_state": delivery_state,
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "external_release_enabled": False,
        "page_publication_enabled": False,
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: dict(provider_adapter_readiness_summary or {}),
        "provider_adapter_readiness": provider_readiness,
        "provider_adapter_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
        "provider_adapter_mode": provider_readiness.get("mode"),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "package_manifest": package_manifest,
        "evidence_item_manifest": evidence_item_manifest,
        "field_masking_summary": field_masking_summary,
        "page_draft": page_draft,
        "approval_audit_prerequisites": approval_audit_prerequisites,
        "customer_visible_control_state": {
            "customer_visible_enabled": False,
            "customer_page_publication_enabled": False,
            "customer_visible_export_enabled": False,
            "client_page_release_enabled": False,
            "control_state": "BLOCKED_BY_DEFAULT",
        },
        "delivery_readiness_summary": delivery_readiness_summary,
        "artifact_manifest": {
            "artifact_manifest_id": artifact_manifest_id,
            "artifact_generation_enabled": False,
            "artifacts": [
                {"artifact_id": evidence_pack_id, "artifact_type": "evidence_pack_manifest", "state": "DRAFT"},
                {"artifact_id": page_draft_id, "artifact_type": "page_draft", "state": page_state},
                {"artifact_id": artifact_manifest_id, "artifact_type": "package_manifest", "state": package_state},
            ],
        },
        "source_object_refs": source_object_refs,
        "blocked_reasons": _clean_list(blocked_reasons),
        "created_at": now,
    }
    carrier["readiness_summary"] = build_leadpack_delivery_readiness_summary(carrier)
    return carrier


def leadpack_delivery_package_summary(carrier: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "package_id": carrier.get("package_id"),
        "opportunity_id": carrier.get("opportunity_id"),
        "evidence_pack_id": carrier.get("evidence_pack_id"),
        "page_draft_id": carrier.get("page_draft_id"),
        "artifact_manifest_id": carrier.get("artifact_manifest_id"),
        "masking_state": carrier.get("masking_state"),
        "approval_state": carrier.get("approval_state"),
        "audit_state": carrier.get("audit_state"),
        "package_state": carrier.get("package_state"),
        "page_state": carrier.get("page_state"),
        "delivery_state": carrier.get("delivery_state"),
        "customer_visible_enabled": False,
        "external_delivery_enabled": False,
        "delivery_ready": False,
    }


__all__ = [
    "LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY",
    "LEADPACK_DELIVERY_PACKAGE_INPUT_KEY",
    "LEADPACK_DELIVERY_PACKAGE_OBJECT_TYPE",
    "LEADPACK_DELIVERY_READINESS_INPUT_KEY",
    "LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY",
    "LEADPACK_PACKAGE_ID_INPUT_KEY",
    "LEADPACK_PAGE_DRAFT_ID_INPUT_KEY",
    "build_leadpack_delivery_package_carrier",
    "build_leadpack_delivery_readiness_summary",
    "leadpack_delivery_package_summary",
]
