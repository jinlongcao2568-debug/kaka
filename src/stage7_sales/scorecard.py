from __future__ import annotations

from typing import Any

from shared.utils import ensure_list
from stage7_sales.runtime import optional_int, required_runtime_value


def resolve_scorecard_projection(runtime_state: Any) -> dict[str, Any]:
    return {
        "project_value_score_optional": optional_int(required_runtime_value(runtime_state, "project_value_score")),
        "opportunity_value_score_optional": optional_int(
            required_runtime_value(runtime_state, "opportunity_value_score")
        ),
        "buyer_fit_runtime_score": int(required_runtime_value(runtime_state, "buyer_fit_scorecard_score")),
        "buyer_fit_purchase_intent_score": int(
            required_runtime_value(runtime_state, "buyer_fit_purchase_intent_score")
        ),
        "buyer_fit_payment_capacity_score": int(
            required_runtime_value(runtime_state, "buyer_fit_payment_capacity_score")
        ),
        "buyer_fit_window_urgency_score": int(
            required_runtime_value(runtime_state, "buyer_fit_window_urgency_score")
        ),
        "buyer_fit_attack_motivation_score": int(
            required_runtime_value(runtime_state, "buyer_fit_attack_motivation_score")
        ),
        "challenger_buyer_fit_runtime_score": int(
            required_runtime_value(runtime_state, "challenger_buyer_fit_scorecard_score")
        ),
        "buyer_fit_reason_tags": ensure_list(required_runtime_value(runtime_state, "buyer_fit_reason_tags")),
        "challenger_buyer_fit_reason_tags": ensure_list(
            required_runtime_value(runtime_state, "challenger_buyer_fit_reason_tags")
        ),
        "lead_value_reason_tags": ensure_list(required_runtime_value(runtime_state, "lead_value_reason_tags")),
        "opportunity_value_reason_tags": ensure_list(
            required_runtime_value(runtime_state, "opportunity_value_reason_tags")
        ),
    }


def build_buyer_fit_scorecard_trace(
    runtime_state: Any,
    *,
    buyer_fit_reason_tags: list[Any],
    challenger_buyer_fit_reason_tags: list[Any],
) -> dict[str, Any]:
    return {
        "buyer_fit_scorecard_id": runtime_state.resolve("buyer_fit_scorecard_id"),
        "buyer_fit_scorecard_score": runtime_state.resolve("buyer_fit_scorecard_score"),
        "buyer_fit_scorecard_grade": runtime_state.resolve("buyer_fit_scorecard_grade"),
        "challenger_buyer_fit_scorecard_id": runtime_state.resolve("challenger_buyer_fit_scorecard_id"),
        "challenger_buyer_fit_scorecard_score": runtime_state.resolve("challenger_buyer_fit_scorecard_score"),
        "challenger_buyer_fit_scorecard_grade": runtime_state.resolve("challenger_buyer_fit_scorecard_grade"),
        "buyer_fit_reason_tag_policy_id": runtime_state.resolve("buyer_fit_reason_tag_policy_id"),
        "buyer_fit_reason_tags": buyer_fit_reason_tags,
        "challenger_buyer_fit_reason_tag_policy_id": runtime_state.resolve(
            "challenger_buyer_fit_reason_tag_policy_id"
        ),
        "challenger_buyer_fit_reason_tags": challenger_buyer_fit_reason_tags,
        "buyer_fit_missing_formal_sources": runtime_state.resolve("buyer_fit_missing_formal_sources", []),
        "buyer_fit_derivation_trace": runtime_state.resolve("buyer_fit_derivation_trace"),
    }


def build_value_derivation_trace(
    runtime_state: Any,
    *,
    lead_value_reason_tags: list[Any],
    opportunity_value_reason_tags: list[Any],
) -> dict[str, Any]:
    return {
        "value_derivation_trace": runtime_state.resolve("value_derivation_trace"),
        "project_value_band": runtime_state.resolve("project_value_band"),
        "lead_value_band": runtime_state.resolve("lead_value_band"),
        "opportunity_value_band": runtime_state.resolve("opportunity_value_band"),
        "project_value_reason_tag_policy_id": runtime_state.resolve("project_value_reason_tag_policy_id"),
        "project_value_reason_tags": runtime_state.resolve("project_value_reason_tags"),
        "lead_value_reason_tag_policy_id": runtime_state.resolve("lead_value_reason_tag_policy_id"),
        "lead_value_reason_tags": lead_value_reason_tags,
        "opportunity_value_reason_tag_policy_id": runtime_state.resolve("opportunity_value_reason_tag_policy_id"),
        "opportunity_value_reason_tags": opportunity_value_reason_tags,
    }
