# Stage: stage2_ingestion
# Consumes formal objects: public_chain, clock_chain_profile, notice_version_chain, fixation_bundle
# Dependent handoff: H-01-STAGE1-TO-STAGE2, H-02-STAGE2-TO-STAGE3
# Dependent schema/contracts: contracts/governance/source_registry.json, contracts/governance/route_policy_catalog.json, handoff/stage1_to_stage2/contract.json, handoff/stage2_to_stage3/contract.json

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import ensure_enum, ensure_enum_or_fallback, get_flag


@dataclass(frozen=True)
class Stage2Extraction:
    project_id: str
    source_registry_id: str
    source_registry_id_source: str
    route_policy_id: str
    route_policy_id_source: str
    source_family: str
    platform_level: str
    region_scope: str
    coverage_tier: str
    carrier_type: str
    origin_carrier_type: str
    default_route: str
    default_route_source: str
    fallback_route: str
    fallback_route_source: str
    route_decision_state: str
    route_review_reasons: list[str]
    route_downgrade_signals: list[str]
    route_block_signals: list[str]
    baseline_collection_state: str
    collection_state: str
    rollout_enabled: bool
    backlog_reason_optional: str | None
    clock_conflict_state: str
    version_conflict_state: str
    version_precedence_rule_id: str
    version_precedence_source: str
    clock_precedence_rule_id: str
    clock_precedence_source: str
    first_seen_at: str
    last_retrieved_at: str
    window_clock_state: str
    timeline_nodes: list[str]
    required_node_set: list[str]
    node_presence_matrix: dict[str, Any]
    statutory_node_completeness: bool
    current_notice_version_id: str
    superseded_version_ids: list[str]
    replacement_edges: list[Any]
    version_chain_strategy: str
    winning_version_resolution_rule_id: str
    clock_resolution_rule_id: str
    clock_resolution_rule_source: str
    current_action_start_at_optional: str | None
    current_action_deadline_at_optional: str | None
    source_url: str
    content_hash: str
    storage_path: str
    source_entry: dict[str, Any]
    route_policy: dict[str, Any]


def _resolve_precedence_rule_from_order(
    precedence_order: list[Any],
    candidate_values: Mapping[str, Any],
    *,
    compatibility_default: str,
) -> tuple[str, str]:
    for source_name_raw in precedence_order:
        source_name = str(source_name_raw)
        candidate = candidate_values.get(source_name)
        text = str(candidate or "").strip()
        if not text or text.endswith("DEFAULT"):
            continue
        return text, source_name.split(".", 1)[0]
    return compatibility_default, "compatibility_default"


def _resolve_authoritative_text(
    *candidates: tuple[str, Any],
    fallback: str,
    default_source: str,
) -> tuple[str, str]:
    for source_name, candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text, source_name
    return fallback, default_source


def _collection_state(
    flags: Mapping[str, Any],
    *,
    store: ContractStore,
    route_policy: Mapping[str, Any],
    baseline_collection_state: str,
    requires_manual_review: bool,
    rollout_enabled: bool,
    version_precedence_source: str,
    clock_precedence_source: str,
    authority_review_required: bool,
) -> tuple[str, str]:
    runtime_map = route_policy.get("collection_state_runtime_map", {})
    baseline_to_runtime = runtime_map.get("baseline_to_runtime", {})
    success_state = ensure_enum_or_fallback(
        store,
        "collection_state",
        runtime_map.get("success_state"),
        fallback="PARSED",
    )
    review_state = ensure_enum_or_fallback(
        store,
        "collection_state",
        runtime_map.get("review_state"),
        fallback="REVIEW_REQUIRED",
    )
    block_state = ensure_enum_or_fallback(
        store,
        "collection_state",
        runtime_map.get("block_state"),
        fallback="BLOCKED",
    )
    baseline_projected = ensure_enum_or_fallback(
        store,
        "collection_state",
        baseline_to_runtime.get(baseline_collection_state),
        fallback=review_state,
    )

    if get_flag(flags, "robots_block") or baseline_collection_state == "BLOCKED":
        state = block_state
    elif (
        get_flag(flags, "coverage_review")
        or requires_manual_review
        or not rollout_enabled
        or get_flag(flags, "version_conflict")
        or get_flag(flags, "clock_conflict")
        or version_precedence_source == "compatibility_default"
        or clock_precedence_source == "compatibility_default"
        or authority_review_required
        or baseline_projected == review_state
    ):
        state = review_state
    else:
        state = success_state

    if get_flag(flags, "clock_conflict"):
        conflict = "CONFLICTING"
    elif get_flag(flags, "missing_source") or clock_precedence_source == "compatibility_default":
        conflict = "UNRESOLVED"
    else:
        conflict = "CONSISTENT"
    return state, conflict


def _route_decision(
    *,
    route_policy: Mapping[str, Any],
    flags: Mapping[str, Any],
    route_review_reasons: list[str],
    collection_state: str,
) -> tuple[str, list[str], list[str]]:
    decision = str(route_policy.get("default_decision", "ALLOW"))
    downgrade_signals: list[str] = []
    block_signals: list[str] = []

    if get_flag(flags, "coverage_review"):
        downgrade_signals.extend([str(item) for item in route_policy.get("downgrade_signals", [])])
    if get_flag(flags, "robots_block"):
        block_signals.extend([str(item) for item in route_policy.get("blocked_signals", [])])
        decision = "BLOCK"
    elif collection_state == "BLOCKED":
        decision = "BLOCK"
    elif route_review_reasons or collection_state == "REVIEW_REQUIRED" or decision in {"REVIEW", "FALLBACK"}:
        decision = "REVIEW"
    else:
        decision = "ALLOW"

    return decision, downgrade_signals, block_signals


def extract_stage2(stage1_bundle: StageBundle, store: ContractStore, *, now: str) -> Stage2Extraction:
    inputs = stage1_bundle.inputs or {}
    flags = inputs.get("flags", {})
    execution_context = stage1_bundle.record("execution_context")
    clock_strategy_profile = stage1_bundle.record("clock_strategy_profile")
    handoff = stage1_bundle.handoff or {}

    authority_fields = (
        "source_registry_id",
        "route_policy_id",
        "default_route",
        "fallback_route",
        "clock_resolution_rule_id",
        "clock_precedence_rule_id",
    )
    authority_review_reasons = [
        f"missing_h01_authority_field:{field_name}"
        for field_name in authority_fields
        if handoff.get(field_name) in (None, "")
    ]
    source_registry_id_source = "h01_authority" if handoff.get("source_registry_id") else "execution_context_authority_fallback"
    route_policy_id_source = "h01_authority" if handoff.get("route_policy_id") else "execution_context_authority_fallback"
    default_route_source = "h01_authority" if handoff.get("default_route") else "execution_context_authority_fallback"
    fallback_route_source = "h01_authority" if handoff.get("fallback_route") else "execution_context_authority_fallback"
    source_registry_id = str(handoff.get("source_registry_id") or execution_context.get("source_registry_id"))
    route_policy_id = str(handoff.get("route_policy_id") or execution_context.get("route_policy_id"))
    carrier_authority = handoff.get("carrier_type") or execution_context.get("carrier_type") or inputs.get("carrier_type")
    default_route = ensure_enum_or_fallback(
        store,
        "route_type",
        handoff.get("default_route"),
        fallback=str(execution_context.get("default_route", "")),
    )
    fallback_route = ensure_enum_or_fallback(
        store,
        "route_type",
        handoff.get("fallback_route") or execution_context.get("fallback_route"),
        fallback=default_route,
    )
    source_entry = store.resolve_source_entry(
        source_registry_id=source_registry_id,
        source_family=str(execution_context.get("source_family")),
        platform_level=str(execution_context.get("platform_level")),
        region_scope=str(execution_context.get("region_scope")),
        coverage_tier=str(execution_context.get("coverage_tier")),
        carrier_type=ensure_enum(store, "carrier_type", carrier_authority),
    )
    route_policy = store.resolve_route_policy(
        route_policy_id=route_policy_id,
        source_registry_id=source_registry_id,
        source_family=str(execution_context.get("source_family")),
    )
    expected_default_route = ensure_enum_or_fallback(
        store,
        "route_type",
        source_entry.get("default_route") or route_policy.get("default_route"),
        fallback=str(route_policy.get("default_route", default_route)),
    )
    expected_fallback_route = ensure_enum_or_fallback(
        store,
        "route_type",
        source_entry.get("fallback_route") or route_policy.get("fallback_route"),
        fallback=default_route,
    )
    if default_route != expected_default_route:
        authority_review_reasons.append("default_route_mismatch_requires_review")
    if fallback_route != expected_fallback_route:
        authority_review_reasons.append("fallback_route_mismatch_requires_review")
    baseline_collection_state = ensure_enum_or_fallback(
        store,
        "collection_state",
        handoff.get("baseline_collection_state") or str(source_entry.get("collection_state", "")) or None,
        fallback="DISCOVERED",
    )
    rollout_enabled_raw = handoff.get("rollout_enabled")
    rollout_enabled = bool(rollout_enabled_raw) if rollout_enabled_raw is not None else bool(source_entry.get("rollout_enabled", True))
    backlog_reason_raw = handoff.get("backlog_reason_optional")
    if backlog_reason_raw is None and "backlog_reason_optional" not in handoff:
        backlog_reason_raw = source_entry.get("backlog_reason_optional")
    backlog_reason_optional = str(backlog_reason_raw) if backlog_reason_raw is not None else None
    version_relation = route_policy.get("version_chain_relation", {})
    version_precedence_rule_id, version_precedence_source = _resolve_precedence_rule_from_order(
        list(
            version_relation.get(
                "precedence_order",
                [
                    "payload.winning_version_resolution_rule_id",
                    "source_registry.winning_version_resolution_rule_id",
                    "route_policy.version_chain_relation.winning_version_resolution_rule_id",
                ],
            )
        ),
        {
            "payload.winning_version_resolution_rule_id": inputs.get("winning_version_resolution_rule_id"),
            "source_registry.winning_version_resolution_rule_id": source_entry.get(
                "winning_version_resolution_rule_id"
            ),
            "route_policy.version_chain_relation.winning_version_resolution_rule_id": version_relation.get(
                "winning_version_resolution_rule_id"
            ),
        },
        compatibility_default="VERSION-DEFAULT",
    )
    clock_relation = route_policy.get("clock_chain_relation", {})
    clock_precedence_rule_id, clock_precedence_source = _resolve_authoritative_text(
        ("h01_authority", handoff.get("clock_precedence_rule_id")),
        ("source_registry", source_entry.get("clock_precedence_rule_id")),
        ("route_policy", clock_relation.get("clock_precedence_rule_id")),
        fallback="CLOCK-PREC-DEFAULT",
        default_source="compatibility_default",
    )
    clock_resolution_rule_id, clock_resolution_rule_source = _resolve_authoritative_text(
        ("h01_authority", handoff.get("clock_resolution_rule_id")),
        ("clock_strategy_profile", clock_strategy_profile.get("clock_resolution_rule_id")),
        ("route_policy", route_policy.get("clock_chain_relation", {}).get("clock_resolution_rule_id")),
        fallback="CLOCK-DEFAULT",
        default_source="compatibility_default",
    )
    expected_clock_resolution_rule_id = str(
        source_entry.get("clock_resolution_rule_id")
        or clock_relation.get("clock_resolution_rule_id")
        or "CLOCK-DEFAULT"
    )
    expected_clock_precedence_rule_id = str(
        source_entry.get("clock_precedence_rule_id")
        or clock_relation.get("clock_precedence_rule_id")
        or "CLOCK-PREC-DEFAULT"
    )
    if clock_resolution_rule_id != expected_clock_resolution_rule_id:
        authority_review_reasons.append("clock_resolution_rule_mismatch_requires_review")
    if clock_precedence_rule_id != expected_clock_precedence_rule_id:
        authority_review_reasons.append("clock_precedence_rule_mismatch_requires_review")

    collection_state, clock_conflict_state = _collection_state(
        flags,
        store=store,
        route_policy=route_policy,
        baseline_collection_state=baseline_collection_state,
        requires_manual_review=bool(execution_context.get("requires_manual_review")),
        rollout_enabled=rollout_enabled,
        version_precedence_source=version_precedence_source,
        clock_precedence_source=clock_precedence_source,
        authority_review_required=bool(authority_review_reasons),
    )
    route_review_reasons: list[str] = list(dict.fromkeys(authority_review_reasons))
    if collection_state == "REVIEW_REQUIRED":
        route_review_reasons.append("collection_state_requires_review")
    if not rollout_enabled:
        route_review_reasons.append("rollout_scope_requires_review")
    if version_precedence_source == "compatibility_default":
        route_review_reasons.append("version_precedence_requires_review")
    if clock_conflict_state in {"CONFLICTING", "UNRESOLVED"}:
        route_review_reasons.append("clock_conflict_requires_review")
    route_decision_state, route_downgrade_signals, route_block_signals = _route_decision(
        route_policy=route_policy,
        flags=flags,
        route_review_reasons=route_review_reasons,
        collection_state=collection_state,
    )

    project_id = str(inputs.get("project_id", "PROJECT-UNKNOWN"))
    origin_carrier_type = ensure_enum_or_fallback(
        store,
        "carrier_type",
        handoff.get("carrier_type") or execution_context.get("carrier_type") or inputs.get("origin_carrier_type"),
        fallback=str(carrier_authority or source_entry.get("carrier_type")),
    )
    current_action_start_at_optional = (
        handoff.get("current_action_start_at_optional")
        if "current_action_start_at_optional" in handoff
        else inputs.get("current_action_start_at_optional")
    )
    current_action_deadline_at_optional = (
        handoff.get("current_action_deadline_at_optional")
        if "current_action_deadline_at_optional" in handoff
        else inputs.get("current_action_deadline_at_optional")
    )

    return Stage2Extraction(
        project_id=project_id,
        source_registry_id=source_registry_id,
        source_registry_id_source=source_registry_id_source,
        route_policy_id=route_policy_id,
        route_policy_id_source=route_policy_id_source,
        source_family=str(execution_context.get("source_family")),
        platform_level=str(execution_context.get("platform_level")),
        region_scope=str(execution_context.get("region_scope")),
        coverage_tier=str(execution_context.get("coverage_tier")),
        carrier_type=ensure_enum(store, "carrier_type", str(source_entry.get("carrier_type"))),
        origin_carrier_type=origin_carrier_type,
        default_route=default_route,
        default_route_source=default_route_source,
        fallback_route=fallback_route,
        fallback_route_source=fallback_route_source,
        route_decision_state=route_decision_state,
        route_review_reasons=route_review_reasons,
        route_downgrade_signals=route_downgrade_signals,
        route_block_signals=route_block_signals,
        baseline_collection_state=baseline_collection_state,
        collection_state=collection_state,
        rollout_enabled=rollout_enabled,
        backlog_reason_optional=backlog_reason_optional,
        clock_conflict_state=clock_conflict_state,
        version_conflict_state=(
            "CONFLICTING"
            if get_flag(flags, "version_conflict")
            else ("UNRESOLVED" if version_precedence_source == "compatibility_default" else "CONSISTENT")
        ),
        version_precedence_rule_id=version_precedence_rule_id,
        version_precedence_source=version_precedence_source,
        clock_precedence_rule_id=clock_precedence_rule_id,
        clock_precedence_source=clock_precedence_source,
        first_seen_at=str(inputs.get("first_seen_at", now)),
        last_retrieved_at=str(inputs.get("last_retrieved_at", now)),
        window_clock_state=ensure_enum_or_fallback(
            store,
            "window_clock_state",
            inputs.get("window_clock_state"),
            fallback="UNKNOWN",
        ),
        timeline_nodes=list(inputs.get("timeline_nodes", ["NOTICE_PUBLISHED"])),
        required_node_set=list(inputs.get("required_node_set", ["NOTICE_PUBLISHED"])),
        node_presence_matrix=dict(inputs.get("node_presence_matrix", {"NOTICE_PUBLISHED": True})),
        statutory_node_completeness=bool(inputs.get("statutory_node_completeness", True)),
        current_notice_version_id=str(inputs.get("notice_version_id", f"NOTICE-{project_id}")),
        superseded_version_ids=list(inputs.get("superseded_version_ids", [])),
        replacement_edges=list(inputs.get("replacement_edges", [])),
        version_chain_strategy=str(source_entry.get("version_chain_strategy", route_policy.get("version_chain_relation", {}).get("strategy", "LATEST_ONLY"))),
        winning_version_resolution_rule_id=version_precedence_rule_id,
        clock_resolution_rule_id=clock_resolution_rule_id,
        clock_resolution_rule_source=clock_resolution_rule_source,
        current_action_start_at_optional=current_action_start_at_optional,
        current_action_deadline_at_optional=current_action_deadline_at_optional,
        source_url=str(inputs.get("announcement_url", "https://example.invalid/notice")),
        content_hash=str(inputs.get("content_hash", f"HASH-{project_id}")),
        storage_path=str(inputs.get("storage_path", f"capture/{project_id}.json")),
        source_entry=dict(source_entry),
        route_policy=dict(route_policy),
    )


__all__ = ["Stage2Extraction", "extract_stage2"]
