# Stage: stage1_tasking
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: contracts/governance/source_registry.json, contracts/governance/route_policy_catalog.json, handoff/stage1_to_stage2/contract.json

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from shared.contracts_runtime import ContractStore
from shared.utils import ensure_enum, ensure_enum_or_fallback


@dataclass(frozen=True)
class Stage1Extraction:
    review_lane: str
    region_scope: str
    source_family: str
    platform_level: str
    coverage_tier: str
    carrier_type: str
    source_registry_id: str
    route_policy_id: str
    default_route: str
    fallback_route: str
    time_range_from: str
    time_range_until: str
    strategy_template_id: str
    project_rooting_policy: str
    project_root_strategy: str
    project_unification_strategy: str
    window_priority_policy: str
    window_priority: str
    procurement_regime: str
    identity_resolution_rule_id: str
    clock_resolution_rule_id: str
    clock_precedence_rule_id: str
    current_action_start_at_optional: str | None
    current_action_deadline_at_optional: str | None
    baseline_collection_state: str
    rollout_enabled: bool
    backlog_reason_optional: str | None
    requires_manual_review: bool
    fallback_reasons: list[str]
    mismatch_reasons: list[str]
    source_entry: dict[str, Any]
    route_policy: dict[str, Any]


def _year_bounds(now: str) -> tuple[str, str]:
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return f"{current.year}-01-01", f"{current.year}-12-31"


def _resolve_fallback_route(
    *,
    route_policy: Mapping[str, Any],
    source_entry: Mapping[str, Any],
    default_route: str,
    store: ContractStore,
) -> tuple[str, list[str]]:
    fallback_reasons: list[str] = []
    candidates = [
        source_entry.get("fallback_route"),
        *list(route_policy.get("route_fallback_order", [])),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = ensure_enum_or_fallback(store, "route_type", str(candidate), fallback=default_route)
        if resolved != default_route:
            fallback_reasons.append("fallback_route_from_registry_or_policy")
            return resolved, fallback_reasons
    fallback_reasons.append("fallback_route_fell_back_to_default_route")
    return default_route, fallback_reasons


def extract_stage1(payload: Mapping[str, Any], store: ContractStore, *, now: str) -> Stage1Extraction:
    review_lane = ensure_enum(store, "review_lane", payload.get("review_lane"))
    region_scope = ensure_enum(store, "region_scope", payload.get("region_scope"))
    source_family = ensure_enum(store, "source_family", payload.get("source_family"))
    platform_level = ensure_enum(store, "platform_level", payload.get("platform_level"))
    coverage_tier = ensure_enum(store, "coverage_tier", payload.get("coverage_tier"))
    carrier_type = ensure_enum(store, "carrier_type", payload.get("carrier_type"))

    source_entry = store.resolve_source_entry(
        source_family=source_family,
        platform_level=platform_level,
        region_scope=region_scope,
        coverage_tier=coverage_tier,
        carrier_type=carrier_type,
    )
    route_policy = store.resolve_route_policy(
        route_policy_id=str(source_entry.get("route_policy_id", "")) or None,
        source_registry_id=str(source_entry["source_registry_id"]),
        source_family=source_family,
    )
    baseline_collection_state = ensure_enum_or_fallback(
        store,
        "collection_state",
        str(source_entry.get("collection_state", "")) or None,
        fallback="DISCOVERED",
    )
    rollout_enabled = bool(source_entry.get("rollout_enabled", True))
    backlog_reason_raw = source_entry.get("backlog_reason_optional")
    backlog_reason_optional = str(backlog_reason_raw) if backlog_reason_raw is not None else None

    mismatch_reasons: list[str] = []
    declared_default_route = payload.get("default_route")
    registry_default_route = ensure_enum_or_fallback(
        store,
        "route_type",
        str(source_entry.get("default_route", "")) or None,
        fallback=str(route_policy.get("default_route", "")),
    )
    policy_default_route = ensure_enum_or_fallback(
        store,
        "route_type",
        str(route_policy.get("default_route", "")) or None,
        fallback=registry_default_route,
    )
    default_route = registry_default_route or policy_default_route
    if declared_default_route and declared_default_route != default_route:
        mismatch_reasons.append("default_route_mismatch_requires_review")

    fallback_route, fallback_trace = _resolve_fallback_route(
        route_policy=route_policy,
        source_entry=source_entry,
        default_route=default_route,
        store=store,
    )

    time_range_from = payload.get("time_range_from")
    time_range_until = payload.get("time_range_until")
    year_start, year_end = _year_bounds(now)
    fallback_reasons = list(fallback_trace)
    if not time_range_from:
        time_range_from = year_start
        fallback_reasons.append("time_range_from_from_now_year")
    if not time_range_until:
        time_range_until = year_end
        fallback_reasons.append("time_range_until_from_now_year")
    if not rollout_enabled:
        fallback_reasons.append("rollout_scope_requires_review")
    if baseline_collection_state in {"DISCOVERED", "REVIEW_REQUIRED", "BLOCKED"}:
        fallback_reasons.append("baseline_collection_state_requires_review")

    declared_clock_rule = payload.get("clock_resolution_rule_id")
    declared_clock_rule_text = str(declared_clock_rule) if declared_clock_rule is not None else ""
    clock_resolution_rule_id = (
        declared_clock_rule_text
        if declared_clock_rule_text and declared_clock_rule_text != "CLOCK-DEFAULT"
        else str(source_entry.get("clock_resolution_rule_id") or route_policy.get("clock_chain_relation", {}).get("clock_resolution_rule_id", "CLOCK-DEFAULT"))
    )
    clock_precedence_rule_id = str(
        source_entry.get("clock_precedence_rule_id")
        or route_policy.get("clock_chain_relation", {}).get("clock_precedence_rule_id")
        or "CLOCK-PREC-DEFAULT"
    )
    current_action_start_raw = payload.get("current_action_start_at_optional")
    current_action_deadline_raw = payload.get("current_action_deadline_at_optional")
    current_action_start_at_optional = str(current_action_start_raw) if current_action_start_raw is not None else None
    current_action_deadline_at_optional = (
        str(current_action_deadline_raw) if current_action_deadline_raw is not None else None
    )

    requires_manual_review = (
        bool(payload.get("requires_manual_review", False))
        or bool(source_entry.get("requires_manual_review", False))
        or not rollout_enabled
        or baseline_collection_state in {"DISCOVERED", "REVIEW_REQUIRED", "BLOCKED"}
        or bool(mismatch_reasons)
        or str(route_policy.get("default_decision", "ALLOW")) in {"REVIEW", "BLOCK", "FALLBACK"}
    )

    return Stage1Extraction(
        review_lane=review_lane,
        region_scope=region_scope,
        source_family=source_family,
        platform_level=platform_level,
        coverage_tier=coverage_tier,
        carrier_type=carrier_type,
        source_registry_id=str(source_entry["source_registry_id"]),
        route_policy_id=str(route_policy["route_policy_id"]),
        default_route=default_route,
        fallback_route=fallback_route,
        time_range_from=str(time_range_from),
        time_range_until=str(time_range_until),
        strategy_template_id=str(payload.get("strategy_template_id", "STRAT-DEFAULT")),
        project_rooting_policy=str(payload.get("project_rooting_policy", "ROOT_BY_NOTICE")),
        project_root_strategy=str(payload.get("project_root_strategy", "ROOT_BY_NOTICE")),
        project_unification_strategy=str(payload.get("project_unification_strategy", "STRICT")),
        window_priority_policy=str(payload.get("window_priority_policy", "STANDARD")),
        window_priority=str(payload.get("window_priority", "NORMAL")),
        procurement_regime=str(payload.get("procurement_regime", "UNKNOWN")),
        identity_resolution_rule_id=str(payload.get("identity_resolution_rule_id", "ID-DEFAULT")),
        clock_resolution_rule_id=clock_resolution_rule_id,
        clock_precedence_rule_id=clock_precedence_rule_id,
        current_action_start_at_optional=current_action_start_at_optional,
        current_action_deadline_at_optional=current_action_deadline_at_optional,
        baseline_collection_state=baseline_collection_state,
        rollout_enabled=rollout_enabled,
        backlog_reason_optional=backlog_reason_optional,
        requires_manual_review=requires_manual_review,
        fallback_reasons=fallback_reasons,
        mismatch_reasons=mismatch_reasons,
        source_entry=dict(source_entry),
        route_policy=dict(route_policy),
    )


__all__ = ["Stage1Extraction", "extract_stage1"]
