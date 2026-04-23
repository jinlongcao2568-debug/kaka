from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import StageBundle


TRACE_FIELDS = (
    "source_audit_ref",
    "query_trace_id",
    "execution_trace_id_optional",
    "vendor_response_ref_optional",
    "written_back_at",
    "written_back_at_optional",
)

GOVERNED_CONTEXT_FIELDS = (
    "approval_state",
    "projection_mode",
    "run_mode",
    "plan_status",
    "governed_execution_mode",
    "requested_delivery_surface",
    "writeback_targets",
    "written_back_at_optional",
    "contact_legal_basis",
)


def collect_trace_refs(bundle: StageBundle, records: list[Mapping[str, Any]]) -> dict[str, Any]:
    trace_refs: set[str] = set()
    audit_refs: set[str] = set()
    for record in records:
        for field_name in TRACE_FIELDS:
            value = record.get(field_name)
            if value not in (None, "", "NOT_PAID", "NOT_DELIVERED"):
                trace_refs.add(str(value))
        for field_name in record.keys():
            if "audit" in field_name.lower():
                value = record.get(field_name)
                if value not in (None, ""):
                    audit_refs.add(str(value))
    return {
        "policy_trace_present": bool(bundle.inputs.get("policy_trace")),
        "permission_trace_present": bool(bundle.inputs.get("permission_trace")),
        "governance_trace_present": bool(bundle.inputs.get("governance_trace")),
        "semantic_trace_present": bool(bundle.inputs.get("semantic_trace")),
        "trace_refs": sorted(trace_refs),
        "audit_refs": sorted(audit_refs),
    }


def collect_governed_context(
    formal_records: Mapping[str, Mapping[str, Any]],
    *,
    default_mode: str,
) -> dict[str, Any]:
    object_contexts: dict[str, dict[str, Any]] = {}
    for object_type, record in formal_records.items():
        object_context: dict[str, Any] = {}
        for field_name in GOVERNED_CONTEXT_FIELDS:
            value = record.get(field_name)
            if value not in (None, "", [], {}):
                object_context[field_name] = value
        governed_metadata = dict(record.get("governed_metadata", {}))
        if governed_metadata:
            object_context["governed_metadata"] = governed_metadata
        if object_context:
            object_contexts[object_type] = object_context

    governed_context: dict[str, Any] = {
        "surface_mode": default_mode,
    }
    if object_contexts:
        governed_context["object_contexts"] = object_contexts
    return governed_context


def merge_trace_refs(*surfaces: Mapping[str, Any]) -> dict[str, Any]:
    trace_refs: set[str] = set()
    audit_refs: set[str] = set()
    flags = {
        "policy_trace_present": False,
        "permission_trace_present": False,
        "governance_trace_present": False,
        "semantic_trace_present": False,
    }
    for surface in surfaces:
        trace = surface.get("trace_refs", {})
        for flag_name in flags:
            flags[flag_name] = flags[flag_name] or bool(trace.get(flag_name))
        trace_refs.update(str(value) for value in trace.get("trace_refs", []) if value)
        audit_refs.update(str(value) for value in trace.get("audit_refs", []) if value)
    return {
        **flags,
        "trace_refs": sorted(trace_refs),
        "audit_refs": sorted(audit_refs),
    }


def missing_audit_refs(required_audit_refs: list[str], aggregated_trace_refs: Mapping[str, Any]) -> list[str]:
    available = {
        "project_fact_audit_ref": bool(aggregated_trace_refs.get("audit_refs")),
        "candidate_projection_audit_ref": bool(aggregated_trace_refs.get("trace_refs")),
        "approval_chain_audit_ref": bool(
            aggregated_trace_refs.get("permission_trace_present")
            or aggregated_trace_refs.get("governance_trace_present")
        ),
        "trace_bundle_ref": bool(aggregated_trace_refs.get("trace_refs")),
    }
    return [audit_ref for audit_ref in required_audit_refs if not available.get(audit_ref, False)]


def collect_candidate_surface_block_reasons(
    *,
    stage8_surface_state: str,
    stage9_surface_state: str,
    surface_state: str,
    missing_approvals: list[str],
    missing_review_gates: list[str],
    missing_audit_refs: list[str],
) -> dict[str, list[str]]:
    blocked_reasons: list[str] = []
    hold_reasons: list[str] = []
    if stage8_surface_state in {"blocked", "review-required", "draft-only", "governed-hold"}:
        hold_reasons.append("stage8_governed_preview_not_external_ready")
    if stage9_surface_state in {"blocked", "review-required", "draft-only", "governed-hold"}:
        hold_reasons.append("stage9_internal_governed_preview_not_external_ready")
    if surface_state == "blocked":
        blocked_reasons.extend(
            [
                "candidate_surface_blocked_by_underlying_stage_surface",
                "delivery_matrix_or_runtime_guard_blocked_requested_projection",
            ]
        )
    if missing_approvals:
        blocked_reasons.append("approval_prerequisites_not_met")
    if missing_review_gates:
        blocked_reasons.append("review_gate_prerequisites_not_met")
    if missing_audit_refs:
        blocked_reasons.append("audit_prerequisites_not_met")
    return {
        "blocked_reasons": blocked_reasons,
        "hold_reasons": hold_reasons,
    }
