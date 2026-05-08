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
    procurement_category: str
    legal_system_type_candidate: str
    legal_system_classification_confidence: str
    legal_system_classification_reasons: list[str]
    remedy_path_candidate: str
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


def _classification_text(
    payload: Mapping[str, Any],
    source_entry: Mapping[str, Any],
    route_policy: Mapping[str, Any],
) -> str:
    parts: list[str] = []
    for source in (payload, source_entry, route_policy):
        for key, value in source.items():
            if isinstance(value, (str, int, float, bool)):
                parts.append(str(value))
            elif isinstance(value, list):
                parts.extend(str(item) for item in value if isinstance(item, (str, int, float, bool)))
    return " ".join(part for part in parts if part).lower()


def _derive_procurement_regime(payload: Mapping[str, Any], text: str) -> tuple[str, str]:
    explicit = str(payload.get("procurement_regime") or "").strip().upper()
    if explicit:
        return explicit, "payload.procurement_regime"

    method_text = " ".join(
        str(payload.get(key) or "")
        for key in (
            "tender_method",
            "procurement_method",
            "purchase_method",
            "notice_type",
            "project_name",
            "source_title",
        )
    ).lower()
    combined = f"{method_text} {text}"
    if "单一来源" in combined or "single source" in combined:
        return "SINGLE_SOURCE", "classifier.method_keywords"
    if any(keyword in combined for keyword in ("竞争性谈判", "竞争性磋商", "谈判采购", "磋商公告", "negotiation")):
        return "NEGOTIATION", "classifier.method_keywords"
    if "邀请招标" in combined or "invited tender" in combined:
        return "INVITED_TENDER", "classifier.method_keywords"
    if any(keyword in combined for keyword in ("公开招标", "招标公告", "中标候选人公示", "open tender")):
        return "OPEN_TENDER", "classifier.method_keywords"
    if any(keyword in combined for keyword in ("询价", "比选", "询比", "框架协议")):
        return "OTHER", "classifier.method_keywords"
    return "UNKNOWN", "classifier.no_method_signal"


def _classify_legal_system(payload: Mapping[str, Any], text: str) -> tuple[str, str, str, list[str], str]:
    explicit_category = str(payload.get("procurement_category") or "").strip().upper()
    explicit_legal = str(payload.get("legal_system_type_candidate") or "").strip().upper()
    if explicit_legal:
        category = explicit_category or "UNKNOWN"
        return explicit_legal, category, "EXPLICIT", ["payload.legal_system_type_candidate"], "REVIEW_REQUIRED"

    gov_keywords = (
        "政府采购",
        "中国政府采购网",
        "财政部",
        "采购人",
        "供应商",
        "竞争性磋商",
        "竞争性谈判",
        "询价",
        "单一来源",
        "质疑",
        "投诉",
    )
    tender_keywords = (
        "招标投标",
        "招标人",
        "投标人",
        "公共资源交易",
        "工程建设",
        "依法必须招标",
        "中标候选人",
        "评标委员会",
        "异议",
    )
    state_owned_keywords = (
        "国企采购",
        "阳光采购",
        "平台采购",
        "集团采购",
        "非依法必须招标",
        "非依法必招",
    )

    gov_hits = [keyword for keyword in gov_keywords if keyword.lower() in text]
    tender_hits = [keyword for keyword in tender_keywords if keyword.lower() in text]
    state_owned_hits = [keyword for keyword in state_owned_keywords if keyword.lower() in text]
    reasons: list[str] = []
    reasons.extend(f"government_procurement_keyword:{keyword}" for keyword in gov_hits[:4])
    reasons.extend(f"tender_bidding_keyword:{keyword}" for keyword in tender_hits[:4])
    reasons.extend(f"state_owned_platform_keyword:{keyword}" for keyword in state_owned_hits[:3])

    if explicit_category:
        if not reasons:
            reasons.append("payload.procurement_category")
        if "GOVERNMENT" in explicit_category:
            return "GOVERNMENT_PROCUREMENT_LAW", explicit_category, "EXPLICIT", reasons, "QUESTION_COMPLAINT"
        if "TENDER" in explicit_category or "ENGINEERING" in explicit_category:
            return "TENDER_BIDDING_LAW", explicit_category, "EXPLICIT", reasons, "OBJECTION_COMPLAINT"
        if "STATE_OWNED" in explicit_category or "PLATFORM" in explicit_category:
            return "STATE_OWNED_PLATFORM_PROCUREMENT", explicit_category, "EXPLICIT", reasons, "REVIEW_REQUIRED"
        return "UNKNOWN", explicit_category, "EXPLICIT", reasons, "REVIEW_REQUIRED"

    has_engineering = any(keyword in text for keyword in ("工程", "施工", "勘察", "设计", "监理", "epc"))
    if gov_hits and tender_hits and has_engineering:
        return (
            "MIXED_GOVERNMENT_PROCUREMENT_ENGINEERING",
            "GOVERNMENT_PROCUREMENT_ENGINEERING",
            "MEDIUM",
            reasons,
            "REVIEW_REQUIRED",
        )
    if gov_hits and not tender_hits:
        return "GOVERNMENT_PROCUREMENT_LAW", "GOVERNMENT_PROCUREMENT", "HIGH", reasons, "QUESTION_COMPLAINT"
    if tender_hits and not gov_hits:
        category = "MANDATORY_TENDER_ENGINEERING" if has_engineering else "TENDER_BIDDING_PROJECT"
        return "TENDER_BIDDING_LAW", category, "HIGH", reasons, "OBJECTION_COMPLAINT"
    if state_owned_hits:
        return (
            "STATE_OWNED_PLATFORM_PROCUREMENT",
            "STATE_OWNED_PLATFORM_PROCUREMENT",
            "MEDIUM",
            reasons,
            "REVIEW_REQUIRED",
        )
    if gov_hits and tender_hits:
        return "MIXED_PUBLIC_PROCUREMENT", "MIXED_PUBLIC_PROCUREMENT", "MEDIUM", reasons, "REVIEW_REQUIRED"
    return "UNKNOWN", "UNKNOWN", "LOW", ["no_legal_system_keyword_signal"], "REVIEW_REQUIRED"


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
    classification_text = _classification_text(payload, source_entry, route_policy)
    procurement_regime, procurement_regime_source = _derive_procurement_regime(payload, classification_text)
    (
        legal_system_type_candidate,
        procurement_category,
        legal_system_classification_confidence,
        legal_system_classification_reasons,
        remedy_path_candidate,
    ) = _classify_legal_system(payload, classification_text)
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
    declared_fallback_route = payload.get("fallback_route")
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
    if declared_fallback_route and declared_fallback_route != fallback_route:
        mismatch_reasons.append("fallback_route_mismatch_requires_review")

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

    clock_relation = route_policy.get("clock_chain_relation", {})
    clock_resolution_rule_id = str(
        source_entry.get("clock_resolution_rule_id")
        or clock_relation.get("clock_resolution_rule_id")
        or "CLOCK-DEFAULT"
    )
    clock_precedence_rule_id = str(
        source_entry.get("clock_precedence_rule_id")
        or clock_relation.get("clock_precedence_rule_id")
        or "CLOCK-PREC-DEFAULT"
    )
    declared_clock_rule = payload.get("clock_resolution_rule_id")
    if declared_clock_rule and str(declared_clock_rule) != clock_resolution_rule_id:
        mismatch_reasons.append("clock_resolution_rule_mismatch_requires_review")
    declared_clock_precedence_rule = payload.get("clock_precedence_rule_id")
    if declared_clock_precedence_rule and str(declared_clock_precedence_rule) != clock_precedence_rule_id:
        mismatch_reasons.append("clock_precedence_rule_mismatch_requires_review")
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
        procurement_regime=procurement_regime,
        procurement_category=procurement_category,
        legal_system_type_candidate=legal_system_type_candidate,
        legal_system_classification_confidence=legal_system_classification_confidence,
        legal_system_classification_reasons=[
            procurement_regime_source,
            *legal_system_classification_reasons,
        ],
        remedy_path_candidate=remedy_path_candidate,
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
