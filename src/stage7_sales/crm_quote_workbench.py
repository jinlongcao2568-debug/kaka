from __future__ import annotations

from typing import Any, Mapping

from shared.provider_adapter_config import (
    LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER,
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
_CRM_SANDBOX_SYNC_TARGETS = ("account", "opportunity", "activity")
_QUOTE_APPROVAL_STEPS = (
    "internal_quote_review",
    "discount_approval_if_requested",
    "client_quote_release",
)
_APPROVED_STATES = {"APPROVED", "APPROVAL_READY", "PASSED", "PASS"}
_QUOTE_VERSION_READY_STATES = {"APPROVED", "VERSION_APPROVED", "LOCKED", "LOCKED_VERSION", "APPROVED_VERSION"}
_QUOTE_EXPIRATION_READY_STATES = {"DRAFT_VALIDITY_SET", "VALID", "VALIDITY_SET", "APPROVED"}
_AUDIT_READY_STATES = {"PRESENT", "APPROVED", "AUDITED", "PASS"}
_NOT_REQUESTED_STATES = {"", "NONE", "NOT_REQUESTED", "NOT_REQUIRED"}


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


def _requested_live_fallback(inputs: Mapping[str, Any], provider_adapter_readiness_summary: Mapping[str, Any] | None) -> bool:
    summary = dict(provider_adapter_readiness_summary or {})
    return (
        _truthy(inputs.get("live_fallback_requested"))
        or _truthy(inputs.get("provider_live_fallback_requested"))
        or _truthy(inputs.get("crm_quote_live_fallback_requested"))
        or bool(summary.get("requested_live_mode", False))
    )


def _approved_crm_quote_execution_requested(
    inputs: Mapping[str, Any],
    *,
    requested_live_crm: bool,
    requested_external_quote: bool,
    requested_live_execution: bool,
) -> bool:
    return (
        requested_live_crm
        or requested_external_quote
        or requested_live_execution
        or any(
            _truthy(inputs.get(field_name))
            for field_name in (
                "approved_crm_quote_execution_requested",
                "approved_crm_sync_requested",
                "approved_quote_send_requested",
                "crm_quote_provider_execution_requested",
                "controlled_crm_quote_execution_requested",
                "approved_provider_execution_requested",
                "provider_execution_requested",
            )
        )
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


def _operator_action_audit_refs(inputs: Mapping[str, Any]) -> list[str]:
    refs: list[Any] = []
    supplied_refs = inputs.get("operator_action_audit_refs")
    if isinstance(supplied_refs, list):
        refs.extend(supplied_refs)
    elif supplied_refs not in _EMPTY_VALUES:
        refs.append(supplied_refs)
    for field_name in (
        "operator_action_audit_ref",
        "operator_action_audit_id",
        "operator_approval_audit_ref",
        "crm_quote_operator_action_audit_ref",
    ):
        if inputs.get(field_name) not in _EMPTY_VALUES:
            refs.append(inputs.get(field_name))
    return _clean_list(refs)


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


def _sandbox_state(*, provider_suspended: bool, live_requested: bool = False) -> str:
    if provider_suspended:
        return "SUSPENDED"
    if live_requested:
        return "BLOCKED"
    return "SANDBOX_READBACK_READY"


def _stage7_trace_value(
    stage7_resolution_trace: Mapping[str, Any],
    *path: str,
    default: Any = None,
) -> Any:
    cursor: Any = stage7_resolution_trace
    for key in path:
        if not isinstance(cursor, Mapping):
            return default
        cursor = cursor.get(key)
    return default if cursor in _EMPTY_VALUES else cursor


def _crm_sandbox_sync_records(
    *,
    project_id: str,
    opportunity_id: str,
    lead_id: Any,
    offer_id: Any,
    saleability_status: Any,
    offer_state: Any,
    provider_suspended: bool,
    requested_live_crm: bool,
    now: str,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for target in _CRM_SANDBOX_SYNC_TARGETS:
        records[target] = {
            "sandbox_sync_record_id": build_id("CRMSYNC", project_id, f"{opportunity_id}-{target.upper()}"),
            "sync_target": target,
            "sync_record_type": f"crm_{target}",
            "sandbox_execution_mode": "SANDBOX_READBACK_ONLY",
            "sandbox_sync_state": _sandbox_state(
                provider_suspended=provider_suspended,
                live_requested=requested_live_crm,
            ),
            "readback_only": True,
            "real_crm_sync_enabled": False,
            "real_crm_sync_executed": False,
            "live_fallback_allowed": False,
            "provider_adapter_suspended": provider_suspended,
            "source_refs": {
                "sales_lead_id": lead_id,
                "opportunity_id": opportunity_id,
                "offer_recommendation_id": offer_id,
                "saleability_status": saleability_status,
                "offer_recommendation_state": offer_state,
            },
            "created_at": now,
        }
    return records


def _discount_approval_state(inputs: Mapping[str, Any]) -> dict[str, Any]:
    discount_value = (
        inputs.get("discount_rate_optional")
        or inputs.get("discount_rate")
        or inputs.get("requested_discount_rate_optional")
        or inputs.get("discount_amount_optional")
    )
    discount_requested = _truthy(inputs.get("discount_requested")) or discount_value not in _EMPTY_VALUES
    approval_state = str(inputs.get("discount_approval_state", "") or "").strip()
    if not discount_requested:
        approval_state = approval_state or "NOT_REQUESTED"
    elif approval_state not in {"APPROVED", "REJECTED"}:
        approval_state = "MISSING_OR_PENDING"
    return {
        "discount_requested": discount_requested,
        "discount_value_optional": discount_value if discount_value not in _EMPTY_VALUES else None,
        "discount_approval_state": approval_state,
        "discount_approval_required_before_external_quote": bool(discount_requested),
        "external_quote_still_disabled": True,
    }


def _quote_sandbox_record(
    *,
    project_id: str,
    opportunity_id: str,
    quote_draft_id: str,
    offer_recommendation: Mapping[str, Any],
    inputs: Mapping[str, Any],
    stage7_resolution_trace: Mapping[str, Any],
    approval_state: str,
    audit_state: str,
    missing_audit_refs: list[str],
    provider_suspended: bool,
    requested_external_quote: bool,
    now: str,
) -> dict[str, Any]:
    price_resolution = dict(stage7_resolution_trace.get("price_resolution", {}))
    formal_sink_projection = dict(stage7_resolution_trace.get("formal_sink_projection", {}))
    quote_version = str(inputs.get("quote_version_optional") or inputs.get("quote_version") or "1")
    expiration_at = (
        inputs.get("quote_expires_at_optional")
        or inputs.get("quote_valid_until_optional")
        or formal_sink_projection.get("current_action_deadline_at_optional")
        or "NOT_SET_REVIEW_REQUIRED"
    )
    quote_state = _sandbox_state(
        provider_suspended=provider_suspended,
        live_requested=requested_external_quote,
    )
    return {
        "quote_sandbox_record_id": build_id("QSBOX", project_id, opportunity_id),
        "quote_draft_id": quote_draft_id,
        "sandbox_execution_mode": "SANDBOX_READBACK_ONLY",
        "quote_sandbox_state": quote_state,
        "readback_only": True,
        "external_quote_enabled": False,
        "external_quote_sent": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
        "price_recommendation": {
            "offer_recommendation_id": offer_recommendation.get("offer_recommendation_id"),
            "recommended_quote_band": offer_recommendation.get("recommended_quote_band")
            or price_resolution.get("recommended_quote_band"),
            "recommended_sku": offer_recommendation.get("sku_code"),
            "normalized_price_amount_optional": _stage7_trace_value(
                stage7_resolution_trace,
                "formal_sink_projection",
                "normalized_price_amount_optional",
            ),
            "price_conflict_gate_status_optional": _stage7_trace_value(
                stage7_resolution_trace,
                "formal_sink_projection",
                "price_conflict_gate_status_optional",
            ),
            "price_resolution_policy_ref": price_resolution.get("pricing_policy_id"),
            "quote_band_authority_ref": price_resolution.get("quote_band_authority_ref"),
        },
        "approval": {
            "approval_state": approval_state,
            "approval_steps": list(_QUOTE_APPROVAL_STEPS),
            "approval_required_before_external_quote": True,
            "external_quote_still_disabled": True,
        },
        "version": {
            "quote_version_id": build_id("QVER", project_id, f"{opportunity_id}-V{quote_version}"),
            "version_number": quote_version,
            "version_state": "DRAFT_VERSION",
            "supersedes_quote_version_id_optional": inputs.get("supersedes_quote_version_id_optional"),
            "customer_visible_version_locked": False,
        },
        "audit": {
            "audit_state": audit_state,
            "required_audit_refs": list(_AUDIT_REF_FIELDS),
            "missing_audit_refs": list(missing_audit_refs),
            "audit_required_before_external_quote": True,
            "external_quote_audit_ready": False,
        },
        "expiration": {
            "expires_at": expiration_at,
            "validity_state": "REVIEW_REQUIRED" if expiration_at == "NOT_SET_REVIEW_REQUIRED" else "DRAFT_VALIDITY_SET",
            "external_quote_send_allowed": False,
        },
        "discount_approval": _discount_approval_state(inputs),
        "provider_adapter_suspended": provider_suspended,
        "created_at": now,
    }


def _deal_tracking_record(
    *,
    project_id: str,
    opportunity_id: str,
    crm_action_id: str,
    quote_draft_id: str,
    saleability_status: Any,
    offer_state: Any,
    provider_suspended: bool,
    now: str,
) -> dict[str, Any]:
    return {
        "deal_tracking_record_id": build_id("DEAL", project_id, opportunity_id),
        "opportunity_id": opportunity_id,
        "crm_action_id": crm_action_id,
        "quote_draft_id": quote_draft_id,
        "deal_state": "SUSPENDED" if provider_suspended else "INTERNAL_TRACKING_ONLY",
        "readback_only": True,
        "sales_pipeline_write_enabled": False,
        "real_crm_deal_update_enabled": False,
        "source_state": {
            "saleability_status": saleability_status,
            "offer_recommendation_state": offer_state,
        },
        "created_at": now,
    }


def _sales_followup_record(
    *,
    project_id: str,
    opportunity_id: str,
    crm_action_id: str,
    inputs: Mapping[str, Any],
    provider_suspended: bool,
    now: str,
) -> dict[str, Any]:
    return {
        "sales_note_id": build_id("SNOTE", project_id, opportunity_id),
        "callback_task_id": build_id("CALLBACK", project_id, opportunity_id),
        "crm_action_id": crm_action_id,
        "opportunity_id": opportunity_id,
        "sales_note_state": "SUSPENDED" if provider_suspended else "SANDBOX_NOTE_READY",
        "callback_state": "SUSPENDED" if provider_suspended else "SANDBOX_CALLBACK_READY",
        "sales_note_body_optional": inputs.get("sales_note_optional"),
        "callback_at_optional": inputs.get("callback_at_optional") or inputs.get("next_callback_at_optional"),
        "callback_reason_optional": inputs.get("callback_reason_optional"),
        "readback_only": True,
        "real_crm_activity_write_enabled": False,
        "real_callback_dispatch_enabled": False,
        "created_at": now,
    }


def _provider_config_ref(
    *,
    provider_adapter_readiness_summary: Mapping[str, Any] | None,
    provider_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    summary = dict(provider_adapter_readiness_summary or {})
    provider_id = provider_readiness.get("provider_id")
    config_source = summary.get("config_source")
    configured = bool(summary and provider_readiness and provider_id and config_source)
    return {
        "provider_config_state": "CONFIGURED" if configured else "MISSING",
        "provider_config_required": True,
        "provider_configured": configured,
        "config_source": config_source,
        "config_source_ref": summary.get("config_source_ref"),
        "provider_family": provider_readiness.get("family", "crm_quote"),
        "provider_id": provider_id,
        "provider_mode": provider_readiness.get("mode") or summary.get("mode"),
        "readback_only": bool(provider_readiness.get("readback_only", summary.get("readback_only", True))),
        "controlled_provider_adapter_scope": LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
    }


def _sandbox_pass_state(
    *,
    crm_sync_records: Mapping[str, Any],
    quote_sandbox_record: Mapping[str, Any],
) -> str:
    crm_states = [
        str(dict(record).get("sandbox_sync_state", "BLOCKED"))
        for record in crm_sync_records.values()
        if isinstance(record, Mapping)
    ]
    quote_state = str(quote_sandbox_record.get("quote_sandbox_state", "BLOCKED"))
    if any(state == "SUSPENDED" for state in [*crm_states, quote_state]):
        return "SUSPENDED"
    if crm_states and all(state == "SANDBOX_READBACK_READY" for state in crm_states) and quote_state == "SANDBOX_READBACK_READY":
        return "PASS"
    return "BLOCKED"


def _normalized_state(value: Any, *, default: str = "") -> str:
    if value in _EMPTY_VALUES:
        return default
    return str(value).strip().upper().replace("-", "_").replace(" ", "_") or default


def _quote_policy_state(
    *,
    inputs: Mapping[str, Any],
    quote_sandbox_record: Mapping[str, Any],
    audit_state: str,
) -> dict[str, Any]:
    version = dict(quote_sandbox_record.get("version", {}))
    approval = dict(quote_sandbox_record.get("approval", {}))
    expiration = dict(quote_sandbox_record.get("expiration", {}))
    discount = dict(quote_sandbox_record.get("discount_approval", {}))
    audit = dict(quote_sandbox_record.get("audit", {}))

    quote_version_state = _normalized_state(
        inputs.get("quote_version_state")
        or inputs.get("quote_version_approval_state")
        or version.get("version_state"),
        default="MISSING",
    )
    quote_approval_state = _normalized_state(
        inputs.get("quote_approval_state")
        or inputs.get("quote_send_approval_state")
        or approval.get("approval_state"),
        default="MISSING",
    )
    quote_audit_state = _normalized_state(
        inputs.get("quote_audit_state")
        or inputs.get("quote_send_audit_state")
        or audit.get("audit_state")
        or audit_state,
        default="MISSING",
    )
    quote_expiration_state = _normalized_state(
        inputs.get("quote_expiration_state")
        or inputs.get("quote_validity_state")
        or expiration.get("validity_state"),
        default="MISSING",
    )
    discount_approval_state = _normalized_state(
        discount.get("discount_approval_state"),
        default="MISSING",
    )
    discount_requested = bool(discount.get("discount_requested", False))
    expires_at = expiration.get("expires_at")

    return {
        "quote_version_state": quote_version_state,
        "quote_version_policy_satisfied": quote_version_state in _QUOTE_VERSION_READY_STATES,
        "quote_approval_state": quote_approval_state,
        "quote_approval_satisfied": quote_approval_state in _APPROVED_STATES,
        "quote_audit_state": quote_audit_state,
        "quote_audit_satisfied": quote_audit_state in _AUDIT_READY_STATES,
        "quote_expiration_state": quote_expiration_state,
        "quote_expiration_policy_satisfied": (
            quote_expiration_state in _QUOTE_EXPIRATION_READY_STATES
            and expires_at not in _EMPTY_VALUES
            and expires_at != "NOT_SET_REVIEW_REQUIRED"
        ),
        "discount_requested": discount_requested,
        "discount_approval_state": discount_approval_state,
        "discount_approval_satisfied": (
            discount_approval_state in _APPROVED_STATES
            if discount_requested
            else discount_approval_state in _NOT_REQUESTED_STATES
        ),
        "expires_at": expires_at,
    }


def _provider_result_state(inputs: Mapping[str, Any], *, enabled: bool) -> str:
    supplied = inputs.get("provider_result_readback")
    supplied_payload = dict(supplied) if isinstance(supplied, Mapping) else {}
    state = _normalized_state(
        supplied_payload.get("result_state")
        or supplied_payload.get("state")
        or inputs.get("crm_quote_provider_result_state")
        or inputs.get("provider_result_state")
        or inputs.get("controlled_provider_result_state"),
        default="",
    )
    if state:
        if state in {"OK", "ACCEPTED", "RECORDED", "SYNCED", "SENT"}:
            return "SUCCESS"
        if state in {"FAIL", "FAILED", "ERROR", "TIMEOUT", "RATE_LIMITED"}:
            return "FAILED"
        return state
    return "SUCCESS" if enabled else "NOT_EXECUTED"


def _quote_send_record(
    *,
    project_id: str,
    opportunity_id: str,
    provider_execution_id: str,
    quote_draft_id: str,
    quote_sandbox_record: Mapping[str, Any],
    execution_request_state: str,
    provider_execution_state: str,
    enabled: bool,
    now: str,
) -> dict[str, Any]:
    return {
        "quote_send_record_id": build_id("QSEND", project_id, opportunity_id),
        "provider_execution_id": provider_execution_id,
        "quote_draft_id": quote_draft_id,
        "quote_sandbox_record_id": quote_sandbox_record.get("quote_sandbox_record_id"),
        "quote_send_state": "CONTROLLED_FAKE_QUOTE_SEND_RECORDED" if enabled else execution_request_state,
        "execution_request_state": execution_request_state,
        "provider_execution_state": provider_execution_state,
        "controlled_provider_adapter_scope": LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER,
        "controlled_fake_quote_send_recorded": bool(enabled),
        "external_quote_sent": False,
        "real_external_quote_sent": False,
        "provider_call_executed": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
        "created_at": now,
    }


def _provider_result_readback(
    *,
    inputs: Mapping[str, Any],
    provider_execution_id: str,
    crm_action_id: str,
    quote_draft_id: str,
    provider_readiness: Mapping[str, Any],
    execution_request_state: str,
    provider_execution_state: str,
    enabled: bool,
) -> dict[str, Any]:
    supplied = inputs.get("provider_result_readback")
    supplied_payload = dict(supplied) if isinstance(supplied, Mapping) else {}
    return {
        **supplied_payload,
        "provider_execution_id": provider_execution_id,
        "crm_action_id": crm_action_id,
        "quote_draft_id": quote_draft_id,
        "result_state": provider_execution_state if enabled else "NOT_EXECUTED",
        "execution_request_state": execution_request_state,
        "provider_execution_state": provider_execution_state,
        "provider_family": provider_readiness.get("family", "crm_quote"),
        "provider_id": provider_readiness.get("provider_id"),
        "provider_status_readback": dict(provider_readiness.get("provider_status_readback", {})),
        "controlled_provider_adapter_enabled": bool(enabled),
        "controlled_provider_adapter_scope": LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER,
        "controlled_provider_execution_executed": bool(enabled),
        "controlled_crm_sync_recorded": bool(enabled),
        "controlled_quote_send_recorded": bool(enabled),
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "provider_call_executed": False,
        "real_crm_sync_enabled": False,
        "real_crm_sync_executed": False,
        "external_quote_sent": False,
        "real_external_quote_sent": False,
        "real_provider_receipt_generated": False,
        "readback_only": True,
    }


def _deal_tracking_timeline(
    *,
    now: str,
    sandbox_pass_state: str,
    execution_request_state: str,
    provider_execution_state: str,
    provider_result_readback: Mapping[str, Any],
    blocked_reasons: list[str],
    suspension_reasons: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "event": "crm_quote_sandbox_records_created",
            "at": now,
            "state": sandbox_pass_state,
            "real_provider_call_enabled": False,
        },
        {
            "event": "approved_crm_quote_execution_request_evaluated",
            "at": now,
            "state": execution_request_state,
            "blocked_reasons": list(blocked_reasons),
            "suspension_reasons": list(suspension_reasons),
            "real_provider_call_enabled": False,
        },
        {
            "event": "crm_quote_provider_result_readback_recorded",
            "at": now,
            "state": provider_result_readback.get("result_state"),
            "provider_execution_state": provider_execution_state,
            "controlled_provider_execution_executed": bool(
                provider_result_readback.get("controlled_provider_execution_executed", False)
            ),
            "provider_call_executed": False,
            "external_quote_sent": False,
        },
    ]


def _approved_crm_quote_execution_carrier(
    *,
    project_id: str,
    opportunity_id: str,
    crm_action_id: str,
    quote_draft_id: str,
    crm_sync_records: Mapping[str, Any],
    quote_sandbox_record: Mapping[str, Any],
    deal_tracking_record: Mapping[str, Any],
    sales_followup_record: Mapping[str, Any],
    inputs: Mapping[str, Any],
    provider_adapter_readiness_summary: Mapping[str, Any] | None,
    provider_readiness: Mapping[str, Any],
    audit_state: str,
    provider_suspended: bool,
    requested_live_crm: bool,
    requested_external_quote: bool,
    requested_live_execution: bool,
    now: str,
) -> dict[str, Any]:
    provider_execution_id = build_id("CRMQUOTEEXEC", project_id, opportunity_id)
    requested = _approved_crm_quote_execution_requested(
        inputs,
        requested_live_crm=requested_live_crm,
        requested_external_quote=requested_external_quote,
        requested_live_execution=requested_live_execution,
    )
    provider_config = _provider_config_ref(
        provider_adapter_readiness_summary=provider_adapter_readiness_summary,
        provider_readiness=provider_readiness,
    )
    sandbox_pass_state = _sandbox_pass_state(
        crm_sync_records=crm_sync_records,
        quote_sandbox_record=quote_sandbox_record,
    )
    operator_action_audit_refs = _operator_action_audit_refs(inputs)
    crm_approval_state = _normalized_state(
        inputs.get("crm_approval_state") or inputs.get("approval_state"),
        default="MISSING",
    )
    quote_policy = _quote_policy_state(
        inputs=inputs,
        quote_sandbox_record=quote_sandbox_record,
        audit_state=audit_state,
    )
    live_fallback_requested = _requested_live_fallback(inputs, provider_adapter_readiness_summary)

    blocked_reasons: list[Any] = []
    suspension_reasons: list[Any] = []
    if not requested:
        blocked_reasons.append("approved_crm_quote_execution_not_requested")
    if provider_config["provider_config_state"] != "CONFIGURED":
        blocked_reasons.append("provider_config_missing")
    if sandbox_pass_state != "PASS":
        blocked_reasons.append("sandbox_not_passed")
    if crm_approval_state not in _APPROVED_STATES:
        blocked_reasons.append("crm_approval_missing")
    if not quote_policy["quote_approval_satisfied"]:
        blocked_reasons.append("quote_approval_missing")
    if not quote_policy["quote_audit_satisfied"]:
        blocked_reasons.append("quote_audit_missing")
    if not operator_action_audit_refs:
        blocked_reasons.append("operator_action_audit_missing")
    if not quote_policy["quote_version_policy_satisfied"]:
        blocked_reasons.append("quote_version_policy_not_satisfied")
    if not quote_policy["quote_expiration_policy_satisfied"]:
        blocked_reasons.append("quote_expiration_policy_not_satisfied")
    if not quote_policy["discount_approval_satisfied"]:
        blocked_reasons.append("discount_approval_missing")
    if provider_suspended:
        suspension_reasons.append("provider_reliability_suspended_fail_closed")
    if live_fallback_requested:
        blocked_reasons.append("live_fallback_requested_but_blocked")
    if requested_external_quote and not quote_policy["quote_approval_satisfied"]:
        blocked_reasons.append("external_quote_send_unapproved")
    if requested_live_crm and crm_approval_state not in _APPROVED_STATES:
        blocked_reasons.append("crm_sync_unapproved")

    blocked_reasons.extend(
        reason
        for reason in provider_readiness.get("blocked_reasons", [])
        if str(reason).startswith(
            (
                "provider_health_",
                "provider_rate_",
                "provider_timeout_",
                "provider_circuit_",
                "provider_failure_",
                "provider_reliability_",
            )
        )
    )
    if provider_suspended:
        blocked_reasons.append("provider_reliability_suspended_fail_closed")

    blocked_reasons = _clean_list(blocked_reasons)
    suspension_reasons = _clean_list(suspension_reasons)

    if provider_suspended or sandbox_pass_state == "SUSPENDED":
        execution_request_state = "SUSPENDED"
    elif blocked_reasons:
        execution_request_state = "BLOCKED"
    elif requested:
        execution_request_state = "APPROVED"
    else:
        execution_request_state = "BLOCKED"

    enabled = execution_request_state == "APPROVED"
    result_state = _provider_result_state(inputs, enabled=enabled)
    provider_execution_state = result_state if enabled else execution_request_state
    provider_result = _provider_result_readback(
        inputs=inputs,
        provider_execution_id=provider_execution_id,
        crm_action_id=crm_action_id,
        quote_draft_id=quote_draft_id,
        provider_readiness=provider_readiness,
        execution_request_state=execution_request_state,
        provider_execution_state=provider_execution_state,
        enabled=enabled,
    )
    quote_send = _quote_send_record(
        project_id=project_id,
        opportunity_id=opportunity_id,
        provider_execution_id=provider_execution_id,
        quote_draft_id=quote_draft_id,
        quote_sandbox_record=quote_sandbox_record,
        execution_request_state=execution_request_state,
        provider_execution_state=provider_execution_state,
        enabled=enabled,
        now=now,
    )
    timeline = _deal_tracking_timeline(
        now=now,
        sandbox_pass_state=sandbox_pass_state,
        execution_request_state=execution_request_state,
        provider_execution_state=provider_execution_state,
        provider_result_readback=provider_result,
        blocked_reasons=blocked_reasons,
        suspension_reasons=suspension_reasons,
    )
    replay_state = {
        "state": "REPLAYABLE",
        "repository_backed": True,
        "approved_crm_quote_execution_record_replayable": True,
        "provider_result_readback_replayable": True,
        "deal_tracking_timeline_replayable": True,
        "sales_note_record_replayable": True,
        "sales_callback_record_replayable": True,
        "provider_status_replayable": bool(
            dict(provider_readiness.get("provider_status_readback", {})).get("replayable", True)
        ),
        "controlled_provider_execution_replayable": True,
        "real_provider_call_executed": False,
        "no_broad_fallback": True,
    }
    gate_states = {
        "provider_config_state": provider_config["provider_config_state"],
        "sandbox_pass_state": sandbox_pass_state,
        "crm_approval_state": crm_approval_state,
        "quote_approval_state": quote_policy["quote_approval_state"],
        "quote_audit_state": quote_policy["quote_audit_state"],
        "operator_action_audit_refs": operator_action_audit_refs,
        "quote_version_state": quote_policy["quote_version_state"],
        "quote_expiration_state": quote_policy["quote_expiration_state"],
        "discount_approval_state": quote_policy["discount_approval_state"],
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "provider_adapter_suspended": bool(provider_suspended),
        "live_fallback_requested": bool(live_fallback_requested),
    }
    summary = {
        "provider_execution_id": provider_execution_id,
        "crm_action_id": crm_action_id,
        "quote_draft_id": quote_draft_id,
        "opportunity_id": opportunity_id,
        "provider_config_ref": provider_config,
        "provider_adapter_readiness_summary": dict(provider_readiness),
        "provider_reliability_state": provider_readiness.get("provider_reliability_state"),
        "execution_request_state": execution_request_state,
        "provider_execution_state": provider_execution_state,
        "approved_crm_quote_execution_requested": bool(requested),
        "approved_crm_quote_execution_enabled": bool(enabled),
        "controlled_provider_adapter_scope": LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER,
        "controlled_provider_execution_executed": bool(
            provider_result.get("controlled_provider_execution_executed", False)
        ),
        "real_provider_call_enabled": False,
        "real_provider_call_executed": False,
        "real_crm_sync_enabled": False,
        "external_quote_sent": False,
        "real_external_quote_sent": False,
        "gate_states": gate_states,
        "blocked_reasons": blocked_reasons,
        "suspension_reasons": suspension_reasons,
        "provider_result_readback": provider_result,
        "deal_tracking_timeline": timeline,
        "quote_send_record": quote_send,
        "sales_note_record": {
            "sales_note_id": sales_followup_record.get("sales_note_id"),
            "provider_execution_id": provider_execution_id,
            "crm_action_id": crm_action_id,
            "sales_note_state": sales_followup_record.get("sales_note_state"),
            "controlled_fake_note_recorded": bool(enabled),
            "real_crm_activity_write_enabled": False,
            "real_provider_call_enabled": False,
        },
        "sales_callback_record": {
            "callback_task_id": sales_followup_record.get("callback_task_id"),
            "provider_execution_id": provider_execution_id,
            "crm_action_id": crm_action_id,
            "callback_state": sales_followup_record.get("callback_state"),
            "controlled_fake_callback_recorded": bool(enabled),
            "real_callback_dispatch_enabled": False,
            "real_provider_call_enabled": False,
        },
        "deal_tracking_record": dict(deal_tracking_record),
        "replay_state": replay_state,
        "decided_at": now,
    }
    return summary


def build_crm_quote_workbench_readiness_summary(carrier: Mapping[str, Any]) -> dict[str, Any]:
    blocked_reasons = _clean_list(ensure_list(carrier.get("blocked_reasons")))
    provider_readiness = dict(carrier.get("provider_adapter_readiness", {}))
    provider_circuit_breaker = dict(provider_readiness.get("provider_circuit_breaker", {}))
    provider_failure_taxonomy = dict(provider_readiness.get("provider_failure_taxonomy", {}))
    provider_status_readback = dict(provider_readiness.get("provider_status_readback", {}))
    crm_sync_records = dict(carrier.get("crm_sandbox_sync_records", {}))
    quote_sandbox_record = dict(carrier.get("quote_sandbox_record", {}))
    deal_tracking_record = dict(carrier.get("deal_tracking_record", {}))
    sales_followup_record = dict(carrier.get("sales_followup_record", {}))
    approved_execution_summary = dict(carrier.get("approved_crm_quote_execution_summary", {}))
    provider_result_readback = dict(carrier.get("provider_result_readback", {}))
    replay_state = dict(carrier.get("replay_state", {}))
    provider_suspended = bool(provider_readiness.get("provider_adapter_suspended", False))
    return {
        "opportunity_id": carrier.get("opportunity_id"),
        "provider_execution_id": carrier.get("provider_execution_id"),
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
        "sandbox_execution_readiness": "SUSPENDED" if provider_suspended else "SANDBOX_READY",
        "crm_sandbox_sync_targets": list(crm_sync_records.keys()),
        "crm_account_sync_record_id": dict(crm_sync_records.get("account", {})).get("sandbox_sync_record_id"),
        "crm_opportunity_sync_record_id": dict(crm_sync_records.get("opportunity", {})).get("sandbox_sync_record_id"),
        "crm_activity_sync_record_id": dict(crm_sync_records.get("activity", {})).get("sandbox_sync_record_id"),
        "quote_sandbox_record_id": quote_sandbox_record.get("quote_sandbox_record_id"),
        "quote_sandbox_state": quote_sandbox_record.get("quote_sandbox_state"),
        "quote_version_id": dict(quote_sandbox_record.get("version", {})).get("quote_version_id"),
        "discount_approval_state": dict(quote_sandbox_record.get("discount_approval", {})).get(
            "discount_approval_state"
        ),
        "deal_tracking_record_id": deal_tracking_record.get("deal_tracking_record_id"),
        "sales_note_id": sales_followup_record.get("sales_note_id"),
        "callback_task_id": sales_followup_record.get("callback_task_id"),
        "approved_crm_quote_execution_requested": bool(
            carrier.get("approved_crm_quote_execution_requested", False)
        ),
        "approved_crm_quote_execution_enabled": bool(
            carrier.get("approved_crm_quote_execution_enabled", False)
        ),
        "execution_request_state": carrier.get("execution_request_state"),
        "provider_execution_state": carrier.get("provider_execution_state"),
        "provider_result_state": provider_result_readback.get("result_state"),
        "controlled_provider_adapter_scope": carrier.get("controlled_provider_adapter_scope"),
        "controlled_provider_execution_executed": bool(
            carrier.get("controlled_provider_execution_executed", False)
        ),
        "provider_result_readback_replayable": bool(
            replay_state.get("provider_result_readback_replayable", False)
        ),
        "deal_tracking_timeline_replayable": bool(
            replay_state.get("deal_tracking_timeline_replayable", False)
        ),
        "approved_crm_quote_execution_summary": approved_execution_summary,
        "ready_for_live_execution": False,
        "ready_for_external_quote": False,
        "live_execution_enabled": False,
        "external_quote_sent": False,
        "real_external_quote_sent": False,
        "blocked_reason_count": len(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "suspension_reasons": list(carrier.get("suspension_reasons", [])),
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
    if provider_suspended:
        blocked_reasons.append("provider_adapter_suspended_fail_closed")
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
    crm_sandbox_sync_records = _crm_sandbox_sync_records(
        project_id=project_id,
        opportunity_id=opportunity_id,
        lead_id=lead_id,
        offer_id=offer_id,
        saleability_status=saleability_status,
        offer_state=offer_state,
        provider_suspended=provider_suspended,
        requested_live_crm=requested_live_crm,
        now=now,
    )
    quote_sandbox_record = _quote_sandbox_record(
        project_id=project_id,
        opportunity_id=opportunity_id,
        quote_draft_id=quote_draft_id,
        offer_recommendation=offer_recommendation,
        inputs=inputs,
        stage7_resolution_trace=stage7_resolution_trace,
        approval_state=approval_state,
        audit_state=audit_state,
        missing_audit_refs=missing_audit_refs,
        provider_suspended=provider_suspended,
        requested_external_quote=requested_external_quote,
        now=now,
    )
    deal_tracking_record = _deal_tracking_record(
        project_id=project_id,
        opportunity_id=opportunity_id,
        crm_action_id=crm_action_id,
        quote_draft_id=quote_draft_id,
        saleability_status=saleability_status,
        offer_state=offer_state,
        provider_suspended=provider_suspended,
        now=now,
    )
    sales_followup_record = _sales_followup_record(
        project_id=project_id,
        opportunity_id=opportunity_id,
        crm_action_id=crm_action_id,
        inputs=inputs,
        provider_suspended=provider_suspended,
        now=now,
    )
    approved_execution = _approved_crm_quote_execution_carrier(
        project_id=project_id,
        opportunity_id=opportunity_id,
        crm_action_id=crm_action_id,
        quote_draft_id=quote_draft_id,
        crm_sync_records=crm_sandbox_sync_records,
        quote_sandbox_record=quote_sandbox_record,
        deal_tracking_record=deal_tracking_record,
        sales_followup_record=sales_followup_record,
        inputs=inputs,
        provider_adapter_readiness_summary=provider_adapter_readiness_summary,
        provider_readiness=provider_readiness,
        audit_state=audit_state,
        provider_suspended=provider_suspended,
        requested_live_crm=requested_live_crm,
        requested_external_quote=requested_external_quote,
        requested_live_execution=requested_live_execution,
        now=now,
    )
    provider_execution_id = str(approved_execution["provider_execution_id"])
    for sync_record in crm_sandbox_sync_records.values():
        sync_record["provider_execution_id"] = provider_execution_id
        sync_record["approved_provider_execution_state"] = approved_execution["execution_request_state"]
        sync_record["controlled_fake_crm_sync_recorded"] = bool(
            approved_execution["approved_crm_quote_execution_enabled"]
        )
        sync_record["provider_call_executed"] = False
    deal_tracking_record["provider_execution_id"] = provider_execution_id
    deal_tracking_record["provider_execution_state"] = approved_execution["provider_execution_state"]
    sales_followup_record["provider_execution_id"] = provider_execution_id
    sales_followup_record["provider_execution_state"] = approved_execution["provider_execution_state"]

    carrier = {
        "provider_execution_id": provider_execution_id,
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
        "external_quote_sent": False,
        "real_external_quote_sent": False,
        "real_crm_receipt_generated": False,
        "customer_visible_quote_generated": False,
        "customer_visible_delivery_package_generated": False,
        "account_sync_record": dict(crm_sandbox_sync_records["account"]),
        "opportunity_sync_record": dict(crm_sandbox_sync_records["opportunity"]),
        "activity_sync_record": dict(crm_sandbox_sync_records["activity"]),
        "crm_sandbox_sync_records": crm_sandbox_sync_records,
        "quote_send_record": dict(approved_execution["quote_send_record"]),
        "quote_sandbox_record": quote_sandbox_record,
        "quote_version_state": approved_execution["gate_states"]["quote_version_state"],
        "quote_approval_state": approved_execution["gate_states"]["quote_approval_state"],
        "quote_expiration_state": approved_execution["gate_states"]["quote_expiration_state"],
        "discount_approval_state": approved_execution["gate_states"]["discount_approval_state"],
        "quote_audit_state": approved_execution["gate_states"]["quote_audit_state"],
        "operator_action_audit_refs": list(approved_execution["gate_states"]["operator_action_audit_refs"]),
        "provider_config_ref": dict(approved_execution["provider_config_ref"]),
        "provider_adapter_readiness_summary": dict(approved_execution["provider_adapter_readiness_summary"]),
        "deal_tracking_record": deal_tracking_record,
        "deal_tracking_timeline": list(approved_execution["deal_tracking_timeline"]),
        "sales_followup_record": sales_followup_record,
        "sales_note_record": dict(approved_execution["sales_note_record"]),
        "sales_callback_record": dict(approved_execution["sales_callback_record"]),
        "sandbox_adapter_execution": {
            "execution_mode": "SANDBOX_READBACK_ONLY",
            "crm_sync_target_count": len(crm_sandbox_sync_records),
            "quote_record_ready": bool(quote_sandbox_record),
            "deal_tracking_ready": bool(deal_tracking_record),
            "sales_followup_ready": bool(sales_followup_record),
            "provider_adapter_suspended": provider_suspended,
            "readiness_state": "SUSPENDED" if provider_suspended else "SANDBOX_READY",
            "sandbox_pass_state": approved_execution["gate_states"]["sandbox_pass_state"],
            "real_crm_sync_enabled": False,
            "external_quote_send_enabled": False,
            "real_provider_call_enabled": False,
            "live_fallback_allowed": False,
        },
        "approved_crm_quote_execution_requested": bool(
            approved_execution["approved_crm_quote_execution_requested"]
        ),
        "approved_crm_quote_execution_enabled": bool(
            approved_execution["approved_crm_quote_execution_enabled"]
        ),
        "execution_request_state": approved_execution["execution_request_state"],
        "provider_execution_state": approved_execution["provider_execution_state"],
        "controlled_provider_adapter_scope": approved_execution["controlled_provider_adapter_scope"],
        "controlled_provider_execution_executed": bool(
            approved_execution["controlled_provider_execution_executed"]
        ),
        "provider_result_readback": dict(approved_execution["provider_result_readback"]),
        "suspension_reasons": list(approved_execution["suspension_reasons"]),
        "replay_state": dict(approved_execution["replay_state"]),
        "approved_crm_quote_execution_summary": approved_execution,
        "blocked_reasons": _clean_list(blocked_reasons + approved_execution["blocked_reasons"]),
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
            "sandbox_record_id": quote_sandbox_record["quote_sandbox_record_id"],
            "quote_version_id": quote_sandbox_record["version"]["quote_version_id"],
            "discount_approval_state": quote_sandbox_record["discount_approval"]["discount_approval_state"],
            "expires_at": quote_sandbox_record["expiration"]["expires_at"],
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
