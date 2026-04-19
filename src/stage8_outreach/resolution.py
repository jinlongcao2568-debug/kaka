# Stage: stage8_outreach
# Consumes formal objects: contact_target, outreach_plan, touch_record
# Dependent handoff: H-07-STAGE7-TO-STAGE8, H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: contracts/sales/stage8_resolution_policy.json, contracts/sales/contact_priority_policy_catalog.json, contracts/sales/contact_compliance_matrix.json, contracts/sales/contact_source_policy_catalog.json, contracts/sales/vendor_registry_catalog.json, contracts/sales/source_vendor_usage_policy.json, contracts/sales/channel_vendor_execution_policy.json

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from shared.context_packet import ContextPacket
from shared.contract_loader import load_contract
from shared.policy_executor import (
    PolicyExecutor,
    _contact_priority_conflict,
    _contact_priority_organization_policy,
    _contact_priority_sort_key,
)
from shared.state_packet import StatePacket


def _policy(settings: Any | None = None) -> dict[str, Any]:
    return load_contract("contracts/sales/stage8_resolution_policy.json", settings)


def _vendor_registry(settings: Any | None = None) -> dict[str, Any]:
    return load_contract("contracts/sales/vendor_registry_catalog.json", settings)


def _contact_source_policy(settings: Any | None = None) -> dict[str, Any]:
    return load_contract("contracts/sales/contact_source_policy_catalog.json", settings)


def _source_vendor_usage(settings: Any | None = None) -> dict[str, Any]:
    return load_contract("contracts/sales/source_vendor_usage_policy.json", settings)


def _execution_vendor_policy(settings: Any | None = None) -> dict[str, Any]:
    return load_contract("contracts/sales/channel_vendor_execution_policy.json", settings)


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


def _normalized_text(value: Any | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.upper() in {"UNKNOWN", "NONE", "NULL", "N/A"}:
        return ""
    return text.casefold()


def _stage_range_matches(stage_range: str, stage: int) -> bool:
    token = str(stage_range or "").strip()
    if not token:
        return False
    if "-" in token:
        start_text, end_text = token.split("-", 1)
        try:
            return int(start_text) <= stage <= int(end_text)
        except ValueError:
            return False
    try:
        return int(token) == stage
    except ValueError:
        return False


def _stage8_source_usage_policy(
    usage_policies: list[Mapping[str, Any]],
    *,
    source_role: str,
) -> Mapping[str, Any] | None:
    return next(
        (
            entry
            for entry in usage_policies
            if str(entry.get("vendor_role")) == source_role
            and _stage_range_matches(str(entry.get("stage_range", "")), 8)
        ),
        None,
    )


def _stage8_execution_policy(
    execution_policies: list[Mapping[str, Any]],
    *,
    vendor_id: str,
) -> Mapping[str, Any] | None:
    return next(
        (
            entry
            for entry in execution_policies
            if str(entry.get("vendor_id")) == vendor_id and int(entry.get("stage", 0)) == 8
        ),
        None,
    )


def _source_fallback_vendor_id(
    *,
    candidate: Mapping[str, Any],
    registry: Mapping[str, Mapping[str, Any]],
    source_role: str,
    selected_vendor_id: str | None,
) -> str:
    explicit_fallback = str(candidate.get("fallback_vendor_id_optional") or "")
    if (
        explicit_fallback
        and explicit_fallback in registry
        and explicit_fallback != selected_vendor_id
        and str(registry[explicit_fallback].get("vendor_role")) == source_role
    ):
        return explicit_fallback
    alternate_vendor_id = next(
        (
            vendor_id
            for vendor_id, entry in registry.items()
            if vendor_id != selected_vendor_id and str(entry.get("vendor_role")) == source_role
        ),
        None,
    )
    if alternate_vendor_id:
        return str(alternate_vendor_id)
    return str(selected_vendor_id or candidate.get("source_vendor_id_optional") or "")


def _execution_fallback_vendor_id(
    *,
    candidate: Mapping[str, Any],
    registry: Mapping[str, Mapping[str, Any]],
    allowed_vendor_ids: list[str],
    selected_vendor_id: str | None,
) -> str:
    explicit_fallback = str(candidate.get("execution_fallback_vendor_id_optional") or "")
    if (
        explicit_fallback
        and explicit_fallback in registry
        and explicit_fallback != selected_vendor_id
        and explicit_fallback in allowed_vendor_ids
    ):
        return explicit_fallback
    alternate_vendor_id = next(
        (
            vendor_id
            for vendor_id in allowed_vendor_ids
            if vendor_id != selected_vendor_id and vendor_id in registry
        ),
        None,
    )
    if alternate_vendor_id:
        return str(alternate_vendor_id)
    return str(selected_vendor_id or candidate.get("execution_vendor_id_optional") or "")


def _candidate_policy_state(
    executor: PolicyExecutor,
    context: ContextPacket,
) -> tuple[StatePacket, dict[str, Any]]:
    state = StatePacket(capability_mode="stage8_candidate_selection")
    decisions: dict[str, Any] = {}
    for policy_key in ("contact_source_policy", "contact_compliance", "contact_priority"):
        decision = executor.execute(policy_key, context, state)
        state.add_decision(decision)
        decisions[policy_key] = decision
    return state, decisions


def _match_key(candidate: Mapping[str, Any], merge_policy: Mapping[str, Any]) -> str:
    for entry in merge_policy.get("matchKeyOrder", []):
        key = str(entry.get("key", "candidate_identity"))
        fields = [str(field) for field in entry.get("fields", [])]
        normalized_parts = [_normalized_text(candidate.get(field)) for field in fields]
        if all(normalized_parts):
            return f"{key}::{'::'.join(normalized_parts)}"
    candidate_id = _normalized_text(candidate.get("candidate_id")) or "unknown"
    return f"candidate_identity::{candidate_id}"


def _source_priority_weight(candidate: Mapping[str, Any], source_policy_entry: Mapping[str, Any]) -> int:
    role = str(candidate.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE"))
    weights = source_policy_entry.get("sourcePriorityWeights", {})
    try:
        return int(weights.get(role, 0))
    except (TypeError, ValueError):
        return 0


def _candidate_merge_sort_key(
    candidate: Mapping[str, Any],
    source_policy_entry: Mapping[str, Any],
) -> tuple[int, int, float, str]:
    return (
        -_source_priority_weight(candidate, source_policy_entry),
        0 if str(candidate.get("source_auditability_state", "UNKNOWN")) == "AUDITABLE" else 1,
        -_parse_time(str(candidate.get("last_evaluated_at"))).timestamp(),
        str(candidate.get("candidate_id", "")),
    )


def _distinct_values(group: list[Mapping[str, Any]], field_name: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for candidate in group:
        value = candidate.get(field_name)
        normalized = _normalized_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        values.append(str(value))
    return values


def _merged_candidate_snapshot(
    group: list[dict[str, Any]],
    *,
    merge_key: str,
    merge_policy: Mapping[str, Any],
    source_policy_entry: Mapping[str, Any],
) -> dict[str, Any]:
    ordered = sorted(group, key=lambda item: _candidate_merge_sort_key(item, source_policy_entry))
    primary = dict(ordered[0])
    merged = dict(primary)
    for candidate in ordered[1:]:
        for field_name, value in candidate.items():
            if field_name == "candidate_id":
                continue
            existing = merged.get(field_name)
            if _normalized_text(existing):
                continue
            if _normalized_text(value):
                merged[field_name] = value

    source_conflict_fields = [
        field_name
        for field_name in merge_policy.get("sourceConflictFields", [])
        if len(_distinct_values(ordered, str(field_name))) > 1
    ]
    review_required_fields = {
        str(field_name) for field_name in merge_policy.get("sourceConflictReviewRequiredFields", [])
    }
    merged_candidate_ids = [str(candidate.get("candidate_id")) for candidate in ordered]
    merged_source_roles = list(dict.fromkeys(str(candidate.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE")) for candidate in ordered))
    merged_source_vendor_ids_optional = [
        str(candidate.get("source_vendor_id_optional"))
        for candidate in ordered
        if candidate.get("source_vendor_id_optional") not in (None, "")
    ]
    formal_merge_required_roles = {
        str(role) for role in merge_policy.get("formalMergeRequiredSourceRoles", [])
    }
    primary_source_role = str(primary.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE"))
    source_merge_review_required = bool(
        set(source_conflict_fields) & review_required_fields
        or (len(ordered) == 1 and primary_source_role in formal_merge_required_roles)
    )
    if len(ordered) > 1:
        formal_merge_state = "FORMAL_MERGED_MULTI_SOURCE"
    elif primary_source_role in formal_merge_required_roles:
        formal_merge_state = "REVIEW_REQUIRED_SINGLE_THIRD_PARTY"
    else:
        formal_merge_state = "NOT_REQUIRED_SINGLE_SOURCE"

    merged.update(
        {
            "merge_key": merge_key,
            "merged_candidate_ids": merged_candidate_ids,
            "merged_source_roles": merged_source_roles,
            "merged_source_vendor_ids_optional": merged_source_vendor_ids_optional,
            "formal_merge_state": formal_merge_state,
            "source_conflict_flag": bool(source_conflict_fields),
            "source_conflict_reason": (
                "source_conflict:" + ",".join(source_conflict_fields)
                if source_conflict_fields
                else "no_source_conflict"
            ),
            "source_conflict_fields": source_conflict_fields,
            "source_merge_review_required": source_merge_review_required,
        }
    )
    return merged


def _base_candidate(inputs: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    return {
        "candidate_id": str(inputs.get("candidate_id", "single-input-candidate")),
        "org_name": inputs.get("org_name", "DEFAULT_ORG"),
        "org_type": inputs.get("org_type", "ENTERPRISE"),
        "person_name_optional": inputs.get("person_name_optional", "UNKNOWN"),
        "role_cluster": inputs.get("role_cluster", "PROCUREMENT_DECISION"),
        "public_contact_source": inputs.get("public_contact_source", "PUBLIC_SITE"),
        "source_family": inputs.get("source_family", "PROCUREMENT_NOTICE"),
        "source_auditability_state": inputs.get("source_auditability_state", "AUDITABLE"),
        "source_vendor_role": inputs.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE"),
        "source_vendor_id_optional": inputs.get("source_vendor_id_optional"),
        "source_vendor_type_optional": inputs.get("source_vendor_type_optional"),
        "source_audit_ref": inputs.get("source_audit_ref", inputs.get("source_document_ref")),
        "query_trace_id": inputs.get("query_trace_id"),
        "vendor_response_ref_optional": inputs.get("vendor_response_ref_optional", inputs.get("source_slice_ref")),
        "fallback_vendor_id_optional": inputs.get("fallback_vendor_id_optional"),
        "contact_channel": inputs.get("contact_channel", "EMAIL"),
        "channel_family": inputs.get("channel_family", "ORG_EMAIL"),
        "contact_validity_status": inputs.get("contact_validity_status", "UNKNOWN"),
        "contact_legal_basis": inputs.get("contact_legal_basis", "REVIEW_REQUIRED"),
        "reasonable_expectation_status": inputs.get("reasonable_expectation_status", "UNKNOWN"),
        "channel_policy_status": inputs.get("channel_policy_status", "REVIEW"),
        "frequency_policy_state": inputs.get("frequency_policy_state", "REVIEW"),
        "opt_out_state": inputs.get("opt_out_state", "PENDING_CONFIRMATION"),
        "quiet_hours_policy_state": inputs.get("quiet_hours_policy_state", "REVIEW"),
        "last_evaluated_at": inputs.get("last_evaluated_at", now),
    }


def resolve_source_vendor(
    *,
    settings: Any | None,
    candidate: Mapping[str, Any],
    project_id: str,
) -> dict[str, Any]:
    policy = _policy(settings)["sourceVendorResolution"]
    registry = {entry["vendor_id"]: entry for entry in _vendor_registry(settings)["entries"]}
    usage = _source_vendor_usage(settings)["stagePolicies"]

    explicit_vendor_id = candidate.get("source_vendor_id_optional")
    source_role = str(candidate.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE"))
    usage_policy = _stage8_source_usage_policy(usage, source_role=source_role)
    authorized_source_roles = {str(role) for role in policy.get("authorizedSourceRoles", [])}
    resolved_from = "POLICY_DEFAULT"
    selected_vendor_id: str | None = None
    resolution_state = "ALLOW"
    unresolved_reason = ""
    if explicit_vendor_id not in (None, ""):
        explicit_vendor_id = str(explicit_vendor_id)
        if explicit_vendor_id in registry and str(registry[explicit_vendor_id].get("vendor_role")) == source_role:
            selected_vendor_id = explicit_vendor_id
            resolved_from = "EXPLICIT_INPUT"
        elif explicit_vendor_id in registry:
            resolved_from = "EXPLICIT_ROLE_MISMATCH"
            resolution_state = "BLOCK"
            unresolved_reason = "source_vendor_role_mismatch"
        else:
            resolved_from = "EXPLICIT_UNKNOWN_VENDOR"
            resolution_state = "BLOCK"
            unresolved_reason = "source_vendor_not_in_registry"
    elif source_role not in authorized_source_roles or usage_policy is None:
        resolved_from = "ROLE_POLICY_UNRESOLVED"
        resolution_state = "BLOCK"
        unresolved_reason = "source_role_not_authorized_for_stage8"
    else:
        preferred = next(
            (entry["preferredVendorIds"] for entry in policy["resolutionOrder"] if entry["source_role"] == source_role),
            [],
        )
        for vendor_id in preferred:
            if vendor_id in registry and str(registry[vendor_id].get("vendor_role")) == source_role:
                selected_vendor_id = vendor_id
                break
        if not selected_vendor_id:
            for vendor_id, entry in registry.items():
                if str(entry.get("vendor_role")) == source_role:
                    selected_vendor_id = vendor_id
                    resolved_from = "REGISTRY_FALLBACK"
                    break
    if not selected_vendor_id:
        resolution_state = "BLOCK"
        if not unresolved_reason:
            resolved_from = "POLICY_UNRESOLVED"
            unresolved_reason = "no_registered_vendor_for_source_role"

    resolved_vendor_id = str(selected_vendor_id or explicit_vendor_id or "")
    vendor_entry = registry.get(resolved_vendor_id, {})
    fallback_vendor_id = _source_fallback_vendor_id(
        candidate=candidate,
        registry=registry,
        source_role=source_role,
        selected_vendor_id=selected_vendor_id,
    )
    return {
        "source_vendor_id_optional": resolved_vendor_id,
        "source_vendor_type_optional": candidate.get("source_vendor_type_optional", vendor_entry.get("vendor_type", "SOURCE_VENDOR")),
        "source_vendor_role": source_role,
        "source_audit_ref": candidate.get("source_audit_ref") or f"AUDIT-{project_id}",
        "query_trace_id": candidate.get("query_trace_id") or f"TRACE-{project_id}-SOURCE",
        "vendor_response_ref_optional": candidate.get("vendor_response_ref_optional") or f"RESP-{project_id}",
        "fallback_vendor_id_optional": fallback_vendor_id,
        "source_resolution_trace": {
            "resolved_from": resolved_from,
            "policy_state": usage_policy.get("usage_state") if usage_policy else "UNSPECIFIED",
            "candidate_role": source_role,
            "decision_state": resolution_state,
            "unresolved_reason_optional": unresolved_reason or None,
            "registry_vendor_matched": bool(selected_vendor_id),
        },
    }


def resolve_execution_vendor(
    *,
    settings: Any | None,
    candidate: Mapping[str, Any],
    project_id: str,
) -> dict[str, Any]:
    policy = _policy(settings)["executionVendorResolution"]
    registry = {entry["vendor_id"]: entry for entry in _vendor_registry(settings)["entries"]}
    execution_policy_entries = _execution_vendor_policy(settings)["entries"]

    channel_family = str(candidate.get("channel_family", "ORG_EMAIL"))
    explicit_vendor_id = candidate.get("execution_vendor_id_optional")
    resolved_from = "POLICY_DEFAULT"
    selected_vendor_id: str | None = None
    allowed_vendor_ids = policy["channelFamilyToVendorIds"].get(channel_family, [])
    resolution_state = "ALLOW"
    unresolved_reason = ""
    if explicit_vendor_id not in (None, ""):
        explicit_vendor_id = str(explicit_vendor_id)
        if explicit_vendor_id in registry and explicit_vendor_id in allowed_vendor_ids:
            selected_vendor_id = explicit_vendor_id
            resolved_from = "EXPLICIT_INPUT"
        elif explicit_vendor_id in registry:
            resolved_from = "EXPLICIT_CHANNEL_MISMATCH"
            resolution_state = "BLOCK"
            unresolved_reason = "execution_vendor_not_allowed_for_channel"
        else:
            resolved_from = "EXPLICIT_UNKNOWN_VENDOR"
            resolution_state = "BLOCK"
            unresolved_reason = "execution_vendor_not_in_registry"
    else:
        for vendor_id in allowed_vendor_ids:
            if vendor_id in registry:
                selected_vendor_id = vendor_id
                break
    if not selected_vendor_id:
        resolution_state = "BLOCK"
        if not unresolved_reason:
            resolved_from = "CHANNEL_POLICY_UNRESOLVED"
            unresolved_reason = (
                "channel_family_not_configured_for_execution_vendor"
                if not allowed_vendor_ids
                else "no_registered_execution_vendor_for_channel"
            )
    resolved_vendor_id = str(selected_vendor_id or explicit_vendor_id or "")
    vendor_entry = registry.get(resolved_vendor_id, {})
    execution_policy = (
        _stage8_execution_policy(execution_policy_entries, vendor_id=resolved_vendor_id)
        if resolved_vendor_id
        else None
    )
    fallback_vendor_id = _execution_fallback_vendor_id(
        candidate=candidate,
        registry=registry,
        allowed_vendor_ids=[str(vendor_id) for vendor_id in allowed_vendor_ids],
        selected_vendor_id=selected_vendor_id,
    )
    return {
        "execution_vendor_id_optional": resolved_vendor_id,
        "execution_vendor_type_optional": candidate.get("execution_vendor_type_optional", vendor_entry.get("vendor_type", "EXECUTION_VENDOR")),
        "execution_vendor_role_optional": candidate.get("execution_vendor_role_optional", vendor_entry.get("vendor_role", "EXECUTION_VENDOR")),
        "execution_trace_id_optional": candidate.get("execution_trace_id_optional") or f"TRACE-{project_id}-EXEC",
        "vendor_response_ref_optional": candidate.get("execution_vendor_response_ref_optional") or candidate.get("vendor_response_ref_optional") or f"EXEC-RESP-{project_id}",
        "fallback_vendor_id_optional": fallback_vendor_id,
        "execution_resolution_trace": {
            "resolved_from": resolved_from,
            "channel_family": channel_family,
            "policy_state": execution_policy.get("execution_policy_state") if execution_policy else "UNSPECIFIED",
            "decision_state": resolution_state,
            "unresolved_reason_optional": unresolved_reason or None,
            "registry_vendor_matched": bool(selected_vendor_id),
        },
    }


def select_contact_candidate(
    *,
    settings: Any | None,
    saleable_opportunity: Any,
    legal_action_actor_profile: Mapping[str, Any] | None,
    procurement_decision_actor_profile: Mapping[str, Any] | None,
    inputs: Mapping[str, Any],
    now: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = _policy(settings)["candidateCollection"]
    executor = PolicyExecutor(settings)
    priority_policy = executor.load_policy("contact_priority")["policies"][0]
    organization_policy = _contact_priority_organization_policy(priority_policy)
    merge_policy = policy.get("mergePolicy", {})
    source_policy_entry = next(
        (
            entry
            for entry in _contact_source_policy(settings).get("entries", [])
            if str(entry.get("objectType")) == "contact_target" and int(entry.get("stage", 0)) == 8
        ),
        {},
    )
    base = _base_candidate(inputs, now=now)
    pool = inputs.get("contact_candidate_pool")
    candidates = list(pool) if isinstance(pool, list) and pool else [base]

    grouped_candidates: dict[str, list[dict[str, Any]]] = {}
    for index, candidate in enumerate(candidates, start=1):
        merged = {
            **base,
            **dict(candidate),
            "candidate_id": str(dict(candidate).get("candidate_id", f"candidate-{index}")),
        }
        merge_key = _match_key(merged, merge_policy)
        grouped_candidates.setdefault(merge_key, []).append(merged)

    ranked: list[dict[str, Any]] = []
    for merge_key, group in grouped_candidates.items():
        merged = _merged_candidate_snapshot(
            group,
            merge_key=merge_key,
            merge_policy=merge_policy,
            source_policy_entry=source_policy_entry,
        )
        context = ContextPacket.from_records(
            capability_mode="stage8_outreach",
            stage=8,
            project_id=str(saleable_opportunity.get("project_id")),
            records={
                "saleable_opportunity": saleable_opportunity,
                "legal_action_actor_profile": legal_action_actor_profile or {},
                "procurement_decision_actor_profile": procurement_decision_actor_profile or {},
            },
            inputs=merged,
        )
        candidate_state, decisions = _candidate_policy_state(executor, context)
        source_decision = decisions["contact_source_policy"]
        compliance_decision = decisions["contact_compliance"]
        priority_decision = decisions["contact_priority"]
        blocked = source_decision.decision_state == "BLOCK" or str(
            candidate_state.resolve("candidate_compliance_decision", "REVIEW_REQUIRED")
        ) == "BLOCKED"
        score = int(candidate_state.resolve("contact_priority_score", 0))
        ranked.append(
            {
                **merged,
                "score": score,
                "priority_trace": priority_decision.trace,
                "policy_trace": [decision.trace for decision in decisions.values()],
                "blocked": blocked,
                "requires_manual_review": bool(
                    candidate_state.resolve("requires_manual_review", False)
                ),
                "organization_channel": bool(
                    candidate_state.resolve("organization_channel_flag", False)
                ),
                "organization_first_eligible": bool(
                    candidate_state.resolve("organization_first_eligible", False)
                ),
                "selected_reason": str(
                    candidate_state.resolve("contact_selection_reason", "resolver selection")
                ),
                "contact_priority_reason_tags": candidate_state.resolve(
                    "contact_priority_reason_tags",
                    [],
                ),
                "candidate_compliance_decision": str(
                    candidate_state.resolve("candidate_compliance_decision", "REVIEW_REQUIRED")
                ),
                "execution_compliance_decision": str(
                    candidate_state.resolve("execution_compliance_decision", "REVIEW_REQUIRED")
                ),
                "source_policy_decision": str(
                    candidate_state.resolve("source_policy_decision", source_decision.decision_state)
                ),
                "legal_basis_weight": int(candidate_state.resolve("legal_basis_weight", 0)),
                "source_auditability_rank": int(
                    candidate_state.resolve("source_auditability_rank", 0)
                ),
            }
        )

    eligible = [candidate for candidate in ranked if not candidate["blocked"]]
    org_eligible = [
        candidate for candidate in eligible if candidate["organization_first_eligible"]
    ]
    selection_pool = org_eligible or eligible or ranked
    selection_pool.sort(key=lambda item: _contact_priority_sort_key(priority_policy, item))

    selected = dict(selection_pool[0])
    baseline_conflict_flag = bool(
        selected["priority_trace"]["outputs"].get("contact_conflict_flag", False)
    )
    baseline_conflict_reason = str(
        selected["priority_trace"]["outputs"].get("contact_conflict_reason", "single candidate")
    )
    conflict_flag, conflict_reason = _contact_priority_conflict(priority_policy, selection_pool)
    if baseline_conflict_flag:
        conflict_flag = True
        if not conflict_reason or conflict_reason == "single candidate":
            conflict_reason = baseline_conflict_reason

    selected["primary_contact_flag"] = bool(
        int(selected["score"]) >= int(organization_policy["minimum_primary_score"])
        and not selected["blocked"]
        and not conflict_flag
        and (
            selected["organization_channel"]
            or (
                not org_eligible
                and organization_policy[
                    "personal_primary_allowed_when_org_path_unavailable"
                ]
            )
        )
    )
    selected["contact_priority_score"] = int(selected["score"])
    selected["contact_priority_reason_tags"] = selected.get(
        "contact_priority_reason_tags", []
    )
    selected["contact_candidate_rank"] = 1
    selection_reason = selected["selected_reason"]
    if selected["organization_channel"]:
        selection_reason = f"organization_first_selected;{selection_reason}"
    elif not org_eligible:
        selection_reason = f"organization_path_unavailable;{selection_reason}"
    selected["contact_selection_reason"] = selection_reason
    selected["contact_conflict_flag"] = conflict_flag
    selected["contact_conflict_reason"] = conflict_reason
    selected["requires_manual_review"] = bool(
        selected.get("requires_manual_review", False)
        or selected.get("source_merge_review_required", False)
        or conflict_flag
    )
    selected["priority_trace"]["outputs"].update(
        {
            "primary_contact_flag": selected["primary_contact_flag"],
            "contact_selection_reason": selected["contact_selection_reason"],
            "contact_conflict_flag": conflict_flag,
            "contact_conflict_reason": conflict_reason,
            "requires_manual_review": selected["requires_manual_review"],
        }
    )

    trace = {
        "candidate_pool_mode": "CONTACT_TARGET_EQUIVALENT_COLLECTION",
        "candidate_pool_count": len(ranked),
        "input_candidate_count": len(candidates),
        "merge_policy_id": str(merge_policy.get("policyId", "contact_candidate_formal_merge_v1")),
        "dedupe_applied": len(ranked) != len(candidates),
        "source_conflict_candidate_count": sum(1 for candidate in ranked if candidate.get("source_conflict_flag")),
        "source_merge_review_required_count": sum(
            1 for candidate in ranked if candidate.get("source_merge_review_required")
        ),
        "eligible_candidate_count": len(eligible),
        "selected_candidate_id": selected["candidate_id"],
        "selected_candidate_source": (
            "formal_merge"
            if selected.get("formal_merge_state") != "NOT_REQUIRED_SINGLE_SOURCE"
            or len(selected.get("merged_candidate_ids", [])) > 1
            else ("candidate_pool" if len(candidates) > 1 else "single_input_projection")
        ),
        "merged_candidates": [
            {
                key: value
                for key, value in candidate.items()
                if key not in {"priority_trace", "policy_trace"}
            }
            for candidate in ranked
        ],
        "ranked_candidates": [
            {
                "candidate_id": entry["candidate_id"],
                "score": entry["score"],
                "role_cluster": entry.get("role_cluster"),
                "channel_family": entry.get("channel_family"),
                "merge_key": entry.get("merge_key"),
                "merged_candidate_ids": entry.get("merged_candidate_ids", []),
                "merged_source_roles": entry.get("merged_source_roles", []),
                "source_conflict_flag": bool(entry.get("source_conflict_flag", False)),
                "source_conflict_reason_optional": (
                    entry.get("source_conflict_reason")
                    if entry.get("source_conflict_flag", False)
                    else None
                ),
                "source_merge_review_required": bool(entry.get("source_merge_review_required", False)),
                "organization_channel": entry["organization_channel"],
                "candidate_compliance_decision": entry.get(
                    "candidate_compliance_decision"
                ),
                "execution_compliance_decision": entry.get(
                    "execution_compliance_decision"
                ),
                "source_policy_decision": entry.get("source_policy_decision"),
                "blocked": entry["blocked"],
            }
            for entry in selection_pool
        ],
        "conflict_flag": conflict_flag,
        "conflict_reason": conflict_reason,
    }
    return selected, trace


__all__ = [
    "resolve_execution_vendor",
    "resolve_source_vendor",
    "select_contact_candidate",
]
