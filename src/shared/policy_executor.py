from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from shared.context_packet import ContextPacket
from shared.contract_loader import load_contract
from shared.state_packet import PolicyDecision, StatePacket


def _to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
                ("challenger_candidate_profile.challenge_actionability_score", challenger_profile.get("challenge_actionability_score")),
                ("inputs.challenge_actionability_score", context.input("challenge_actionability_score")),
            ],
            fallback_value=actionability_default,
            fallback_source=actionability_default_source,
        )
        readiness_default, readiness_default_source = fallback("execution_readiness_score")
        execution_readiness_score, execution_readiness_source, readiness_fallback = _resolve_with_contract_fallback(
            [
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
            challenger.get("challenge_actionability_score", 0) * policy["weights"]["challenge_actionability_score"] / 100
            + policy["component_scores"]["external_use_grade"].get(external_use_grade, 30) * policy["weights"]["external_use_grade"] / 100
            + challenger.get("focus_bidder_attackability_score", 0) * policy["weights"]["focus_bidder_attackability_score"] / 100
            + challenger.get("challenger_pain_score", 0) * policy["weights"]["challenger_pain_score"] / 100
            + challenger.get("execution_readiness_score", 0) * policy["weights"]["execution_readiness_score"] / 100
            + policy["component_scores"]["confidence_band_penalty"].get(context.input("confidence_band", "MEDIUM"), -10)
        )
        score = round(max(0, min(100, score)))
        confidence_band = _band_from_min_score(
            score,
            policy.get("confidence_band_rules", []),
            label_key="band",
            default="LOW",
        )
        quality_grade = _band_from_min_score(
            score,
            policy.get("quality_grade_rules", []),
            label_key="grade",
            default="D",
        )
        cutoff_policy = policy.get("cutoff_policy", {})
        evidence_ref_count = int(context.input("evidence_ref_count_optional", policy["evidence_requirements"]["min_evidence_refs"]))
        cutoff_reasons: list[str] = []
        if score < int(cutoff_policy.get("candidate_only_score_lt", 55)):
            cutoff_reasons.append("score_below_candidate_only_cutoff")
        if confidence_band in {str(item) for item in cutoff_policy.get("candidate_only_confidence_bands", ["LOW"])}:
            cutoff_reasons.append(f"confidence_band={confidence_band}")
        if (
            evidence_ref_count < int(policy["evidence_requirements"]["min_evidence_refs"])
            and external_use_grade not in ("E3_CLIENT_VISIBLE", "E4_EXTERNAL_ACTION_READY")
        ):
            cutoff_reasons.append("insufficient_evidence_refs")

        return self._decision(
            policy_key="competitor_confidence",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state="REVIEW" if cutoff_reasons or confidence_band == "LOW" or quality_grade == "D" else "ALLOW",
            outputs={
                "competitor_confidence_score": score,
                "competitor_confidence_band": confidence_band,
                "competitor_quality_grade": quality_grade,
                "competitor_cutoff_reasons": cutoff_reasons,
                "competitor_cutoff_policy_id_optional": cutoff_policy.get("policy_id"),
                "competitor_ranking_policy_id_optional": policy.get("ranking_policy", {}).get("policy_id"),
            },
            reasons=[f"competitor_confidence_score={score}"] + [f"cutoff={reason}" for reason in cutoff_reasons],
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
        delivery_risk_state = project_fact.get("delivery_risk_state", context.input("delivery_risk_state", "REVIEW"))
        coverage_sellable_state = project_fact.get("coverage_sellable_state", context.input("coverage_sellable_state", "RESTRICTED"))

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
                    "buyer_fit_score_source": buyer_fit_score_source,
                    "buyer_fit_policy_trace": buyer_fit_trace,
                    "gating_inputs": {
                        "rule_gate_status": rule_gate_status,
                        "evidence_gate_status": evidence_gate_status,
                        "sale_gate_status": sale_gate_status,
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
        entry = catalog["entries"][0]
        source_family = context.input("source_family", "PROCUREMENT_NOTICE")
        auditability = context.input("source_auditability_state", "AUDITABLE")
        source_role = context.input("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE")
        legal_basis = context.input("contact_legal_basis", "REVIEW_REQUIRED")
        outputs = {
            "source_family": source_family,
            "source_auditability_state": auditability,
            "source_vendor_role": source_role,
            "requires_manual_review": False,
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
        role_cluster = context.input("role_cluster", "ORG_GATEKEEPER")
        role_key = {
            "PROCUREMENT_DECISION": "PROCUREMENT_DECISION_ACTOR",
            "LEGAL_ACTION": "LEGAL_ACTION_ACTOR",
            "ORG_GATEKEEPER": "ORG_GATEKEEPER",
        }.get(role_cluster, role_cluster)
        legal_basis = context.input("contact_legal_basis", "REVIEW_REQUIRED")
        channel_family = context.input("channel_family", "ORG_EMAIL")
        reasonableness = context.input("reasonable_expectation_status", "UNKNOWN")
        validity = context.input("contact_validity_status", "UNKNOWN")
        auditability = context.input("source_auditability_state", "AUDITABLE")

        score = policy["scoring_model"]["base_score"]
        score += policy["scoring_model"]["role_weights"].get(role_key, 0)
        score += policy["scoring_model"]["legal_basis_weights"].get(legal_basis, -20)
        score += policy["scoring_model"]["channel_family_weights"].get(channel_family, 0)
        score += policy["scoring_model"]["reasonableness_weights"].get(reasonableness, 0)
        score += policy["scoring_model"]["validity_weights"].get(validity, 0)
        if auditability != "AUDITABLE":
            score += policy["scoring_model"]["auditability_penalty"]["penalty"]
        score = max(0, min(100, score))
        conflict_flag = channel_family in ("PERSONAL_PHONE", "PERSONAL_EMAIL", "SOCIAL_DM", "IM_DIRECT")

        return self._decision(
            policy_key="contact_priority",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state="REVIEW" if conflict_flag or score < 60 else "ALLOW",
            outputs={
                "primary_contact_flag": score >= 60 and channel_family.startswith("ORG_"),
                "contact_priority_score": score,
                "contact_priority_reason_tags": [
                    f"ROLE_{role_key}",
                    f"CHANNEL_{channel_family}",
                    f"LEGAL_{legal_basis}",
                    "AUDITABLE" if auditability == "AUDITABLE" else "AUDIT_REVIEW",
                ],
                "contact_candidate_rank": 1 if score >= 60 else 99,
                "contact_selection_reason": f"role={role_key};channel={channel_family}",
                "contact_conflict_flag": conflict_flag,
                "contact_conflict_reason": "manual review required" if conflict_flag else "single candidate",
                "requires_manual_review": conflict_flag
                or state.resolve("candidate_compliance_decision", "ALLOW_PREVIEW") in ("REVIEW_REQUIRED", "BLOCKED"),
            },
            reasons=[f"priority_score={score}"],
        )

    def _evaluate_outreach_cadence(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("outreach_cadence")
        strategy_catalog = self.load_policy("outreach_strategy")
        policy = catalog["policies"][0]
        strategy_entry = strategy_catalog["entries"][0]
        urgency = context.input("commercial_urgency_level_optional", "NORMAL")
        window_urgency = state.resolve("window_urgency_score", context.input("window_urgency_score", 50))
        profile_id = _select_stage8_cadence_profile_id(urgency, window_urgency)
        profile = next(item for item in policy["cadence_profiles"] if item["profile_id"] == profile_id)
        channel_family = context.input("channel_family", "ORG_EMAIL")
        channel_override = next((item for item in policy["channel_overrides"] if item["channel_family"] == channel_family), {})
        channel_ladder = _select_stage8_channel_ladder(policy, channel_family)
        fallback_sequence = list(channel_ladder.get("fallback_sequence", []))
        run_mode = context.input("run_mode", "DRY_RUN")
        strategy_profile = next(
            (item for item in strategy_entry.get("strategy_profiles", []) if item["run_mode"] == run_mode),
            {},
        )
        requested_delivery_surface = context.input(
            "requested_delivery_surface",
            strategy_entry.get("defaultRequestedDeliverySurface", "INTERNAL_OPERATIONS"),
        )
        next_touch = (_to_dt(context.now) or datetime.utcnow()) + timedelta(hours=profile["first_touch_sla_hours"])
        return self._decision(
            policy_key="outreach_cadence",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state="REVIEW" if channel_override.get("requires_manual_review") else "ALLOW",
            outputs={
                "requested_delivery_surface": requested_delivery_surface,
                "projection_mode": strategy_profile.get("projection_mode", "INTERNAL_GOVERNED_PREVIEW"),
                "cadence_profile_id": profile_id,
                "retry_policy_id": str(
                    policy.get("retry_policy_id")
                    or self._ref_tail(strategy_entry.get("retryPolicyRef"), "RETRY-001")
                ),
                "stop_policy_id": str(
                    policy.get("stop_policy_id")
                    or self._ref_tail(strategy_entry.get("stopPolicyRef"), "STOP-001")
                ),
                "plan_status": strategy_profile.get("default_plan_status", "DRAFT"),
                "approval_run_required": bool(strategy_profile.get("approval_run_required", run_mode in ("APPROVAL_RUN", "REAL_RUN"))),
                "writeback_required": bool(strategy_profile.get("writeback_required", True)),
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

    def _evaluate_retry_policy(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("retry_policy")
        feedback_catalog = self.load_policy("feedback_reason")
        policy = catalog["policies"][0]
        response_status = context.input("response_status", "NO_RESPONSE")
        retry_count = int(state.resolve("retry_count", context.input("retry_count", 0)))
        attempt_index = int(state.resolve("attempt_index", context.input("attempt_index", 1)))
        rule = next((item for item in policy["retry_rules"] if item["response_status"] == response_status), None)
        feedback_entry = next(
            (
                item
                for item in feedback_catalog["entries"][0].get("mappings", [])
                if item["response_status"] == response_status
            ),
            {},
        )
        outputs = {
            "retry_count": retry_count,
            "attempt_index": attempt_index,
            "retry_scheduled_optional": False,
            "next_step_optional": feedback_entry.get("next_step_optional", "WAIT"),
            "feedback_reason": feedback_entry.get("feedback_reason", response_status),
            "failure_reason_tag_optional": feedback_entry.get("failure_reason_tag_optional", response_status),
            "writeback_targets": list(feedback_entry.get("writeback_targets", ["saleable_opportunity"])),
            "writeback_target_optional": next(iter(feedback_entry.get("writeback_targets", ["saleable_opportunity"])), "saleable_opportunity"),
        }
        decision_state = "ALLOW"
        reasons = [f"response_status={response_status}"]
        if rule is None:
            decision_state = "FALLBACK"
            reasons = ["no retry rule matched"]
        else:
            outputs["next_step_optional"] = feedback_entry.get("next_step_optional", rule["next_action"])
            if rule["next_action"] == "RETRY":
                if retry_count < rule["max_retries"]:
                    outputs["retry_count"] = retry_count + 1
                    outputs["attempt_index"] = attempt_index + 1
                    outputs["retry_scheduled_optional"] = True
                else:
                    decision_state = "REVIEW"
                    reasons.append("retry exhausted")
            else:
                decision_state = "REVIEW" if rule["next_action"] in ("HANDOFF_TO_HUMAN", "RESELECT_CONTACT", "REVIEW_STAGE6_7") else "ALLOW"
                for field_name in ("plan_status", "contact_target_status", "opt_out_state", "requires_manual_review"):
                    if field_name in rule:
                        outputs[field_name] = rule[field_name]
        if feedback_entry.get("stop_reason_optional") and not outputs.get("stop_reason_optional"):
            outputs["stop_reason_optional"] = feedback_entry["stop_reason_optional"]
        return self._decision(
            policy_key="retry_policy",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=decision_state,
            outputs=outputs,
            reasons=reasons,
            fallback_used=(decision_state == "FALLBACK"),
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
        stop_semantics = str(state.resolve("stop_semantics", "NONE"))

        outputs = {
            "contact_target_status": candidate_status,
            "plan_status": state.resolve(
                "plan_status",
                "APPROVED" if context.input("approval_state", "NOT_REQUIRED") == "APPROVED" else "DRAFT",
            ),
            "requires_manual_review": bool(candidate_status == "REVIEW_REQUIRED" or execution_decision in ("REVIEW_REQUIRED", "BLOCKED")),
            "auto_contact_allowed": bool(candidate_status == "ELIGIBLE" and execution_decision == "ALLOW_PREVIEW"),
            "stop_reason_optional": str(state.resolve("stop_reason_optional", "NOT_STOPPED")),
        }
        decision_state = "ALLOW"
        if legal_basis == "BLOCKED" or opt_out_state in ("OPTED_OUT", "BLOCKED") or candidate_status in ("BLOCKED", "INVALID") or stop_semantics == "PERMANENT_BLOCK":
            outputs.update(
                {
                    "contact_target_status": candidate_status if candidate_status == "INVALID" else "BLOCKED",
                    "plan_status": "CANCELLED",
                    "auto_contact_allowed": False,
                    "stop_reason_optional": "permanent_block",
                }
            )
            decision_state = "BLOCK"
        elif stop_semantics == "EXECUTION_BLOCKED" or execution_decision == "BLOCKED":
            outputs.update(
                {
                    "plan_status": "BLOCKED",
                    "requires_manual_review": True,
                    "auto_contact_allowed": False,
                    "stop_reason_optional": "execution_blocked",
                }
            )
            decision_state = "REVIEW"
        elif stop_semantics == "QUIET_HOURS_SCHEDULE" or execution_decision == "SCHEDULED":
            outputs.update(
                {
                    "plan_status": "SCHEDULED",
                    "requires_manual_review": False,
                    "auto_contact_allowed": False,
                    "stop_reason_optional": "quiet_hours_block",
                }
            )
            decision_state = "REVIEW"
        elif candidate_status == "REVIEW_REQUIRED" or execution_decision == "REVIEW_REQUIRED":
            outputs.update(
                {
                    "plan_status": "REVIEW_REQUIRED",
                    "requires_manual_review": True,
                    "auto_contact_allowed": False,
                    "stop_reason_optional": "review_required",
                }
            )
            decision_state = "REVIEW"
        elif max_retry_count > 0 and retry_count >= max_retry_count:
            outputs.update(
                {
                    "contact_target_status": "REVIEW_REQUIRED",
                    "plan_status": "CANCELLED",
                    "requires_manual_review": True,
                    "auto_contact_allowed": False,
                    "stop_reason_optional": "retry_exhausted",
                }
            )
            decision_state = "REVIEW"
        return self._decision(
            policy_key="touch_stop",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state=decision_state,
            outputs=outputs,
            reasons=[outputs["stop_reason_optional"] if outputs["stop_reason_optional"] != "NOT_STOPPED" else "stop conditions clear"],
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
        matched_rule = None
        for rule in policy["mapping_rules"]:
            field_name, expected_value = rule["condition"].split("=", 1)
            if facts.get(field_name) == expected_value:
                matched_rule = rule
                break

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
        outcome_reason_tags = {
            "PARTIAL_PAYMENT": ["PAYMENT_FAILED"],
            "PAYMENT_FAILURE": ["PAYMENT_FAILED"],
            "AMOUNT_MISMATCH": ["AMOUNT_MISMATCH"],
            "PAYER_MISMATCH": ["PAYER_CONFIRMED_MISMATCH"],
            "REFUND_REQUESTED": ["SIGNED"],
            "REFUND_APPROVED": ["SIGNED"],
            "REFUND_COMPLETED": ["REFUND_COMPLETED"],
            "WRITE_OFF_REVIEW": ["PAYMENT_FAILED"],
            "CHARGEBACK_REVIEW": ["PAYMENT_FAILED"],
        }.get(exception_family, [exception_family])
        decision_state = (
            "BLOCK"
            if exception_family in ("PAYMENT_FAILURE", "AMOUNT_MISMATCH", "PAYER_MISMATCH", "REFUND_COMPLETED")
            else "REVIEW"
        )
        outputs: dict[str, Any] = {
            "payment_exception_family_optional": exception_family,
            "payment_exception_reason_optional": exception_family,
            "payment_exception_reason_tags_optional": [exception_family],
            "outcome_family": matched_rule["outcome_family"],
            "trigger_type": matched_rule["governance_trigger"],
            "outcome_reason_tags": outcome_reason_tags,
            "governance_feedback_triggered_optional": True,
            "payment_exception_writeback_targets_optional": matched_rule.get(
                "writeback_targets",
                policy.get("writeback_targets", []),
            ),
            "payer_match_state": "MATCHED",
            "amount_match_state": "MATCHED",
        }
        outputs.update(dict(matched_rule.get("state_sinks", {})))
        if exception_family == "AMOUNT_MISMATCH":
            outputs["amount_mismatch_state_optional"] = "CONFIRMED"
            outputs["amount_match_state"] = "MISMATCHED"
        if exception_family == "PAYER_MISMATCH":
            outputs["payer_mismatch_state"] = "CONFIRMED"
            outputs["payer_match_state"] = "MISMATCHED"
        if exception_family in {"REFUND_REQUESTED", "REFUND_APPROVED", "REFUND_COMPLETED"}:
            outputs["refund_amount_band_optional"] = context.input(
                "refund_amount_band_optional",
                context.input("amount_band"),
            )
        if exception_family == "REFUND_COMPLETED":
            outputs["archival_status"] = "ARCHIVE_EXCEPTION"
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
        matched_rule = None
        for rule in policy["mapping_rules"]:
            field_name, expected_value = rule["condition"].split("=", 1)
            if facts.get(field_name) == expected_value:
                matched_rule = rule
                break

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
        outcome_reason_tags = {
            "REDELIVERY_REQUIRED": ["REDELIVERY_FAILED"],
            "REWORK_REQUIRED": ["DELIVERY_REJECTED"],
            "DELIVERY_FAILED": ["DELIVERY_FAILED"],
            "ARCHIVE_FAILURE": ["ARCHIVE_FAILURE"],
            "RETRIEVAL_FAILED": ["ARCHIVE_FAILURE"],
        }.get(exception_family, [exception_family])
        outputs: dict[str, Any] = {
            "delivery_exception_family_optional": exception_family,
            "delivery_exception_reason_optional": exception_family,
            "delivery_exception_reason_tags_optional": [exception_family],
            "governance_feedback_triggered_optional": True,
            "delivery_exception_writeback_targets_optional": matched_rule.get(
                "writeback_targets",
                policy.get("writeback_targets", []),
            ),
        }
        outputs.update(dict(matched_rule.get("state_sinks", {})))
        if not (has_payment_exception and exception_family in ("ARCHIVE_FAILURE", "RETRIEVAL_FAILED")):
            outputs["outcome_family"] = matched_rule["outcome_family"]
            outputs["trigger_type"] = matched_rule["governance_trigger"]
            outputs["outcome_reason_tags"] = outcome_reason_tags
        if exception_family == "REDELIVERY_REQUIRED":
            outputs["redeliver_required_optional"] = True
            outputs["customer_ack_state_optional"] = "PENDING"
        if exception_family == "REWORK_REQUIRED":
            outputs["resend_required_optional"] = True
            outputs["customer_ack_state_optional"] = "REJECTED"
        if exception_family == "PARTIAL_DELIVERY":
            outputs["partial_delivery_state_optional"] = "PARTIAL"
            outputs["customer_ack_state_optional"] = "PENDING"
        if exception_family == "DELIVERY_REJECTED":
            outputs["customer_ack_state_optional"] = "REJECTED"
        if exception_family == "ACK_TIMEOUT":
            outputs["customer_ack_state_optional"] = "TIMEOUT"
        if exception_family == "ARCHIVE_FAILURE":
            outputs["archival_status"] = "ARCHIVE_EXCEPTION"
        if exception_family == "RETRIEVAL_FAILED":
            outputs["retrieval_status"] = "FAILED"

        return self._decision(
            policy_key="delivery_exception",
            catalog_id=catalog["catalogId"],
            policy_id=policy["policy_id"],
            decision_state="BLOCK" if exception_family in ("DELIVERY_FAILED", "ARCHIVE_FAILURE", "RETRIEVAL_FAILED") else "REVIEW",
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
        if entry is None:
            return self._decision(
                policy_key="outcome_taxonomy",
                catalog_id=catalog["catalogId"],
                policy_id=None,
                decision_state="REVIEW",
                outputs={"writeback_targets": ["project_fact"], "recommendation_effect": "manual review", "outcome_reason_tags": reason_tags},
                reasons=["unknown outcome_family"],
            )
        invalid_tags = [tag for tag in reason_tags if tag not in entry["allowed_reason_tags"]]
        return self._decision(
            policy_key="outcome_taxonomy",
            catalog_id=catalog["catalogId"],
            policy_id=outcome_family,
            decision_state="REVIEW" if invalid_tags else "ALLOW",
            outputs={"writeback_targets": entry["writeback_targets"], "recommendation_effect": entry["recommendation_effect"], "outcome_reason_tags": reason_tags},
            reasons=[f"invalid_reason_tags={invalid_tags}"] if invalid_tags else ["outcome taxonomy matched"],
        )

    def _evaluate_governance_taxonomy(self, context: ContextPacket, state: StatePacket) -> PolicyDecision:
        catalog = self.load_policy("governance_taxonomy")
        trigger_type = state.resolve("trigger_type", context.input("trigger_type", "OTHER"))
        entry = next((item for item in catalog["entries"] if item["trigger_type"] == trigger_type), None)
        if entry is None:
            return self._decision(
                policy_key="governance_taxonomy",
                catalog_id=catalog["catalogId"],
                policy_id=None,
                decision_state="REVIEW",
                outputs={"required_actions": ["record audit"], "impact_scope": "REVIEW_REQUIRED", "writeback_targets": ["project_fact"], "recommendation_effect": "manual review"},
                reasons=["unknown governance trigger"],
            )
        return self._decision(
            policy_key="governance_taxonomy",
            catalog_id=catalog["catalogId"],
            policy_id=trigger_type,
            decision_state="ALLOW",
            outputs={
                "required_actions": entry["required_actions"],
                "impact_scope": entry["impact_scope"],
                "writeback_targets": entry["writeback_targets"],
                "recommendation_effect": entry["recommendation_effect"],
                "governance_feedback_policy_id_optional": trigger_type,
            },
            reasons=["governance taxonomy matched"],
        )


__all__ = ["PolicyExecutor"]
