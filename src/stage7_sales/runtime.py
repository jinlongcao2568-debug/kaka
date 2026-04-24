from __future__ import annotations

from typing import Any, Mapping

from shared.context_packet import ContextPacket


STAGE7_CRM_QUOTE_GOVERNED_METADATA = {
    "governed_execution_mode": "INTERNAL_GOVERNED",
    "readiness_only": True,
    "prerequisite_only": True,
    "blocked_by_default": True,
    "crm_runtime_enabled": False,
    "external_quote_enabled": False,
    "external_delivery_enabled": False,
}


def build_stage7_crm_quote_governed_metadata() -> dict[str, Any]:
    return dict(STAGE7_CRM_QUOTE_GOVERNED_METADATA)


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def optional_number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return float(value)


def optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def require_h06_field(stage6_handoff: Mapping[str, Any], field_name: str) -> Any:
    value = stage6_handoff.get(field_name)
    if value in (None, ""):
        raise ValueError(f"missing H-06 formal carrier field: {field_name}")
    return value


def required_runtime_value(runtime_state: Any, field_name: str) -> Any:
    value = runtime_state.resolve(field_name)
    if value is None:
        raise ValueError(f"Stage7 formal policy derivation missing {field_name}")
    return value


def resolved_policy_output(
    runtime_state: Any,
    policy_key: str,
    field_name: str,
    *,
    allow_none: bool = False,
) -> Any:
    policy_outputs = runtime_state.outputs.get(policy_key, {})
    if field_name in policy_outputs:
        return policy_outputs.get(field_name)
    value = runtime_state.resolve(field_name)
    if value is None and not allow_none:
        raise ValueError(f"Stage7 formal policy derivation missing {field_name}")
    return value


def build_stage7_runtime_context(
    *,
    project_id: Any,
    project_fact: Mapping[str, Any],
    legal_action_recommendation: Mapping[str, Any],
    challenger_candidate_profile: Mapping[str, Any],
    report_record: Mapping[str, Any],
    inputs: Mapping[str, Any],
    now: Any,
    sale_gate_status: Any,
    competitor_quality_grade: Any,
    window_status: Any,
    report_status: Any,
    review_task_status: Any,
    focus_bidder_id: Any,
    challenger_bidder_id: Any,
    challenger_profile_id: Any,
    candidate_position_label: Any,
    buyer_type_hint: Any,
    challenge_actionability_score: int,
    execution_readiness_score: int,
    real_competitor_count: int,
    project_value_score_seed: Any,
    normalized_price_amount_seed: Any,
    price_conflict_gate_status_seed: Any,
    confidence_score_seed: Any,
    current_action_start_at_optional: str | None,
    current_action_deadline_at_optional: str | None,
) -> ContextPacket:
    return ContextPacket.from_records(
        capability_mode="stage7_sales",
        stage=7,
        project_id=project_id,
        records={
            "project_fact": project_fact,
            "legal_action_recommendation": legal_action_recommendation,
            "challenger_candidate_profile": challenger_candidate_profile,
            "report_record": report_record,
        },
        inputs={
            **dict(inputs),
            "now": now,
            "sale_gate_status": sale_gate_status,
            "competitor_quality_grade": competitor_quality_grade,
            "window_status": window_status,
            "report_status": report_status,
            "review_task_status": review_task_status,
            "focus_bidder_id": focus_bidder_id,
            "challenger_bidder_id": challenger_bidder_id,
            "challenger_profile_id": challenger_profile_id,
            "candidate_position_label": candidate_position_label,
            "buyer_type_hint": buyer_type_hint,
            "challenge_actionability_score": challenge_actionability_score,
            "execution_readiness_score": execution_readiness_score,
            "real_competitor_count": real_competitor_count,
            "project_value_score_optional": project_value_score_seed,
            "normalized_price_amount_optional": normalized_price_amount_seed,
            "price_conflict_gate_status_optional": price_conflict_gate_status_seed,
            "confidence_score_optional": confidence_score_seed,
            "current_action_start_at_optional": current_action_start_at_optional,
            "current_action_deadline_at_optional": current_action_deadline_at_optional,
        },
    )
