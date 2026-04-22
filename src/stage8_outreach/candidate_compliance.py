# Stage: stage8_outreach
# Internal boundary helpers for candidate selection and compliance projection.

from __future__ import annotations

from typing import Any, Mapping

from stage8_outreach.resolution import (
    resolve_execution_vendor,
    resolve_source_vendor,
    select_contact_candidate,
)
from shared.utils import build_id, ensure_enum, ensure_list


H07_AUTHORITATIVE_FIELDS = (
    "source_family",
    "channel_family",
    "channel_policy_status",
    "contact_validity_status",
    "contact_legal_basis",
    "reasonable_expectation_status",
    "frequency_policy_state",
    "opt_out_state",
    "quiet_hours_policy_state",
    "commercial_urgency_level_optional",
    "role_cluster",
)


def merge_stage7_authoritative_inputs(
    *,
    inputs: Mapping[str, Any],
    stage7_handoff: Mapping[str, Any],
) -> dict[str, Any]:
    authoritative_inputs = dict(inputs)
    for field_name in H07_AUTHORITATIVE_FIELDS:
        handoff_value = stage7_handoff.get(field_name, inputs.get(field_name))
        if handoff_value is not None:
            authoritative_inputs[field_name] = handoff_value
    return authoritative_inputs


def select_stage8_contact_candidate(
    *,
    settings: Any | None,
    saleable_opportunity: Mapping[str, Any],
    legal_action_actor_profile: Mapping[str, Any] | None,
    procurement_decision_actor_profile: Mapping[str, Any] | None,
    inputs: Mapping[str, Any],
    now: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return select_contact_candidate(
        settings=settings,
        saleable_opportunity=saleable_opportunity,
        legal_action_actor_profile=legal_action_actor_profile,
        procurement_decision_actor_profile=procurement_decision_actor_profile,
        inputs=inputs,
        now=now,
    )


def build_source_vendor_payload(
    *,
    settings: Any | None,
    store: Any,
    candidate: Mapping[str, Any],
    project_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = resolve_source_vendor(
        settings=settings,
        candidate=candidate,
        project_id=project_id,
    )
    trace = dict(resolved.pop("source_resolution_trace", {}))
    payload = {
        **resolved,
        "source_vendor_type_optional": ensure_enum(
            store, "vendor_type", resolved.get("source_vendor_type_optional", "SOURCE_VENDOR")
        ),
        "source_vendor_role": ensure_enum(
            store, "vendor_role", resolved.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE")
        ),
    }
    return payload, trace


def build_execution_vendor_payload(
    *,
    settings: Any | None,
    store: Any,
    candidate: Mapping[str, Any],
    project_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = resolve_execution_vendor(
        settings=settings,
        candidate=candidate,
        project_id=project_id,
    )
    trace = dict(resolved.pop("execution_resolution_trace", {}))
    payload = {
        **resolved,
        "execution_vendor_type_optional": ensure_enum(
            store, "vendor_type", resolved.get("execution_vendor_type_optional", "EXECUTION_VENDOR")
        ),
        "execution_vendor_role_optional": ensure_enum(
            store, "vendor_role", resolved.get("execution_vendor_role_optional", "EXECUTION_VENDOR")
        ),
    }
    return payload, trace


def source_capability_family(source_vendor_role: str) -> str:
    if source_vendor_role == "CONTACT_ENRICHMENT_SOURCE":
        return "contact_enrichment"
    return "external_source"


def execution_action_intent(run_mode: str) -> str:
    return {
        "DRY_RUN": "DRY_RUN",
        "APPROVAL_RUN": "APPROVAL_EXECUTION",
        "REAL_RUN": "LIVE_EXECUTION",
    }.get(run_mode, "PREVIEW_ONLY")


def resolution_guard(
    trace: Mapping[str, Any],
    *,
    default_policy_state: str,
    blocked_reason: str,
) -> tuple[dict[str, Any], list[str], bool, bool]:
    resolution_state = str(trace.get("decision_state", "ALLOW")).upper()
    unresolved_reason = str(trace.get("unresolved_reason_optional") or "")
    metadata = {
        "policy_state": str(trace.get("policy_state") or default_policy_state),
    }
    reasons = [unresolved_reason or blocked_reason] if resolution_state == "BLOCK" else []
    if resolution_state == "BLOCK":
        metadata.update(
            {
                "current_status": "BLOCKED",
                "policy_state": "BLOCKED",
                "override_mode": "PERMANENTLY_BLOCKED",
            }
        )
    return metadata, reasons, resolution_state == "BLOCK", resolution_state == "REVIEW"


def build_governed_metadata(
    *,
    runtime_state: Any,
    requested_delivery_surface: str,
    projection_mode: str,
    run_mode: str,
    approval_state: str,
    writeback_targets: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "requested_delivery_surface": requested_delivery_surface,
        "projection_mode": projection_mode,
        "run_mode": run_mode,
        "approval_state": approval_state,
        "permission_decision_state": runtime_state.permission_decision_state,
        "governance_decision_state": runtime_state.governance_decision_state,
        "semantic_decision_state": runtime_state.semantic_decision_state,
        "policy_decision_state": runtime_state.decision_state,
        "candidate_compliance_decision": runtime_state.resolve("candidate_compliance_decision"),
        "execution_compliance_decision": runtime_state.resolve("execution_compliance_decision"),
        "stop_semantics": runtime_state.resolve("stop_semantics"),
        "permission_trace": runtime_state.capability_trace,
        "governance_trace": runtime_state.governance_trace,
        "semantic_trace": runtime_state.semantic_trace,
        "writeback_targets": ensure_list(writeback_targets),
    }


def contact_candidate_base(inputs: Mapping[str, Any], now: str) -> dict[str, Any]:
    return {
        "candidate_id": str(inputs.get("candidate_id", "single-input-candidate")),
        "org_name": inputs.get("org_name", "DEFAULT_ORG"),
        "org_type": inputs.get("org_type", "ENTERPRISE"),
        "person_name_optional": inputs.get("person_name_optional", "UNKNOWN"),
        "role_cluster": inputs.get("role_cluster", "PROCUREMENT_DECISION"),
        "public_contact_source": inputs.get("public_contact_source", "PUBLIC_SITE"),
        "source_family": inputs.get("source_family", "PROCUREMENT_NOTICE"),
        "source_auditability_state": inputs.get("source_auditability_state", "AUDITABLE"),
        "contact_channel": inputs.get("contact_channel", "EMAIL"),
        "channel_family": inputs.get("channel_family", "ORG_EMAIL"),
        "contact_validity_status": inputs.get("contact_validity_status", "UNKNOWN"),
        "contact_legal_basis": inputs.get("contact_legal_basis", "REVIEW_REQUIRED"),
        "reasonable_expectation_status": inputs.get("reasonable_expectation_status", "UNKNOWN"),
        "channel_policy_status": inputs.get("channel_policy_status", "REVIEW"),
        "frequency_policy_state": inputs.get("frequency_policy_state", "REVIEW"),
        "opt_out_state": inputs.get("opt_out_state", "PENDING_CONFIRMATION"),
        "quiet_hours_policy_state": inputs.get("quiet_hours_policy_state", "REVIEW"),
        "source_vendor_role": inputs.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE"),
        "last_evaluated_at": inputs.get("last_evaluated_at", now),
    }


def build_reselect_history(
    *,
    inputs: Mapping[str, Any],
    winning_contact_candidate_id: str,
    now: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    previous_candidate_id = (
        inputs.get("previous_contact_candidate_id_optional")
        or inputs.get("last_contact_candidate_id_optional")
        or inputs.get("previous_primary_contact_candidate_id_optional")
    )
    reselect_reason = inputs.get("reselect_reason_optional")
    if not reselect_reason:
        reselect_reason = {
            "WRONG_ROLE": "wrong_role_reselect_required",
            "INVALID_CONTACT": "invalid_contact_reselect_required",
            "OPPORTUNITY_CHANGED": "opportunity_changed_reselect_required",
            "DECLINED": "declined_contact_reselect_optional",
            "NO_RESPONSE": "no_response_reselect_optional",
        }.get(str(inputs.get("response_status", "")))
    if not previous_candidate_id or not reselect_reason or str(previous_candidate_id) == winning_contact_candidate_id:
        return (str(reselect_reason) if reselect_reason else None), []
    return (
        str(reselect_reason),
        [
            {
                "reselect_from_candidate_id": str(previous_candidate_id),
                "reselect_to_candidate_id": winning_contact_candidate_id,
                "reselect_reason": str(reselect_reason),
                "trigger_response_status": str(inputs.get("response_status", "UNKNOWN")),
                "recorded_at": now,
            }
        ],
    )


def build_contact_candidate_carriers(
    *,
    saleable_opportunity: Mapping[str, Any],
    inputs: Mapping[str, Any],
    now: str,
    selected_candidate: Mapping[str, Any],
    candidate_trace: Mapping[str, Any],
    multi_competitor_collection_id: str,
    winning_challenger_profile_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project_id = str(saleable_opportunity.get("project_id"))
    saleable_opportunity_id = str(saleable_opportunity.get("opportunity_id"))
    base = contact_candidate_base(inputs, now)
    resolved_candidates = candidate_trace.get("merged_candidates")
    raw_candidates = (
        list(resolved_candidates)
        if isinstance(resolved_candidates, list) and resolved_candidates
        else [dict(selected_candidate)]
    )
    candidate_lookup: dict[str, dict[str, Any]] = {}
    for index, raw_candidate in enumerate(raw_candidates, start=1):
        if not isinstance(raw_candidate, Mapping):
            continue
        candidate_id = str(raw_candidate.get("candidate_id", f"candidate-{index}"))
        candidate_lookup[candidate_id] = {
            **base,
            **dict(raw_candidate),
            "candidate_id": candidate_id,
        }
    selected_candidate_id = str(
        candidate_trace.get("selected_candidate_id", selected_candidate.get("candidate_id", base["candidate_id"]))
    )
    ordered_trace_entries = list(candidate_trace.get("ranked_candidates", []))
    if not ordered_trace_entries:
        ordered_trace_entries = [
            {
                "candidate_id": selected_candidate_id,
                "score": int(selected_candidate.get("contact_priority_score", 0)),
                "role_cluster": selected_candidate.get("role_cluster", base["role_cluster"]),
                "channel_family": selected_candidate.get("channel_family", base["channel_family"]),
                "organization_channel": True,
                "blocked": False,
            }
        ]

    candidate_list: list[dict[str, Any]] = []
    trace_entries: list[dict[str, Any]] = []
    for rank, trace_entry in enumerate(ordered_trace_entries, start=1):
        candidate_id = str(trace_entry.get("candidate_id", f"candidate-{rank}"))
        raw_candidate = candidate_lookup.get(candidate_id, {**base, **dict(selected_candidate), "candidate_id": candidate_id})
        selected_flag = candidate_id == selected_candidate_id
        candidate_item = {
            "candidate_id": candidate_id,
            "org_name": str(raw_candidate.get("org_name", base["org_name"])),
            "org_type": str(raw_candidate.get("org_type", base["org_type"])),
            "person_name_optional": str(raw_candidate.get("person_name_optional", base["person_name_optional"])),
            "role_cluster": str(raw_candidate.get("role_cluster", base["role_cluster"])),
            "public_contact_source": str(raw_candidate.get("public_contact_source", base["public_contact_source"])),
            "contact_channel": str(raw_candidate.get("contact_channel", base["contact_channel"])),
            "channel_family": str(raw_candidate.get("channel_family", base["channel_family"])),
            "source_family": str(raw_candidate.get("source_family", base["source_family"])),
            "source_auditability_state": str(raw_candidate.get("source_auditability_state", base["source_auditability_state"])),
            "merge_key": str(raw_candidate.get("merge_key", f"candidate_identity::{candidate_id}")),
            "merged_candidate_ids": ensure_list(raw_candidate.get("merged_candidate_ids", [candidate_id])),
            "merged_source_roles": ensure_list(raw_candidate.get("merged_source_roles", [raw_candidate.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE")])),
            "merged_source_vendor_ids_optional": ensure_list(raw_candidate.get("merged_source_vendor_ids_optional", [])),
            "formal_merge_state": str(raw_candidate.get("formal_merge_state", "NOT_REQUIRED_SINGLE_SOURCE")),
            "source_conflict_flag": bool(raw_candidate.get("source_conflict_flag", False)),
            "source_conflict_reason": str(raw_candidate.get("source_conflict_reason", "no_source_conflict")),
            "source_conflict_fields": ensure_list(raw_candidate.get("source_conflict_fields", [])),
            "source_merge_review_required": bool(raw_candidate.get("source_merge_review_required", False)),
            "contact_priority_score": int(trace_entry.get("score", raw_candidate.get("contact_priority_score", 0))),
            "contact_priority_reason_tags": ensure_list(
                raw_candidate.get(
                    "contact_priority_reason_tags",
                    selected_candidate.get("contact_priority_reason_tags", [] if not selected_flag else []),
                )
            ),
            "contact_candidate_rank": rank,
            "primary_contact_flag": selected_flag and bool(selected_candidate.get("primary_contact_flag", False)),
            "contact_conflict_flag": selected_flag and bool(candidate_trace.get("conflict_flag", False)),
            "contact_conflict_reason": str(
                candidate_trace.get("conflict_reason", "single candidate")
                if selected_flag and candidate_trace.get("conflict_flag", False)
                else "no_conflict"
            ),
            "contact_selection_reason": str(
                selected_candidate.get("contact_selection_reason", "resolver selection")
                if selected_flag
                else raw_candidate.get("contact_selection_reason", "ranked candidate")
            ),
            "contactability_snapshot": {
                "contact_validity_status": str(raw_candidate.get("contact_validity_status", base["contact_validity_status"])),
                "contact_legal_basis": str(raw_candidate.get("contact_legal_basis", base["contact_legal_basis"])),
                "reasonable_expectation_status": str(raw_candidate.get("reasonable_expectation_status", base["reasonable_expectation_status"])),
                "channel_policy_status": str(raw_candidate.get("channel_policy_status", base["channel_policy_status"])),
                "frequency_policy_state": str(raw_candidate.get("frequency_policy_state", base["frequency_policy_state"])),
                "opt_out_state": str(raw_candidate.get("opt_out_state", base["opt_out_state"])),
                "quiet_hours_policy_state": str(raw_candidate.get("quiet_hours_policy_state", base["quiet_hours_policy_state"])),
            },
            "selected_flag": selected_flag,
            "blocked": bool(trace_entry.get("blocked", False)),
        }
        candidate_list.append(candidate_item)
        trace_entries.append(
            {
                "candidate_id": candidate_id,
                "candidate_rank": rank,
                "score": int(trace_entry.get("score", candidate_item["contact_priority_score"])),
                "role_cluster": str(trace_entry.get("role_cluster", candidate_item["role_cluster"])),
                "channel_family": str(trace_entry.get("channel_family", candidate_item["channel_family"])),
                "merge_key": str(trace_entry.get("merge_key", candidate_item["merge_key"])),
                "merged_candidate_ids": ensure_list(trace_entry.get("merged_candidate_ids", candidate_item["merged_candidate_ids"])),
                "merged_source_roles": ensure_list(trace_entry.get("merged_source_roles", candidate_item["merged_source_roles"])),
                "source_conflict_flag": bool(trace_entry.get("source_conflict_flag", candidate_item["source_conflict_flag"])),
                "source_conflict_reason_optional": (
                    str(trace_entry.get("source_conflict_reason_optional", candidate_item["source_conflict_reason"]))
                    if bool(trace_entry.get("source_conflict_flag", candidate_item["source_conflict_flag"]))
                    else None
                ),
                "source_merge_review_required": bool(
                    trace_entry.get("source_merge_review_required", candidate_item["source_merge_review_required"])
                ),
                "organization_channel": bool(trace_entry.get("organization_channel", False)),
                "blocked": bool(trace_entry.get("blocked", False)),
                "selected_flag": selected_flag,
            }
        )

    winning_candidate = next(
        (item for item in candidate_list if item["candidate_id"] == selected_candidate_id),
        candidate_list[0],
    )
    winning_candidate_raw = candidate_lookup.get(
        winning_candidate["candidate_id"],
        {**base, **dict(selected_candidate), "candidate_id": winning_candidate["candidate_id"]},
    )
    winning_candidate_snapshot = {
        **winning_candidate_raw,
        **winning_candidate["contactability_snapshot"],
        "contact_priority_score": winning_candidate["contact_priority_score"],
        "contact_priority_reason_tags": winning_candidate["contact_priority_reason_tags"],
        "contact_candidate_rank": winning_candidate["contact_candidate_rank"],
        "primary_contact_flag": winning_candidate["primary_contact_flag"],
        "contact_conflict_flag": winning_candidate["contact_conflict_flag"],
        "contact_conflict_reason": winning_candidate["contact_conflict_reason"],
        "contact_selection_reason": winning_candidate["contact_selection_reason"],
        "merge_key": winning_candidate["merge_key"],
        "merged_candidate_ids": winning_candidate["merged_candidate_ids"],
        "merged_source_roles": winning_candidate["merged_source_roles"],
        "merged_source_vendor_ids_optional": winning_candidate["merged_source_vendor_ids_optional"],
        "formal_merge_state": winning_candidate["formal_merge_state"],
        "source_conflict_flag": winning_candidate["source_conflict_flag"],
        "source_conflict_reason": winning_candidate["source_conflict_reason"],
        "source_conflict_fields": winning_candidate["source_conflict_fields"],
        "source_merge_review_required": winning_candidate["source_merge_review_required"],
    }
    reselect_reason, reselect_history = build_reselect_history(
        inputs=inputs,
        winning_contact_candidate_id=winning_candidate["candidate_id"],
        now=now,
    )
    collection_id = build_id("CCOLL", project_id)
    selection_trace_id = build_id("CTRACE", project_id)
    collection_payload = {
        "contact_candidate_collection_id": collection_id,
        "saleable_opportunity_id": saleable_opportunity_id,
        "project_id": project_id,
        "multi_competitor_collection_id": multi_competitor_collection_id,
        "winning_challenger_profile_id": winning_challenger_profile_id,
        "candidate_list": candidate_list,
        "winning_contact_candidate_id": winning_candidate["candidate_id"],
        "selection_trace_id": selection_trace_id,
        "merge_policy_id": str(candidate_trace.get("merge_policy_id", "contact_candidate_formal_merge_v1")),
        "dedupe_applied": bool(candidate_trace.get("dedupe_applied", False)),
        "source_conflict_candidate_count": int(candidate_trace.get("source_conflict_candidate_count", 0)),
        "source_merge_review_required_count": int(
            candidate_trace.get("source_merge_review_required_count", 0)
        ),
        "reselect_reason_optional": reselect_reason,
        "reselect_history": reselect_history,
        "created_by_stage": 8,
        "downstream_consumer": [
            "contact_target",
            "outreach_plan",
            "touch_record",
        ],
    }
    trace_payload = {
        "contact_selection_trace_id": selection_trace_id,
        "contact_candidate_collection_id": collection_id,
        "saleable_opportunity_id": saleable_opportunity_id,
        "multi_competitor_collection_id": multi_competitor_collection_id,
        "winning_contact_candidate_id": winning_candidate["candidate_id"],
        "selection_policy_id": "contact_candidate_pool_equivalent_v1",
        "selection_basis": [
            "higher_score",
            "organization_channel_first",
            "auditability_auditable_first",
            "newer_last_evaluated_at_first",
        ],
        "merge_policy_id": str(candidate_trace.get("merge_policy_id", "contact_candidate_formal_merge_v1")),
        "dedupe_applied": bool(candidate_trace.get("dedupe_applied", False)),
        "source_conflict_candidate_count": int(candidate_trace.get("source_conflict_candidate_count", 0)),
        "source_merge_review_required_count": int(
            candidate_trace.get("source_merge_review_required_count", 0)
        ),
        "trace_entries": trace_entries,
        "winning_selection_reason": winning_candidate["contact_selection_reason"],
        "conflict_flag": bool(candidate_trace.get("conflict_flag", False)),
        "conflict_reason_optional": (
            str(candidate_trace.get("conflict_reason"))
            if candidate_trace.get("conflict_flag", False)
            else None
        ),
        "reselect_reason_optional": reselect_reason,
        "reselect_history": reselect_history,
        "created_by_stage": 8,
        "downstream_consumer": [
            "contact_target",
            "outreach_plan",
            "touch_record",
        ],
    }
    return collection_payload, trace_payload, winning_candidate_snapshot


__all__ = [
    "H07_AUTHORITATIVE_FIELDS",
    "build_contact_candidate_carriers",
    "build_execution_vendor_payload",
    "build_governed_metadata",
    "build_reselect_history",
    "build_source_vendor_payload",
    "contact_candidate_base",
    "execution_action_intent",
    "merge_stage7_authoritative_inputs",
    "resolution_guard",
    "select_stage8_contact_candidate",
    "source_capability_family",
]
