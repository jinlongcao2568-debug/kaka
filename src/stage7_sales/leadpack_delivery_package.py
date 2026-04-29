from __future__ import annotations

import hashlib
import json
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
_CUSTOMER_VISIBLE_FIELD_ALLOWLIST = [
    "opportunity_id",
    "saleability_status",
    "opportunity_grade",
    "recommended_sku",
    "offer_recommendation_state",
    "sku_code",
    "recommended_delivery_form",
    "recommended_quote_band",
    "buyer_type",
    "fit_score",
    "fit_reason_tags",
]
_CUSTOMER_VISIBLE_FIELD_BLACKLIST = [
    "policy_trace",
    "semantic_trace",
    "governance_trace",
    "internal_score_raw",
    "outreach_plan",
    "payment_record",
    "delivery_record",
    "governance_feedback_event",
    "provider_credential",
]
_APPROVED_ACCESS_STATES = {
    "APPROVED",
    "AUTHORIZED",
    "AUTH_GRANTED",
    "GRANTED",
    "PRESENT",
    "PASSED",
    "VALID",
}
_APPROVED_EXTERNAL_VISIBILITY_STATES = {
    "APPROVED",
    "CLIENT_VISIBLE_APPROVED",
    "CUSTOMER_VISIBLE_APPROVED",
    "PUBLIC_APPROVED",
    "EXTERNAL_VISIBLE_APPROVED",
}
_APPROVED_REVIEW_GATE_STATES = {
    "APPROVED",
    "PASSED",
    "CLOSED_APPROVED",
    "REVIEWED",
}


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


def _input_state(inputs: Mapping[str, Any], keys: list[str], *, default: str = "MISSING") -> str:
    for key in keys:
        value = inputs.get(key)
        if value not in _EMPTY_VALUES:
            return str(value).strip()
    return default


def _approved_state(value: str, allowed: set[str]) -> bool:
    return str(value or "").strip().upper() in allowed


def _approved_unlock_requested(inputs: Mapping[str, Any]) -> bool:
    return any(
        _truthy(inputs.get(key))
        for key in (
            "approved_customer_visible_unlock_requested",
            "approved_customer_artifact_access_requested",
            "approved_customer_page_publication_requested",
            "approved_export_artifact_generation_requested",
            "approved_customer_download_requested",
            "customer_visible_export_enabled",
            "client_page_release_enabled",
            "export_artifact_generation_enabled",
            "page_publication_enabled",
            "customer_download_requested",
            "download_requested",
        )
    )


def _approved_customer_visible_unlock_summary(
    *,
    inputs: Mapping[str, Any],
    approval_state: str,
    audit_state: str,
    missing_approvals: list[str],
    missing_audit_refs: list[str],
    provider_suspended: bool,
) -> dict[str, Any]:
    unlock_requested = _approved_unlock_requested(inputs)
    customer_account_access_state = _input_state(
        inputs,
        [
            "customer_account_access_state",
            "customer_access_state",
            "account_access_control_state",
        ],
    )
    customer_artifact_access_state = _input_state(
        inputs,
        [
            "customer_artifact_access_approval_state",
            "customer_artifact_access_state",
            "customer_visible_access_state",
        ],
    )
    download_auth_state = _input_state(
        inputs,
        [
            "customer_download_auth_state",
            "download_auth_state",
            "customer_artifact_download_auth_state",
        ],
    )
    external_visibility_state = _input_state(
        inputs,
        [
            "customer_external_visibility_state",
            "external_visibility_state",
            "client_visible_release_state",
        ],
    )
    review_gate_states = {
        gate: _input_state(inputs, [gate, f"{gate}_state"])
        for gate in _REQUIRED_REVIEW_GATES
    }
    implementation_decision_state = _input_state(
        inputs,
        [
            "implementation_decision_state",
            "leadpack_implementation_decision_state",
            "customer_artifact_implementation_decision_state",
        ],
    )
    download_auth_audit_ref = _input_state(
        inputs,
        [
            "download_auth_audit_ref",
            "customer_download_audit_ref",
            "customer_artifact_access_audit_ref",
        ],
    )
    customer_access_audit_ref = _input_state(
        inputs,
        [
            "customer_access_audit_ref",
            "customer_artifact_access_audit_ref",
            "operator_customer_access_audit_ref",
        ],
    )
    field_policy_state = "ENFORCED"
    masking_state = "ENFORCED"
    watermark_state = "ENFORCED"
    version_hash_state = "PRESENT"

    blocking_reasons: list[str] = []
    if not unlock_requested:
        blocking_reasons.append("approved_customer_visible_unlock_not_requested")
    if approval_state != "APPROVED":
        blocking_reasons.append("approval_state_not_approved")
    blocking_reasons.extend(f"missing_approval:{item}" for item in missing_approvals)
    if audit_state != "PRESENT":
        blocking_reasons.append("audit_state_not_present")
    blocking_reasons.extend(f"missing_audit_ref:{item}" for item in missing_audit_refs)
    if not _approved_state(customer_account_access_state, _APPROVED_ACCESS_STATES):
        blocking_reasons.append("customer_account_access_not_approved")
    if not _approved_state(customer_artifact_access_state, _APPROVED_ACCESS_STATES):
        blocking_reasons.append("customer_artifact_access_not_approved")
    if not _approved_state(download_auth_state, _APPROVED_ACCESS_STATES):
        blocking_reasons.append("download_auth_not_approved")
    if download_auth_audit_ref == "MISSING":
        blocking_reasons.append("download_auth_audit_ref_missing")
    if customer_access_audit_ref == "MISSING":
        blocking_reasons.append("customer_access_audit_ref_missing")
    if not _approved_state(external_visibility_state, _APPROVED_EXTERNAL_VISIBILITY_STATES):
        blocking_reasons.append("external_visibility_not_approved")
    for gate, state in review_gate_states.items():
        if not _approved_state(state, _APPROVED_REVIEW_GATE_STATES):
            blocking_reasons.append(f"review_gate_not_approved:{gate}")
    if not _approved_state(implementation_decision_state, _APPROVED_REVIEW_GATE_STATES):
        blocking_reasons.append("implementation_decision_not_approved")
    if provider_suspended:
        blocking_reasons.append("provider_adapter_suspended_fail_closed")
    if _truthy(inputs.get("internal_blackbox_score_export_requested")) or _truthy(
        inputs.get("internal_score_raw_customer_visible_requested")
    ):
        blocking_reasons.append("internal_blackbox_score_exposure_blocked")
    if _truthy(inputs.get("unreviewed_inference_customer_visible_requested")) or _truthy(
        inputs.get("unreviewed_inference_present")
    ):
        blocking_reasons.append("unreviewed_inference_customer_visible_blocked")
    if _truthy(inputs.get("formal_legal_document_auto_send_requested")) or _truthy(
        inputs.get("legal_document_auto_send_requested")
    ):
        blocking_reasons.append("legal_document_auto_send_blocked")
    if _truthy(inputs.get("direct_stage8_stage9_object_export_requested")):
        blocking_reasons.append("direct_stage8_stage9_object_export_blocked")

    enabled = unlock_requested and not blocking_reasons
    return {
        "unlock_requested": unlock_requested,
        "approved_customer_visible_unlock_enabled": enabled,
        "unlock_state": "APPROVED_CUSTOMER_VISIBLE_READBACK" if enabled else "BLOCKED",
        "customer_account_access_state": customer_account_access_state,
        "customer_artifact_access_state": customer_artifact_access_state,
        "download_auth_state": download_auth_state,
        "download_auth_audit_ref": download_auth_audit_ref,
        "customer_access_audit_ref": customer_access_audit_ref,
        "external_visibility_state": external_visibility_state,
        "review_gate_states": review_gate_states,
        "implementation_decision_state": implementation_decision_state,
        "field_policy_state": field_policy_state,
        "masking_state": masking_state,
        "watermark_state": watermark_state,
        "version_hash_state": version_hash_state,
        "blocking_reasons": _clean_list(blocking_reasons),
        "real_provider_call_enabled": False,
        "real_customer_download_executed": False,
        "stage8_execution_triggered": False,
        "stage9_payment_delivery_triggered": False,
        "external_software_release_enabled": False,
    }


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


def _stable_version_hash(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _artifact_candidate_controls(
    *,
    project_id: str,
    opportunity_id: str,
    package_id: str,
    evidence_pack_id: str,
    page_draft_id: str,
    artifact_manifest_id: str,
    masking_state: str,
    provider_suspended: bool,
    approved_unlock_summary: Mapping[str, Any],
    inputs: Mapping[str, Any],
    now: str,
) -> dict[str, Any]:
    unlock_enabled = bool(approved_unlock_summary.get("approved_customer_visible_unlock_enabled", False))
    field_policy = {
        "field_allowlist": list(_CUSTOMER_VISIBLE_FIELD_ALLOWLIST),
        "field_blacklist": list(_CUSTOMER_VISIBLE_FIELD_BLACKLIST),
        "allowlist_enforced": True,
        "blacklist_enforced": True,
        "direct_object_export_allowed": False,
        "internal_black_box_score_exposure_allowed": False,
    }
    watermark = {
        "watermark_id": build_id("WATERMARK", project_id, opportunity_id),
        "watermark_state": "APPLIED_TO_APPROVED_ARTIFACT" if unlock_enabled else "APPLIED_TO_DRAFT",
        "watermark_text": (
            "CUSTOMER VISIBLE - APPROVED AUDITED COPY"
            if unlock_enabled
            else "INTERNAL DRAFT - NOT CUSTOMER RELEASED"
        ),
        "applies_to": ["page_draft", "export_simulation", "customer_visible_artifact"],
        "customer_removal_allowed": False,
    }
    hash_source = {
        "package_id": package_id,
        "evidence_pack_id": evidence_pack_id,
        "page_draft_id": page_draft_id,
        "artifact_manifest_id": artifact_manifest_id,
        "field_policy": field_policy,
        "masking_state": masking_state,
        "watermark_text": watermark["watermark_text"],
    }
    artifact_version_hash = _stable_version_hash(hash_source)
    download_requested = _truthy(inputs.get("download_requested")) or _truthy(
        inputs.get("customer_download_requested")
    )
    download_audit = {
        "download_audit_id": build_id("DLAUDIT", project_id, opportunity_id),
        "download_audit_state": (
            "APPROVED_DOWNLOAD_AUTH_RECORDED"
            if unlock_enabled
            else "SANDBOX_RECORDED" if download_requested else "READBACK_READY"
        ),
        "download_requested": download_requested,
        "download_enabled": unlock_enabled,
        "customer_download_enabled": unlock_enabled,
        "real_customer_download_executed": False,
        "download_auth_state": approved_unlock_summary.get("download_auth_state"),
        "download_auth_audit_ref": approved_unlock_summary.get("download_auth_audit_ref"),
        "audit_required": True,
        "audit_replayable": True,
        "created_at": now,
    }
    export_page_replay = {
        "replay_id": build_id("LPREPLAY", project_id, opportunity_id),
        "replay_state": "SUSPENDED" if provider_suspended else "REPLAY_READY",
        "page_draft_id": page_draft_id,
        "artifact_manifest_id": artifact_manifest_id,
        "artifact_version_hash": artifact_version_hash,
        "export_simulation_enabled": True,
        "customer_visible_export_enabled": unlock_enabled,
        "external_delivery_enabled": False,
        "direct_export_enabled": False,
        "page_publication_enabled": unlock_enabled,
        "customer_download_enabled": unlock_enabled,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
    }
    customer_visible_artifact_candidate = {
        "candidate_id": build_id("LPCAND", project_id, opportunity_id),
        "candidate_state": (
            "APPROVED_CUSTOMER_VISIBLE_READBACK"
            if unlock_enabled
            else "SUSPENDED" if provider_suspended else "SANDBOX_CANDIDATE_READY"
        ),
        "candidate_only": not unlock_enabled,
        "readback_only": True,
        "customer_visible_enabled": unlock_enabled,
        "customer_visible_export_enabled": unlock_enabled,
        "external_delivery_enabled": False,
        "export_artifact_generation_enabled": unlock_enabled,
        "page_publication_enabled": unlock_enabled,
        "field_policy": field_policy,
        "masking": {
            "masking_state": masking_state,
            "masking_required": True,
            "masked_before_customer_visible_release": True,
        },
        "watermark": watermark,
        "artifact_version_hash": artifact_version_hash,
        "download_audit": download_audit,
        "export_page_replay": export_page_replay,
        "approved_customer_visible_unlock_summary": dict(approved_unlock_summary),
    }
    page_export_candidate = {
        "page_candidate_id": build_id("LPPAGECAND", project_id, opportunity_id),
        "export_candidate_id": build_id("LPEXPORTCAND", project_id, opportunity_id),
        "candidate_state": customer_visible_artifact_candidate["candidate_state"],
        "page_draft_id": page_draft_id,
        "artifact_manifest_id": artifact_manifest_id,
        "artifact_version_hash": artifact_version_hash,
        "watermark_id": watermark["watermark_id"],
        "download_audit_id": download_audit["download_audit_id"],
        "replay_id": export_page_replay["replay_id"],
        "page_publication_enabled": unlock_enabled,
        "direct_export_enabled": False,
        "customer_visible_export_enabled": unlock_enabled,
        "export_artifact_generation_enabled": unlock_enabled,
        "external_delivery_enabled": False,
        "download_enabled": unlock_enabled,
        "customer_download_enabled": unlock_enabled,
        "approved_customer_visible_unlock_summary": dict(approved_unlock_summary),
    }
    return {
        "field_policy": field_policy,
        "watermark": watermark,
        "artifact_version_hash": artifact_version_hash,
        "download_audit": download_audit,
        "export_page_replay": export_page_replay,
        "customer_visible_artifact_candidate": customer_visible_artifact_candidate,
        "page_export_candidate": page_export_candidate,
    }


def build_leadpack_delivery_readiness_summary(carrier: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(carrier.get("blocked_reasons")))
    provider_readiness = dict(carrier.get("provider_adapter_readiness", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    customer_candidate = dict(carrier.get("customer_visible_artifact_candidate", {}))
    page_export_candidate = dict(carrier.get("page_export_candidate", {}))
    download_audit = dict(carrier.get("download_audit", {}))
    export_page_replay = dict(carrier.get("export_page_replay", {}))
    approved_unlock_summary = dict(carrier.get("approved_customer_visible_unlock_summary", {}))
    customer_visible_enabled = bool(carrier.get("customer_visible_enabled", False))
    export_artifact_generation_enabled = bool(
        carrier.get("export_artifact_generation_enabled", False)
    )
    page_publication_enabled = bool(carrier.get("page_publication_enabled", False))
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
        "delivery_ready": bool(carrier.get("delivery_ready", customer_visible_enabled)),
        "customer_visible_artifact_candidate_state": customer_candidate.get("candidate_state"),
        "page_export_candidate_state": page_export_candidate.get("candidate_state"),
        "artifact_version_hash": carrier.get("artifact_version_hash"),
        "field_allowlist_count": len(dict(carrier.get("field_policy", {})).get("field_allowlist", [])),
        "field_blacklist_count": len(dict(carrier.get("field_policy", {})).get("field_blacklist", [])),
        "watermark_state": dict(carrier.get("watermark", {})).get("watermark_state"),
        "download_audit_state": download_audit.get("download_audit_state"),
        "download_audit_id": download_audit.get("download_audit_id"),
        "export_page_replay_state": export_page_replay.get("replay_state"),
        "export_page_replay_id": export_page_replay.get("replay_id"),
        "page_export_replay_ready": export_page_replay.get("replay_state") == "REPLAY_READY",
        "customer_visible_enabled": customer_visible_enabled,
        "customer_visible_export_enabled": bool(
            carrier.get("customer_visible_export_enabled", customer_visible_enabled)
        ),
        "client_page_release_enabled": bool(
            carrier.get("client_page_release_enabled", customer_visible_enabled)
        ),
        "export_artifact_generation_enabled": export_artifact_generation_enabled,
        "page_publication_enabled": page_publication_enabled,
        "download_enabled": bool(download_audit.get("download_enabled", False)),
        "customer_download_enabled": bool(download_audit.get("customer_download_enabled", False)),
        "external_delivery_enabled": False,
        "external_release_enabled": False,
        "approved_customer_visible_unlock_summary": approved_unlock_summary,
        "approved_customer_visible_unlock_enabled": bool(
            approved_unlock_summary.get("approved_customer_visible_unlock_enabled", False)
        ),
        "approved_customer_visible_unlock_state": approved_unlock_summary.get("unlock_state"),
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
    provider_suspended = bool(provider_readiness.get("provider_adapter_suspended", False))
    approved_unlock_summary = _approved_customer_visible_unlock_summary(
        inputs=inputs,
        approval_state=approval_state,
        audit_state=audit_state,
        missing_approvals=missing_approvals,
        missing_audit_refs=missing_audit_refs,
        provider_suspended=provider_suspended,
    )
    approved_unlock_enabled = bool(
        approved_unlock_summary.get("approved_customer_visible_unlock_enabled", False)
    )
    if provider_suspended:
        package_state = "PACKET_HELD"
    if approved_unlock_enabled:
        package_state = "PACKET_APPROVED_CUSTOMER_VISIBLE_READBACK"
    page_state = (
        "PAGE_APPROVED_CUSTOMER_VISIBLE_READBACK"
        if approved_unlock_enabled
        else "PAGE_DRAFT_ONLY"
    )
    delivery_state = (
        "CUSTOMER_VISIBLE_DELIVERY_READBACK_READY"
        if approved_unlock_enabled
        else _delivery_state(package_state=package_state)
    )

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
        "customer_visible_enabled": approved_unlock_enabled,
        "external_delivery_enabled": False,
        "field_allowlist": list(_CUSTOMER_VISIBLE_FIELD_ALLOWLIST),
        "field_blacklist": list(_CUSTOMER_VISIBLE_FIELD_BLACKLIST),
        "allowlist_enforced": True,
        "blacklist_enforced": True,
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
            (
                "customer_visible_export_enabled=true"
                if approved_unlock_enabled
                else "customer_visible_export_enabled=false"
            ),
            (
                "page_publication_enabled=true"
                if approved_unlock_enabled
                else "page_publication_enabled=false"
            ),
            "direct_stage8_stage9_object_export_blocked",
            "high_restriction_fields_masked_or_summary_only",
        ],
    }
    operator_review_summary = {
        "manual_review_required": not approved_unlock_enabled,
        "review_state": "APPROVED" if approved_unlock_enabled else "REVIEW_REQUIRED",
        "required_review_gates": list(_REQUIRED_REVIEW_GATES),
        "missing_review_gates": [] if approved_unlock_enabled else list(_REQUIRED_REVIEW_GATES),
        "operator_can_review_internal_package": True,
        "operator_can_publish_customer_page": approved_unlock_enabled,
        "operator_can_deliver_external": False,
    }
    approval_audit_prerequisites = {
        "required_approvals": list(_REQUIRED_APPROVALS),
        "missing_approvals": missing_approvals,
        "approval_state": approval_state,
        "required_review_gates": list(_REQUIRED_REVIEW_GATES),
        "missing_review_gates": [] if approved_unlock_enabled else list(_REQUIRED_REVIEW_GATES),
        "required_audit_refs": list(_REQUIRED_AUDIT_REFS),
        "missing_audit_refs": missing_audit_refs,
        "audit_state": audit_state,
        "approved_customer_visible_unlock_summary": dict(approved_unlock_summary),
    }
    delivery_readiness_summary = {
        "delivery_ready": approved_unlock_enabled,
        "package_state": package_state,
        "page_state": page_state,
        "delivery_state": delivery_state,
        "customer_visible_enabled": approved_unlock_enabled,
        "customer_visible_export_enabled": approved_unlock_enabled,
        "client_page_release_enabled": approved_unlock_enabled,
        "export_artifact_generation_enabled": approved_unlock_enabled,
        "external_delivery_enabled": False,
        "external_release_enabled": False,
        "page_publication_enabled": approved_unlock_enabled,
        "download_enabled": approved_unlock_enabled,
        "customer_download_enabled": approved_unlock_enabled,
        "blocked_by_default": not approved_unlock_enabled,
        "approved_customer_visible_unlock_summary": dict(approved_unlock_summary),
        "missing_approvals": missing_approvals,
        "missing_audit_refs": missing_audit_refs,
        "missing_review_gates": [] if approved_unlock_enabled else list(_REQUIRED_REVIEW_GATES),
    }
    artifact_controls = _artifact_candidate_controls(
        project_id=project_id,
        opportunity_id=opportunity_id,
        package_id=package_id,
        evidence_pack_id=evidence_pack_id,
        page_draft_id=page_draft_id,
        artifact_manifest_id=artifact_manifest_id,
        masking_state=masking_state,
        provider_suspended=provider_suspended,
        approved_unlock_summary=approved_unlock_summary,
        inputs=inputs,
        now=now,
    )
    delivery_readiness_summary.update(
        {
            "customer_visible_artifact_candidate_state": artifact_controls[
                "customer_visible_artifact_candidate"
            ]["candidate_state"],
            "page_export_candidate_state": artifact_controls["page_export_candidate"]["candidate_state"],
            "artifact_version_hash": artifact_controls["artifact_version_hash"],
            "download_audit_id": artifact_controls["download_audit"]["download_audit_id"],
            "download_audit_state": artifact_controls["download_audit"]["download_audit_state"],
            "export_page_replay_id": artifact_controls["export_page_replay"]["replay_id"],
            "export_page_replay_state": artifact_controls["export_page_replay"]["replay_state"],
        }
    )
    if approved_unlock_enabled:
        blocked_reasons = [
            "external_software_release_controlled_opening_required",
            "real_provider_delivery_not_executed",
            "stage8_stage9_execution_not_triggered",
            "automated_refund_program_excluded",
        ]
    else:
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
    blocked_reasons.extend(approved_unlock_summary.get("blocking_reasons", []))
    if provider_suspended:
        blocked_reasons.append("provider_adapter_suspended_fail_closed")
    if (
        not approved_unlock_enabled
        and (
            _truthy(inputs.get("customer_visible_enabled"))
            or _truthy(inputs.get("customer_visible_export_enabled"))
        )
    ):
        blocked_reasons.append("customer_visible_request_blocked")
    if _truthy(inputs.get("external_delivery_enabled")) or _truthy(inputs.get("direct_export_enabled")):
        blocked_reasons.append("external_delivery_or_direct_export_request_blocked")
    if (
        not approved_unlock_enabled
        and (
            _truthy(inputs.get("page_publication_enabled"))
            or _truthy(inputs.get("client_page_release_enabled"))
        )
    ):
        blocked_reasons.append("page_publication_request_blocked")
    if _truthy(inputs.get("external_release_enabled")) or _truthy(inputs.get("live_execution_enabled")):
        blocked_reasons.append("external_or_live_request_blocked")
    if (
        not approved_unlock_enabled
        and (
            _truthy(inputs.get("download_requested"))
            or _truthy(inputs.get("customer_download_requested"))
        )
    ):
        blocked_reasons.append("customer_download_request_blocked")
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
        "draft_only": not approved_unlock_enabled,
        "customer_visible_enabled": approved_unlock_enabled,
        "page_publication_enabled": approved_unlock_enabled,
        "public_url": None,
        "watermark": artifact_controls["watermark"],
        "artifact_version_hash": artifact_controls["artifact_version_hash"],
        "export_page_replay": artifact_controls["export_page_replay"],
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
        "field_policy": artifact_controls["field_policy"],
        "watermark": artifact_controls["watermark"],
        "artifact_version_hash": artifact_controls["artifact_version_hash"],
        "download_audit": artifact_controls["download_audit"],
        "export_page_replay": artifact_controls["export_page_replay"],
        "customer_visible_artifact_candidate": artifact_controls["customer_visible_artifact_candidate"],
        "page_export_candidate": artifact_controls["page_export_candidate"],
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
        "delivery_ready": approved_unlock_enabled,
        "customer_visible_enabled": approved_unlock_enabled,
        "customer_visible_export_enabled": approved_unlock_enabled,
        "client_page_release_enabled": approved_unlock_enabled,
        "export_artifact_generation_enabled": approved_unlock_enabled,
        "download_enabled": approved_unlock_enabled,
        "customer_download_enabled": approved_unlock_enabled,
        "external_delivery_enabled": False,
        "external_release_enabled": False,
        "page_publication_enabled": approved_unlock_enabled,
        "approved_customer_visible_unlock_summary": dict(approved_unlock_summary),
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: dict(provider_adapter_readiness_summary or {}),
        "provider_adapter_readiness": provider_readiness,
        "provider_adapter_config_source": dict(provider_adapter_readiness_summary or {}).get("config_source"),
        "provider_adapter_mode": provider_readiness.get("mode"),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": provider_suspended,
        "provider_circuit_breaker_state": dict(provider_readiness.get("provider_circuit_breaker", {})).get("state"),
        "provider_failure_taxonomy": dict(provider_readiness.get("provider_failure_taxonomy", {})),
        "provider_status_readback": dict(provider_readiness.get("provider_status_readback", {})),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "package_manifest": package_manifest,
        "evidence_item_manifest": evidence_item_manifest,
        "field_masking_summary": field_masking_summary,
        "field_policy": artifact_controls["field_policy"],
        "watermark": artifact_controls["watermark"],
        "artifact_version_hash": artifact_controls["artifact_version_hash"],
        "download_audit": artifact_controls["download_audit"],
        "export_page_replay": artifact_controls["export_page_replay"],
        "customer_visible_artifact_candidate": artifact_controls["customer_visible_artifact_candidate"],
        "page_export_candidate": artifact_controls["page_export_candidate"],
        "page_draft": page_draft,
        "approval_audit_prerequisites": approval_audit_prerequisites,
        "customer_visible_control_state": {
            "customer_visible_enabled": approved_unlock_enabled,
            "customer_page_publication_enabled": approved_unlock_enabled,
            "customer_visible_export_enabled": approved_unlock_enabled,
            "client_page_release_enabled": approved_unlock_enabled,
            "download_enabled": approved_unlock_enabled,
            "customer_download_enabled": approved_unlock_enabled,
            "control_state": (
                "APPROVED_CUSTOMER_VISIBLE_READBACK"
                if approved_unlock_enabled
                else "CONTROLLED_OPENING_REQUIRED"
            ),
            "approved_customer_visible_unlock_summary": dict(approved_unlock_summary),
        },
        "delivery_readiness_summary": delivery_readiness_summary,
        "artifact_manifest": {
            "artifact_manifest_id": artifact_manifest_id,
            "artifact_generation_enabled": approved_unlock_enabled,
            "artifact_version_hash": artifact_controls["artifact_version_hash"],
            "watermark_id": artifact_controls["watermark"]["watermark_id"],
            "download_audit_id": artifact_controls["download_audit"]["download_audit_id"],
            "artifacts": [
                {
                    "artifact_id": evidence_pack_id,
                    "artifact_type": "evidence_pack_manifest",
                    "state": "APPROVED_READBACK" if approved_unlock_enabled else "DRAFT",
                },
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
    download_audit = dict(carrier.get("download_audit", {}))
    approved_unlock_summary = dict(carrier.get("approved_customer_visible_unlock_summary", {}))
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
        "customer_visible_enabled": bool(carrier.get("customer_visible_enabled", False)),
        "customer_visible_export_enabled": bool(
            carrier.get("customer_visible_export_enabled", False)
        ),
        "client_page_release_enabled": bool(carrier.get("client_page_release_enabled", False)),
        "export_artifact_generation_enabled": bool(
            carrier.get("export_artifact_generation_enabled", False)
        ),
        "page_publication_enabled": bool(carrier.get("page_publication_enabled", False)),
        "download_enabled": bool(download_audit.get("download_enabled", False)),
        "customer_download_enabled": bool(download_audit.get("customer_download_enabled", False)),
        "external_delivery_enabled": False,
        "delivery_ready": bool(carrier.get("delivery_ready", False)),
        "approved_customer_visible_unlock_enabled": bool(
            approved_unlock_summary.get("approved_customer_visible_unlock_enabled", False)
        ),
        "approved_customer_visible_unlock_state": approved_unlock_summary.get("unlock_state"),
        "artifact_version_hash": carrier.get("artifact_version_hash"),
        "customer_visible_artifact_candidate_state": dict(
            carrier.get("customer_visible_artifact_candidate", {})
        ).get("candidate_state"),
        "page_export_candidate_state": dict(carrier.get("page_export_candidate", {})).get("candidate_state"),
        "download_audit_id": download_audit.get("download_audit_id"),
        "export_page_replay_id": dict(carrier.get("export_page_replay", {})).get("replay_id"),
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
