from __future__ import annotations

from typing import Any, Iterable, Mapping

from storage.runtime_closeout_precedence import runtime_blocker_subqueue_routes


def limited_sellable_review_projection(
    downstream_counts: Mapping[str, Any],
    *,
    stage7_commercial_input_allowed: bool,
) -> dict[str, Any]:
    has_official_b_or_c = any(
        str(grade).startswith(("B_", "C_")) and _int(count) > 0
        for grade, count in downstream_counts.items()
    )
    if has_official_b_or_c and not stage7_commercial_input_allowed:
        return {
            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
            "limited_sellable_review_reason": "official_b_or_c_readback_requires_manual_stage5_stage6_review",
            "commercialization_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        }
    if has_official_b_or_c:
        return {
            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
            "limited_sellable_review_candidate_state": "NOT_READY",
            "limited_sellable_review_reason": "stage7_commercial_input_already_allowed_by_closeout_gate",
            "commercialization_boundary_state": "CUSTOMER_DELIVERABLE_ONLY_AFTER_STAGE7_GATE",
        }
    return {
        "strong_lead_candidate_state": "NOT_READY",
        "limited_sellable_review_candidate_state": "NOT_READY",
        "limited_sellable_review_reason": "",
        "commercialization_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
    }


def runtime_blocker_projection_fields(runtime_blockers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = [dict(item) for item in runtime_blockers if isinstance(item, Mapping)]
    routes = runtime_blocker_subqueue_routes(records)
    return {
        "runtime_blocker_ledger_records": records,
        "runtime_blocker_ledger_state_counts": _counts(item.get("blocker_state") for item in records),
        "runtime_blocker_ledger_layer_counts": _counts(item.get("runtime_layer") for item in records),
        "runtime_blocker_subqueue_routes": routes,
        "runtime_blocker_subqueue_counts": _counts(routes),
    }


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
