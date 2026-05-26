from __future__ import annotations

from typing import Any, Iterable, Mapping

from storage.runtime_closeout_precedence import runtime_blocker_subqueue_routes


def limited_sellable_review_projection(
    downstream_counts: Mapping[str, Any],
    *,
    stage7_commercial_input_allowed: bool,
    field_tasks: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    field_task_list = [task for task in field_tasks if isinstance(task, Mapping)]
    detail_projection = limited_sellable_review_detail_projection(
        downstream_counts,
        field_tasks=field_task_list,
        stage7_commercial_input_allowed=stage7_commercial_input_allowed,
    )
    has_official_b_or_c = any(
        str(grade).startswith(("B_", "C_")) and _int(count) > 0
        for grade, count in downstream_counts.items()
    )
    stage7_gate = _stage7_governed_preview_gate(
        requested=stage7_commercial_input_allowed,
        has_official_b_or_c=has_official_b_or_c,
        official_readback_records=detail_projection.get("limited_sellable_review_official_readback_records") or [],
    )
    stage7_governed_preview_allowed = bool(stage7_gate["stage7_governed_preview_allowed"])
    if has_official_b_or_c and not stage7_governed_preview_allowed:
        return {
            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
            "limited_sellable_review_reason": "official_b_or_c_readback_requires_manual_stage5_stage6_review",
            "commercialization_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
            **stage7_gate,
            **detail_projection,
        }
    if has_official_b_or_c:
        return {
            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
            "limited_sellable_review_candidate_state": "NOT_READY",
            "limited_sellable_review_reason": "stage7_governed_preview_allowed_by_evidence_chain_gate",
            "commercialization_boundary_state": "CUSTOMER_DELIVERABLE_ONLY_AFTER_STAGE7_GATE",
            **stage7_gate,
            **detail_projection,
        }
    return {
        "strong_lead_candidate_state": "NOT_READY",
        "limited_sellable_review_candidate_state": "NOT_READY",
        "limited_sellable_review_reason": "",
        "commercialization_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        **stage7_gate,
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
        "limited_sellable_review_public_source_chain_counts": _counts(
            record.get("public_source_chain") for record in official_readback_records
        ),
        "limited_sellable_review_stage4_bridge_backfill_state_counts": _counts(
            record.get("stage4_bridge_backfill_state") for record in official_readback_records
        ),
        "limited_sellable_review_gdcic_project_code_route_policy_counts": _counts(
            record.get("gdcic_project_code_route_policy") for record in official_readback_records
        ),
        "limited_sellable_review_official_readback_records": official_readback_records,
        "limited_sellable_review_required_actions": _dedupe(required_actions),
        "limited_sellable_review_customer_visible_allowed": False,
        "limited_sellable_review_query_miss_is_not_clearance": True,
        "limited_sellable_review_no_legal_conclusion": True,
    }


def _stage7_governed_preview_gate(
    *,
    requested: bool,
    has_official_b_or_c: bool,
    official_readback_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    records = [record for record in official_readback_records if isinstance(record, Mapping)]
    complete_records = [record for record in records if _stage7_evidence_record_complete(record)]
    missing_reasons: list[str] = []
    if not requested:
        missing_reasons.append("stage7_commercial_input_not_requested")
    if not has_official_b_or_c:
        missing_reasons.append("abcd_b_or_c_grade_missing")
    if not records:
        missing_reasons.append("official_readback_record_missing")
    elif not complete_records:
        missing_reasons.extend(_stage7_evidence_missing_reasons(records))
    allowed = requested and has_official_b_or_c and bool(complete_records)
    return {
        "stage7_governed_preview_gate_state": (
            "ALLOWED_INTERNAL_GOVERNED_PREVIEW" if allowed else "BLOCKED_EVIDENCE_CHAIN_INCOMPLETE"
        ),
        "stage7_governed_preview_allowed": allowed,
        "stage7_governed_preview_missing_reasons": _dedupe(missing_reasons),
        "stage7_governed_preview_complete_record_count": len(complete_records),
        "stage7_governed_preview_required_fields": [
            "official_source_url_refs",
            "official_source_text_sha256_refs",
            "adapter_result_state=MATCHED",
            "field_readback_state",
            "downstream_release_evidence_abcd_grade=B_or_C",
            "no_legal_conclusion=true",
        ],
        "stage7_governed_preview_customer_visible_allowed": False,
    }


def _stage7_evidence_record_complete(record: Mapping[str, Any]) -> bool:
    return not _stage7_evidence_record_missing_reasons(record)


def _stage7_evidence_missing_reasons(records: Iterable[Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for record in records:
        reasons.extend(_stage7_evidence_record_missing_reasons(record))
    return _dedupe(reasons)


def _stage7_evidence_record_missing_reasons(record: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    grade = str(record.get("downstream_release_evidence_abcd_grade") or "")
    if not _list(record.get("official_source_url_refs")):
        reasons.append("official_source_url_missing")
    if not _list(record.get("official_source_text_sha256_refs")):
        reasons.append("official_source_text_sha256_missing")
    if str(record.get("adapter_result_state") or "") != "MATCHED":
        reasons.append("adapter_result_state_not_matched")
    if not str(record.get("field_readback_state") or "").strip():
        reasons.append("field_readback_state_missing")
    if not grade.startswith(("B_", "C_")):
        reasons.append("abcd_b_or_c_grade_missing")
    if not bool(record.get("no_legal_conclusion", True)):
        reasons.append("no_legal_conclusion_false")
    return reasons


def _limited_sellable_official_readback_record(task: Mapping[str, Any]) -> dict[str, Any]:
    grade = str(task.get("downstream_release_evidence_abcd_grade") or "").strip()
    if not grade.startswith(("B_", "C_")):
        return {}
    field_match_summary = task.get("field_match_summary") if isinstance(task.get("field_match_summary"), Mapping) else {}
    field_summary = task.get("field_summary") if isinstance(task.get("field_summary"), Mapping) else {}
    source_records = [
        record for record in _list(field_match_summary.get("source_specific_records")) if isinstance(record, Mapping)
    ]
    public_source_chain = _public_source_chain(task, source_records)
    gdcic_route_allowed = bool(
        task.get("gdcic_project_code_route_allowed")
        or field_summary.get("gdcic_project_code_route_allowed")
        or field_match_summary.get("gdcic_project_code_route_allowed")
    )
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
        "public_source_chain": public_source_chain,
        "stage4_bridge_backfill_state": _stage4_bridge_backfill_state(public_source_chain, gdcic_route_allowed),
        "gdcic_project_code_route_allowed": gdcic_route_allowed,
        "gdcic_project_code_route_policy": _gdcic_project_code_route_policy(public_source_chain, gdcic_route_allowed),
        "review_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _public_source_chain(task: Mapping[str, Any], source_records: Iterable[Mapping[str, Any]]) -> str:
    source_profile_id = str(task.get("source_profile_id") or "")
    adapter_id = str(task.get("source_specific_adapter_id") or "")
    target_type = str(task.get("release_evidence_target_type") or "")
    records = [record for record in source_records if isinstance(record, Mapping)]
    if (
        "YGP" in source_profile_id.upper()
        or "ygp" in adapter_id.lower()
        or any(record.get("ygp_project_code") or record.get("ygp_project_code_variants") for record in records)
    ):
        return "YGP_ORIGINAL_READBACK_BACKFILL"
    if "zfcj" in adapter_id.lower() or "ZFCJ" in source_profile_id.upper():
        return "LOCAL_AUTHORITY_PUBLIC_API_READBACK"
    if "gdcic" in adapter_id.lower() or "GDCIC" in source_profile_id.upper():
        return "GDCIC_OPENPLATFORM_PUBLIC_READBACK"
    if target_type:
        return f"PUBLIC_SOURCE_READBACK:{target_type}"
    return "PUBLIC_SOURCE_READBACK"


def _stage4_bridge_backfill_state(public_source_chain: str, gdcic_route_allowed: bool) -> str:
    if gdcic_route_allowed:
        return "GDCIC_PROJECT_CODE_ROUTE_READY"
    if public_source_chain == "YGP_ORIGINAL_READBACK_BACKFILL":
        return "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
    return "OFFICIAL_READBACK_READY_FOR_STAGE5_STAGE6_REVIEW"


def _gdcic_project_code_route_policy(public_source_chain: str, gdcic_route_allowed: bool) -> str:
    if gdcic_route_allowed:
        return "ONLY_EXPLICIT_PROVINCIAL_OR_URL_PROJECT_CODE_ALLOWED"
    if public_source_chain == "YGP_ORIGINAL_READBACK_BACKFILL":
        return "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE"
    return "NO_GDCIC_PROJECT_CODE_ROUTE_FROM_THIS_READBACK"


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
