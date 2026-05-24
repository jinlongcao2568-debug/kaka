from __future__ import annotations

from typing import Any, Iterable, Mapping

from storage.runtime_closeout_precedence import runtime_blocker_subqueue_routes


def limited_sellable_review_projection(
    downstream_counts: Mapping[str, Any],
    *,
    stage7_commercial_input_allowed: bool,
    field_tasks: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    detail_projection = limited_sellable_review_detail_projection(
        downstream_counts,
        field_tasks=field_tasks,
        stage7_commercial_input_allowed=stage7_commercial_input_allowed,
    )
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
            **detail_projection,
        }
    if has_official_b_or_c:
        return {
            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
            "limited_sellable_review_candidate_state": "NOT_READY",
            "limited_sellable_review_reason": "stage7_commercial_input_already_allowed_by_closeout_gate",
            "commercialization_boundary_state": "CUSTOMER_DELIVERABLE_ONLY_AFTER_STAGE7_GATE",
            **detail_projection,
        }
    return {
        "strong_lead_candidate_state": "NOT_READY",
        "limited_sellable_review_candidate_state": "NOT_READY",
        "limited_sellable_review_reason": "",
        "commercialization_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        **detail_projection,
    }


def limited_sellable_review_detail_projection(
    downstream_counts: Mapping[str, Any],
    *,
    field_tasks: Iterable[Mapping[str, Any]] = (),
    stage7_commercial_input_allowed: bool,
) -> dict[str, Any]:
    official_readback_records = [
        record
        for record in (
            _limited_sellable_official_readback_record(task)
            for task in field_tasks
            if isinstance(task, Mapping)
        )
        if record
    ]
    evidence_grade_counts = {
        str(grade): _int(count)
        for grade, count in downstream_counts.items()
        if str(grade).startswith(("B_", "C_")) and _int(count) > 0
    }
    gap_grade_counts = {
        str(grade): _int(count)
        for grade, count in downstream_counts.items()
        if str(grade).startswith("D_") and _int(count) > 0
    }
    required_actions: list[str] = []
    if official_readback_records and not stage7_commercial_input_allowed:
        required_actions.extend(
            [
                "manual_stage5_stage6_review_before_limited_sellable_internal_package",
                "keep_customer_download_delivery_payment_refund_disabled",
            ]
        )
    if gap_grade_counts:
        required_actions.append("keep_d_grade_blockers_as_non_clearance_and_continue_fallback_readback")
    if official_readback_records:
        required_actions.append("verify_official_readback_scope_before_any_stage7_preview")
    return {
        "limited_sellable_review_official_readback_task_count": len(official_readback_records),
        "limited_sellable_review_evidence_grade_counts": evidence_grade_counts,
        "limited_sellable_review_gap_grade_counts": gap_grade_counts,
        "limited_sellable_review_official_readback_records": official_readback_records,
        "limited_sellable_review_required_actions": _dedupe(required_actions),
        "limited_sellable_review_customer_visible_allowed": False,
        "limited_sellable_review_query_miss_is_not_clearance": True,
        "limited_sellable_review_no_legal_conclusion": True,
    }


def _limited_sellable_official_readback_record(task: Mapping[str, Any]) -> dict[str, Any]:
    grade = str(task.get("downstream_release_evidence_abcd_grade") or "").strip()
    if not grade.startswith(("B_", "C_")):
        return {}
    field_match_summary = task.get("field_match_summary") if isinstance(task.get("field_match_summary"), Mapping) else {}
    field_summary = task.get("field_summary") if isinstance(task.get("field_summary"), Mapping) else {}
    source_records = [
        record for record in _list(field_match_summary.get("source_specific_records")) if isinstance(record, Mapping)
    ]
    return {
        "field_query_task_id": str(task.get("field_query_task_id") or task.get("release_evidence_adapter_task_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "release_evidence_target_type": str(task.get("release_evidence_target_type") or ""),
        "source_profile_id": str(task.get("source_profile_id") or ""),
        "source_specific_adapter_id": str(
            task.get("source_specific_adapter_id")
            or field_summary.get("source_specific_adapter_id")
            or ""
        ),
        "adapter_result_state": str(task.get("adapter_result_state") or ""),
        "field_readback_state": str(
            task.get("field_readback_state")
            or task.get("field_query_probe_state")
            or field_summary.get("field_query_probe_state")
            or ""
        ),
        "downstream_release_evidence_abcd_grade": grade,
        "official_source_url_refs": _dedupe(record.get("url") for record in source_records),
        "official_source_text_sha256_refs": _dedupe(record.get("source_text_sha256") for record in source_records),
        "ygp_project_code_variants": _dedupe(
            code
            for record in source_records
            for code in _list(record.get("ygp_project_code_variants"))
        ),
        "ygp_biz_code_variants": _dedupe(record.get("ygp_biz_code") for record in source_records),
        "ygp_site_code_variants": _dedupe(record.get("ygp_site_code") for record in source_records),
        "ygp_notice_id_variants": _dedupe(record.get("ygp_notice_id") for record in source_records),
        "gdcic_project_code_route_allowed": bool(
            task.get("gdcic_project_code_route_allowed")
            or field_summary.get("gdcic_project_code_route_allowed")
            or field_match_summary.get("gdcic_project_code_route_allowed")
        ),
        "review_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
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


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
