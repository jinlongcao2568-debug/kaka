from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Mapping

from shared.context_packet import ContextPacket
from shared.contract_loader import load_contract
from shared.policy_contract_helpers import (
    _coerce_assignment_value as _contract_helper_coerce_assignment_value,
    _ensure_list as _contract_helper_ensure_list,
    _match_contract_rule as _contract_helper_match_contract_rule,
    _matches_stage8_policy_condition as _contract_helper_matches_stage8_policy_condition,
    _merge_contract_state_sinks as _contract_helper_merge_contract_state_sinks,
    _parse_assignment_actions as _contract_helper_parse_assignment_actions,
    _resolve_condition_operand as _contract_helper_resolve_condition_operand,
)
from shared.state_packet import PolicyDecision, StatePacket
from shared.utils import build_id


def _to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sort_timestamp(value: Any) -> float:
    parsed = _to_dt(str(value) if value not in (None, "") else None)
    if parsed is None:
        return float("inf")
    try:
        return -parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return float("inf")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _matches_range(value: float | int | None, rule: dict[str, Any] | None) -> bool:
    if rule is None:
        return True
    if value is None:
        return False
    numeric_value = float(value)
    if "lt" in rule and not numeric_value < float(rule["lt"]):
        return False
    if "lte" in rule and not numeric_value <= float(rule["lte"]):
        return False
    if "gt" in rule and not numeric_value > float(rule["gt"]):
        return False
    if "gte" in rule and not numeric_value >= float(rule["gte"]):
        return False
    return True


def _matches_allowed(value: Any, allowed: list[Any] | None, excluded: list[Any] | None) -> bool:
    if allowed is not None and value not in allowed:
        return False
    if excluded is not None and value in excluded:
        return False
    return True


def _bounded_score(value: Any, default: float = 0.0) -> float:
    numeric_value = float(value) if _is_number(value) else default
    return max(0.0, min(100.0, numeric_value))


def _normalize_numeric_output(value: float | int) -> int | float:
    rounded = round(float(value), 2)
    return int(rounded) if rounded.is_integer() else rounded


def _band_from_min_score(
    score: float | int,
    rules: list[dict[str, Any]],
    *,
    label_key: str,
    default: str,
) -> str:
    ordered_rules = sorted(
        (rule for rule in rules if label_key in rule),
        key=lambda item: int(item.get("min_score", 0)),
        reverse=True,
    )
    rounded = round(_bounded_score(score))
    for rule in ordered_rules:
        if rounded >= int(rule.get("min_score", 0)):
            return str(rule[label_key])
    return default


def _score_from_matrix(
    *,
    gate_status: str,
    price_band: str,
    matrix: list[dict[str, Any]],
    default: int,
) -> int:
    for entry in matrix:
        if str(entry.get("gate_status")) != gate_status:
            continue
        entry_band = str(entry.get("price_band", "ANY"))
        if entry_band in ("ANY", price_band):
            return int(entry.get("score", default))
    return default


def _grade_from_bands(score: float | int, bands: list[dict[str, Any]]) -> str:
    rounded = round(_bounded_score(score))
    for band in bands:
        if rounded >= int(band["minInclusive"]):
            return str(band["grade"])
    return "D"


def _downgrade_grade(grade: str, steps: int = 1) -> str:
    order = ["A", "B", "C", "D"]
    if grade not in order:
        return "D"
    return order[min(len(order) - 1, order.index(grade) + steps)]


def _is_missing(value: Any) -> bool:
    return value in (None, "")


def _resolve_with_contract_fallback(
    candidates: list[tuple[str, Any]],
    *,
    fallback_value: Any,
    fallback_source: str,
) -> tuple[Any, str, bool]:
    for source, value in candidates:
        if not _is_missing(value):
            return value, source, False
    return fallback_value, fallback_source, True


def _sanitize_reason_tag_value(value: Any) -> str:
    if value in (None, ""):
        return "UNKNOWN"
    token = str(value).upper()
    token = "".join(ch if ch.isalnum() else "_" for ch in token)
    token = token.strip("_")
    return token or "UNKNOWN"


class _ReasonTagTemplateDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "UNKNOWN"


def _render_reason_tags(templates: list[str], values: dict[str, Any]) -> list[str]:
    normalized = {key: _sanitize_reason_tag_value(value) for key, value in values.items()}
    return [template.format_map(_ReasonTagTemplateDict(normalized)) for template in templates]


def _bucket_from_contract(score: float | int, buckets: list[dict[str, Any]], *, default: str = "LOW") -> str:
    return _band_from_min_score(score, buckets, label_key="bucket", default=default)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _ensure_list(value: Any) -> list[Any]:
    return _contract_helper_ensure_list(value)


def _contact_priority_role_key(role_cluster: Any) -> str:
    normalized = str(role_cluster or "ORG_GATEKEEPER").upper()
    return {
        "PROCUREMENT_DECISION": "PROCUREMENT_DECISION_ACTOR",
        "PROCUREMENT_DECISION_ACTOR": "PROCUREMENT_DECISION_ACTOR",
        "LEGAL_ACTION": "LEGAL_ACTION_ACTOR",
        "LEGAL_ACTION_ACTOR": "LEGAL_ACTION_ACTOR",
        "CLIENT_AUTHORIZED_CONTACT": "CLIENT_AUTHORIZED_CONTACT",
        "DELIVERY_COORDINATOR": "DELIVERY_COORDINATOR",
        "ORG_GATEKEEPER": "ORG_GATEKEEPER",
    }.get(normalized, normalized)


def _contact_priority_organization_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    default_policy = {
        "organization_channel_families": [
            "ORG_PHONE",
            "ORG_EMAIL",
            "PUBLIC_FORM",
            "CRM_APPROVED_DIRECT",
        ],
        "minimum_primary_score": 60,
        "personal_primary_allowed_when_org_path_unavailable": True,
    }
    for rule in policy.get("organization_first_rules", []):
        match = re.search(r"\((?P<families>[^)]+)\).*score\s*>=\s*(?P<score>\d+)", str(rule))
        if not match:
            continue
        families = [
            token.strip()
            for token in match.group("families").split("/")
            if token.strip()
        ]
        if families:
            default_policy["organization_channel_families"] = families
        default_policy["minimum_primary_score"] = int(match.group("score"))
        break
    for rule in policy.get("organization_first_rules", []):
        text = str(rule).casefold()
        if "personal channel families can be primary only when no organization contact is eligible" in text:
            default_policy["personal_primary_allowed_when_org_path_unavailable"] = True
            break
    return default_policy


def _contact_priority_conflict_rules(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    parsed_rules: list[dict[str, Any]] = []
    for raw_rule in policy.get("conflict_rules", []):
        text = str(raw_rule).casefold()
        threshold_match = re.search(r"<=\s*(\d+)", text)
        if not threshold_match:
            continue
        if "role_cluster" in text:
            field_name = "role_cluster"
            reason = f"role_cluster_diff_within_{threshold_match.group(1)}"
        elif "channel_family" in text:
            field_name = "channel_family"
            reason = f"channel_family_diff_within_{threshold_match.group(1)}"
        else:
            continue
        parsed_rules.append(
            {
                "field": field_name,
                "score_diff_lte": int(threshold_match.group(1)),
                "reason": reason,
            }
        )
    return parsed_rules


def _contact_priority_sort_key(policy: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    score = int(candidate.get("contact_priority_score", candidate.get("score", 0)))
    ordering: list[Any] = [-score]
    for raw_tiebreaker in policy.get("tiebreakers", []):
        tiebreaker = str(raw_tiebreaker).casefold()
        if "higher legal basis weight" in tiebreaker:
            ordering.append(-int(candidate.get("legal_basis_weight", 0)))
        elif "higher source auditability" in tiebreaker:
            ordering.append(-int(candidate.get("source_auditability_rank", 0)))
        elif "more recent last_evaluated_at" in tiebreaker:
            ordering.append(_sort_timestamp(candidate.get("last_evaluated_at")))
        elif "organization channel over personal channel" in tiebreaker:
            ordering.append(
                0
                if bool(
                    candidate.get(
                        "organization_channel_flag",
                        candidate.get("organization_channel", False),
                    )
                )
                else 1
            )
    ordering.append(str(candidate.get("candidate_id", "")))
    return tuple(ordering)


def _contact_priority_conflict(
    policy: Mapping[str, Any],
    ranked_candidates: list[Mapping[str, Any]],
) -> tuple[bool, str]:
    if len(ranked_candidates) < 2:
        return False, "single candidate"
    winner = ranked_candidates[0]
    runner_up = ranked_candidates[1]
    score_diff = int(winner.get("contact_priority_score", winner.get("score", 0))) - int(
        runner_up.get("contact_priority_score", runner_up.get("score", 0))
    )
    for rule in _contact_priority_conflict_rules(policy):
        if score_diff > int(rule["score_diff_lte"]):
            continue
        if str(winner.get(rule["field"], "")) == str(runner_up.get(rule["field"], "")):
            continue
        return True, str(rule["reason"])
    return False, "single candidate"


def _matches_key_value_condition(condition: str, facts: Mapping[str, Any]) -> bool:
    field_name, separator, expected_value = str(condition).partition("=")
    if not separator:
        return False
    actual = facts.get(field_name.strip())
    return str(actual) == expected_value.strip()


def _match_contract_rule(rules: list[dict[str, Any]], facts: Mapping[str, Any]) -> dict[str, Any] | None:
    return _contract_helper_match_contract_rule(rules, facts)


def _merge_contract_state_sinks(*sources: Mapping[str, Any] | None) -> dict[str, Any]:
    return _contract_helper_merge_contract_state_sinks(*sources)


def _coerce_assignment_value(value: str) -> Any:
    return _contract_helper_coerce_assignment_value(value)


def _parse_assignment_actions(actions: list[str]) -> dict[str, Any]:
    return _contract_helper_parse_assignment_actions(actions)


def _resolve_condition_operand(token: str, facts: Mapping[str, Any]) -> Any:
    return _contract_helper_resolve_condition_operand(token, facts)


def _matches_stage8_policy_condition(condition: str, facts: Mapping[str, Any]) -> bool:
    return _contract_helper_matches_stage8_policy_condition(condition, facts)


def _normalize_alias_token(value: Any, *, normalizer: str) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).upper()
    if normalizer == "UPPER_ALNUM":
        normalized = "".join(ch for ch in normalized if ch.isalnum())
    return normalized or None


def _select_stage8_cadence_profile_id(urgency: str, window_urgency: Any) -> str:
    normalized_urgency = str(urgency or "NORMAL").upper()
    numeric_window_urgency = int(window_urgency) if _is_number(window_urgency) else 50
    if normalized_urgency == "CRITICAL" or numeric_window_urgency >= 90:
        return "CADENCE-CRITICAL"
    if normalized_urgency == "HIGH" or numeric_window_urgency >= 80:
        return "CADENCE-HIGH"
    if normalized_urgency == "LOW":
        return "CADENCE-LOW"
    return "CADENCE-NORMAL"


def _select_stage8_channel_ladder(policy: dict[str, Any], channel_family: str) -> dict[str, Any]:
    ladder = next(
        (
            item
            for item in policy.get("channel_ladders", [])
            if str(item.get("entry_channel_family")) == channel_family
        ),
        None,
    )
    if ladder is not None:
        return ladder
    return {
        "ladder_id": f"LADDER-{channel_family or 'DEFAULT'}",
        "step_sequence": [channel_family] if channel_family else [],
        "fallback_sequence": [],
        "fallback_trigger_response_statuses": [],
        "sequence_mode": "GOVERNED_PREVIEW_ONLY",
        "live_execution_enabled": False,
        "advance_requires_manual_review": False,
    }


def _component_score(model: dict[str, Any], component_name: str, value: Any, default: float = 0.0) -> float:
    mapping = model.get("component_scores", {}).get(component_name)
    if mapping is not None:
        return float(mapping.get(str(value), default))
    return _bounded_score(value, default)


def _matches_window_rule(
    rule: dict[str, Any],
    *,
    days_remaining: float | None,
    deadline_missing: bool,
    existing_window_status: str | None,
    sale_gate_status: str | None,
    current_action_clock: str | None,
    clock_conflict_state: str | None,
    window_status: str | None = None,
    commercial_urgency_level: str | None = None,
    score: int | None = None,
) -> bool:
    if "deadline_missing" in rule and bool(rule["deadline_missing"]) != deadline_missing:
        return False
    if "window_status_missing" in rule:
        window_status_missing = not existing_window_status
        if bool(rule["window_status_missing"]) != window_status_missing:
            return False
    if not _matches_allowed(
        existing_window_status,
        rule.get("existing_window_statuses"),
        rule.get("existing_window_statuses_excluded"),
    ):
        return False
    if not _matches_allowed(
        sale_gate_status,
        rule.get("sale_gate_statuses"),
        rule.get("sale_gate_statuses_excluded"),
    ):
        return False
    if not _matches_allowed(
        current_action_clock,
        rule.get("current_action_clock_states"),
        rule.get("current_action_clock_states_excluded"),
    ):
        return False
    if not _matches_allowed(
        clock_conflict_state,
        rule.get("clock_conflict_states"),
        rule.get("clock_conflict_states_excluded"),
    ):
        return False
    if not _matches_allowed(
        window_status,
        rule.get("window_statuses"),
        rule.get("window_statuses_excluded"),
    ):
        return False
    if not _matches_allowed(
        commercial_urgency_level,
        rule.get("commercial_urgency_levels"),
        rule.get("commercial_urgency_levels_excluded"),
    ):
        return False
    if not _matches_range(days_remaining, rule.get("days_remaining")):
        return False
    if not _matches_range(score, rule.get("score")):
        return False
    return bool(rule) or rule.get("default", False)


class PolicyExecutor:
    POLICY_FILES = {
        "window_value": "contracts/sales/window_value_policy_catalog.json",
        "value_scoring": "contracts/sales/lead_value_scoring_catalog.json",
        "buyer_fit_scorecard": "contracts/sales/buyer_fit_scorecard.json",
        "sku_recommendation": "contracts/sales/sku_recommendation_policy_catalog.json",
        "opportunity_policy": "contracts/sales/opportunity_policy_catalog.json",
        "stage6_legal_action": "contracts/sales/stage6_legal_action_resolution_catalog.json",
        "price_normalization": "contracts/sales/price_normalization_catalog.json",
        "competitor_confidence": "contracts/sales/competitor_confidence_catalog.json",
        "contact_priority": "contracts/sales/contact_priority_policy_catalog.json",
        "contact_source_policy": "contracts/sales/contact_source_policy_catalog.json",
        "contact_compliance": "contracts/sales/contact_compliance_matrix.json",
        "outreach_strategy": "contracts/sales/outreach_strategy_catalog.json",
        "outreach_cadence": "contracts/sales/outreach_cadence_catalog.json",
        "retry_policy": "contracts/sales/retry_policy_catalog.json",
        "feedback_reason": "contracts/sales/feedback_reason_catalog.json",
        "touch_stop": "contracts/sales/touch_stop_condition_catalog.json",
        "payment_exception": "contracts/sales/payment_exception_catalog.json",
        "delivery_exception": "contracts/sales/delivery_exception_catalog.json",
        "outcome_taxonomy": "contracts/sales/outcome_taxonomy_catalog.json",
        "governance_taxonomy": "contracts/sales/governance_feedback_policy_catalog.json",
    }

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self._cache: dict[str, Any] = {}

    def load_policy(self, policy_key: str) -> Any:
        if policy_key not in self._cache:
            self._cache[policy_key] = load_contract(self.POLICY_FILES[policy_key], self.settings)
        return self._cache[policy_key]

    def execute(self, policy_key: str, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        method = getattr(self, f"_evaluate_{policy_key}", None)
        if method is None:
            raise KeyError(f"policy executor not implemented for: {policy_key}")
        return method(context, state)

    def _decision(
        self,
        *,
        policy_key: str,
        catalog_id: str,
        policy_id: str | list[str] | None,
        decision_state: str,
        outputs: dict[str, Any],
        reasons: list[str],
        fallback_used: bool = False,
    ) -> PolicyDecision:
        return PolicyDecision(
            policy_key=policy_key,
            decision_state=decision_state,
            outputs=outputs,
            reasons=reasons,
            fallback_used=fallback_used,
            trace={
                "policy_key": policy_key,
                "catalog_id": catalog_id,
                "policy_id": policy_id,
                "decision_state": decision_state,
                "outputs": outputs,
                "reasons": reasons,
                "fallback_used": fallback_used,
            },
        )

    def _ref_tail(self, value: str | None, fallback: str) -> str:
        if not value:
            return fallback
        if "#" in value:
            return value.split("#", 1)[1]
        return value

    def _evaluate_window_value(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("window_value")
        policy = catalog["policies"][0]
        deadline = _to_dt(context.input("current_action_deadline_at_optional"))
        now = _to_dt(context.now) or datetime.utcnow()
        days_remaining = None if deadline is None else (deadline - now).total_seconds() / 86400
        deadline_missing = deadline is None
        existing_window_status = context.input("window_status") or context.record(
            "legal_action_recommendation"
        ).get("window_status")
        sale_gate_status = context.input("sale_gate_status") or context.record("project_fact").get(
            "sale_gate_status"
        )
        current_action_clock = context.input("current_action_clock") or context.record(
            "clock_chain_profile"
        ).get("current_action_clock")
        clock_conflict_state = context.input("clock_conflict_state") or context.record(
            "clock_chain_profile"
        ).get("clock_conflict_state")

        matched_rule_id = policy["policy_id"]
        matched_reason = "window_value_policy_applied"
        fallback_used = False

        window_status: str | None = None
        window_risk_level: str | None = None
        window_urgency_score: int | None = None
        review_lane: str | None = None

        if deadline_missing:
            for rule in policy.get("status_fallback_rules", []):
                if _matches_window_rule(
                    rule,
                    days_remaining=days_remaining,
                    deadline_missing=deadline_missing,
                    existing_window_status=existing_window_status,
                    sale_gate_status=sale_gate_status,
                    current_action_clock=current_action_clock,
                    clock_conflict_state=clock_conflict_state,
                ):
                    matched_rule_id = rule.get("rule_id", matched_rule_id)
                    matched_reason = rule.get("reason", matched_rule_id)
                    fallback_used = True
                    window_status = rule["window_status"]
                    window_risk_level = rule["window_risk_level"]
                    window_urgency_score = int(rule["window_urgency_score"])
                    review_lane = rule["review_lane"]
                    break

        if window_status is None:
            for rule in policy.get("status_rules", []):
                if _matches_window_rule(
                    rule,
                    days_remaining=days_remaining,
                    deadline_missing=deadline_missing,
                    existing_window_status=existing_window_status,
                    sale_gate_status=sale_gate_status,
                    current_action_clock=current_action_clock,
                    clock_conflict_state=clock_conflict_state,
                ):
                    matched_rule_id = rule.get("rule_id", matched_rule_id)
                    matched_reason = rule.get("reason", matched_rule_id)
                    window_status = rule["window_status"]
                    window_risk_level = rule.get("window_risk_level")
                    break

        if window_status == "ACTIONABLE" and window_risk_level is None:
            for rule in policy.get("window_risk_rules", []):
                if _matches_window_rule(
                    rule,
                    days_remaining=days_remaining,
                    deadline_missing=deadline_missing,
                    existing_window_status=existing_window_status,
                    sale_gate_status=sale_gate_status,
                    current_action_clock=current_action_clock,
                    clock_conflict_state=clock_conflict_state,
                ):
                    window_risk_level = rule["window_risk_level"]
                    break
        if window_risk_level is None:
            window_risk_level = "MEDIUM"

        if window_urgency_score is None:
            for rule in policy.get("urgency_score_rules", []):
                if _matches_window_rule(
                    rule,
                    days_remaining=days_remaining,
                    deadline_missing=deadline_missing,
                    existing_window_status=existing_window_status,
                    sale_gate_status=sale_gate_status,
                    current_action_clock=current_action_clock,
                    clock_conflict_state=clock_conflict_state,
                    window_status=window_status,
                ):
                    window_urgency_score = int(rule["urgency_score"])
                    break
        if window_urgency_score is None:
            window_urgency_score = 50

        if review_lane is None:
            for rule in policy.get("review_lane_rules", []):
                if _matches_window_rule(
                    rule,
                    days_remaining=days_remaining,
                    deadline_missing=deadline_missing,
                    existing_window_status=existing_window_status,
                    sale_gate_status=sale_gate_status,
                    current_action_clock=current_action_clock,
                    clock_conflict_state=clock_conflict_state,
                    window_status=window_status,
                ):
                    review_lane = rule["review_lane"]
                    break
        if review_lane is None:
            review_lane = "STANDARD"

        queue_policy = policy.get("queue_priority_policy", {})
        commercial_weights = queue_policy.get("weights", {}).get(
            "commercial_urgency_level_weights", {}
        )
        commercial_urgency_level = context.input(
            "commercial_urgency_level",
            context.input(
                "commercial_urgency_level_optional",
                queue_policy.get("commercial_urgency_default", "NORMAL"),
            ),
        )
        if commercial_urgency_level not in commercial_weights:
            commercial_urgency_level = queue_policy.get("commercial_urgency_default", "NORMAL")

        risk_weight = int(
            queue_policy.get("weights", {})
            .get("window_risk_level_weights", {})
            .get(window_risk_level, 0)
        )
        commercial_weight = int(commercial_weights.get(commercial_urgency_level, 0))
        window_weight = float(
            queue_policy.get("weights", {}).get("window_urgency_weight", 0.6)
        )

        review_priority_score = round(
            window_urgency_score * window_weight + risk_weight + commercial_weight
        )
        review_priority_score = max(0, min(100, int(review_priority_score)))
        for rule in queue_policy.get("score_overrides", []):
            if _matches_window_rule(
                rule,
                days_remaining=days_remaining,
                deadline_missing=deadline_missing,
                existing_window_status=existing_window_status,
                sale_gate_status=sale_gate_status,
                current_action_clock=current_action_clock,
                clock_conflict_state=clock_conflict_state,
                window_status=window_status,
                commercial_urgency_level=commercial_urgency_level,
                score=review_priority_score,
            ):
                if "review_priority_score" in rule:
                    review_priority_score = int(rule["review_priority_score"])
                if "min_score" in rule:
                    review_priority_score = max(review_priority_score, int(rule["min_score"]))

        review_queue_bucket = "LOW"
        for rule in queue_policy.get("bucket_rules", []):
            if _matches_window_rule(
                rule,
                days_remaining=days_remaining,
                deadline_missing=deadline_missing,
                existing_window_status=existing_window_status,
                sale_gate_status=sale_gate_status,
                current_action_clock=current_action_clock,
                clock_conflict_state=clock_conflict_state,
                window_status=window_status,
                commercial_urgency_level=commercial_urgency_level,
                score=review_priority_score,
            ):
                review_queue_bucket = rule["review_queue_bucket"]
                break

        outputs = {
            "window_status": window_status,
            "window_risk_level": window_risk_level,
            "window_urgency_score": window_urgency_score,
            "review_lane": review_lane,
            "review_priority_score": review_priority_score,
            "review_queue_bucket": review_queue_bucket,
            "commercial_urgency_level": commercial_urgency_level,
        }
        reasons = [
            matched_reason,
            f"review_priority_score={review_priority_score}",
            f"review_queue_bucket={review_queue_bucket}",
        ]
        if days_remaining is not None:
            reasons.insert(1, f"days_remaining={days_remaining:.2f}")

        decision_state = "ALLOW"
        if window_status == "MISSED":
            decision_state = "BLOCK"
        elif window_status == "REVIEW_REQUIRED":
            decision_state = "REVIEW"
        elif fallback_used:
            decision_state = "FALLBACK"

        return self._decision(
            policy_key="window_value",
            catalog_id=catalog["catalogId"],
            policy_id=[policy["policy_id"], matched_rule_id],
            decision_state=decision_state,
            outputs=outputs,
            reasons=reasons,
            fallback_used=fallback_used,
        )

    def _evaluate_stage6_legal_action(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("stage6_legal_action")
        policy = catalog["policies"][0]
        project_fact = context.record("project_fact")
        report_record = context.record("report_record")
        legal_action_recommendation = context.record("legal_action_recommendation")

        sale_gate_status = context.input(
            "sale_gate_status",
            project_fact.get("sale_gate_status"),
        )
        report_status = context.input(
            "report_status",
            report_record.get("report_status"),
        )
        rule_gate_status = context.input(
            "rule_gate_status",
            project_fact.get("rule_gate_status"),
        )
        evidence_gate_status = context.input(
            "evidence_gate_status",
            project_fact.get("evidence_gate_status"),
        )
        window_status = context.input(
            "window_status",
            legal_action_recommendation.get("window_status"),
        )
        requested_action_family = _optional_str(
            context.input("requested_action_family_optional", context.input("action_family"))
        )
        requested_recommended_next_step = _optional_str(
            context.input(
                "requested_recommended_next_step_optional",
                context.input("recommended_next_step"),
            )
        )
        semantic_decision_state = _optional_str(context.input("semantic_decision_state_optional"))
        action_chain_closed = (
            sale_gate_status == "OPEN"
            and report_status == "ISSUED"
            and rule_gate_status == "PASS"
            and evidence_gate_status == "PASS"
            and window_status == "ACTIONABLE"
        )
        facts = {
            "sale_gate_status": sale_gate_status,
            "report_status": report_status,
            "rule_gate_status": rule_gate_status,
            "evidence_gate_status": evidence_gate_status,
            "window_status": window_status,
            "action_chain_closed": action_chain_closed,
            "semantic_decision_state": semantic_decision_state,
        }

        def matches_rule(rule: Mapping[str, Any]) -> bool:
            if bool(rule.get("default", False)):
                return True
            for field_name, expected in dict(rule.get("when", {})).items():
                actual = facts.get(field_name)
                if isinstance(expected, list):
                    if actual not in expected:
                        return False
                elif actual != expected:
                    return False
            return True

        resolution_rule = next(
            rule for rule in policy.get("resolution_rules", []) if matches_rule(rule)
        )
        action_family = str(resolution_rule["outputs"]["action_family"])
        recommended_next_step = str(
            resolution_rule["outputs"]["recommended_next_step"]
        )
        resolution_sources = {
            "action_family": str(resolution_rule.get("rule_id", "ACTION-UNRESOLVED")),
            "recommended_next_step": str(
                resolution_rule.get("rule_id", "ACTION-UNRESOLVED")
            ),
        }

        override_policy = dict(policy.get("override_policy", {}))
        if (
            action_chain_closed
            and override_policy.get(
                "allow_requested_action_family_when_action_chain_closed", False
            )
            and requested_action_family
        ):
            action_family = requested_action_family
            resolution_sources["action_family"] = "REQUESTED_ACTION_FAMILY_OVERRIDE"
        if (
            action_chain_closed
            and override_policy.get(
                "allow_requested_recommended_next_step_when_action_chain_closed", False
            )
            and requested_recommended_next_step
        ):
            recommended_next_step = requested_recommended_next_step
            resolution_sources[
                "recommended_next_step"
            ] = "REQUESTED_RECOMMENDED_NEXT_STEP_OVERRIDE"

        semantic_rule_id: str | None = None
        semantic_override = dict(policy.get("semantic_override", {}))
        semantic_override_states = {
            str(item) for item in semantic_override.get("applies_to_decision_states", [])
        }
        if semantic_decision_state in semantic_override_states:
            action_family = str(semantic_override.get("action_family", action_family))
            resolution_sources["action_family"] = (
                f"SEMANTIC_OVERRIDE::{semantic_decision_state}"
            )
            preserve_next_step = bool(
                semantic_override.get(
                    "preserve_recommended_next_step_when_action_chain_closed", False
                )
            )
            if not (action_chain_closed and preserve_next_step):
                semantic_rule = next(
                    rule
                    for rule in semantic_override.get("review_next_step_rules", [])
                    if matches_rule(rule)
                )
                semantic_rule_id = str(
                    semantic_rule.get("rule_id", "SEMANTIC-REVIEW-UNRESOLVED")
                )
                recommended_next_step = str(
                    semantic_rule.get(
                        "recommended_next_step", recommended_next_step
                    )
                )
                resolution_sources["recommended_next_step"] = (
                    f"SEMANTIC_OVERRIDE::{semantic_rule_id}"
                )
            else:
                semantic_rule_id = "SEMANTIC_OVERRIDE_PRESERVE_ACTION_CHAIN_NEXT_STEP"
                resolution_sources["recommended_next_step"] = (
                    f"SEMANTIC_OVERRIDE::{semantic_rule_id}"
                )

        reasons = [
            f"resolution_rule={resolution_rule.get('rule_id', 'ACTION-UNRESOLVED')}",
            f"action_chain_closed={action_chain_closed}",
        ]
        if semantic_rule_id:
            reasons.append(f"semantic_override={semantic_rule_id}")

        return self._decision(
            policy_key="stage6_legal_action",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=(
                "ALLOW"
                if action_chain_closed and semantic_decision_state not in semantic_override_states
                else "REVIEW"
            ),
            outputs={
                "action_family": action_family,
                "recommended_next_step": recommended_next_step,
                "legal_action_resolution_trace": {
                    "policy_id": policy["policy_id"],
                    "resolution_rule_id": str(
                        resolution_rule.get("rule_id", "ACTION-UNRESOLVED")
                    ),
                    "semantic_rule_id_optional": semantic_rule_id,
                    "action_chain_closed": action_chain_closed,
                    "component_inputs": facts,
                    "requested_action_family_optional": requested_action_family,
                    "requested_recommended_next_step_optional": requested_recommended_next_step,
                    "resolved_sources": resolution_sources,
                },
            },
            reasons=reasons,
        )

    def _evaluate_price_normalization(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("price_normalization")
        policy = catalog["policies"][0]
        resolution_policy = load_contract("contracts/sales/stage7_resolution_policy.json", self.settings)[
            "priceCandidateResolution"
        ]
        priority_index = {
            entry["source_type"]: {
                "priority": int(entry["priority"]),
                "reliability_score": int(entry["reliability_score"]),
            }
            for entry in policy.get("source_priority", [])
        }
        normalization = policy.get("normalization", {})
        tax_policy = normalization.get("tax_conversion", {})
        unit_policy = normalization.get("unit_normalization", {})
        scope_policy = normalization.get("lot_package_resolution", {})
        freshness_policy = normalization.get("freshness_decay", {})
        band_rules = policy.get("band_rules", [])
        score_matrix = policy.get("price_signal_score_matrix", [])
        base_currency = str(normalization.get("base_currency", "CNY"))
        target_tax_basis = str(normalization.get("target_tax_basis", "EX_TAX"))
        target_unit_basis = str(unit_policy.get("target_unit_basis", "TOTAL_AMOUNT"))
        supported_tax_basis = {
            str(item) for item in normalization.get("supported_tax_basis", ["EX_TAX", "INCL_TAX", "UNKNOWN"])
        }
        supported_unit_basis = {
            str(item) for item in unit_policy.get("supported_unit_basis", ["TOTAL_AMOUNT", "UNKNOWN"])
        }
        default_scope_key = str(scope_policy.get("default_scope_key", "GLOBAL"))
        default_recency_days = int(freshness_policy.get("default_recency_days_when_missing", 9999))
        reference_source_types = {str(item) for item in freshness_policy.get("reference_source_types", [])}
        stale_reference_days = int(freshness_policy.get("review_if_reference_older_than_days", 365))
        low_reliability_threshold = int(policy.get("conflict_thresholds", {}).get("low_reliability_score_threshold", 60))
        now = _to_dt(str(context.input("now"))) if context.input("now") else None
        raw_candidates = context.input("price_source_set_optional", [])
        candidates: list[dict[str, Any]] = []

        def resolve_recency_days(item: dict[str, Any]) -> int:
            recency_value = item.get("recency_days_optional")
            if _is_number(recency_value):
                return max(0, int(recency_value))
            source_date = item.get("source_date_optional")
            source_dt = _to_dt(str(source_date)) if source_date else None
            if source_dt and now:
                delta = now - source_dt
                return max(0, int(delta.total_seconds() // 86400))
            return default_recency_days

        def resolve_freshness_bucket(recency_days: int) -> dict[str, Any]:
            for bucket in freshness_policy.get("age_buckets", []):
                if recency_days <= int(bucket.get("max_days", default_recency_days)):
                    return bucket
            age_buckets = freshness_policy.get("age_buckets", [])
            return age_buckets[-1] if age_buckets else {"freshness_score": 100, "reliability_penalty": 0}

        def resolve_scope_key(item: dict[str, Any]) -> str:
            lot = str(item.get("lot_id_optional") or "").strip()
            package = str(item.get("package_id_optional") or "").strip()
            if not lot and not package:
                return default_scope_key
            return f"{lot or '-'}|{package or '-'}"

        def dedup_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
            key_values: list[Any] = []
            for field_name in resolution_policy.get("dedupKey", []):
                value = candidate.get(field_name)
                if field_name == "amount" and _is_number(value):
                    value = round(float(value), 2)
                key_values.append(value)
            return tuple(key_values)

        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if not isinstance(item, dict):
                    continue
                amount_value = item.get("normalized_amount_optional", item.get("amount", item.get("amount_optional")))
                if not _is_number(amount_value):
                    continue
                source_type = str(item.get("source_type", "MANUAL_INPUT"))
                currency = str(item.get("currency", item.get("normalized_currency_optional", base_currency))).upper()
                priority_meta = priority_index.get(source_type, {"priority": 999, "reliability_score": 0})
                recency_days = resolve_recency_days(item)
                freshness_bucket = resolve_freshness_bucket(recency_days)
                candidate_review_flags: list[str] = []
                normalized_amount = float(amount_value)
                fx_rate = item.get("fx_rate_optional", item.get("fx_rate"))
                if currency != base_currency:
                    if bool(normalization.get("allow_fx_rate")) and _is_number(fx_rate):
                        normalized_amount *= float(fx_rate)
                    else:
                        candidate_review_flags.append("FX_RATE_MISSING")
                tax_basis = str(item.get("tax_basis_optional") or "").upper()
                if tax_basis not in supported_tax_basis:
                    if "tax_inclusive_optional" in item:
                        tax_basis = "INCL_TAX" if bool(item.get("tax_inclusive_optional")) else "EX_TAX"
                    else:
                        tax_basis = "UNKNOWN"
                if tax_basis == "INCL_TAX" and target_tax_basis == "EX_TAX":
                    tax_rate = item.get("tax_rate_optional", tax_policy.get("fallback_tax_rate", 0.0))
                    if _is_number(tax_rate):
                        normalized_amount = normalized_amount / (1 + float(tax_rate))
                    else:
                        candidate_review_flags.append("MISSING_TAX_RATE")
                elif tax_basis == "UNKNOWN" and bool(tax_policy.get("review_if_unknown_on_selected_candidate")):
                    candidate_review_flags.append("UNKNOWN_TAX_BASIS")

                unit_basis = str(item.get("unit_basis_optional", target_unit_basis)).upper()
                if unit_basis not in supported_unit_basis:
                    unit_basis = "UNKNOWN"
                if unit_basis != target_unit_basis:
                    quantity = item.get("quantity_optional", item.get("quantity"))
                    if _is_number(quantity):
                        normalized_amount *= float(quantity)
                    elif bool(unit_policy.get("review_if_quantity_missing")):
                        candidate_review_flags.append("MISSING_UNIT_QUANTITY")

                if source_type in reference_source_types and recency_days > stale_reference_days:
                    candidate_review_flags.append("STALE_REFERENCE")

                candidates.append(
                    {
                        "source_type": source_type,
                        "amount": float(_normalize_numeric_output(normalized_amount)),
                        "currency": base_currency,
                        "priority": priority_meta["priority"],
                        "reliability_score": max(
                            0,
                            priority_meta["reliability_score"] - int(freshness_bucket.get("reliability_penalty", 0)),
                        ),
                        "recency_days_optional": recency_days,
                        "freshness_score": int(freshness_bucket.get("freshness_score", 100)),
                        "normalized_tax_basis": target_tax_basis,
                        "source_tax_basis": tax_basis,
                        "normalized_unit_basis": target_unit_basis,
                        "source_unit_basis": unit_basis,
                        "lot_id_optional": item.get("lot_id_optional"),
                        "package_id_optional": item.get("package_id_optional"),
                        "scope_key": resolve_scope_key(item),
                        "review_flags": candidate_review_flags,
                        "fx_rate_optional": _normalize_numeric_output(float(fx_rate)) if _is_number(fx_rate) else None,
                    }
                )
        deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for candidate in candidates:
            key = dedup_key(candidate)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = candidate
                continue
            existing_key = (
                existing["priority"],
                -existing["reliability_score"],
                -existing.get("freshness_score", 0),
                existing["recency_days_optional"],
            )
            candidate_key = (
                candidate["priority"],
                -candidate["reliability_score"],
                -candidate.get("freshness_score", 0),
                candidate["recency_days_optional"],
            )
            if candidate_key < existing_key:
                deduped[key] = candidate
        deduped_candidates = list(deduped.values())
        deduped_candidates.sort(
            key=lambda item: (
                item["priority"],
                -item["reliability_score"],
                -item.get("freshness_score", 0),
                item["recency_days_optional"],
            )
        )

        selected_candidate = deduped_candidates[0] if deduped_candidates else None
        review_flags: set[str] = set()
        if selected_candidate is None:
            fallback_amount = context.input("normalized_price_amount_optional")
            selected_source_type = "H06_FORMAL_SINK"
            if not _is_number(fallback_amount):
                fallback_amount = context.input("bid_price")
                selected_source_type = "DIRECT_BID_PRICE"
            if not _is_number(fallback_amount):
                fallback_amount = context.input("estimated_contract_value_optional")
                selected_source_type = "PROJECT_ESTIMATE"
            if not _is_number(fallback_amount):
                fallback_amount = None
            if fallback_amount is None:
                return self._decision(
                    policy_key="price_normalization",
                    catalog_id=catalog["catalogId"],
                    policy_id=[policy["policy_id"], resolution_policy["policyId"]],
                    decision_state="FALLBACK",
                    outputs={
                        "normalized_price_amount": None,
                        "normalized_price_currency": base_currency,
                        "price_band": "UNKNOWN",
                        "recommended_quote_band": "CUSTOM",
                        "price_signal_score": 30,
                        "price_conflict_gate_status": "REVIEW",
                        "selected_price_source_type": "UNKNOWN",
                        "price_candidate_count": len(candidates),
                        "price_candidate_deduped_count": len(deduped_candidates),
                        "price_source_priority_applied": [],
                        "normalized_tax_basis": target_tax_basis,
                        "normalized_unit_basis": target_unit_basis,
                        "selected_scope_key": default_scope_key,
                        "price_review_flags": [
                            "MISSING_NUMERIC_PRICE"
                        ],
                        "selected_candidate_trace": {},
                        "price_resolution_policy_id": resolution_policy["policyId"],
                    },
                    reasons=["missing numeric price amount"],
                    fallback_used=True,
                )
            amount = float(fallback_amount)
            selected_candidate = {
                "source_type": selected_source_type,
                "amount": float(_normalize_numeric_output(amount)),
                "currency": base_currency,
                "priority": 999 if selected_source_type != "H06_FORMAL_SINK" else 0,
                "reliability_score": 80 if selected_source_type == "H06_FORMAL_SINK" else 40,
                "recency_days_optional": 0 if selected_source_type == "H06_FORMAL_SINK" else default_recency_days,
                "freshness_score": 100 if selected_source_type == "H06_FORMAL_SINK" else 35,
                "normalized_tax_basis": target_tax_basis,
                "normalized_unit_basis": target_unit_basis,
                "scope_key": default_scope_key,
                "review_flags": [] if selected_source_type == "H06_FORMAL_SINK" else ["DIRECT_FALLBACK_USED"],
                "lot_id_optional": None,
                "package_id_optional": None,
                "source_tax_basis": target_tax_basis,
                "source_unit_basis": target_unit_basis,
            }
            if selected_source_type != "H06_FORMAL_SINK":
                review_flags.add("DIRECT_FALLBACK_USED")
        amount = selected_candidate["amount"]
        if not _is_number(amount):
            return self._decision(
                policy_key="price_normalization",
                catalog_id=catalog["catalogId"],
                policy_id=[policy["policy_id"], resolution_policy["policyId"]],
                decision_state="FALLBACK",
                outputs={
                    "normalized_price_amount": None,
                    "normalized_price_currency": base_currency,
                    "price_band": "UNKNOWN",
                    "recommended_quote_band": "CUSTOM",
                    "price_signal_score": 30,
                    "price_conflict_gate_status": "REVIEW",
                    "selected_price_source_type": "UNKNOWN",
                    "price_candidate_count": len(candidates),
                    "price_candidate_deduped_count": len(deduped_candidates),
                    "price_source_priority_applied": [],
                    "normalized_tax_basis": target_tax_basis,
                    "normalized_unit_basis": target_unit_basis,
                    "selected_scope_key": default_scope_key,
                    "price_review_flags": [
                        "MISSING_NUMERIC_PRICE"
                    ],
                    "selected_candidate_trace": {},
                    "price_resolution_policy_id": resolution_policy["policyId"],
                },
                reasons=["missing numeric price amount"],
                fallback_used=True,
            )

        comparable_candidates = [
            entry for entry in deduped_candidates if entry.get("scope_key") == selected_candidate.get("scope_key")
        ] or [selected_candidate]
        review_flags.update(selected_candidate.get("review_flags", []))
        if (
            bool(policy["conflict_thresholds"].get("review_if_scope_mismatch"))
            and deduped_candidates
            and any(entry.get("scope_key") != selected_candidate.get("scope_key") for entry in deduped_candidates)
        ):
            review_flags.add("SCOPE_MISMATCH")
        if (
            bool(policy["conflict_thresholds"].get("review_if_tax_basis_mixed"))
            and len({entry.get("source_tax_basis") for entry in comparable_candidates if entry.get("source_tax_basis") not in (None, "", "UNKNOWN")}) > 1
        ):
            review_flags.add("TAX_BASIS_MIXED")
        if (
            bool(policy["conflict_thresholds"].get("review_if_unit_basis_mixed"))
            and len({entry.get("source_unit_basis") for entry in comparable_candidates if entry.get("source_unit_basis") not in (None, "", "UNKNOWN")}) > 1
        ):
            review_flags.add("UNIT_BASIS_MIXED")
        if (
            bool(policy["conflict_thresholds"].get("review_if_only_low_reliability_sources"))
            and comparable_candidates
            and all(int(entry.get("reliability_score", 0)) < low_reliability_threshold for entry in comparable_candidates)
        ):
            review_flags.add("ONLY_LOW_RELIABILITY_SOURCES")
        if (
            bool(policy["conflict_thresholds"].get("review_if_stale_reference_only"))
            and comparable_candidates
            and all(
                str(entry.get("source_type")) in reference_source_types
                and int(entry.get("recency_days_optional", default_recency_days)) > stale_reference_days
                for entry in comparable_candidates
            )
        ):
            review_flags.add("STALE_REFERENCE_ONLY")

        relative_diff = context.input("price_relative_diff_optional")
        if not _is_number(relative_diff) and len(comparable_candidates) >= 2:
            amounts = [entry["amount"] for entry in comparable_candidates]
            price_max = max(amounts)
            price_min = min(amounts)
            relative_diff = 0.0 if price_max == 0 else abs(price_max - price_min) / price_max
        if not _is_number(relative_diff):
            relative_diff = 0.0
        if relative_diff >= policy["conflict_thresholds"]["relative_diff_block"]:
            gate_status = "BLOCK"
        elif relative_diff >= policy["conflict_thresholds"]["relative_diff_review"]:
            gate_status = "REVIEW"
        else:
            gate_status = "PASS"
        if gate_status != "BLOCK" and review_flags:
            gate_status = "REVIEW"

        price_band = "UNKNOWN"
        for rule in band_rules:
            if bool(rule.get("default")):
                continue
            if _matches_range(amount, rule):
                price_band = str(rule.get("price_band", "UNKNOWN"))
                break
        if price_band == "UNKNOWN":
            default_rule = next((rule for rule in band_rules if bool(rule.get("default"))), None)
            if default_rule:
                price_band = str(default_rule.get("price_band", "UNKNOWN"))

        selected_candidate_trace = {
            "selected_candidate_rule": resolution_policy["selectedCandidateRule"],
            "amount": selected_candidate["amount"],
            "currency": selected_candidate["currency"],
            "normalized_tax_basis": target_tax_basis,
            "normalized_unit_basis": target_unit_basis,
            "scope_key": selected_candidate.get("scope_key", default_scope_key),
            "reliability_score": selected_candidate.get("reliability_score"),
            "freshness_score": selected_candidate.get("freshness_score"),
            "recency_days_optional": selected_candidate.get("recency_days_optional"),
        }
        outputs = {
            "normalized_price_amount": _normalize_numeric_output(float(amount)),
            "normalized_price_currency": base_currency,
            "price_band": price_band,
            "recommended_quote_band": policy["quote_band_mapping"][price_band],
            "price_signal_score": _score_from_matrix(
                gate_status=gate_status,
                price_band=price_band,
                matrix=score_matrix,
                default=30,
            ),
            "price_conflict_gate_status": gate_status,
            "selected_price_source_type": selected_candidate["source_type"] if selected_candidate else "DIRECT_FALLBACK",
            "price_candidate_count": len(candidates),
            "price_candidate_deduped_count": len(deduped_candidates),
            "price_source_priority_applied": [entry["source_type"] for entry in deduped_candidates],
            "normalized_tax_basis": target_tax_basis,
            "normalized_unit_basis": target_unit_basis,
            "selected_scope_key": selected_candidate.get("scope_key", default_scope_key),
            "price_review_flags": sorted(review_flags),
            "selected_candidate_trace": selected_candidate_trace,
            "price_resolution_policy_id": resolution_policy["policyId"],
        }
        decision_state = "BLOCK" if gate_status == "BLOCK" else "REVIEW" if gate_status == "REVIEW" else "ALLOW"
        return self._decision(
            policy_key="price_normalization",
            catalog_id=catalog["catalogId"],
            policy_id=[policy["policy_id"], resolution_policy["policyId"]],
            decision_state=decision_state,
            outputs=outputs,
            reasons=[f"price_band={price_band}", f"gate={gate_status}"] + [f"review_flag={flag}" for flag in sorted(review_flags)],
        )

    def _evaluate_buyer_fit_scorecard(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("buyer_fit_scorecard")
        scorecards = {entry["scorecardId"]: entry for entry in catalog["scorecards"]}
        derivations = catalog["dimensionDerivations"]
        project_fact = context.record("project_fact")
        report_record = context.record("report_record")
        challenger_profile = context.record("challenger_candidate_profile")
        legal_action_recommendation = context.record("legal_action_recommendation")
        fallback_policy = catalog.get("fallbackPolicy", {})
        source_fallbacks = fallback_policy.get("sourceFallbacks", {})
        reason_tag_policies = catalog.get("reasonTagPolicies", {})
        score_buckets = catalog.get("scoreBuckets", [])

        def fallback(field_name: str) -> tuple[Any, str]:
            entry = source_fallbacks[field_name]
            return entry["fallbackValue"], str(entry["contractSource"])

        sale_gate_default, sale_gate_default_source = fallback("sale_gate_status")
        sale_gate_status, sale_gate_status_source, sale_gate_fallback = _resolve_with_contract_fallback(
            [
                ("project_fact.sale_gate_status", project_fact.get("sale_gate_status")),
                ("inputs.sale_gate_status", context.input("sale_gate_status")),
            ],
            fallback_value=sale_gate_default,
            fallback_source=sale_gate_default_source,
        )
        coverage_default, coverage_default_source = fallback("coverage_sellable_state")
        coverage_sellable_state, coverage_sellable_state_source, coverage_fallback = _resolve_with_contract_fallback(
            [
                ("project_fact.coverage_sellable_state", project_fact.get("coverage_sellable_state")),
                ("inputs.coverage_sellable_state", context.input("coverage_sellable_state")),
            ],
            fallback_value=coverage_default,
            fallback_source=coverage_default_source,
        )
        crm_owner_default, crm_owner_default_source = fallback("crm_owner_state")
        crm_owner_state, crm_owner_state_source, crm_owner_fallback = _resolve_with_contract_fallback(
            [("inputs.crm_owner_state", context.input("crm_owner_state"))],
            fallback_value=crm_owner_default,
            fallback_source=crm_owner_default_source,
        )
        report_default, report_default_source = fallback("report_status")
        report_status, report_status_source, report_status_fallback = _resolve_with_contract_fallback(
            [
                ("report_record.report_status", report_record.get("report_status")),
                ("inputs.report_status", context.input("report_status")),
            ],
            fallback_value=report_default,
            fallback_source=report_default_source,
        )
        actionability_default, actionability_default_source = fallback("challenge_actionability_score")
        challenge_actionability, challenge_actionability_source, actionability_fallback = _resolve_with_contract_fallback(
            [
                ("competitor_confidence.selected_candidate", state.resolve("selected_challenge_actionability_score")),
                ("challenger_candidate_profile.challenge_actionability_score", challenger_profile.get("challenge_actionability_score")),
                ("inputs.challenge_actionability_score", context.input("challenge_actionability_score")),
            ],
            fallback_value=actionability_default,
            fallback_source=actionability_default_source,
        )
        readiness_default, readiness_default_source = fallback("execution_readiness_score")
        execution_readiness_score, execution_readiness_source, readiness_fallback = _resolve_with_contract_fallback(
            [
                ("competitor_confidence.selected_candidate", state.resolve("selected_execution_readiness_score")),
                ("challenger_candidate_profile.execution_readiness_score", challenger_profile.get("execution_readiness_score")),
                ("inputs.execution_readiness_score", context.input("execution_readiness_score")),
            ],
            fallback_value=readiness_default,
            fallback_source=readiness_default_source,
        )
        competitor_default, competitor_default_source = fallback("competitor_quality_grade")
        competitor_grade, competitor_grade_source, competitor_grade_fallback = _resolve_with_contract_fallback(
            [
                ("competitor_confidence.policy_output", state.resolve("competitor_quality_grade")),
                ("project_fact.competitor_quality_grade", project_fact.get("competitor_quality_grade")),
            ],
            fallback_value=competitor_default,
            fallback_source=competitor_default_source,
        )
        urgency_default, urgency_default_source = fallback("window_urgency_score")
        window_urgency_score, window_urgency_source, urgency_fallback = _resolve_with_contract_fallback(
            [
                ("window_value.policy_output", state.resolve("window_urgency_score")),
                ("inputs.window_urgency_score", context.input("window_urgency_score")),
            ],
            fallback_value=urgency_default,
            fallback_source=urgency_default_source,
        )
        window_status_default, window_status_default_source = fallback("window_status")
        window_status, window_status_source, window_status_fallback = _resolve_with_contract_fallback(
            [
                ("window_value.policy_output", state.resolve("window_status")),
                ("legal_action_recommendation.window_status", legal_action_recommendation.get("window_status")),
                ("inputs.window_status", context.input("window_status")),
            ],
            fallback_value=window_status_default,
            fallback_source=window_status_default_source,
        )
        source_trace = {
            "sale_gate_status": sale_gate_status_source,
            "coverage_sellable_state": coverage_sellable_state_source,
            "crm_owner_state": crm_owner_state_source,
            "report_status": report_status_source,
            "challenge_actionability_score": challenge_actionability_source,
            "execution_readiness_score": execution_readiness_source,
            "competitor_quality_grade": competitor_grade_source,
            "window_urgency_score": window_urgency_source,
            "window_status": window_status_source,
        }
        missing_formal_sources = [
            field_name
            for field_name, used_fallback in (
                ("sale_gate_status", sale_gate_fallback),
                ("coverage_sellable_state", coverage_fallback),
                ("crm_owner_state", crm_owner_fallback),
                ("report_status", report_status_fallback),
                ("challenge_actionability_score", actionability_fallback),
                ("execution_readiness_score", readiness_fallback),
                ("competitor_quality_grade", competitor_grade_fallback),
                ("window_urgency_score", urgency_fallback),
                ("window_status", window_status_fallback),
            )
            if used_fallback
        ]
        base_fit_rule = derivations["base_fit_score"]
        base_fit_score = round(
            _component_score(base_fit_rule, "sale_gate_status", sale_gate_status)
            * float(base_fit_rule["weights"]["sale_gate_status"])
            + _component_score(base_fit_rule, "report_status", report_status)
            * float(base_fit_rule["weights"]["report_status"])
            + _component_score(base_fit_rule, "competitor_quality_grade", competitor_grade)
            * float(base_fit_rule["weights"]["competitor_quality_grade"])
            + _bounded_score(window_urgency_score) * float(base_fit_rule["weights"]["window_urgency_score"])
            + _bounded_score(challenge_actionability) * float(base_fit_rule["weights"]["challenge_actionability_score"])
        )
        purchase_intent_rule = derivations["purchase_intent_score"]
        purchase_intent_score = _component_score(
            purchase_intent_rule,
            "report_status",
            report_status,
            float(purchase_intent_rule["component_scores"]["report_status"]["READY"]),
        )
        payment_capacity_rule = derivations["payment_capacity_score"]
        payment_capacity_score = _component_score(
            payment_capacity_rule,
            "sale_gate_status",
            sale_gate_status,
            float(payment_capacity_rule["component_scores"]["sale_gate_status"]["REVIEW"]),
        )
        attack_motivation_score = _bounded_score(challenge_actionability)
        challenge_actionability_bucket = _bucket_from_contract(attack_motivation_score, score_buckets)
        execution_readiness_bucket = _bucket_from_contract(_bounded_score(execution_readiness_score), score_buckets)

        general = scorecards["general_buyer_fit_v1"]
        challenger = scorecards["challenger_buyer_fit_v1"]

        def reason_tags(*, buyer_grade: str, challenger_grade: str) -> tuple[list[str], list[str]]:
            buyer_templates = reason_tag_policies["buyer_fit"]["templates"]
            challenger_templates = reason_tag_policies["challenger_buyer_fit"]["templates"]
            buyer_tags = _render_reason_tags(
                buyer_templates,
                {
                    "sale_gate_status": sale_gate_status,
                    "report_status": report_status,
                    "window_status": window_status,
                    "buyer_fit_grade": buyer_grade,
                    "crm_owner_state": crm_owner_state,
                },
            )
            challenger_tags = _render_reason_tags(
                challenger_templates,
                {
                    "challenge_actionability_bucket": challenge_actionability_bucket,
                    "execution_readiness_bucket": execution_readiness_bucket,
                    "window_status": window_status,
                    "challenger_buyer_fit_grade": challenger_grade,
                },
            )
            if missing_formal_sources:
                missing_tag = str(fallback_policy.get("missingFormalSourceReasonTag", "MISSING_FORMAL_SOURCE"))
                buyer_tags.append(missing_tag)
                challenger_tags.append(missing_tag)
            return buyer_tags, challenger_tags

        if sale_gate_status == "BLOCK" or coverage_sellable_state in ("NOT_READY", "SUSPENDED"):
            buyer_tags, challenger_tags = reason_tags(buyer_grade="D", challenger_grade="D")
            return self._decision(
                policy_key="buyer_fit_scorecard",
                catalog_id=catalog["catalogId"],
                policy_id=[general["scorecardId"], challenger["scorecardId"]],
                decision_state="BLOCK",
                outputs={
                    "buyer_fit_scorecard_id": general["scorecardId"],
                    "buyer_fit_scorecard_score": 0,
                    "buyer_fit_scorecard_grade": "D",
                    "challenger_buyer_fit_scorecard_id": challenger["scorecardId"],
                    "challenger_buyer_fit_scorecard_score": 0,
                    "challenger_buyer_fit_scorecard_grade": "D",
                    "buyer_fit_attack_motivation_score": attack_motivation_score,
                    "buyer_fit_purchase_intent_score": purchase_intent_score,
                    "buyer_fit_payment_capacity_score": payment_capacity_score,
                    "buyer_fit_window_urgency_score": window_urgency_score,
                    "buyer_fit_reason_tag_policy_id": reason_tag_policies["buyer_fit"]["policyId"],
                    "buyer_fit_reason_tags": buyer_tags,
                    "challenger_buyer_fit_reason_tag_policy_id": reason_tag_policies["challenger_buyer_fit"]["policyId"],
                    "challenger_buyer_fit_reason_tags": challenger_tags,
                    "buyer_fit_derivation_trace": {
                        "base_fit_score": base_fit_score,
                        "derivation_ids": list(derivations.keys()),
                        "component_sources": base_fit_rule["sources"],
                        "component_sources_used": source_trace,
                        "missing_formal_sources": missing_formal_sources,
                    },
                    "buyer_fit_missing_formal_sources": missing_formal_sources,
                },
                reasons=["buyer_fit hard blocker triggered"],
                fallback_used=bool(missing_formal_sources),
            )

        def score(entry: dict[str, Any], fit_score_value: float) -> tuple[int, str]:
            field_values = {
                "fit_score": fit_score_value,
                "attack_motivation_score": attack_motivation_score,
                "purchase_intent_score": purchase_intent_score,
                "payment_capacity_score": payment_capacity_score,
                "window_urgency_score": window_urgency_score,
            }
            total = 0.0
            for dimension in entry["dimensions"]:
                total += max(0, min(100, field_values[dimension["field"]])) * float(dimension["weight"])
            rounded = round(max(0, min(100, total)))
            return rounded, _grade_from_bands(rounded, entry["gradeBands"])

        buyer_score, buyer_grade = score(general, base_fit_score)
        challenger_score, challenger_grade = score(challenger, buyer_score)
        buyer_tags, challenger_tags = reason_tags(buyer_grade=buyer_grade, challenger_grade=challenger_grade)
        decision_state = (
            "REVIEW"
            if buyer_grade == "D" or crm_owner_state == "UNASSIGNED" or bool(missing_formal_sources)
            else "ALLOW"
        )
        reasons = [f"buyer_fit_scorecard_grade={buyer_grade}"]
        if missing_formal_sources:
            reasons.append(
                "missing_formal_sources=" + ",".join(sorted(missing_formal_sources))
            )
        return self._decision(
            policy_key="buyer_fit_scorecard",
            catalog_id=catalog["catalogId"],
            policy_id=[general["scorecardId"], challenger["scorecardId"]],
            decision_state=decision_state,
            outputs={
                "buyer_fit_scorecard_id": general["scorecardId"],
                "buyer_fit_scorecard_score": buyer_score,
                "buyer_fit_scorecard_grade": buyer_grade,
                "challenger_buyer_fit_scorecard_id": challenger["scorecardId"],
                "challenger_buyer_fit_scorecard_score": challenger_score,
                "challenger_buyer_fit_scorecard_grade": challenger_grade,
                "buyer_fit_attack_motivation_score": round(attack_motivation_score),
                "buyer_fit_purchase_intent_score": round(purchase_intent_score),
                "buyer_fit_payment_capacity_score": round(payment_capacity_score),
                "buyer_fit_window_urgency_score": round(window_urgency_score),
                "buyer_fit_reason_tag_policy_id": reason_tag_policies["buyer_fit"]["policyId"],
                "buyer_fit_reason_tags": buyer_tags,
                "challenger_buyer_fit_reason_tag_policy_id": reason_tag_policies["challenger_buyer_fit"]["policyId"],
                "challenger_buyer_fit_reason_tags": challenger_tags,
                "buyer_fit_derivation_trace": {
                    "base_fit_score": base_fit_score,
                    "derivation_ids": list(derivations.keys()),
                    "component_sources": base_fit_rule["sources"],
                    "component_sources_used": source_trace,
                    "missing_formal_sources": missing_formal_sources,
                },
                "buyer_fit_missing_formal_sources": missing_formal_sources,
            },
            reasons=reasons,
            fallback_used=bool(missing_formal_sources),
        )

    def _evaluate_competitor_confidence(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("competitor_confidence")
        policy = catalog["policies"][0]
        challenger = context.record("challenger_candidate_profile")
        if not challenger:
            return self._decision(
                policy_key="competitor_confidence",
                catalog_id=catalog["catalogId"],
                policy_id=policy["policy_id"],
                decision_state="REVIEW",
                outputs={"competitor_confidence_score": 0, "competitor_confidence_band": "LOW", "competitor_quality_grade": "D"},
                reasons=["missing challenger profile"],
            )

        external_use_grade = context.input("external_use_grade", "E2_REVIEW_READY")
        score = (
            _bounded_score(challenger.get("challenge_actionability_score", 0))
            * policy["weights"]["challenge_actionability_score"]
            / 100
            + policy["component_scores"]["external_use_grade"].get(external_use_grade, 30)
            * policy["weights"]["external_use_grade"]
            / 100
            + _bounded_score(challenger.get("focus_bidder_attackability_score", 0))
            * policy["weights"]["focus_bidder_attackability_score"]
            / 100
            + _bounded_score(challenger.get("challenger_pain_score", 0))
            * policy["weights"]["challenger_pain_score"]
            / 100
            + _bounded_score(challenger.get("execution_readiness_score", 0))
            * policy["weights"]["execution_readiness_score"]
            / 100
            + policy["component_scores"]["confidence_band_penalty"].get(context.input("confidence_band", "MEDIUM"), -10)
        )
        score = round(_bounded_score(score))

        def confidence_band_for(score_value: int | float) -> str:
            return _band_from_min_score(
                score_value,
                policy.get("confidence_band_rules", []),
                label_key="band",
                default="LOW",
            )

        def quality_grade_for(score_value: int | float) -> str:
            return _band_from_min_score(
                score_value,
                policy.get("quality_grade_rules", []),
                label_key="grade",
                default="D",
            )

        confidence_band = confidence_band_for(score)
        quality_grade = quality_grade_for(score)
        cutoff_policy = policy.get("cutoff_policy", {})
        evidence_ref_count = int(context.input("evidence_ref_count_optional", policy["evidence_requirements"]["min_evidence_refs"]))

        def policy_cutoff_reasons(score_value: int, band_value: str) -> list[str]:
            reasons: list[str] = []
            if score_value < int(cutoff_policy.get("candidate_only_score_lt", 55)):
                reasons.append("score_below_candidate_only_cutoff")
            if band_value in {str(item) for item in cutoff_policy.get("candidate_only_confidence_bands", ["LOW"])}:
                reasons.append(f"confidence_band={band_value}")
            if (
                evidence_ref_count < int(policy["evidence_requirements"]["min_evidence_refs"])
                and external_use_grade not in ("E3_CLIENT_VISIBLE", "E4_EXTERNAL_ACTION_READY")
            ):
                reasons.append("insufficient_evidence_refs")
            return reasons

        cutoff_reasons = policy_cutoff_reasons(score, confidence_band)
        base_outputs = {
            "competitor_confidence_score": score,
            "competitor_confidence_band": confidence_band,
            "competitor_quality_grade": quality_grade,
            "competitor_cutoff_reasons": cutoff_reasons,
            "competitor_cutoff_policy_id_optional": cutoff_policy.get("policy_id"),
            "competitor_ranking_policy_id_optional": policy.get("ranking_policy", {}).get("policy_id"),
        }

        if context.stage != 7 and context.capability_mode != "stage7_sales":
            return self._decision(
                policy_key="competitor_confidence",
                catalog_id=catalog["catalogId"],
                policy_id=policy["policy_id"],
                decision_state="REVIEW" if cutoff_reasons or confidence_band == "LOW" or quality_grade == "D" else "ALLOW",
                outputs=base_outputs,
                reasons=[f"competitor_confidence_score={score}"] + [f"cutoff={reason}" for reason in cutoff_reasons],
            )

        resolution_policy = load_contract("contracts/sales/stage7_resolution_policy.json", self.settings)[
            "multiCompetitorResolution"
        ]
        entity_policy = resolution_policy.get("entityResolution", {})
        ranking_policy = policy.get("ranking_policy", {})
        ranking_policy_id = ranking_policy.get("policy_id")
        cutoff_policy_id = cutoff_policy.get("policy_id")
        top_n_limit = max(1, int(ranking_policy.get("top_n_limit", 3)))
        position_priority = {
            str(label): int(priority)
            for label, priority in ranking_policy.get("candidate_position_priority", {}).items()
        }
        candidate_source_priority = {
            str(label): int(priority)
            for label, priority in entity_policy.get("candidateSourcePriority", {}).items()
        }
        ranking_weights = ranking_policy.get("score_component_weights", {})
        fallback_confidence = int(ranking_policy.get("fallback_confidence_score", 45))
        sort_basis = list(ranking_policy.get("sort_order", []))
        winner_selection = str(
            ranking_policy.get(
                "winner_selection",
                resolution_policy.get("retention", {}).get("winner_selection", "highest_ranked_non_candidate_only_else_rank_1"),
            )
        )
        candidate_only_tags = {str(item) for item in ranking_policy.get("candidate_only_reason_tags", [])}
        candidate_only_bands = {str(item) for item in cutoff_policy.get("candidate_only_confidence_bands", ["LOW"])}
        cutoff_score = int(cutoff_policy.get("candidate_only_score_lt", 55))
        alias_fields = [str(field_name) for field_name in entity_policy.get("aliasFields", [])]
        alias_normalizer = str(entity_policy.get("aliasNormalizer", "UPPER_ALNUM"))

        def candidate_only_tag(prefix: str, fallback: str) -> str:
            return next((tag for tag in candidate_only_tags if tag.startswith(prefix)), fallback)

        score_cutoff_tag = candidate_only_tag("CONFIDENCE_SCORE_LT_", f"CONFIDENCE_SCORE_LT_{cutoff_score}")

        def ranking_score(confidence_score: int, actionability_score: int, readiness_score: int) -> int:
            return round(
                _bounded_score(actionability_score) * float(ranking_weights.get("challenge_actionability_score", 0.45))
                + _bounded_score(readiness_score) * float(ranking_weights.get("execution_readiness_score", 0.35))
                + _bounded_score(confidence_score) * float(ranking_weights.get("confidence_score_optional", 0.20))
            )

        def alias_tokens(raw_candidate: dict[str, Any]) -> list[str]:
            tokens: list[str] = []
            for field_name in alias_fields:
                raw_value = raw_candidate.get(field_name)
                for value in _ensure_list(raw_value):
                    normalized = _normalize_alias_token(value, normalizer=alias_normalizer)
                    if normalized:
                        tokens.append(normalized)
            return sorted(set(tokens))

        def canonical_entity_key(raw_candidate: dict[str, Any], alias_token_list: list[str]) -> str:
            for field_name in entity_policy.get("canonicalIdPreference", []):
                candidate_value = _optional_str(raw_candidate.get(field_name))
                if candidate_value:
                    return f"{field_name}:{candidate_value}"
            if alias_token_list:
                return f"alias:{alias_token_list[0]}"
            return f"fallback:{_optional_str(raw_candidate.get('candidate_id')) or build_id('MCAND', context.project_id, 'UNRESOLVED')}"

        def ranking_cutoff_reasons(candidate: dict[str, Any], rank: int) -> list[str]:
            reasons: list[str] = []
            if rank > top_n_limit:
                reasons.append("RANK_GT_TOP_N")
            confidence_score = int(candidate["confidence_score_optional"])
            band = confidence_band_for(confidence_score)
            if confidence_score < cutoff_score:
                reasons.append(score_cutoff_tag)
            if band in candidate_only_bands:
                reasons.append(f"CONFIDENCE_BAND_{band}")
            return [reason for reason in reasons if not candidate_only_tags or reason in candidate_only_tags]

        focus_bidder_id = _optional_str(context.input("focus_bidder_id", challenger.get("focus_bidder_id"))) or build_id(
            "FOCUS", context.project_id
        )
        challenger_bidder_id = _optional_str(
            context.input("challenger_bidder_id", challenger.get("challenger_bidder_id"))
        ) or build_id("BID", context.project_id, "CHALLENGER")
        challenger_profile_id = _optional_str(
            context.input("challenger_profile_id", challenger.get("challenger_profile_id"))
        ) or build_id("CHAL", context.project_id)
        candidate_position_label = _optional_str(
            context.input("candidate_position_label", challenger.get("candidate_position_label"))
        ) or "UNKNOWN"
        challenge_actionability_score = int(
            _optional_int(context.input("challenge_actionability_score", challenger.get("challenge_actionability_score"))) or 0
        )
        execution_readiness_score = int(
            _optional_int(context.input("execution_readiness_score", challenger.get("execution_readiness_score"))) or 0
        )
        real_competitor_count = int(
            context.input("real_competitor_count", context.record("project_fact").get("real_competitor_count", 0))
        )

        raw_candidates: list[dict[str, Any]] = [
            {
                "candidate_id": build_id("MCAND", context.project_id, "WINNER"),
                "challenger_profile_id": challenger_profile_id,
                "focus_bidder_id": focus_bidder_id,
                "challenger_bidder_id": challenger_bidder_id,
                "candidate_position_label": candidate_position_label,
                "confidence_score_optional": score,
                "challenge_actionability_score": challenge_actionability_score,
                "execution_readiness_score": execution_readiness_score,
                "ranking_reason_tags_optional": [
                    "STAGE6_FORMAL_CHALLENGER",
                    f"POSITION_{candidate_position_label}",
                    f"RANKING_POLICY_{ranking_policy_id}",
                    f"CUTOFF_POLICY_{cutoff_policy_id}",
                ],
                "ranking_score": ranking_score(score, challenge_actionability_score, execution_readiness_score),
                "selected_flag": False,
                "candidate_source": "STAGE6_CHALLENGER_PROFILE",
                "_entity_key": f"challenger_bidder_id:{challenger_bidder_id}",
                "_alias_tokens": [],
            }
        ]
        raw_pool = context.input("multi_competitor_candidate_pool", [])
        if isinstance(raw_pool, list):
            for index, raw_candidate in enumerate(raw_pool, start=1):
                if not isinstance(raw_candidate, dict):
                    continue
                raw_profile_id = _optional_str(raw_candidate.get("challenger_profile_id")) or build_id(
                    "CHALT", context.project_id, f"{index:02d}"
                )
                raw_bidder_id = (
                    _optional_str(raw_candidate.get("challenger_bidder_id"))
                    or _optional_str(raw_candidate.get("bidder_id"))
                    or build_id("BID", context.project_id, f"MC{index:02d}")
                )
                raw_position = _optional_str(raw_candidate.get("candidate_position_label")) or "OTHER"
                raw_confidence = _optional_int(raw_candidate.get("confidence_score_optional"))
                raw_actionability = int(
                    raw_candidate.get(
                        "challenge_actionability_score",
                        raw_candidate.get(
                            "challenge_actionability_score_optional",
                            max(35, raw_confidence or 0, challenge_actionability_score - 8),
                        ),
                    )
                )
                raw_readiness = int(
                    raw_candidate.get(
                        "execution_readiness_score",
                        raw_candidate.get(
                            "execution_readiness_score_optional",
                            max(30, raw_confidence or 0, execution_readiness_score - 10),
                        ),
                    )
                )
                effective_confidence = raw_confidence if raw_confidence is not None else fallback_confidence
                normalized_aliases = alias_tokens(raw_candidate)
                raw_entity_key = canonical_entity_key(
                    {
                        **raw_candidate,
                        "challenger_profile_id": raw_profile_id,
                        "challenger_bidder_id": raw_bidder_id,
                    },
                    normalized_aliases,
                )
                raw_candidates.append(
                    {
                        "candidate_id": _optional_str(raw_candidate.get("candidate_id")) or build_id(
                            "MCAND", context.project_id, f"{index:02d}"
                        ),
                        "challenger_profile_id": raw_profile_id,
                        "focus_bidder_id": _optional_str(raw_candidate.get("focus_bidder_id")) or focus_bidder_id,
                        "challenger_bidder_id": raw_bidder_id,
                        "candidate_position_label": raw_position,
                        "confidence_score_optional": effective_confidence,
                        "ranking_reason_tags_optional": _ensure_list(
                            raw_candidate.get(
                                "ranking_reason_tags_optional",
                                [
                                    f"POSITION_{raw_position}",
                                    "POOL_CANDIDATE",
                                    f"RANKING_POLICY_{ranking_policy_id}",
                                    f"CUTOFF_POLICY_{cutoff_policy_id}",
                                ],
                            )
                        ),
                        "challenge_actionability_score": raw_actionability,
                        "execution_readiness_score": raw_readiness,
                        "ranking_score": ranking_score(effective_confidence, raw_actionability, raw_readiness),
                        "selected_flag": False,
                        "candidate_source": _optional_str(raw_candidate.get("candidate_source")) or "DIRECT_POOL_INPUT",
                        "_entity_key": raw_entity_key,
                        "_alias_tokens": normalized_aliases,
                    }
                )

        deduped_candidates: dict[str, dict[str, Any]] = {}
        alias_deduped_count = 0
        for candidate in raw_candidates:
            entity_key = str(candidate["_entity_key"])
            existing = deduped_candidates.get(entity_key)
            if existing is None:
                deduped_candidates[entity_key] = candidate
                continue
            alias_deduped_count += 1
            existing_key = (
                candidate_source_priority.get(str(existing["candidate_source"]), 99),
                -int(existing["confidence_score_optional"]),
                -int(existing["ranking_score"]),
                position_priority.get(str(existing["candidate_position_label"]), 99),
                str(existing["candidate_id"]),
            )
            candidate_key = (
                candidate_source_priority.get(str(candidate["candidate_source"]), 99),
                -int(candidate["confidence_score_optional"]),
                -int(candidate["ranking_score"]),
                position_priority.get(str(candidate["candidate_position_label"]), 99),
                str(candidate["candidate_id"]),
            )
            winner = candidate if candidate_key < existing_key else existing
            loser = existing if winner is candidate else candidate
            winner["ranking_reason_tags_optional"] = _ensure_list(winner["ranking_reason_tags_optional"]) + [
                "ENTITY_RESOLUTION_DEDUP",
                f"DEDUPED_{loser['candidate_id']}",
            ]
            deduped_candidates[entity_key] = winner

        candidates = list(deduped_candidates.values())
        candidates.sort(
            key=lambda item: (
                -int(item["ranking_score"]),
                -int(item["confidence_score_optional"]),
                position_priority.get(str(item["candidate_position_label"]), 99),
                str(item["candidate_id"]),
            )
        )

        top_n_candidate_ids: list[str] = []
        candidate_only_candidate_ids: list[str] = []
        winner_candidate: dict[str, Any] | None = None
        for rank, item in enumerate(candidates, start=1):
            reasons = ranking_cutoff_reasons(item, rank)
            if rank <= top_n_limit:
                top_n_candidate_ids.append(str(item["candidate_id"]))
            item["candidate_rank"] = rank
            if reasons:
                candidate_only_candidate_ids.append(str(item["candidate_id"]))
            item["ranking_reason_tags_optional"] = _ensure_list(item["ranking_reason_tags_optional"]) + reasons
            if winner_candidate is None and rank <= top_n_limit and not reasons:
                winner_candidate = item

        if winner_candidate is None:
            winner_candidate = candidates[0]

        for item in candidates:
            item["selected_flag"] = item["candidate_id"] == winner_candidate["candidate_id"]

        def sanitized_candidate(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "candidate_id": str(item["candidate_id"]),
                "challenger_profile_id": str(item["challenger_profile_id"]),
                "focus_bidder_id": str(item["focus_bidder_id"]),
                "challenger_bidder_id": str(item["challenger_bidder_id"]),
                "candidate_position_label": str(item["candidate_position_label"]),
                "candidate_rank": int(item["candidate_rank"]),
                "confidence_score_optional": int(item["confidence_score_optional"]),
                "ranking_reason_tags_optional": _ensure_list(item["ranking_reason_tags_optional"]),
                "challenge_actionability_score": int(item["challenge_actionability_score"]),
                "execution_readiness_score": int(item["execution_readiness_score"]),
                "ranking_score": int(item["ranking_score"]),
                "selected_flag": bool(item["selected_flag"]),
                "candidate_source": str(item["candidate_source"]),
            }

        sanitized_candidates = [sanitized_candidate(item) for item in candidates]
        winning_candidate = sanitized_candidate(winner_candidate)
        selected_score = int(winning_candidate["confidence_score_optional"])
        selected_band = confidence_band_for(selected_score)
        selected_grade = quality_grade_for(selected_score)
        selected_cutoff_reasons = policy_cutoff_reasons(selected_score, selected_band)
        selection_trace = {
            "selection_policy_id": resolution_policy["policyId"],
            "authoritative_ranking_policy_id": ranking_policy_id,
            "authoritative_cutoff_policy_id": cutoff_policy_id,
            "authoritative_ranking_policy_ref": resolution_policy.get("ranking", {}).get("authoritativePolicyRef"),
            "authoritative_cutoff_policy_ref": resolution_policy.get("retention", {}).get("authoritativePolicyRef"),
            "sort_basis": sort_basis,
            "ranking_mode": str(ranking_policy.get("ranking_mode", "TOP_N_RETAINED_WITH_CANDIDATE_ONLY_CUTOFF")),
            "input_candidate_count": len(candidates),
            "top_n_limit": top_n_limit,
            "candidate_only_reason_tags": sorted(candidate_only_tags),
            "winner_selection_basis": [
                f"winner_selection={winner_selection}",
                f"ranking_policy_id={ranking_policy_id}",
                f"cutoff_policy_id={cutoff_policy_id}",
                f"real_competitor_count={real_competitor_count}",
                f"winning_candidate_id={winning_candidate['candidate_id']}",
                f"winning_challenger_profile_id={winning_candidate['challenger_profile_id']}",
                f"candidate_only_candidate_ids={','.join(candidate_only_candidate_ids) if candidate_only_candidate_ids else 'NONE'}",
            ],
        }
        trace_summary = {
            "policy_id": resolution_policy["policyId"],
            "ranking_policy_id": ranking_policy_id,
            "cutoff_policy_id": cutoff_policy_id,
            "candidate_only_candidate_ids": candidate_only_candidate_ids,
            "alias_deduped_count": alias_deduped_count,
            "deduped_candidate_count": len(candidates),
            "top_n_limit": top_n_limit,
        }
        outputs = {
            **base_outputs,
            "competitor_confidence_score": selected_score,
            "competitor_confidence_band": selected_band,
            "competitor_quality_grade": selected_grade,
            "competitor_cutoff_reasons": selected_cutoff_reasons,
            "selected_focus_bidder_id": winning_candidate["focus_bidder_id"],
            "selected_challenger_bidder_id": winning_candidate["challenger_bidder_id"],
            "selected_challenger_profile_id": winning_candidate["challenger_profile_id"],
            "selected_candidate_position_label": winning_candidate["candidate_position_label"],
            "selected_challenge_actionability_score": winning_candidate["challenge_actionability_score"],
            "selected_execution_readiness_score": winning_candidate["execution_readiness_score"],
            "selected_candidate_only_optional": winning_candidate["candidate_id"] in candidate_only_candidate_ids,
            "multi_competitor_candidates": sanitized_candidates,
            "top_n_candidate_ids": top_n_candidate_ids,
            "winning_competitor_candidate": winning_candidate,
            "competitor_selection_trace": selection_trace,
            "competitor_trace_summary": trace_summary,
        }

        return self._decision(
            policy_key="competitor_confidence",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state="REVIEW" if selected_cutoff_reasons or selected_band == "LOW" or selected_grade == "D" else "ALLOW",
            outputs=outputs,
            reasons=[f"competitor_confidence_score={selected_score}"]
            + [f"cutoff={reason}" for reason in selected_cutoff_reasons],
        )

    def _evaluate_value_scoring(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("value_scoring")
        models = {entry["model_id"]: entry for entry in catalog["models"]}
        project_fact = context.record("project_fact")
        derivation_policy = catalog.get("derivationPolicy", {})
        fallback_policy = derivation_policy.get("sourceFallbacks", {})
        reason_tag_policies = catalog.get("reasonTagPolicies", {})

        def fallback(field_name: str) -> tuple[Any, str]:
            entry = fallback_policy[field_name]
            return entry["fallbackValue"], str(entry["contractSource"])

        window_default, window_default_source = fallback("window_urgency_score")
        window_urgency_score, window_urgency_source, window_urgency_fallback = _resolve_with_contract_fallback(
            [
                ("window_value.policy_output", state.resolve("window_urgency_score")),
                ("inputs.window_urgency_score", context.input("window_urgency_score")),
            ],
            fallback_value=window_default,
            fallback_source=window_default_source,
        )
        price_default, price_default_source = fallback("price_signal_score")
        price_signal_score, price_signal_source, price_signal_fallback = _resolve_with_contract_fallback(
            [
                ("price_normalization.policy_output", state.resolve("price_signal_score")),
                ("inputs.price_signal_score", context.input("price_signal_score")),
            ],
            fallback_value=price_default,
            fallback_source=price_default_source,
        )
        competitor_default, competitor_default_source = fallback("competitor_quality_grade")
        competitor_grade, competitor_grade_source, competitor_grade_fallback = _resolve_with_contract_fallback(
            [
                ("competitor_confidence.policy_output", state.resolve("competitor_quality_grade")),
                ("project_fact.competitor_quality_grade", project_fact.get("competitor_quality_grade")),
            ],
            fallback_value=competitor_default,
            fallback_source=competitor_default_source,
        )
        external_use_default, external_use_default_source = fallback("external_use_grade")
        external_use_grade, external_use_grade_source, external_use_fallback = _resolve_with_contract_fallback(
            [("inputs.external_use_grade", context.input("external_use_grade"))],
            fallback_value=external_use_default,
            fallback_source=external_use_default_source,
        )
        competitor_confidence_default, competitor_confidence_default_source = fallback("competitor_confidence_score")
        competitor_confidence_score, competitor_confidence_source, competitor_confidence_fallback = _resolve_with_contract_fallback(
            [
                ("competitor_confidence.policy_output", state.resolve("competitor_confidence_score")),
                ("project_fact.confidence_score_optional", project_fact.get("confidence_score_optional")),
            ],
            fallback_value=competitor_confidence_default,
            fallback_source=competitor_confidence_default_source,
        )
        challenge_actionability_default, challenge_actionability_default_source = fallback("challenge_actionability_score")
        challenge_actionability_score, challenge_actionability_source, challenge_actionability_fallback = _resolve_with_contract_fallback(
            [
                ("competitor_confidence.selected_candidate", state.resolve("selected_challenge_actionability_score")),
                ("challenger_candidate_profile.challenge_actionability_score", context.record("challenger_candidate_profile").get("challenge_actionability_score")),
                ("inputs.challenge_actionability_score", context.input("challenge_actionability_score")),
            ],
            fallback_value=challenge_actionability_default,
            fallback_source=challenge_actionability_default_source,
        )
        rule_gate_default, rule_gate_default_source = fallback("rule_gate_status")
        rule_gate_status, rule_gate_source, rule_gate_fallback = _resolve_with_contract_fallback(
            [
                ("project_fact.rule_gate_status", project_fact.get("rule_gate_status")),
                ("inputs.rule_gate_status", context.input("rule_gate_status")),
            ],
            fallback_value=rule_gate_default,
            fallback_source=rule_gate_default_source,
        )
        evidence_gate_default, evidence_gate_default_source = fallback("evidence_gate_status")
        evidence_gate_status, evidence_gate_source, evidence_gate_fallback = _resolve_with_contract_fallback(
            [
                ("project_fact.evidence_gate_status", project_fact.get("evidence_gate_status")),
                ("inputs.evidence_gate_status", context.input("evidence_gate_status")),
            ],
            fallback_value=evidence_gate_default,
            fallback_source=evidence_gate_default_source,
        )
        sale_gate_default, sale_gate_default_source = fallback("sale_gate_status")
        sale_gate_status, sale_gate_source, sale_gate_fallback = _resolve_with_contract_fallback(
            [
                ("project_fact.sale_gate_status", project_fact.get("sale_gate_status")),
                ("inputs.sale_gate_status", context.input("sale_gate_status")),
            ],
            fallback_value=sale_gate_default,
            fallback_source=sale_gate_default_source,
        )
        window_status_default, window_status_default_source = fallback("window_status")
        window_status, window_status_source, window_status_fallback = _resolve_with_contract_fallback(
            [
                ("window_value.policy_output", state.resolve("window_status")),
                ("legal_action_recommendation.window_status", context.record("legal_action_recommendation").get("window_status")),
                ("inputs.window_status", context.input("window_status")),
            ],
            fallback_value=window_status_default,
            fallback_source=window_status_default_source,
        )
        delivery_risk_default, delivery_risk_default_source = fallback("delivery_risk_state")
        delivery_risk_state, delivery_risk_source, delivery_risk_fallback = _resolve_with_contract_fallback(
            [
                ("project_fact.delivery_risk_state", project_fact.get("delivery_risk_state")),
                ("inputs.delivery_risk_state", context.input("delivery_risk_state")),
            ],
            fallback_value=delivery_risk_default,
            fallback_source=delivery_risk_default_source,
        )
        coverage_default, coverage_default_source = fallback("coverage_sellable_state")
        coverage_sellable_state, coverage_source, coverage_fallback = _resolve_with_contract_fallback(
            [
                ("project_fact.coverage_sellable_state", project_fact.get("coverage_sellable_state")),
                ("inputs.coverage_sellable_state", context.input("coverage_sellable_state")),
            ],
            fallback_value=coverage_default,
            fallback_source=coverage_default_source,
        )

        buyer_fit_score = state.resolve("buyer_fit_scorecard_score")
        buyer_fit_decision = None
        if _is_number(buyer_fit_score):
            buyer_fit_score_source = "buyer_fit_scorecard_policy_output"
            buyer_fit_trace = state.resolve("buyer_fit_derivation_trace", {})
        else:
            buyer_fit_decision = self._evaluate_buyer_fit_scorecard(context, state)
            buyer_fit_score = buyer_fit_decision.outputs["buyer_fit_scorecard_score"]
            buyer_fit_score_source = str(
                derivation_policy.get("buyerFitReplayTraceLabel", "buyer_fit_scorecard_policy_replay")
            )
            buyer_fit_trace = buyer_fit_decision.outputs.get("buyer_fit_derivation_trace", {})
        buyer_fit_score = round(_bounded_score(buyer_fit_score))

        project_model = models["PROJECT-VALUE-001"]
        project_score = (
            _bounded_score(window_urgency_score) * project_model["weights"]["window_urgency_score"] / 100
            + _component_score(project_model, "external_use_grade", external_use_grade, 30) * project_model["weights"]["external_use_grade"] / 100
            + _component_score(project_model, "coverage_sellable_state", coverage_sellable_state, 70) * project_model["weights"]["coverage_sellable_state"] / 100
            + _component_score(project_model, "delivery_risk_state", delivery_risk_state, 60) * project_model["weights"]["delivery_risk_state"] / 100
            + _component_score(project_model, "competitor_quality_grade", competitor_grade, 50) * project_model["weights"]["competitor_quality_grade"] / 100
            + _bounded_score(price_signal_score) * project_model["weights"]["price_signal_score"] / 100
        )
        if sale_gate_status == "BLOCK" or rule_gate_status == "BLOCK" or evidence_gate_status == "BLOCK":
            project_score = 0
        project_score = round(max(0, min(100, project_score)))
        project_band = _grade_from_bands(project_score, project_model["gradeBands"])
        if window_status == "MISSED" and project_score > 0:
            project_band = _downgrade_grade(project_band)

        lead_model = models["LEAD-VALUE-001"]
        lead_score = (
            project_score * lead_model["weights"]["project_value_score"] / 100
            + _bounded_score(competitor_confidence_score) * lead_model["weights"]["challenger_confidence_score"] / 100
            + _bounded_score(window_urgency_score) * lead_model["weights"]["window_urgency_score"] / 100
            + _component_score(lead_model, "external_use_grade", external_use_grade, 30) * lead_model["weights"]["external_use_grade"] / 100
        )
        lead_score = round(max(0, min(100, lead_score)))
        if window_status == "MISSED":
            lead_score = min(54, lead_score)
        lead_band = _grade_from_bands(lead_score, lead_model["gradeBands"])

        opportunity_model = models["OPPORTUNITY-VALUE-001"]
        opportunity_score = (
            project_score * opportunity_model["weights"]["project_value_score"] / 100
            + buyer_fit_score * opportunity_model["weights"]["buyer_fit.fit_score"] / 100
            + _bounded_score(challenge_actionability_score) * opportunity_model["weights"]["challenge_actionability_score"] / 100
            + _bounded_score(price_signal_score) * opportunity_model["weights"]["price_signal_score"] / 100
            + _bounded_score(window_urgency_score) * opportunity_model["weights"]["window_urgency_score"] / 100
        )
        if (
            sale_gate_status == "BLOCK"
            or delivery_risk_state == "BLOCK"
            or coverage_sellable_state in ("NOT_READY", "SUSPENDED")
        ):
            opportunity_score = 0
        opportunity_score = round(max(0, min(100, opportunity_score)))
        opportunity_grade = _grade_from_bands(opportunity_score, opportunity_model["gradeBands"])
        source_trace = {
            "window_urgency_score": window_urgency_source,
            "price_signal_score": price_signal_source,
            "competitor_quality_grade": competitor_grade_source,
            "external_use_grade": external_use_grade_source,
            "competitor_confidence_score": competitor_confidence_source,
            "challenge_actionability_score": challenge_actionability_source,
            "rule_gate_status": rule_gate_source,
            "evidence_gate_status": evidence_gate_source,
            "sale_gate_status": sale_gate_source,
            "delivery_risk_state": delivery_risk_source,
            "coverage_sellable_state": coverage_source,
            "window_status": window_status_source,
        }
        missing_formal_sources = [
            field_name
            for field_name, used_fallback in (
                ("window_urgency_score", window_urgency_fallback),
                ("price_signal_score", price_signal_fallback),
                ("competitor_quality_grade", competitor_grade_fallback),
                ("external_use_grade", external_use_fallback),
                ("competitor_confidence_score", competitor_confidence_fallback),
                ("challenge_actionability_score", challenge_actionability_fallback),
                ("rule_gate_status", rule_gate_fallback),
                ("evidence_gate_status", evidence_gate_fallback),
                ("sale_gate_status", sale_gate_fallback),
                ("delivery_risk_state", delivery_risk_fallback),
                ("coverage_sellable_state", coverage_fallback),
                ("window_status", window_status_fallback),
            )
            if used_fallback
        ]

        project_reason_tags = _render_reason_tags(
            reason_tag_policies["project_value"]["templates"],
            {
                "window_status": window_status,
                "sale_gate_status": sale_gate_status,
                "project_value_band": project_band,
                "external_use_grade": external_use_grade,
            },
        )
        lead_reason_tags = _render_reason_tags(
            reason_tag_policies["lead_value"]["templates"],
            {
                "lead_value_band": lead_band,
                "window_status": window_status,
                "competitor_confidence_band": state.resolve("competitor_confidence_band", "LOW"),
                "external_use_grade": external_use_grade,
            },
        )
        opportunity_reason_tags = _render_reason_tags(
            reason_tag_policies["opportunity_value"]["templates"],
            {
                "opportunity_grade": opportunity_grade,
                "window_status": window_status,
                "delivery_risk_state": delivery_risk_state,
            },
        )
        if missing_formal_sources:
            project_reason_tags.append("MISSING_FORMAL_SOURCE")
            lead_reason_tags.append("MISSING_FORMAL_SOURCE")
            opportunity_reason_tags.append("MISSING_FORMAL_SOURCE")

        reasons = [f"opportunity_score={opportunity_score}"]
        if missing_formal_sources:
            reasons.append("missing_formal_sources=" + ",".join(sorted(missing_formal_sources)))

        return self._decision(
            policy_key="value_scoring",
            catalog_id=catalog["catalogId"],
            policy_id=list(models.keys()),
            decision_state="REVIEW" if opportunity_grade == "D" or bool(missing_formal_sources) else "ALLOW",
            outputs={
                "project_value_score": project_score,
                "lead_score": lead_score,
                "opportunity_value_score": opportunity_score,
                "opportunity_grade": opportunity_grade,
                "project_value_band": project_band,
                "lead_value_band": lead_band,
                "opportunity_value_band": opportunity_grade,
                "project_value_reason_tag_policy_id": reason_tag_policies["project_value"]["policyId"],
                "project_value_reason_tags": project_reason_tags,
                "lead_value_reason_tag_policy_id": reason_tag_policies["lead_value"]["policyId"],
                "lead_value_reason_tags": lead_reason_tags,
                "opportunity_value_reason_tag_policy_id": reason_tag_policies["opportunity_value"]["policyId"],
                "opportunity_value_reason_tags": opportunity_reason_tags,
                "value_derivation_trace": {
                    "model_ids": list(models.keys()),
                    "model_gating_rules": {
                        model_id: list(model.get("gating_rules", []))
                        for model_id, model in models.items()
                    },
                    "buyer_fit_score_source": buyer_fit_score_source,
                    "buyer_fit_policy_trace": buyer_fit_trace,
                    "gating_inputs": {
                        "rule_gate_status": rule_gate_status,
                        "evidence_gate_status": evidence_gate_status,
                        "sale_gate_status": sale_gate_status,
                        "delivery_risk_state": delivery_risk_state,
                        "coverage_sellable_state": coverage_sellable_state,
                        "window_status": window_status,
                    },
                    "component_sources_used": source_trace,
                    "missing_formal_sources": missing_formal_sources,
                    "buyer_fit_replayed": buyer_fit_decision is not None,
                },
            },
            reasons=reasons,
            fallback_used=bool(missing_formal_sources),
        )

    def _evaluate_sku_recommendation(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("sku_recommendation")
        policy = catalog["policies"][0]
        project_fact = context.record("project_fact")

        opportunity_grade = state.resolve("opportunity_grade", context.input("opportunity_grade", "D"))
        fit_score = state.resolve("buyer_fit_scorecard_score", 0)
        window_urgency_score = state.resolve("window_urgency_score", context.input("window_urgency_score", 50))
        price_band = state.resolve("price_band", context.input("price_band_optional", "UNKNOWN"))
        price_conflict_gate_status = state.resolve(
            "price_conflict_gate_status",
            context.input("price_conflict_gate_status_optional", "REVIEW"),
        )
        external_use_grade = context.input("external_use_grade", "E2_REVIEW_READY")
        delivery_risk_state = context.input(
            "delivery_risk_state",
            project_fact.get("delivery_risk_state", "REVIEW"),
        )
        coverage_sellable_state = context.input(
            "coverage_sellable_state",
            project_fact.get("coverage_sellable_state", "RESTRICTED"),
        )
        window_status = state.resolve("window_status", context.input("window_status", "REVIEW_REQUIRED"))

        review_reasons: list[str] = []
        if coverage_sellable_state in ("NOT_READY", "SUSPENDED"):
            review_reasons.append("coverage_review_only")
        if delivery_risk_state == "BLOCK":
            review_reasons.append("delivery_risk_blocked")
        if price_conflict_gate_status == "BLOCK":
            review_reasons.append("price_conflict_blocked")
        if external_use_grade == "E1_INTERNAL_ONLY":
            review_reasons.append("external_use_internal_only")
        if window_status == "MISSED":
            review_reasons.append("window_missed")

        if opportunity_grade == "A" and fit_score >= 80 and window_urgency_score >= 70 and external_use_grade in ("E3_CLIENT_VISIBLE", "E4_EXTERNAL_ACTION_READY"):
            sku_code = "SKU-A"
            recommended_delivery_form = "OBJECTION_DRAFT"
            recommended_quote_band = "HIGH"
        elif opportunity_grade == "B" and fit_score >= 65 and external_use_grade in ("E3_CLIENT_VISIBLE", "E4_EXTERNAL_ACTION_READY"):
            sku_code = "SKU-B"
            recommended_delivery_form = "EVIDENCE_PACK"
            recommended_quote_band = "MEDIUM"
        elif opportunity_grade == "C" and fit_score >= 50 and external_use_grade in ("E2_REVIEW_READY", "E3_CLIENT_VISIBLE", "E4_EXTERNAL_ACTION_READY"):
            sku_code = "SKU-C"
            recommended_delivery_form = "ANALYSIS_REPORT"
            recommended_quote_band = "LOW"
        else:
            sku_code = "SKU-C"
            recommended_delivery_form = "PROJECT_BRIEF"
            recommended_quote_band = "CUSTOM"

        if price_band == "UNKNOWN":
            recommended_quote_band = "CUSTOM"

        offer_state = "APPROVED"
        decision_state = "ALLOW"
        if review_reasons:
            offer_state = "REVIEW_REQUIRED"
            decision_state = "REVIEW"

        opportunity_catalog = self.load_policy("opportunity_policy")
        opportunity_policy = next(
            entry
            for entry in opportunity_catalog["policies"]
            if entry["policyId"] == "saleable_opportunity_generation_v1"
        )
        band_policy = opportunity_catalog["expectedBandPolicies"][0]

        def matches_band_rule(rule: dict[str, Any]) -> bool:
            return (
                _matches_allowed(window_status, rule.get("window_statuses"), None)
                and _matches_allowed(opportunity_grade, rule.get("opportunity_grades"), None)
                and _matches_allowed(recommended_delivery_form, rule.get("recommended_delivery_forms"), None)
                and _matches_allowed(price_band, rule.get("price_bands"), None)
                and _matches_range(window_urgency_score, rule.get("window_urgency_score"))
            )

        close_rule = next(rule for rule in band_policy["close_days_rules"] if matches_band_rule(rule))
        cost_rule = next(rule for rule in band_policy["delivery_cost_rules"] if matches_band_rule(rule))
        reason_outputs = {
            "policy": band_policy["policy_id"],
            "sku": sku_code,
            "grade": opportunity_grade,
            "window": window_status,
            "close_band": close_rule["expected_close_days_band"],
            "cost_band": cost_rule["expected_delivery_cost_band"],
            "quote_band": recommended_quote_band,
        }
        why_template = str(
            band_policy.get(
                "whyRecommendedTemplate",
                "policy={policy};sku={sku};grade={grade};window={window};close_band={close_band};cost_band={cost_band};quote_band={quote_band}",
            )
        )
        return self._decision(
            policy_key="sku_recommendation",
            catalog_id=catalog["catalogId"],
            policy_id=[policy["policy_id"], opportunity_policy["policyId"], band_policy["policy_id"]],
            decision_state=decision_state,
            outputs={
                "sku_code": sku_code,
                "recommended_delivery_form": recommended_delivery_form,
                "recommended_quote_band": recommended_quote_band,
                "offer_recommendation_state": offer_state,
                "offer_blocking_reasons_optional": review_reasons,
                "expected_close_days_band": close_rule["expected_close_days_band"],
                "expected_delivery_cost_band": cost_rule["expected_delivery_cost_band"],
                "why_recommended": why_template.format(**reason_outputs),
                "why_recommended_template_id": band_policy.get("whyRecommendedTemplateId", band_policy["policy_id"]),
                "why_recommended_rule_outputs": reason_outputs,
                "opportunity_policy_trace": {
                    "policy_id": band_policy["policy_id"],
                    "close_rule_id": close_rule["rule_id"],
                    "delivery_cost_rule_id": cost_rule["rule_id"],
                    "required_inputs": opportunity_policy["requiredInputs"],
                    "why_recommended_template_id": band_policy.get("whyRecommendedTemplateId", band_policy["policy_id"]),
                    "formal_sink_projection": band_policy.get("formalSinkProjection", {}),
                },
            },
            reasons=review_reasons or [f"sku={sku_code}"],
        )

    def _evaluate_contact_source_policy(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("contact_source_policy")
        entry = next(
            (
                item
                for item in catalog.get("entries", [])
                if str(item.get("objectType")) == "contact_target" and int(item.get("stage", 0)) == 8
            ),
            catalog["entries"][0],
        )
        source_family = context.input("source_family", "PROCUREMENT_NOTICE")
        auditability = context.input("source_auditability_state", "AUDITABLE")
        source_role = context.input("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE")
        legal_basis = context.input("contact_legal_basis", "REVIEW_REQUIRED")
        outputs = {
            "source_family": source_family,
            "source_auditability_state": auditability,
            "source_vendor_role": source_role,
            "requires_manual_review": False,
            "source_priority_weight": int(
                entry.get("sourcePriorityWeights", {}).get(source_role, 0)
            ),
            "direct_projection_forbidden": source_role
            in set(entry.get("directProjectionForbiddenSourceRoles", [])),
            "formal_merge_required": source_role
            in set(entry.get("formalMergeRequiredSourceRoles", [])),
        }
        decision_state = "ALLOW"
        reasons = ["source policy pass"]
        if source_family in entry["forbiddenSourceFamilies"] or legal_basis in entry["blockedLegalBasis"]:
            decision_state = "BLOCK"
            outputs["requires_manual_review"] = True
            reasons = ["source policy blocked"]
        elif source_role not in entry["allowedSourceRoles"] or auditability != "AUDITABLE" or legal_basis in entry["reviewRequiredLegalBasis"]:
            decision_state = "REVIEW"
            outputs["requires_manual_review"] = True
            reasons = ["source policy review"]
        outputs["source_policy_decision"] = decision_state
        return self._decision(
            policy_key="contact_source_policy",
            catalog_id=catalog["catalogId"],
            policy_id=entry["objectType"],
            decision_state=decision_state,
            outputs=outputs,
            reasons=reasons,
        )

    def _evaluate_contact_compliance(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("contact_compliance")
        fact_map = {
            "contact_legal_basis": context.input("contact_legal_basis", "REVIEW_REQUIRED"),
            "contact_validity_status": context.input("contact_validity_status", "UNKNOWN"),
            "channel_policy_status": context.input("channel_policy_status", "REVIEW"),
            "opt_out_state": context.input("opt_out_state", "PENDING_CONFIRMATION"),
            "reasonable_expectation_status": context.input("reasonable_expectation_status", "UNKNOWN"),
            "source_auditability_state": context.input("source_auditability_state", "AUDITABLE"),
            "contact_conflict_flag": bool(context.input("contact_conflict_flag", False)),
            "source_vendor_role": context.input("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE"),
            "execution_policy_state": context.input("execution_policy_state", "PREVIEW_ONLY"),
            "approval_state": context.input("approval_state", "NOT_REQUIRED"),
            "run_mode": context.input("run_mode", "DRY_RUN"),
            "quiet_hours_policy_state": context.input("quiet_hours_policy_state", "REVIEW"),
            "frequency_policy_state": context.input("frequency_policy_state", "REVIEW"),
            "channel_family": context.input("channel_family", "ORG_EMAIL"),
        }

        def matches(rule: dict[str, Any]) -> bool:
            for key, expected in rule.items():
                if key in (
                    "decision",
                    "execution_decision",
                    "contact_target_status",
                    "requires_manual_review",
                    "reason",
                    "stop_semantics",
                ):
                    continue
                actual = fact_map.get(key)
                if isinstance(expected, list):
                    if actual not in expected:
                        return False
                else:
                    if actual != expected:
                        return False
            return True

        row = next((item for item in catalog["matrix"] if matches(item)), None)
        if row is None:
            row = {
                "decision": "REVIEW_REQUIRED",
                "execution_decision": "REVIEW_REQUIRED",
                "contact_target_status": "REVIEW_REQUIRED",
                "requires_manual_review": True,
                "stop_semantics": "EXECUTION_REVIEW_REQUIRED",
                "reason": "fallback_review",
            }
        candidate_decision = str(row.get("decision", "REVIEW_REQUIRED"))
        execution_decision = str(row.get("execution_decision", candidate_decision))
        contact_target_status = str(
            row.get(
                "contact_target_status",
                {
                    "ALLOW_PREVIEW": "ELIGIBLE",
                    "REVIEW_REQUIRED": "REVIEW_REQUIRED",
                    "BLOCKED": "BLOCKED",
                }.get(candidate_decision, "REVIEW_REQUIRED"),
            )
        )
        stop_semantics = str(row.get("stop_semantics", "NONE"))
        decision_state = "ALLOW"
        if candidate_decision == "BLOCKED":
            decision_state = "BLOCK"
        elif candidate_decision == "REVIEW_REQUIRED":
            decision_state = "REVIEW"
        elif execution_decision in ("REVIEW_REQUIRED", "SCHEDULED", "BLOCKED"):
            decision_state = "REVIEW"

        return self._decision(
            policy_key="contact_compliance",
            catalog_id=catalog["catalogId"],
            policy_id="matrix",
            decision_state=decision_state,
            outputs={
                "compliance_decision": candidate_decision,
                "candidate_compliance_decision": candidate_decision,
                "execution_compliance_decision": execution_decision,
                "contact_target_status": contact_target_status,
                "requires_manual_review": bool(row.get("requires_manual_review", False)),
                "stop_semantics": stop_semantics,
            },
            reasons=[
                str(row["reason"]),
                f"candidate={candidate_decision}",
                f"execution={execution_decision}",
            ],
        )

    def _evaluate_contact_priority(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("contact_priority")
        policy = catalog["policies"][0]
        organization_policy = _contact_priority_organization_policy(policy)
        saleable_opportunity = context.record("saleable_opportunity")
        legal_action_actor_profile = context.record("legal_action_actor_profile")
        procurement_decision_actor_profile = context.record(
            "procurement_decision_actor_profile"
        )
        role_cluster = context.input("role_cluster", "ORG_GATEKEEPER")
        role_key = _contact_priority_role_key(role_cluster)
        legal_basis = context.input("contact_legal_basis", "REVIEW_REQUIRED")
        channel_family = context.input("channel_family", "ORG_EMAIL")
        reasonableness = context.input("reasonable_expectation_status", "UNKNOWN")
        validity = context.input("contact_validity_status", "UNKNOWN")
        auditability = context.input("source_auditability_state", "AUDITABLE")
        opportunity_grade = str(
            context.input(
                "opportunity_grade",
                saleable_opportunity.get("opportunity_grade", "D"),
            )
        )
        commercial_urgency_level = str(
            context.input(
                "commercial_urgency_level_optional",
                saleable_opportunity.get("commercial_urgency_level_optional", "NORMAL"),
            )
        )
        actionability_state = str(
            context.input(
                "actionability_state_optional",
                legal_action_actor_profile.get("actionability_state_optional")
                or legal_action_actor_profile.get("actionability_state", "REVIEW_REQUIRED"),
            )
        )
        reachable_state = str(
            context.input(
                "reachable_state_optional",
                procurement_decision_actor_profile.get("reachable_state_optional")
                or procurement_decision_actor_profile.get("reachable_state", "REVIEW_REQUIRED"),
            )
        )
        prior_decision_state = state.decision_state
        source_merge_review_required = bool(context.input("source_merge_review_required", False))
        restricted_channel_conflict = channel_family in {
            "AUTHORIZED_PERSON_DIRECT",
            "SOCIAL_DM",
            "IM_DIRECT",
            "PERSONAL_PHONE",
            "PERSONAL_EMAIL",
        }
        scoring_facts = {
            "channel_policy_status": context.input("channel_policy_status", "REVIEW"),
            "contact_legal_basis": legal_basis,
            "channel_family": channel_family,
            "reasonable_expectation_status": reasonableness,
            "contact_validity_status": validity,
            "source_auditability_state": auditability,
            "opportunity_grade": opportunity_grade,
            "commercial_urgency_level_optional": commercial_urgency_level,
            "actionability_state_optional": actionability_state,
            "reachable_state_optional": reachable_state,
        }

        score = policy["scoring_model"]["base_score"]
        role_weight = int(policy["scoring_model"]["role_weights"].get(role_key, 0))
        legal_basis_weight = int(
            policy["scoring_model"]["legal_basis_weights"].get(legal_basis, -20)
        )
        channel_weight = int(
            policy["scoring_model"]["channel_family_weights"].get(channel_family, 0)
        )
        reasonableness_weight = int(
            policy["scoring_model"]["reasonableness_weights"].get(reasonableness, 0)
        )
        validity_weight = int(policy["scoring_model"]["validity_weights"].get(validity, 0))
        opportunity_grade_weight = int(
            policy["scoring_model"]
            .get("opportunity_grade_weights", {})
            .get(opportunity_grade, 0)
        )
        commercial_urgency_weight = int(
            policy["scoring_model"]
            .get("commercial_urgency_level_weights", {})
            .get(commercial_urgency_level, 0)
        )
        actionability_weight = int(
            policy["scoring_model"]
            .get("actionability_state_weights", {})
            .get(actionability_state, 0)
        )
        reachable_weight = int(
            policy["scoring_model"]
            .get("reachable_state_weights", {})
            .get(reachable_state, 0)
        )
        score += role_weight
        score += legal_basis_weight
        score += channel_weight
        score += reasonableness_weight
        score += validity_weight
        score += opportunity_grade_weight
        score += commercial_urgency_weight
        score += actionability_weight
        score += reachable_weight
        if auditability != "AUDITABLE":
            score += int(policy["scoring_model"]["auditability_penalty"]["penalty"])
        penalty_triggers: list[str] = []
        requires_manual_review = (
            prior_decision_state in ("REVIEW", "BLOCK")
            or source_merge_review_required
            or restricted_channel_conflict
        )
        for penalty_rule in policy["scoring_model"].get("policy_state_penalties", []):
            condition = str(penalty_rule.get("condition", ""))
            if not _matches_key_value_condition(condition, scoring_facts):
                continue
            score += int(penalty_rule.get("penalty", 0))
            penalty_triggers.append(condition)
            if penalty_rule.get("requires_manual_review", False):
                requires_manual_review = True
        score = max(0, min(100, score))
        organization_channel_flag = channel_family in set(
            organization_policy["organization_channel_families"]
        )
        organization_first_eligible = (
            organization_channel_flag
            and score >= int(organization_policy["minimum_primary_score"])
        )
        source_auditability_rank = 1 if auditability == "AUDITABLE" else 0
        decision_state = "BLOCK" if prior_decision_state == "BLOCK" else "REVIEW" if requires_manual_review else "ALLOW"
        auditability_reason = "AUDITABLE" if auditability == "AUDITABLE" else "REVIEW"
        reason_tags = _render_reason_tags(
            list(policy.get("reason_tag_templates", [])),
            {
                "role_key": role_key,
                "legal_basis": legal_basis,
                "channel_family": channel_family,
                "reasonableness": reasonableness,
                "validity": validity,
                "auditability": auditability_reason,
                "opportunity_grade": opportunity_grade,
                "commercial_urgency_level": commercial_urgency_level,
                "actionability_state": actionability_state,
                "reachable_state": reachable_state,
            },
        )
        if source_merge_review_required:
            reason_tags.append("SOURCE_MERGE_REVIEW_REQUIRED")
        if restricted_channel_conflict:
            reason_tags.append("RESTRICTED_CHANNEL_CONFLICT")
        for condition in penalty_triggers:
            reason_tags.append(f"PENALTY_{_sanitize_reason_tag_value(condition)}")

        return self._decision(
            policy_key="contact_priority",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=decision_state,
            outputs={
                "primary_contact_flag": organization_first_eligible,
                "contact_priority_score": score,
                "contact_priority_reason_tags": reason_tags,
                "contact_candidate_rank": 1 if score >= int(organization_policy["minimum_primary_score"]) else 99,
                "contact_selection_reason": (
                    f"score={score};role={role_key};legal_basis={legal_basis};channel={channel_family}"
                ),
                "contact_conflict_flag": bool(context.input("contact_conflict_flag", False))
                or restricted_channel_conflict,
                "contact_conflict_reason": str(
                    context.input(
                        "contact_conflict_reason",
                        "restricted_channel_review"
                        if restricted_channel_conflict
                        else "single candidate",
                    )
                ),
                "requires_manual_review": requires_manual_review,
                "organization_channel_flag": organization_channel_flag,
                "organization_first_eligible": organization_first_eligible,
                "legal_basis_weight": legal_basis_weight,
                "source_auditability_rank": source_auditability_rank,
                "source_merge_review_required": source_merge_review_required,
                "opportunity_grade_weight": opportunity_grade_weight,
                "commercial_urgency_weight": commercial_urgency_weight,
                "actionability_weight": actionability_weight,
                "reachable_weight": reachable_weight,
            },
            reasons=[f"priority_score={score}", f"prior_state={prior_decision_state}"],
        )

    def _evaluate_outreach_cadence(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("outreach_cadence")
        policy = catalog["policies"][0]
        urgency = context.input("commercial_urgency_level_optional", "NORMAL")
        window_urgency = state.resolve("window_urgency_score", context.input("window_urgency_score", 50))
        profile_id = _select_stage8_cadence_profile_id(urgency, window_urgency)
        profile = next(item for item in policy["cadence_profiles"] if item["profile_id"] == profile_id)
        channel_family = context.input("channel_family", "ORG_EMAIL")
        channel_override = next((item for item in policy["channel_overrides"] if item["channel_family"] == channel_family), {})
        channel_ladder = _select_stage8_channel_ladder(policy, channel_family)
        fallback_sequence = list(channel_ladder.get("fallback_sequence", []))
        next_touch = (_to_dt(context.now) or datetime.utcnow()) + timedelta(hours=profile["first_touch_sla_hours"])
        return self._decision(
            policy_key="outreach_cadence",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state="REVIEW" if channel_override.get("requires_manual_review") else "ALLOW",
            outputs={
                "cadence_profile_id": profile_id,
                "retry_policy_id": str(policy.get("retry_policy_id", "RETRY-001")),
                "stop_policy_id": str(policy.get("stop_policy_id", "STOP-001")),
                "retry_count": int(context.input("retry_count", 0)),
                "max_retry_count": int(channel_override.get("max_attempts_7d", profile["max_attempts_7d"])),
                "attempt_index": int(context.input("attempt_index", 1)),
                "next_touch_due_at_optional": next_touch.isoformat(timespec="seconds"),
                "channel_ladder_id": str(channel_ladder.get("ladder_id", f"LADDER-{channel_family}")),
                "ladder_sequence": list(channel_ladder.get("step_sequence", [channel_family])),
                "channel_fallback_sequence": fallback_sequence,
                "fallback_channel_family_optional": next(iter(fallback_sequence), None),
                "fallback_trigger_response_statuses": list(
                    channel_ladder.get("fallback_trigger_response_statuses", [])
                ),
                "ladder_sequence_mode": str(channel_ladder.get("sequence_mode", "GOVERNED_PREVIEW_ONLY")),
                "live_execution_enabled": bool(channel_ladder.get("live_execution_enabled", False)),
                "advance_requires_manual_review": bool(
                    channel_ladder.get("advance_requires_manual_review", False)
                ),
            },
            reasons=[
                f"profile={profile_id}",
                f"ladder={channel_ladder.get('ladder_id', f'LADDER-{channel_family}')}",
            ],
        )

    def _evaluate_feedback_reason(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("feedback_reason")
        entry = next(
            (
                item
                for item in catalog.get("entries", [])
                if int(item.get("stage", 0)) == 8 and str(item.get("objectType")) == "touch_record"
            ),
            catalog["entries"][0],
        )
        response_status = context.input("response_status", "NO_RESPONSE")
        mapping = next(
            (
                item
                for item in entry.get("mappings", [])
                if item["response_status"] == response_status
            ),
            None,
        )
        written_back_at_optional = context.input(
            "written_back_at_optional",
            context.input("now", context.now),
        )
        if mapping is None:
            return self._decision(
                policy_key="feedback_reason",
                catalog_id=catalog["catalogId"],
                policy_id=None,
                decision_state="FALLBACK",
                outputs={
                    "feedback_reason": response_status,
                    "failure_reason_tag_optional": response_status,
                    "next_step_optional": context.input("next_step_optional", "WAIT"),
                    "stop_reason_optional": state.resolve("stop_reason_optional", context.input("stop_reason_optional")),
                    "writeback_required": bool(
                        _ensure_list(context.input("writeback_targets", []))
                    ),
                    "writeback_targets": _ensure_list(context.input("writeback_targets", [])),
                    "writeback_target_optional": context.input("writeback_target_optional"),
                    "written_back_at_optional": written_back_at_optional,
                },
                reasons=["response_status not mapped"],
                fallback_used=True,
            )

        writeback_targets = list(mapping.get("writeback_targets", []))
        return self._decision(
            policy_key="feedback_reason",
            catalog_id=catalog["catalogId"],
            policy_id=response_status,
            decision_state="ALLOW",
            outputs={
                "feedback_reason": mapping["feedback_reason"],
                "failure_reason_tag_optional": mapping["failure_reason_tag_optional"],
                "next_step_optional": mapping["next_step_optional"],
                "stop_reason_optional": mapping.get(
                    "stop_reason_optional",
                    state.resolve("stop_reason_optional", context.input("stop_reason_optional")),
                ),
                "writeback_required": bool(writeback_targets),
                "writeback_targets": writeback_targets,
                "writeback_target_optional": next(iter(writeback_targets), None),
                "written_back_at_optional": written_back_at_optional,
            },
            reasons=[f"response_status={response_status}"],
        )

    def _evaluate_retry_policy(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("retry_policy")
        policy = catalog["policies"][0]
        response_status = context.input("response_status", "NO_RESPONSE")
        retry_count = int(state.resolve("retry_count", context.input("retry_count", 0)))
        attempt_index = int(state.resolve("attempt_index", context.input("attempt_index", 1)))
        max_retry_count = int(
            state.resolve(
                "max_retry_count",
                context.input(
                    "max_retry_count",
                    policy.get("max_attempts_policy", {}).get("default_max_attempts", 0),
                ),
            )
        )
        rule = next((item for item in policy["retry_rules"] if item["response_status"] == response_status), None)
        feedback_decision = self._evaluate_feedback_reason(context, state)
        feedback_outputs = dict(feedback_decision.outputs)
        outputs = {
            **feedback_outputs,
            "retry_count": retry_count,
            "max_retry_count": max_retry_count,
            "attempt_index": attempt_index,
            "retry_scheduled_optional": False,
            "next_action": "REVIEW",
            "backoff_hours_optional": None,
            "next_touch_due_at_optional": state.resolve(
                "next_touch_due_at_optional",
                context.input("next_touch_due_at_optional"),
            ),
        }
        decision_state = "ALLOW"
        reasons = [f"response_status={response_status}"]
        fallback_used = feedback_decision.fallback_used
        if rule is None:
            decision_state = "FALLBACK"
            fallback_used = True
            reasons = ["no retry rule matched"]
        else:
            outputs["next_action"] = rule["next_action"]
            effective_max_retries = int(rule.get("max_retries", max_retry_count or 0))
            if max_retry_count > 0:
                effective_max_retries = min(effective_max_retries, max_retry_count)
            if rule["next_action"] == "RETRY":
                if retry_count < effective_max_retries:
                    backoff_steps = list(rule.get("backoff_hours", []))
                    backoff_index = min(retry_count, len(backoff_steps) - 1) if backoff_steps else -1
                    backoff_hours = backoff_steps[backoff_index] if backoff_index >= 0 else None
                    outputs["retry_count"] = retry_count + 1
                    outputs["attempt_index"] = attempt_index + 1
                    outputs["retry_scheduled_optional"] = True
                    outputs["backoff_hours_optional"] = backoff_hours
                    if backoff_hours is not None:
                        next_touch = (_to_dt(context.now) or datetime.utcnow()) + timedelta(hours=int(backoff_hours))
                        outputs["next_touch_due_at_optional"] = next_touch.isoformat(timespec="seconds")
                    else:
                        fallback_used = True
                        reasons.append("backoff_hours_missing")
                else:
                    decision_state = "REVIEW"
                    reasons.append("retry exhausted")
            else:
                decision_state = "REVIEW" if rule["next_action"] in ("HANDOFF_TO_HUMAN", "RESELECT_CONTACT", "REVIEW_STAGE6_7") else "ALLOW"
                for field_name in ("plan_status", "contact_target_status", "opt_out_state", "requires_manual_review"):
                    if field_name in rule:
                        outputs[field_name] = rule[field_name]
        return self._decision(
            policy_key="retry_policy",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=decision_state,
            outputs=outputs,
            reasons=reasons,
            fallback_used=(decision_state == "FALLBACK") or fallback_used,
        )

    def _evaluate_touch_stop(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("touch_stop")
        policy = catalog["policies"][0]
        legal_basis = context.input("contact_legal_basis", "REVIEW_REQUIRED")
        opt_out_state = state.resolve("opt_out_state", context.input("opt_out_state", "PENDING_CONFIRMATION"))
        retry_count = int(state.resolve("retry_count", 0))
        max_retry_count = int(state.resolve("max_retry_count", 0))
        candidate_status = str(state.resolve("contact_target_status", "REVIEW_REQUIRED"))
        execution_decision = str(
            state.resolve(
                "execution_compliance_decision",
                state.resolve("candidate_compliance_decision", "REVIEW_REQUIRED"),
            )
        )
        stop_reason_optional = state.resolve(
            "stop_reason_optional",
            context.input("stop_reason_optional", "NOT_STOPPED"),
        )

        outputs = {
            "contact_target_status": candidate_status,
            "plan_status": state.resolve(
                "plan_status",
                "APPROVED" if context.input("approval_state", "NOT_REQUIRED") == "APPROVED" else "DRAFT",
            ),
            "requires_manual_review": bool(candidate_status == "REVIEW_REQUIRED" or execution_decision in ("REVIEW_REQUIRED", "BLOCKED")),
            "auto_contact_allowed": bool(candidate_status == "ELIGIBLE" and execution_decision == "ALLOW_PREVIEW"),
            "stop_reason_optional": str(stop_reason_optional or "NOT_STOPPED"),
            "next_touch_due_at_optional": state.resolve(
                "next_touch_due_at_optional",
                context.input("next_touch_due_at_optional"),
            ),
        }
        facts = {
            "contact_legal_basis": legal_basis,
            "opt_out_state": opt_out_state,
            "contact_validity_status": context.input("contact_validity_status", state.resolve("contact_validity_status")),
            "channel_policy_status": context.input("channel_policy_status", state.resolve("channel_policy_status")),
            "frequency_policy_state": context.input(
                "frequency_policy_state",
                state.resolve("frequency_policy_state"),
            ),
            "quiet_hours_policy_state": context.input(
                "quiet_hours_policy_state",
                state.resolve("quiet_hours_policy_state"),
            ),
            "contact_conflict_flag": bool(
                state.resolve("contact_conflict_flag", context.input("contact_conflict_flag", False))
            ),
            "execution_compliance_decision": execution_decision,
            "retry_count": retry_count,
            "max_retry_count": max_retry_count,
        }
        decision_state = "ALLOW"
        matched_rule: dict[str, Any] | None = None
        matched_reason = "stop conditions clear"
        for section_name, section_rules, section_state in (
            ("permanent_block_conditions", policy.get("permanent_block_conditions", []), "BLOCK"),
            ("review_conditions", policy.get("review_conditions", []), "REVIEW"),
        ):
            for rule in section_rules:
                if _matches_stage8_policy_condition(str(rule.get("condition", "")), facts):
                    matched_rule = dict(rule)
                    matched_reason = str(rule.get("reason", section_name))
                    decision_state = section_state
                    break
            if matched_rule is not None:
                break

        if matched_rule is None:
            retry_rule = dict(policy.get("stop_after_retry", {}))
            if retry_rule and _matches_stage8_policy_condition(str(retry_rule.get("condition", "")), facts):
                matched_rule = retry_rule
                matched_reason = str(retry_rule.get("reason", "retry_exhausted"))
                decision_state = "REVIEW"

        if matched_rule is not None:
            outputs.update(_parse_assignment_actions(matched_rule.get("actions", [])))
            outputs["auto_contact_allowed"] = False
            if outputs.get("stop_reason_optional") in (None, "", "NOT_STOPPED"):
                outputs["stop_reason_optional"] = matched_reason
        return self._decision(
            policy_key="touch_stop",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=decision_state,
            outputs=outputs,
            reasons=[matched_reason],
        )

    def _evaluate_payment_exception(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("payment_exception")
        policy = catalog["policies"][0]
        payment_status = context.input("payment_status", "NOT_STARTED")
        refund_state = context.input("refund_state", "NOT_REQUESTED")
        amount_mismatch_state = context.input("amount_mismatch_state_optional", "NO_MISMATCH")
        payment_exception_family = context.input("payment_exception_family_optional", "NO_EXCEPTION")
        payer_mismatch_state = state.resolve(
            "payer_mismatch_state", context.input("payer_mismatch_state", "NO_MISMATCH")
        )

        facts = {
            "payment_status": payment_status,
            "refund_state": refund_state,
            "amount_mismatch_state_optional": amount_mismatch_state,
            "payer_mismatch_state": payer_mismatch_state,
            "payment_exception_family_optional": payment_exception_family,
        }
        matched_rule = _match_contract_rule(policy["mapping_rules"], facts)

        if matched_rule is None:
            return self._decision(
                policy_key="payment_exception",
                catalog_id=catalog["catalogId"],
                policy_id=policy["policy_id"],
                decision_state="ALLOW",
                outputs={},
                reasons=["payment exception clear"],
            )

        exception_family = matched_rule["exception_family"]
        family_semantics = dict(policy.get("family_semantics", {}).get(exception_family, {}))
        state_sinks = _merge_contract_state_sinks(
            family_semantics.get("state_sinks"),
            matched_rule.get("state_sinks"),
        )
        outcome_reason_tags = _ensure_list(
            family_semantics.get("coarse_outcome_reason_tags", [exception_family])
        )
        decision_state = (
            "BLOCK"
            if str(family_semantics.get("semantic_role", ""))
            in {"TERMINAL_PAYMENT_BLOCK", "PAYMENT_IDENTITY_BLOCK", "TERMINAL_REFUND_CLOSURE"}
            else "REVIEW"
        )
        outputs: dict[str, Any] = {
            "payment_exception_family_optional": exception_family,
            "payment_exception_reason_optional": exception_family,
            "payment_exception_reason_tags_optional": [exception_family],
            "outcome_family": family_semantics.get(
                "coarse_outcome_family",
                matched_rule["outcome_family"],
            ),
            "trigger_type": matched_rule["governance_trigger"],
            "outcome_reason_tags": outcome_reason_tags,
            "governance_feedback_triggered_optional": True,
            "payment_exception_writeback_targets_optional": _ensure_list(
                matched_rule.get("writeback_targets")
                or family_semantics.get("additive_writeback_targets")
                or policy.get("writeback_targets", [])
            ),
            "payer_match_state": "MATCHED",
            "amount_match_state": "MATCHED",
            "payment_exception_match_trace_optional": {
                "mapping_rule_condition": str(matched_rule.get("condition", "")),
                "mapping_rule_ref": f"{policy['policy_id']}::condition::{matched_rule.get('condition', '')}",
                "family_semantics_ref": f"{policy['policy_id']}::family_semantics::{exception_family}",
                "exception_family": exception_family,
                "semantic_role": str(family_semantics.get("semantic_role", "")),
                "coarse_outcome_family": str(
                    family_semantics.get(
                        "coarse_outcome_family",
                        matched_rule["outcome_family"],
                    )
                ),
                "governance_trigger": str(matched_rule["governance_trigger"]),
            },
        }
        outputs.update(state_sinks)
        if exception_family in {"REFUND_REQUESTED", "REFUND_APPROVED", "REFUND_COMPLETED"}:
            outputs["refund_amount_band_optional"] = context.input(
                "refund_amount_band_optional",
                context.input("amount_band"),
            )
        return self._decision(
            policy_key="payment_exception",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=decision_state,
            outputs=outputs,
            reasons=[f"payment_exception_family={exception_family}"],
        )

    def _evaluate_delivery_exception(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("delivery_exception")
        policy = catalog["policies"][0]
        delivery_status = context.input("delivery_status", "NOT_READY")
        delivery_exception_family = context.input("delivery_exception_family_optional", "NO_EXCEPTION")
        archival_status = state.resolve("archival_status", context.input("archival_status", "NOT_ARCHIVED"))
        retrieval_status = context.input("retrieval_status", "NOT_AVAILABLE")
        customer_ack_state = context.input("customer_ack_state_optional", "NOT_REQUESTED")
        partial_delivery_state = context.input("partial_delivery_state_optional", "NOT_PARTIAL")
        has_payment_exception = bool(state.resolve("payment_exception_family_optional", ""))

        facts = {
            "delivery_status": delivery_status,
            "delivery_exception_family_optional": delivery_exception_family,
            "archival_status": archival_status,
            "retrieval_status": retrieval_status,
            "customer_ack_state_optional": customer_ack_state,
            "partial_delivery_state_optional": partial_delivery_state,
        }
        matched_rule = _match_contract_rule(policy["mapping_rules"], facts)

        if matched_rule is None:
            return self._decision(
                policy_key="delivery_exception",
                catalog_id=catalog["catalogId"],
                policy_id=policy["policy_id"],
                decision_state="ALLOW",
                outputs={},
                reasons=["delivery exception clear"],
            )

        exception_family = matched_rule["exception_family"]
        family_semantics = dict(policy.get("family_semantics", {}).get(exception_family, {}))
        state_sinks = _merge_contract_state_sinks(
            family_semantics.get("state_sinks"),
            matched_rule.get("state_sinks"),
        )
        outcome_reason_tags = _ensure_list(
            family_semantics.get("coarse_outcome_reason_tags", [exception_family])
        )
        outputs: dict[str, Any] = {
            "delivery_exception_family_optional": exception_family,
            "delivery_exception_reason_optional": exception_family,
            "delivery_exception_reason_tags_optional": [exception_family],
            "governance_feedback_triggered_optional": True,
            "delivery_exception_writeback_targets_optional": _ensure_list(
                matched_rule.get("writeback_targets")
                or family_semantics.get("additive_writeback_targets")
                or policy.get("writeback_targets", [])
            ),
            "delivery_exception_match_trace_optional": {
                "mapping_rule_condition": str(matched_rule.get("condition", "")),
                "mapping_rule_ref": f"{policy['policy_id']}::condition::{matched_rule.get('condition', '')}",
                "family_semantics_ref": f"{policy['policy_id']}::family_semantics::{exception_family}",
                "exception_family": exception_family,
                "semantic_role": str(family_semantics.get("semantic_role", "")),
                "coarse_outcome_family": str(
                    family_semantics.get(
                        "coarse_outcome_family",
                        matched_rule["outcome_family"],
                    )
                ),
                "governance_trigger": str(matched_rule["governance_trigger"]),
            },
        }
        outputs.update(state_sinks)
        if not (has_payment_exception and exception_family in ("ARCHIVE_FAILURE", "RETRIEVAL_FAILED")):
            outputs["outcome_family"] = family_semantics.get(
                "coarse_outcome_family",
                matched_rule["outcome_family"],
            )
            outputs["trigger_type"] = matched_rule["governance_trigger"]
            outputs["outcome_reason_tags"] = outcome_reason_tags

        return self._decision(
            policy_key="delivery_exception",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=(
                "BLOCK"
                if str(family_semantics.get("semantic_role", ""))
                in {"TERMINAL_DELIVERY_BLOCK", "ARCHIVE_BLOCK"}
                else "REVIEW"
            ),
            outputs=outputs,
            reasons=[f"delivery_exception_family={exception_family}"],
        )

    def _evaluate_outcome_taxonomy(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("outcome_taxonomy")
        outcome_family = state.resolve("outcome_family", context.input("outcome_family", "WON"))
        reason_tags = state.resolve("outcome_reason_tags", context.input("outcome_reason_tags", ["SIGNED"]))
        if not isinstance(reason_tags, list):
            reason_tags = [reason_tags]
        entry = next((item for item in catalog["entries"] if item["outcome_family"] == outcome_family), None)
        target_field_roles = dict(catalog.get("target_field_roles", {}))
        if entry is None:
            return self._decision(
                policy_key="outcome_taxonomy",
                catalog_id=catalog["catalogId"],
                policy_id=None,
                decision_state="REVIEW",
                outputs={
                    "writeback_source_family": catalog.get("writeback_source_family", "outcome_taxonomy"),
                    "writeback_merge_semantics": catalog.get("writeback_merge_semantics", "AUTHORITATIVE_BASE"),
                    "target_field_roles": target_field_roles,
                    "writeback_targets": ["project_fact"],
                    "authoritative_base_targets": ["project_fact"],
                    "projected_feedback_only_targets": [],
                    "advisory_targets": [],
                    "feedback_loop_contract_ref": None,
                    "recommendation_effect": "manual review",
                    "outcome_reason_tags": reason_tags,
                },
                reasons=["unknown outcome_family"],
            )
        invalid_tags = [tag for tag in reason_tags if tag not in entry["allowed_reason_tags"]]
        legacy_writeback_targets = _ensure_list(entry.get("writeback_targets", []))
        authoritative_base_targets = _ensure_list(
            entry.get("authoritative_base_targets", legacy_writeback_targets)
        )
        return self._decision(
            policy_key="outcome_taxonomy",
            catalog_id=catalog["catalogId"],
            policy_id=outcome_family,
            decision_state="REVIEW" if invalid_tags else "ALLOW",
            outputs={
                "writeback_source_family": catalog.get("writeback_source_family", "outcome_taxonomy"),
                "writeback_merge_semantics": catalog.get("writeback_merge_semantics", "AUTHORITATIVE_BASE"),
                "target_field_roles": target_field_roles,
                "writeback_targets": legacy_writeback_targets,
                "authoritative_base_targets": authoritative_base_targets,
                "projected_feedback_only_targets": _ensure_list(
                    entry.get("projected_feedback_only_targets", [])
                ),
                "advisory_targets": _ensure_list(entry.get("advisory_targets", [])),
                "feedback_loop_contract_ref": entry.get("feedback_loop_contract_ref"),
                "recommendation_effect": entry["recommendation_effect"],
                "outcome_reason_tags": reason_tags,
            },
            reasons=[f"invalid_reason_tags={invalid_tags}"] if invalid_tags else ["outcome taxonomy matched"],
        )

    def _evaluate_governance_taxonomy(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("governance_taxonomy")
        trigger_type = state.resolve("trigger_type", context.input("trigger_type", "OTHER"))
        entry = next((item for item in catalog["entries"] if item["trigger_type"] == trigger_type), None)
        target_field_roles = dict(catalog.get("target_field_roles", {}))
        if entry is None:
            return self._decision(
                policy_key="governance_taxonomy",
                catalog_id=catalog["catalogId"],
                policy_id=None,
                decision_state="REVIEW",
                outputs={
                    "writeback_source_family": catalog.get("writeback_source_family", "governance_taxonomy"),
                    "writeback_merge_semantics": catalog.get("writeback_merge_semantics", "ADDITIVE_ONLY"),
                    "target_field_roles": target_field_roles,
                    "required_actions": ["record audit"],
                    "impact_scope": "REVIEW_REQUIRED",
                    "governance_owned_self_target": "governance_feedback_event",
                    "additive_writeback_targets": ["project_fact"],
                    "writeback_targets": ["project_fact"],
                    "recommendation_effect": "manual review",
                },
                reasons=["unknown governance trigger"],
            )
        additive_writeback_targets = _ensure_list(
            entry.get("additive_writeback_targets", entry.get("writeback_targets", []))
        )
        return self._decision(
            policy_key="governance_taxonomy",
            catalog_id=catalog["catalogId"],
            policy_id=trigger_type,
            decision_state="ALLOW",
            outputs={
                "writeback_source_family": catalog.get("writeback_source_family", "governance_taxonomy"),
                "writeback_merge_semantics": catalog.get("writeback_merge_semantics", "ADDITIVE_ONLY"),
                "target_field_roles": target_field_roles,
                "required_actions": entry["required_actions"],
                "impact_scope": entry["impact_scope"],
                "governance_owned_self_target": entry.get(
                    "governance_owned_self_target",
                    "governance_feedback_event",
                ),
                "additive_writeback_targets": additive_writeback_targets,
                "writeback_targets": _ensure_list(
                    entry.get("writeback_targets", additive_writeback_targets)
                ),
                "recommendation_effect": entry["recommendation_effect"],
                "governance_feedback_policy_id_optional": trigger_type,
            },
            reasons=["governance taxonomy matched"],
        )


__all__ = [
    "PolicyExecutor",
    "_contact_priority_conflict",
    "_contact_priority_organization_policy",
    "_contact_priority_sort_key",
]
