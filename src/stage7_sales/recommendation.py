from __future__ import annotations

from typing import Any, Mapping

from shared.utils import ensure_list
from stage7_sales.runtime import dedupe_strings


def build_stage7_restriction_reasons(
    *,
    saleability_status_seed: str,
    sale_gate_status: str,
    report_status: str,
    linked_review_request_id_optional: str | None,
    missing_condition_family_optional: str | None,
    offer_recommendation_state: Any,
) -> list[str]:
    reasons: list[str] = []
    if saleability_status_seed == "RESTRICTED":
        reasons.append("h06_saleability_status=RESTRICTED")
    if sale_gate_status in ("REVIEW", "HOLD", "BLOCK"):
        reasons.append(f"sale_gate_status={sale_gate_status}")
    if report_status not in ("READY", "ISSUED"):
        reasons.append(f"report_status={report_status}")
    if report_status == "READY":
        reasons.append("report_status=READY")
    if linked_review_request_id_optional:
        reasons.append(f"linked_review_request_id={linked_review_request_id_optional}")
    if missing_condition_family_optional:
        reasons.append(f"missing_condition_family={missing_condition_family_optional}")
    if offer_recommendation_state == "REVIEW_REQUIRED":
        reasons.append("offer_recommendation_state=REVIEW_REQUIRED")
    return reasons


def build_opportunity_blocking_reasons(
    *,
    inputs: Mapping[str, Any],
    runtime_state: Any,
    saleability_status: str,
    stage7_restriction_reasons: list[str],
) -> list[str]:
    blocking_reasons = ensure_list(inputs.get("blocking_reasons"))
    if saleability_status != "QUALIFIED":
        blocking_reasons.extend(
            ensure_list(runtime_state.resolve("offer_blocking_reasons_optional", ["stage7_review_required"]))
        )
        blocking_reasons.extend(stage7_restriction_reasons)
    return dedupe_strings(blocking_reasons)


def build_opportunity_policy_trace(
    runtime_state: Any,
    *,
    saleable_opportunity: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "opportunity_policy_trace": runtime_state.resolve("opportunity_policy_trace"),
        "why_recommended_template_id": runtime_state.resolve("why_recommended_template_id"),
        "why_recommended_rule_outputs": runtime_state.resolve("why_recommended_rule_outputs"),
        "expected_close_days_band": saleable_opportunity.get("expected_close_days_band"),
        "expected_delivery_cost_band": saleable_opportunity.get("expected_delivery_cost_band"),
        "why_recommended": offer_recommendation.get("why_recommended"),
    }
