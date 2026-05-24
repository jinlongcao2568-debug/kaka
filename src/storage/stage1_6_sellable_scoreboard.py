from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


SCOREBOARD_KIND = "stage1_6_sellable_scoreboard_v1"
SCOREBOARD_VERSION = 1


DEFAULT_PRESSURE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-stage1-6-real-public-pressure-v1")
DEFAULT_FIELD_QUERY_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-field-query-probe-v1")
DEFAULT_GDCIC_BROWSER_READBACK_ROOT = Path("tmp/evaluation-real-samples/gdcic-browser-authorized-readback-v1")
DEFAULT_STAGE6_STATUS_ROOT = Path("tmp/evaluation-real-samples/stage6-review-cycle-runner-v1")
DEFAULT_P13B_COMPANY_HISTORY_ROOT = Path("tmp/evaluation-real-samples/p13b-company-history-overlap-triage-v1")
DEFAULT_P13B_ORIGINAL_NOTICE_BACKTRACE_ROOT = Path("tmp/evaluation-real-samples/p13b-original-notice-backtrace-v1")
DEFAULT_P13B_YGP_ORIGINAL_READBACK_ROOT = Path("tmp/evaluation-real-samples/p13b-ygp-original-readback-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-6-sellable-scoreboard-v1")


def build_stage1_6_sellable_scoreboard(
    *,
    pressure_root: str | Path | None = None,
    pressure_summary_json: str | Path | None = None,
    readiness_json: str | Path | None = None,
    gap_summary_json: str | Path | None = None,
    field_query_root: str | Path | None = None,
    field_query_json: str | Path | None = None,
    gdcic_browser_readback_root: str | Path | None = None,
    gdcic_browser_readback_json: str | Path | None = None,
    p13b_company_history_root: str | Path | None = None,
    p13b_company_history_json: str | Path | None = None,
    p13b_original_notice_backtrace_root: str | Path | None = None,
    p13b_original_notice_backtrace_json: str | Path | None = None,
    p13b_ygp_original_readback_root: str | Path | None = None,
    p13b_ygp_original_readback_json: str | Path | None = None,
    stage6_status_root: str | Path | None = None,
    stage6_status_json: str | Path | None = None,
    output_root: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    pressure_dir = Path(pressure_root or DEFAULT_PRESSURE_ROOT)
    field_dir = Path(field_query_root or DEFAULT_FIELD_QUERY_ROOT)
    gdcic_readback_dir = Path(gdcic_browser_readback_root or DEFAULT_GDCIC_BROWSER_READBACK_ROOT)
    p13b_company_history_dir = Path(p13b_company_history_root or DEFAULT_P13B_COMPANY_HISTORY_ROOT)
    p13b_original_notice_dir = Path(
        p13b_original_notice_backtrace_root or DEFAULT_P13B_ORIGINAL_NOTICE_BACKTRACE_ROOT
    )
    p13b_ygp_original_dir = Path(p13b_ygp_original_readback_root or DEFAULT_P13B_YGP_ORIGINAL_READBACK_ROOT)
    stage6_dir = Path(stage6_status_root or DEFAULT_STAGE6_STATUS_ROOT)
    out_dir = Path(output_root or DEFAULT_OUTPUT_ROOT)
    out_dir.mkdir(parents=True, exist_ok=True)

    pressure_summary_path = _resolve_path(pressure_summary_json, pressure_dir / "pressure-summary.json")
    readiness_path = _resolve_path(readiness_json, pressure_dir / "stage1-6-readiness-table.json")
    gap_summary_path = _resolve_path(gap_summary_json, pressure_dir / "stage1-6-gap-summary-table.json")
    field_query_path = _resolve_path(field_query_json, field_dir / "guangdong-local-field-query-probe-v1.json")
    gdcic_browser_readback_path = _resolve_path(
        gdcic_browser_readback_json,
        gdcic_readback_dir / "gdcic-browser-authorized-readback-v1.json",
    )
    p13b_company_history_path = _resolve_path(
        p13b_company_history_json,
        p13b_company_history_dir / "company-history-overlap-triage-v1.json",
    )
    p13b_original_notice_backtrace_path = _resolve_path(
        p13b_original_notice_backtrace_json,
        p13b_original_notice_dir / "original-notice-backtrace-v1.json",
    )
    p13b_ygp_original_readback_path = _resolve_path(
        p13b_ygp_original_readback_json,
        p13b_ygp_original_dir / "ygp-original-readback-v1.json",
    )
    stage6_status_path = _resolve_stage6_status_path(stage6_status_json, stage6_dir)

    pressure_summary = _read_json_mapping(pressure_summary_path)
    readiness = _read_json_mapping(readiness_path)
    gap_summary = _read_json_mapping(gap_summary_path)
    field_query = _read_json_mapping(field_query_path)
    gdcic_browser_readback = _read_json_mapping(gdcic_browser_readback_path)
    p13b_company_history = _read_json_mapping(p13b_company_history_path)
    p13b_original_notice_backtrace = _read_json_mapping(p13b_original_notice_backtrace_path)
    p13b_ygp_original_readback = _read_json_mapping(p13b_ygp_original_readback_path)
    stage6_status = _read_json_mapping(stage6_status_path)

    readiness_records = _records(readiness)
    gap_records = _records(gap_summary)
    field_records = _field_task_records(field_query)
    p13b_project_signals = _p13b_project_signals(p13b_company_history)
    p13b_original_notice_project_signals = _p13b_original_notice_project_signals(p13b_original_notice_backtrace)
    p13b_ygp_project_signals = _p13b_ygp_project_signals(p13b_ygp_original_readback)
    stage6_records = _records(stage6_status)

    stage6_by_project = {
        str(record.get("project_id") or "").strip(): record
        for record in stage6_records
        if str(record.get("project_id") or "").strip()
    }
    readiness_by_project = {
        str(record.get("project_id") or "").strip(): record
        for record in readiness_records
        if str(record.get("project_id") or "").strip()
    }

    project_ids = _ordered_project_ids(
        readiness_records,
        stage6_records,
        field_records,
        list(p13b_project_signals.values()),
        list(p13b_original_notice_project_signals.values()),
        list(p13b_ygp_project_signals.values()),
    )
    project_rows = [
        _project_scoreboard_row(
            project_id,
            readiness_by_project.get(project_id, {}),
            stage6_by_project.get(project_id, {}),
            [record for record in field_records if str(record.get("project_id") or "").strip() == project_id],
            p13b_project_signals.get(project_id, {}),
            p13b_original_notice_project_signals.get(project_id, {}),
            p13b_ygp_project_signals.get(project_id, {}),
        )
        for project_id in project_ids
    ]
    counts = _scoreboard_counts(
        pressure_summary,
        readiness_records,
        field_query,
        gdcic_browser_readback,
        p13b_company_history,
        p13b_original_notice_backtrace,
        p13b_ygp_original_readback,
        field_records,
        stage6_status,
        stage6_records,
        project_rows,
    )
    blocker_summary = _blocker_summary(
        readiness_records,
        gap_records,
        field_query,
        gdcic_browser_readback,
        p13b_company_history,
        p13b_original_notice_backtrace,
        p13b_ygp_original_readback,
        field_records,
        stage6_records,
        project_rows,
    )
    recommended_next_actions = _recommended_next_actions(blocker_summary, counts)

    result = {
        "scoreboard_kind": SCOREBOARD_KIND,
        "scoreboard_version": SCOREBOARD_VERSION,
        "created_at": created,
        "input_refs": {
            "pressure_summary_json": str(pressure_summary_path),
            "stage1_6_readiness_json": str(readiness_path),
            "stage1_6_gap_summary_json": str(gap_summary_path),
            "release_field_query_json": str(field_query_path),
            "gdcic_browser_authorized_readback_json": str(gdcic_browser_readback_path),
            "p13b_company_history_json": str(p13b_company_history_path),
            "p13b_original_notice_backtrace_json": str(p13b_original_notice_backtrace_path),
            "p13b_ygp_original_readback_json": str(p13b_ygp_original_readback_path),
            "stage6_status_json": str(stage6_status_path),
        },
        "scoreboard": counts,
        "blocker_summary": blocker_summary,
        "recommended_next_actions": recommended_next_actions,
        "project_rows": project_rows,
        "safety": {
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
    }
    _write_json(out_dir / "stage1-6-sellable-scoreboard-v1.json", result)
    _write_markdown(out_dir / "stage1-6-sellable-scoreboard-v1.md", result)
    return result


def _scoreboard_counts(
    pressure_summary: Mapping[str, Any],
    readiness_records: list[Mapping[str, Any]],
    field_query: Mapping[str, Any],
    gdcic_browser_readback: Mapping[str, Any],
    p13b_company_history: Mapping[str, Any],
    p13b_original_notice_backtrace: Mapping[str, Any],
    p13b_ygp_original_readback: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    stage6_status: Mapping[str, Any],
    stage6_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    pressure_candidate_count = _int(pressure_summary.get("candidate_count"))
    candidate_count = pressure_candidate_count or len(readiness_records) or _distinct_count(field_records, "project_id")
    stage2_success_count = sum(
        1
        for record in readiness_records
        if str(record.get("stage2_detail_capture_state") or "").upper() in {"FETCHED", "CAPTURED", "DETAIL_CAPTURED", "READBACK_READY"}
    )
    stage3_success_count = sum(
        1
        for record in readiness_records
        if _stage3_parse_attempt_succeeded(record.get("stage3_field_parse_state"))
    )
    field_summary = _summary(field_query)
    gdcic_readback_summary = _summary(gdcic_browser_readback)
    p13b_summary = _summary(p13b_company_history)
    p13b_original_summary = _summary(p13b_original_notice_backtrace)
    p13b_ygp_summary = _summary(p13b_ygp_original_readback)
    stage6_summary = _summary(stage6_status)
    stage4_matched_count = _count_state(field_summary, field_records, "adapter_result_state", "MATCHED")
    stage4_needs_browser_count = _count_state(field_summary, field_records, "adapter_result_state", "NEEDS_BROWSER")
    stage5_review_count = _stage5_review_count(pressure_summary, readiness_records)
    stage6_fact_ready_count = sum(
        1
        for record in stage6_records
        if str(record.get("stage6_fact_package_state") or "").upper()
        in {"READY", "FACT_READY", "STAGE6_FACT_READY", "FACT_PACKAGE_READY"}
    )
    stage7_sellable_count = _int(pressure_summary.get("customer_sellable_evidence_ready_count")) or sum(
        1
        for record in stage6_records
        if bool(record.get("stage7_commercial_input_allowed"))
        and _has_grade(record, ("A_", "B_", "C_"))
    )
    limited_sellable_review_candidate_count = sum(
        1
        for row in project_rows
        if row.get("limited_sellable_review_candidate_state") == "REVIEW_CANDIDATE"
    )
    strong_lead_review_candidate_count = sum(
        1
        for row in project_rows
        if row.get("strong_lead_candidate_state") == "STRONG_LEAD_REVIEW_CANDIDATE"
    )
    denominator = candidate_count or 0
    sellable_or_limited_count = stage7_sellable_count + limited_sellable_review_candidate_count
    return {
        "candidate_count": candidate_count,
        "stage2_success_count": stage2_success_count,
        "stage3_success_count": stage3_success_count,
        "stage4_matched_task_count": stage4_matched_count,
        "stage4_needs_browser_task_count": stage4_needs_browser_count,
        "stage5_review_count": stage5_review_count,
        "stage5_operational_review_bucket_counts": _counts(
            row.get("stage5_operational_review_bucket") for row in project_rows
        ),
        "stage5_operational_signal_counts": _counts(
            signal
            for row in project_rows
            for signal in _as_list(row.get("stage5_operational_signal_flags"))
        ),
        "stage6_fact_ready_count": stage6_fact_ready_count,
        "stage7_sellable_count": stage7_sellable_count,
        "limited_sellable_review_candidate_count": limited_sellable_review_candidate_count,
        "strong_lead_review_candidate_count": strong_lead_review_candidate_count,
        "sellable_or_limited_review_candidate_count": sellable_or_limited_count,
        "real_public_sellable_pack_rate": _ratio(sellable_or_limited_count, denominator),
        "stage4_release_field_query_project_count": _int(stage6_summary.get("release_field_query_project_count")) or _distinct_count(field_records, "project_id"),
        "stage4_release_field_query_state_counts": dict(stage6_summary.get("release_field_query_state_counts") or {})
        or _counts(record.get("release_field_query_state") for record in stage6_records),
        "stage4_adapter_result_state_counts": dict(field_summary.get("adapter_result_state_counts") or {}),
        "stage4_downstream_abcd_grade_counts": dict(field_summary.get("release_evidence_downstream_abcd_grade_counts") or {}),
        "gdcic_authorized_readback_status": _gdcic_authorized_readback_status(gdcic_readback_summary),
        "p13b_public_source_readback_status": _p13b_public_source_readback_status(p13b_summary),
        "p13b_original_notice_readback_status": _p13b_original_notice_readback_status(p13b_original_summary),
        "p13b_ygp_original_readback_status": _p13b_ygp_original_readback_status(p13b_ygp_summary),
        "stage4_public_source_readback_state_counts": _counts(
            row.get("p13b_public_source_readback_state") for row in project_rows
        ),
        "stage4_original_notice_readback_state_counts": _counts(
            row.get("p13b_original_notice_readback_state") for row in project_rows
        ),
        "stage4_ygp_original_readback_state_counts": _counts(
            row.get("p13b_ygp_original_readback_state") for row in project_rows
        ),
        "stage6_loop_terminal_state_counts": dict(stage6_summary.get("loop_terminal_state_counts") or {})
        or _counts(record.get("loop_terminal_state") for record in stage6_records),
    }


def _project_scoreboard_row(
    project_id: str,
    readiness_record: Mapping[str, Any],
    stage6_record: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    p13b_project_signal: Mapping[str, Any],
    p13b_original_notice_signal: Mapping[str, Any],
    p13b_ygp_signal: Mapping[str, Any],
) -> dict[str, Any]:
    adapter_counts = _counts(record.get("adapter_result_state") for record in field_records)
    grade_counts = _counts(
        record.get("downstream_abcd_grade") or record.get("release_evidence_downstream_abcd_grade")
        for record in field_records
    )
    stage6_grade_counts = dict(stage6_record.get("release_field_query_downstream_abcd_grade_counts") or {})
    combined_grade_counts = {**grade_counts}
    for key, value in stage6_grade_counts.items():
        combined_grade_counts[key] = max(int(combined_grade_counts.get(key) or 0), int(value or 0))
    has_official_b_or_c = any(str(key).startswith(("B_", "C_")) and int(value or 0) > 0 for key, value in combined_grade_counts.items())
    stage7_allowed = bool(stage6_record.get("stage7_commercial_input_allowed"))
    stage6_strong_lead_state = str(stage6_record.get("strong_lead_candidate_state") or "").strip()
    stage6_limited_review_state = str(stage6_record.get("limited_sellable_review_candidate_state") or "").strip()
    strong_lead_candidate_state = (
        stage6_strong_lead_state
        if stage6_strong_lead_state
        else "STRONG_LEAD_REVIEW_CANDIDATE" if has_official_b_or_c else "NOT_READY"
    )
    limited_sellable_review_candidate_state = (
        stage6_limited_review_state
        if stage6_limited_review_state
        else "REVIEW_CANDIDATE" if has_official_b_or_c and not stage7_allowed else "NOT_READY"
    )
    stage5_operational_review = _stage5_operational_review(
        readiness_record=readiness_record,
        stage6_record=stage6_record,
        field_records=field_records,
        p13b_project_signal=p13b_project_signal,
        p13b_original_notice_signal=p13b_original_notice_signal,
        p13b_ygp_signal=p13b_ygp_signal,
        adapter_counts=adapter_counts,
        combined_grade_counts=combined_grade_counts,
        has_official_b_or_c=has_official_b_or_c,
    )
    return {
        "project_id": project_id,
        "project_name": str(readiness_record.get("project_name") or stage6_record.get("project_name") or ""),
        "stage2_detail_capture_state": str(readiness_record.get("stage2_detail_capture_state") or ""),
        "stage3_field_parse_state": str(readiness_record.get("stage3_field_parse_state") or ""),
        "stage5_gate_state": str(readiness_record.get("stage5_gate_state") or ""),
        "stage5_rule_gate_status": str(readiness_record.get("stage5_rule_gate_status") or ""),
        **stage5_operational_review,
        "stage6_fact_package_state": str(stage6_record.get("stage6_fact_package_state") or readiness_record.get("stage6_fact_package_state") or ""),
        "stage6_ready": bool(stage6_record.get("stage6_ready")),
        "stage7_commercial_input_allowed": stage7_allowed,
        "release_field_query_state": str(stage6_record.get("release_field_query_state") or ""),
        "loop_terminal_state": str(stage6_record.get("loop_terminal_state") or ""),
        "stage4_adapter_result_state_counts": adapter_counts or dict(stage6_record.get("release_field_query_adapter_result_state_counts") or {}),
        "stage4_downstream_abcd_grade_counts": combined_grade_counts,
        "authorization_state_counts": dict(stage6_record.get("release_field_query_authorization_state_counts") or {}),
        "p13b_public_source_readback_state": str(
            p13b_project_signal.get("p13b_public_source_readback_state") or ""
        ),
        "p13b_original_notice_backtrace_required_count": _int(
            p13b_project_signal.get("original_notice_backtrace_required_count")
        ),
        "p13b_company_query_state_counts": dict(p13b_project_signal.get("company_query_state_counts") or {}),
        "p13b_bid_show_state_counts": dict(p13b_project_signal.get("bid_show_state_counts") or {}),
        "p13b_overlap_signal_state_counts": dict(p13b_project_signal.get("overlap_signal_state_counts") or {}),
        "p13b_original_notice_readback_state": str(
            p13b_original_notice_signal.get("p13b_original_notice_readback_state") or ""
        ),
        "p13b_original_notice_fetch_state_counts": dict(
            p13b_original_notice_signal.get("original_notice_fetch_state_counts") or {}
        ),
        "p13b_original_notice_match_state_counts": dict(
            p13b_original_notice_signal.get("original_notice_backtrace_match_state_counts") or {}
        ),
        "p13b_ygp_original_readback_state": str(p13b_ygp_signal.get("p13b_ygp_original_readback_state") or ""),
        "p13b_ygp_readback_state_counts": dict(p13b_ygp_signal.get("ygp_readback_state_counts") or {}),
        "p13b_ygp_project_code_variants": _as_list(p13b_ygp_signal.get("ygp_project_code_variants")),
        "p13b_ygp_biz_code_variants": _as_list(p13b_ygp_signal.get("ygp_biz_code_variants")),
        "p13b_ygp_site_code_variants": _as_list(p13b_ygp_signal.get("ygp_site_code_variants")),
        "p13b_ygp_notice_id_variants": _as_list(p13b_ygp_signal.get("ygp_notice_id_variants")),
        "operator_next_actions": [str(item) for item in _as_list(stage6_record.get("release_field_query_operator_next_actions")) if str(item or "").strip()],
        "blocking_bucket": _project_blocking_bucket(readiness_record, stage6_record, field_records),
        "strong_lead_candidate_state": strong_lead_candidate_state,
        "limited_sellable_review_candidate_state": limited_sellable_review_candidate_state,
        "limited_sellable_review_reason": str(stage6_record.get("limited_sellable_review_reason") or ""),
        "commercialization_boundary_state": str(
            stage6_record.get("commercialization_boundary_state")
            or "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE"
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _blocker_summary(
    readiness_records: list[Mapping[str, Any]],
    gap_records: list[Mapping[str, Any]],
    field_query: Mapping[str, Any],
    gdcic_browser_readback: Mapping[str, Any],
    p13b_company_history: Mapping[str, Any],
    p13b_original_notice_backtrace: Mapping[str, Any],
    p13b_ygp_original_readback: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    stage6_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    field_summary = _summary(field_query)
    gdcic_readback_summary = _summary(gdcic_browser_readback)
    p13b_summary = _summary(p13b_company_history)
    p13b_original_summary = _summary(p13b_original_notice_backtrace)
    p13b_ygp_summary = _summary(p13b_ygp_original_readback)
    blocker_taxonomy_counts = dict(field_summary.get("blocker_taxonomy_counts") or {})
    if not blocker_taxonomy_counts:
        blocker_taxonomy_counts = _flatten_counts(field_records, "blocker_taxonomy")
    return {
        "blocking_bucket_counts": _counts(row.get("blocking_bucket") for row in project_rows),
        "field_missing_or_not_found_task_count": sum(1 for record in field_records if str(record.get("adapter_result_state") or "") == "NOT_FOUND"),
        "authorization_blocked_task_count": sum(
            1
            for record in field_records
            if str(record.get("adapter_result_state") or "") == "NEEDS_BROWSER"
            or "LOGIN_OR_SSO_REQUIRED" in str(record.get("authorization_readiness_state") or "")
        ),
        "stage4_matched_without_stage7_saleable_project_count": sum(
            1
            for row in project_rows
            if row.get("limited_sellable_review_candidate_state") == "REVIEW_CANDIDATE"
            and not bool(row.get("stage7_commercial_input_allowed"))
        ),
        "stage5_rule_review_project_count": sum(1 for record in readiness_records if str(record.get("stage5_rule_gate_status") or "").upper() == "REVIEW"),
        "stage6_projection_not_ready_project_count": sum(
            1
            for record in stage6_records
            if _has_grade(record, ("B_", "C_")) and not bool(record.get("stage7_commercial_input_allowed"))
        ),
        "gap_record_count": len(gap_records),
        "remaining_real_world_gap_counts": _flatten_counts(readiness_records, "remaining_real_world_gaps"),
        "fail_closed_reason_counts": _flatten_counts(readiness_records, "fail_closed_reasons"),
        "field_blocker_taxonomy_counts": blocker_taxonomy_counts,
        "operator_next_action_counts": dict(field_summary.get("operator_next_action_counts") or {}),
        "gdcic_authorized_readback_blocker": _gdcic_authorized_readback_status(gdcic_readback_summary),
        "p13b_public_source_readback_blocker": _p13b_public_source_readback_status(p13b_summary),
        "p13b_original_notice_readback_blocker": _p13b_original_notice_readback_status(p13b_original_summary),
        "p13b_ygp_original_readback_blocker": _p13b_ygp_original_readback_status(p13b_ygp_summary),
        "stage5_operational_review_bucket_counts": _counts(
            row.get("stage5_operational_review_bucket") for row in project_rows
        ),
        "stage5_operational_signal_counts": _counts(
            signal
            for row in project_rows
            for signal in _as_list(row.get("stage5_operational_signal_flags"))
        ),
    }


def _recommended_next_actions(blocker_summary: Mapping[str, Any], counts: Mapping[str, Any]) -> list[str]:
    actions: list[str] = []
    if _int(blocker_summary.get("authorization_blocked_task_count")):
        actions.append("provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun_field_query")
    gdcic_blocker = blocker_summary.get("gdcic_authorized_readback_blocker")
    if isinstance(gdcic_blocker, Mapping) and str(gdcic_blocker.get("operator_next_action") or "").strip():
        actions.append(str(gdcic_blocker.get("operator_next_action")))
    if isinstance(gdcic_blocker, Mapping) and str(gdcic_blocker.get("alternative_operator_next_action") or "").strip():
        actions.append(str(gdcic_blocker.get("alternative_operator_next_action")))
    p13b_blocker = blocker_summary.get("p13b_public_source_readback_blocker")
    if isinstance(p13b_blocker, Mapping) and _int(p13b_blocker.get("original_notice_backtrace_required_count")):
        actions.append("run_p13b_original_notice_backtrace_for_bid_show_records")
    if isinstance(p13b_blocker, Mapping) and _int(p13b_blocker.get("source_blocked_count")):
        actions.append("retry_or_route_public_source_blockers_to_local_authority_readback")
    p13b_original_blocker = blocker_summary.get("p13b_original_notice_readback_blocker")
    if isinstance(p13b_original_blocker, Mapping) and _int(p13b_original_blocker.get("fetch_blocked_count")):
        actions.append("continue_p13b_original_notice_backtrace_or_route_blocked_sources")
    p13b_ygp_blocker = blocker_summary.get("p13b_ygp_original_readback_blocker")
    if isinstance(p13b_ygp_blocker, Mapping) and _int(p13b_ygp_blocker.get("ygp_readback_ready_count")):
        actions.append("feed_ygp_original_readback_into_p13b_original_backtrace")
    if isinstance(p13b_ygp_blocker, Mapping) and _int(p13b_ygp_blocker.get("ygp_blocked_count")):
        actions.append("continue_ygp_original_readback_or_route_to_city_source")
    if _int(blocker_summary.get("field_missing_or_not_found_task_count")):
        actions.append("extend_stage4_project_code_and_source_readback_before_claiming_clearance")
    if _int(blocker_summary.get("stage4_matched_without_stage7_saleable_project_count")):
        actions.append("review_b_or_c_official_readback_for_limited_sellable_internal_package")
    if _int(counts.get("stage7_sellable_count")) == 0 and _int(counts.get("limited_sellable_review_candidate_count")) == 0:
        actions.append("do_not_expand_stage8_stage9_until_stage4_sellable_inventory_exists")
    return _dedupe(actions)


def _gdcic_authorized_readback_status(summary: Mapping[str, Any]) -> dict[str, Any]:
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "authorized_session_input_state": "",
            "authorized_session_input_ready": False,
            "authorization_readiness_state": "",
            "target_real_readback_success_count": 0,
            "target_project_manager_change_real_readback_success_count": 0,
            "real_readback_success_not_faked": True,
            "real_readback_success_proof_state": "NO_REAL_AUTHORIZED_READBACK_SUCCESS",
            "operator_next_action": "build_gdcic_browser_authorized_readback_artifact_then_rerun_scoreboard",
            "alternative_operator_next_action": "",
            "authorization_blocker_is_not_terminal_if_alternative_public_sources_exist": False,
            "alternative_public_source_route_count": 0,
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
        }
    authorized_session_ready = bool(summary.get("authorized_session_input_ready"))
    overall_state = str(summary.get("gdcic_authorized_session_overall_state") or "")
    success_count = _int(
        summary.get("target_real_readback_success_count")
        if "target_real_readback_success_count" in summary
        else summary.get("gdcic_browser_readback_ready_count")
    )
    project_manager_success_count = _int(
        summary.get("target_project_manager_change_real_readback_success_count")
        if "target_project_manager_change_real_readback_success_count" in summary
        else summary.get("project_manager_change_ready_count")
    )
    operator_action = str(summary.get("authorization_blocker_operator_next_action") or "").strip()
    alternative_operator_action = str(summary.get("authorization_blocker_alternative_operator_next_action") or "").strip()
    if not operator_action and (not authorized_session_ready or overall_state == "LOGIN_OR_SSO_REQUIRED"):
        operator_action = "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"
    return {
        "artifact_state": "BUILT",
        "authorized_session_input_state": str(summary.get("authorized_session_input_state") or ""),
        "authorized_session_input_ready": authorized_session_ready,
        "authorization_readiness_state": overall_state,
        "target_real_readback_success_count": success_count,
        "target_project_manager_change_real_readback_success_count": project_manager_success_count,
        "real_readback_success_not_faked": bool(summary.get("real_readback_success_not_faked", True)),
        "real_readback_success_proof_state": str(
            summary.get("real_readback_success_proof_state")
            or (
                "PROVEN_BY_BROWSER_AUTHORIZED_READBACK_READY_RECORDS"
                if success_count
                else "NO_REAL_AUTHORIZED_READBACK_SUCCESS"
            )
        ),
        "operator_next_action": operator_action,
        "alternative_operator_next_action": alternative_operator_action,
        "authorization_blocker_is_not_terminal_if_alternative_public_sources_exist": bool(
            summary.get("authorization_blocker_is_not_terminal_if_alternative_public_sources_exist")
        ),
        "alternative_public_source_route_count": _int(summary.get("alternative_public_source_route_count")),
        "alternative_public_source_route_target_type_counts": _counts(
            record.get("release_evidence_target_type")
            for record in _as_list(summary.get("alternative_public_source_route_records"))
            if isinstance(record, Mapping)
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _p13b_public_source_readback_status(summary: Mapping[str, Any]) -> dict[str, Any]:
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "input_mode": "",
            "execution_mode": "",
            "gdcic_alternative_public_source_route_count": 0,
            "queried_company_count": 0,
            "company_search_hit_count": 0,
            "bid_show_record_count": 0,
            "overlap_signal_review_required_count": 0,
            "original_notice_backtrace_required_count": 0,
            "source_blocked_count": 0,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return {
        "artifact_state": "BUILT",
        "input_mode": str(summary.get("input_mode") or ""),
        "execution_mode": str(summary.get("execution_mode") or ""),
        "gdcic_alternative_public_source_route_count": _int(
            summary.get("gdcic_alternative_public_source_route_count")
        ),
        "queried_company_count": _int(summary.get("queried_company_count")),
        "company_search_hit_count": _int(summary.get("company_search_hit_count")),
        "bid_show_record_count": _int(summary.get("bid_show_record_count")),
        "overlap_signal_review_required_count": _int(summary.get("overlap_signal_review_required_count")),
        "original_notice_backtrace_required_count": _int(summary.get("original_notice_backtrace_required_count")),
        "source_blocked_count": _int(summary.get("source_blocked_count")),
        "company_query_state_counts": dict(summary.get("company_query_state_counts") or {}),
        "bid_show_state_counts": dict(summary.get("bid_show_state_counts") or {}),
        "overlap_signal_state_counts": dict(summary.get("overlap_signal_state_counts") or {}),
        "query_miss_is_not_clearance": bool(summary.get("query_miss_is_not_clearance", True)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _p13b_original_notice_readback_status(summary: Mapping[str, Any]) -> dict[str, Any]:
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "execution_mode": "",
            "original_notice_task_count": 0,
            "live_processed_count": 0,
            "fetched_count": 0,
            "fetch_blocked_count": 0,
            "original_notice_overlap_signal_review_required_count": 0,
            "no_match_review_count": 0,
            "source_unsupported_count": 0,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return {
        "artifact_state": "BUILT",
        "execution_mode": str(summary.get("execution_mode") or ""),
        "original_notice_task_count": _int(summary.get("original_notice_task_count")),
        "live_processed_count": _int(summary.get("live_processed_count")),
        "fetched_count": _int(summary.get("fetched_count")),
        "fetch_blocked_count": _int(summary.get("fetch_blocked_count")),
        "original_notice_overlap_signal_review_required_count": _int(
            summary.get("original_notice_overlap_signal_review_required_count")
        ),
        "no_match_review_count": _int(summary.get("no_match_review_count")),
        "source_unsupported_count": _int(summary.get("source_unsupported_count")),
        "fetch_state_counts": dict(summary.get("fetch_state_counts") or {}),
        "overlap_signal_state_counts": dict(summary.get("overlap_signal_state_counts") or {}),
        "original_notice_backtrace_match_state_counts": dict(
            summary.get("original_notice_backtrace_match_state_counts") or {}
        ),
        "query_miss_is_not_clearance": bool(summary.get("query_miss_is_not_clearance", True)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _p13b_ygp_original_readback_status(summary: Mapping[str, Any]) -> dict[str, Any]:
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "execution_mode": "",
            "ygp_original_readback_task_count": 0,
            "ygp_readback_ready_count": 0,
            "ygp_person_period_extracted_count": 0,
            "ygp_blocked_count": 0,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    state_counts = dict(summary.get("ygp_readback_state_counts") or {})
    return {
        "artifact_state": "BUILT",
        "execution_mode": str(summary.get("execution_mode") or ""),
        "ygp_original_readback_task_count": _int(summary.get("ygp_original_readback_task_count")),
        "ygp_readback_ready_count": _int(summary.get("ygp_readback_ready_count")),
        "ygp_person_period_extracted_count": _int(summary.get("ygp_person_period_extracted_count")),
        "ygp_blocked_count": _int(state_counts.get("YGP_ORIGINAL_URL_BLOCKED")),
        "ygp_readback_state_counts": state_counts,
        "ygp_api_discovery_state_counts": dict(summary.get("ygp_api_discovery_state_counts") or {}),
        "stage4_ygp_project_code_backfill_record_count": _int(
            summary.get("stage4_ygp_project_code_backfill_record_count")
        ),
        "stage4_ygp_backfill_state_counts": dict(summary.get("stage4_ygp_backfill_state_counts") or {}),
        "stage4_ygp_gdcic_route_allowed_count": _int(summary.get("stage4_ygp_gdcic_route_allowed_count")),
        "blocker_taxonomy_counts": dict(summary.get("blocker_taxonomy_counts") or {}),
        "query_miss_is_not_clearance": bool(summary.get("query_miss_is_not_clearance", True)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_blocking_bucket(
    readiness_record: Mapping[str, Any],
    stage6_record: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
) -> str:
    if _has_grade(stage6_record, ("B_", "C_")) or any(
        str(record.get("downstream_abcd_grade") or "").startswith(("B_", "C_")) for record in field_records
    ):
        return "stage4_matched_needs_manual_limited_sellable_review"
    if any(str(record.get("adapter_result_state") or "") == "NEEDS_BROWSER" for record in field_records):
        return "authorization_or_browser_blocked"
    if any(str(record.get("adapter_result_state") or "") == "NOT_FOUND" for record in field_records):
        return "official_source_not_found_or_field_missing"
    if str(readiness_record.get("stage5_rule_gate_status") or "").upper() == "REVIEW":
        return "stage5_rule_review"
    if str(readiness_record.get("stage3_field_parse_state") or "").upper() and not str(readiness_record.get("stage3_field_parse_state") or "").upper().startswith("PARSED"):
        return "stage3_parse_gap"
    return "unclassified_review_required"


def _stage5_operational_review(
    *,
    readiness_record: Mapping[str, Any],
    stage6_record: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    p13b_project_signal: Mapping[str, Any],
    p13b_original_notice_signal: Mapping[str, Any],
    p13b_ygp_signal: Mapping[str, Any],
    adapter_counts: Mapping[str, int],
    combined_grade_counts: Mapping[str, int],
    has_official_b_or_c: bool,
) -> dict[str, Any]:
    operator_actions = [
        str(item)
        for item in _as_list(stage6_record.get("release_field_query_operator_next_actions"))
        if str(item or "").strip()
    ]
    authorization_counts = dict(stage6_record.get("release_field_query_authorization_state_counts") or {})
    has_authorization_block = (
        _int(adapter_counts.get("NEEDS_BROWSER")) > 0
        or any("LOGIN_OR_SSO_REQUIRED" in str(key) and _int(value) > 0 for key, value in authorization_counts.items())
        or any("authorized_storage_state_or_user_data_dir" in action for action in operator_actions)
    )
    has_source_not_found = _int(adapter_counts.get("NOT_FOUND")) > 0
    p13b_state = str(p13b_project_signal.get("p13b_public_source_readback_state") or "")
    has_public_source_blocked = (
        p13b_state == "PUBLIC_SOURCE_BLOCKED_REVIEW"
        or _int(p13b_project_signal.get("source_blocked_count")) > 0
    )
    has_original_backtrace_required = (
        p13b_state == "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
        or _int(p13b_project_signal.get("original_notice_backtrace_required_count")) > 0
    )
    has_public_source_not_found = p13b_state == "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"
    original_notice_state = str(p13b_original_notice_signal.get("p13b_original_notice_readback_state") or "")
    has_original_notice_match = original_notice_state == "MATCHED"
    has_original_notice_not_found = original_notice_state == "NOT_FOUND"
    has_original_notice_blocked = original_notice_state == "BLOCKED"
    ygp_state = str(p13b_ygp_signal.get("p13b_ygp_original_readback_state") or "")
    has_ygp_ready = ygp_state == "YGP_READBACK_READY"
    has_ygp_blocked = ygp_state == "YGP_BLOCKED"
    has_weak_official_signal = _int(adapter_counts.get("MATCHED")) > 0 and not has_official_b_or_c
    has_evidence_insufficient = (
        any(str(key).startswith("D_") and _int(value) > 0 for key, value in combined_grade_counts.items())
        or bool(_as_list(readiness_record.get("remaining_real_world_gaps")))
        or bool(_as_list(readiness_record.get("fail_closed_reasons")))
        or str(readiness_record.get("stage5_rule_gate_status") or "").upper() == "REVIEW"
        or str(readiness_record.get("stage5_gate_state") or "").upper() == "REVIEW_REQUIRED"
    )
    signals: list[str] = []
    if has_official_b_or_c:
        signals.append("strong_lead")
    if has_weak_official_signal:
        signals.append("weak_lead")
    if has_authorization_block:
        signals.append("authorization_blocked")
    if has_public_source_blocked:
        signals.append("public_source_blocked")
    if has_original_backtrace_required:
        signals.append("original_notice_backtrace_required")
    if has_original_notice_match:
        signals.append("original_notice_matched")
    if has_original_notice_not_found:
        signals.append("original_notice_not_found")
    if has_original_notice_blocked:
        signals.append("original_notice_blocked")
    if has_ygp_ready:
        signals.append("ygp_readback_ready")
    if has_ygp_blocked:
        signals.append("ygp_readback_blocked")
    if has_source_not_found:
        signals.append("source_not_found")
    if has_public_source_not_found:
        signals.append("public_source_not_found")
    if has_evidence_insufficient:
        signals.append("evidence_insufficient")

    if has_official_b_or_c:
        bucket = "STRONG_LEAD_INTERNAL_REVIEW"
        action = "manual_stage5_stage6_review_before_limited_sellable_internal_package"
    elif has_original_notice_match:
        bucket = "STRONG_LEAD_INTERNAL_REVIEW"
        action = "manual_stage5_stage6_review_before_limited_sellable_internal_package"
    elif has_original_notice_not_found:
        bucket = "ORIGINAL_NOTICE_NOT_FOUND_REVIEW"
        action = "keep_original_notice_no_match_as_non_clearance_and_continue_targeted_readback"
    elif has_original_notice_blocked:
        bucket = "ORIGINAL_NOTICE_BLOCKED_REVIEW"
        action = "continue_p13b_original_notice_backtrace_or_route_blocked_sources"
    elif has_ygp_ready:
        bucket = "YGP_READBACK_READY_REVIEW"
        action = "feed_ygp_original_readback_into_p13b_original_backtrace"
    elif has_ygp_blocked:
        bucket = "YGP_READBACK_BLOCKED_REVIEW"
        action = "continue_ygp_original_readback_or_route_to_city_source"
    elif has_weak_official_signal:
        bucket = "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW"
        action = "strengthen_official_readback_before_any_commercial_projection"
    elif has_original_backtrace_required:
        bucket = "ORIGINAL_NOTICE_BACKTRACE_REQUIRED_REVIEW"
        action = "run_p13b_original_notice_backtrace_without_clearance_claim"
    elif has_public_source_blocked:
        bucket = "PUBLIC_SOURCE_BLOCKED_REVIEW"
        action = "retry_public_source_or_route_to_local_authority_readback"
    elif has_authorization_block:
        bucket = "AUTHORIZATION_BLOCKED_REVIEW"
        action = "provide_authorized_browser_session_then_rerun_release_field_query"
    elif has_source_not_found:
        bucket = "SOURCE_NOT_FOUND_REVIEW"
        action = "try_project_code_backfill_or_jurisdiction_source_without_clearance_claim"
    elif has_public_source_not_found:
        bucket = "PUBLIC_SOURCE_NOT_FOUND_REVIEW"
        action = "keep_no_public_overlap_signal_as_non_clearance_and_manual_review"
    elif has_evidence_insufficient:
        bucket = "EVIDENCE_INSUFFICIENT_REVIEW"
        action = "keep_internal_evidence_gap_and_collect_more_official_readback"
    else:
        bucket = "UNCLASSIFIED_STAGE5_REVIEW"
        action = "review_stage5_inputs_and_classifier_coverage"

    return {
        "stage5_operational_review_bucket": bucket,
        "stage5_operational_signal_flags": signals or ["unclassified_review_required"],
        "stage5_operational_review_reason": "|".join(signals) if signals else "stage5_review_requires_manual_triage",
        "stage5_operational_next_action": action,
        "stage5_query_miss_is_not_clearance": True,
    }


def _resolve_stage6_status_path(value: str | Path | None, root: Path) -> Path:
    if value:
        return Path(value)
    candidates = (
        root / "stage6-review-loop-project-status-table.json",
        root / "stage6-review-cycle-project-status-table.json",
        root / "stage6-review-cycle-runner-v1.json",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_path(value: str | Path | None, default: Path) -> Path:
    return Path(value) if value else default


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    if isinstance(records, list):
        return [dict(record) for record in records if isinstance(record, Mapping)]
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping):
        records = manifest.get("records") or manifest.get("operator_projection_status_table")
        if isinstance(records, Mapping):
            records = records.get("records")
        if isinstance(records, list):
            return [dict(record) for record in records if isinstance(record, Mapping)]
    return []


def _field_task_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    records = manifest.get("field_task_records")
    return [dict(record) for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []


def _p13b_project_signals(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    if not manifest:
        return {}
    project_records = _manifest_records(manifest, "project_task_records")
    query_records = _manifest_records(manifest, "company_history_query_records")
    bid_show_records = _manifest_records(manifest, "bid_show_records")
    overlap_records = _manifest_records(manifest, "overlap_signal_records")
    project_ids = _ordered_project_ids(project_records, query_records, bid_show_records, overlap_records)
    signals: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_queries = [record for record in query_records if str(record.get("project_id") or "").strip() == project_id]
        project_bid_shows = [record for record in bid_show_records if str(record.get("project_id") or "").strip() == project_id]
        project_overlaps = [record for record in overlap_records if str(record.get("project_id") or "").strip() == project_id]
        company_query_counts = _counts(record.get("query_state") for record in project_queries)
        bid_show_counts = _counts(record.get("bid_show_state") for record in project_bid_shows)
        overlap_counts = _counts(record.get("overlap_signal_state") for record in project_overlaps)
        original_backtrace_required = _int(overlap_counts.get("ORIGINAL_NOTICE_BACKTRACE_REQUIRED")) + _int(
            bid_show_counts.get("ORIGINAL_NOTICE_BACKTRACE_REQUIRED")
        )
        source_blocked = _int(company_query_counts.get("SOURCE_BLOCKED_RETRY_REQUIRED"))
        overlap_review_required = _int(overlap_counts.get("OVERLAP_SIGNAL_REVIEW_REQUIRED"))
        no_public_signal = _int(overlap_counts.get("NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"))
        if overlap_review_required:
            readback_state = "MATCHED_OVERLAP_SIGNAL_REVIEW_REQUIRED"
        elif original_backtrace_required:
            readback_state = "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
        elif source_blocked:
            readback_state = "PUBLIC_SOURCE_BLOCKED_REVIEW"
        elif no_public_signal or _int(company_query_counts.get("NO_PUBLIC_OVERLAP_SIGNAL_REVIEW")):
            readback_state = "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"
        else:
            readback_state = "PUBLIC_SOURCE_READBACK_PENDING_OR_NOT_RUN"
        signals[project_id] = {
            "project_id": project_id,
            "p13b_public_source_readback_state": readback_state,
            "company_query_state_counts": company_query_counts,
            "bid_show_state_counts": bid_show_counts,
            "overlap_signal_state_counts": overlap_counts,
            "original_notice_backtrace_required_count": original_backtrace_required,
            "source_blocked_count": source_blocked,
            "overlap_signal_review_required_count": overlap_review_required,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return signals


def _p13b_original_notice_project_signals(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    if not manifest:
        return {}
    fetch_records = _manifest_records(manifest, "original_notice_fetch_records")
    overlap_records = _manifest_records(manifest, "original_notice_overlap_signal_records")
    project_ids = _ordered_project_ids(fetch_records, overlap_records)
    signals: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_fetches = [record for record in fetch_records if str(record.get("project_id") or "").strip() == project_id]
        project_overlaps = [record for record in overlap_records if str(record.get("project_id") or "").strip() == project_id]
        fetch_counts = _counts(record.get("fetch_state") for record in project_fetches)
        overlap_counts = _counts(record.get("original_notice_overlap_signal_state") for record in project_overlaps)
        match_counts = _counts(record.get("original_notice_backtrace_match_state") for record in project_overlaps)
        if _int(match_counts.get("SAME_PERSON_COMPANY_PERIOD_SIGNAL")):
            readback_state = "MATCHED"
        elif (
            _int(match_counts.get("NO_COMPANY_PERSON_PERIOD_MATCH"))
            or _int(match_counts.get("EXTRACTED_DIFFERENT_PERSON_WITH_PERIOD"))
            or _int(overlap_counts.get("ORIGINAL_NOTICE_NO_MATCH_REVIEW"))
        ):
            readback_state = "NOT_FOUND"
        elif _int(fetch_counts.get("ORIGINAL_NOTICE_FETCH_BLOCKED")) or _int(overlap_counts.get("ORIGINAL_NOTICE_SOURCE_UNSUPPORTED_REVIEW")):
            readback_state = "BLOCKED"
        else:
            readback_state = "PENDING_OR_NOT_RUN"
        signals[project_id] = {
            "project_id": project_id,
            "p13b_original_notice_readback_state": readback_state,
            "original_notice_fetch_state_counts": fetch_counts,
            "original_notice_overlap_signal_state_counts": overlap_counts,
            "original_notice_backtrace_match_state_counts": match_counts,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return signals


def _p13b_ygp_project_signals(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    if not manifest:
        return {}
    readback_records = _manifest_records(manifest, "ygp_original_readback_records")
    project_ids = _ordered_project_ids(readback_records)
    signals: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_records = [record for record in readback_records if str(record.get("project_id") or "").strip() == project_id]
        state_counts = _counts(record.get("ygp_readback_state") for record in project_records)
        ready_count = _int(state_counts.get("YGP_ORIGINAL_URL_READBACK_READY")) + _int(
            state_counts.get("YGP_BROWSER_NETWORK_READBACK_READY")
        )
        blocked_count = _int(state_counts.get("YGP_ORIGINAL_URL_BLOCKED")) + _int(
            state_counts.get("YGP_ORIGINAL_URL_UNSUPPORTED")
        )
        if ready_count:
            readback_state = "YGP_READBACK_READY"
        elif blocked_count:
            readback_state = "YGP_BLOCKED"
        else:
            readback_state = "YGP_PENDING_OR_NOT_RUN"
        signals[project_id] = {
            "project_id": project_id,
            "p13b_ygp_original_readback_state": readback_state,
            "ygp_readback_state_counts": state_counts,
            "ygp_project_code_variants": _dedupe(record.get("ygp_project_code") for record in project_records),
            "ygp_biz_code_variants": _dedupe(record.get("ygp_biz_code") for record in project_records),
            "ygp_site_code_variants": _dedupe(record.get("ygp_site_code") for record in project_records),
            "ygp_notice_id_variants": _dedupe(record.get("ygp_notice_id") for record in project_records),
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return signals


def _manifest_records(manifest: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    records = manifest.get(key)
    return [dict(record) for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []


def _summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        return dict(summary)
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping) and isinstance(manifest.get("summary"), Mapping):
        return dict(manifest["summary"])
    return {}


def _ordered_project_ids(*record_groups: list[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for records in record_groups:
        for record in records:
            project_id = str(record.get("project_id") or "").strip()
            if project_id and project_id not in out:
                out.append(project_id)
    return out


def _stage5_review_count(summary: Mapping[str, Any], records: list[Mapping[str, Any]]) -> int:
    counts = summary.get("stage5_rule_gate_status_counts")
    if isinstance(counts, Mapping) and "REVIEW" in counts:
        return int(counts.get("REVIEW") or 0)
    return sum(
        1
        for record in records
        if str(record.get("stage5_rule_gate_status") or "").upper() == "REVIEW"
        or str(record.get("stage5_gate_state") or "").upper() == "REVIEW_REQUIRED"
    )


def _stage3_parse_attempt_succeeded(value: Any) -> bool:
    state = str(value or "").upper()
    if not state:
        return False
    if state.startswith("PARSED"):
        return True
    if state.endswith("_REVIEW_REQUIRED") and "STAGE2" not in state and "PENDING" not in state:
        return True
    return state in {"READBACK_READY", "FIELD_SIGNALS_READY"}


def _count_state(summary: Mapping[str, Any], records: list[Mapping[str, Any]], field: str, state: str) -> int:
    counts = summary.get(f"{field}_counts")
    if isinstance(counts, Mapping) and state in counts:
        return int(counts.get(state) or 0)
    if field == "adapter_result_state":
        counts = summary.get("adapter_result_state_counts")
        if isinstance(counts, Mapping) and state in counts:
            return int(counts.get(state) or 0)
    return sum(1 for record in records if str(record.get(field) or "") == state)


def _has_grade(record: Mapping[str, Any], prefixes: tuple[str, ...]) -> bool:
    counts = record.get("release_field_query_downstream_abcd_grade_counts")
    if isinstance(counts, Mapping):
        return any(str(key).startswith(prefixes) and int(value or 0) > 0 for key, value in counts.items())
    return False


def _flatten_counts(records: list[Mapping[str, Any]], field: str) -> dict[str, int]:
    return _counts(item for record in records for item in _as_list(record.get(field)))


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        out[text] = out.get(text, 0) + 1
    return out


def _distinct_count(records: list[Mapping[str, Any]], field: str) -> int:
    return len({str(record.get(field) or "").strip() for record in records if str(record.get(field) or "").strip()})


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: list[str]) -> list[str]:
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


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    scoreboard = payload.get("scoreboard") if isinstance(payload.get("scoreboard"), Mapping) else {}
    blockers = payload.get("blocker_summary") if isinstance(payload.get("blocker_summary"), Mapping) else {}
    lines = [
        "# Stage1-6 Sellable Scoreboard v1",
        "",
        f"- candidate_count: {scoreboard.get('candidate_count', 0)}",
        f"- stage2_success_count: {scoreboard.get('stage2_success_count', 0)}",
        f"- stage3_success_count: {scoreboard.get('stage3_success_count', 0)}",
        f"- stage4_matched_task_count: {scoreboard.get('stage4_matched_task_count', 0)}",
        f"- stage4_needs_browser_task_count: {scoreboard.get('stage4_needs_browser_task_count', 0)}",
        f"- stage5_review_count: {scoreboard.get('stage5_review_count', 0)}",
        f"- stage5_operational_review_bucket_counts: {json.dumps(scoreboard.get('stage5_operational_review_bucket_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage5_operational_signal_counts: {json.dumps(scoreboard.get('stage5_operational_signal_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage6_fact_ready_count: {scoreboard.get('stage6_fact_ready_count', 0)}",
        f"- stage7_sellable_count: {scoreboard.get('stage7_sellable_count', 0)}",
        f"- limited_sellable_review_candidate_count: {scoreboard.get('limited_sellable_review_candidate_count', 0)}",
        f"- real_public_sellable_pack_rate: {scoreboard.get('real_public_sellable_pack_rate', 0)}",
        f"- gdcic_authorized_readback_status: {json.dumps(scoreboard.get('gdcic_authorized_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p13b_public_source_readback_status: {json.dumps(scoreboard.get('p13b_public_source_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p13b_original_notice_readback_status: {json.dumps(scoreboard.get('p13b_original_notice_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p13b_ygp_original_readback_status: {json.dumps(scoreboard.get('p13b_ygp_original_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_public_source_readback_state_counts: {json.dumps(scoreboard.get('stage4_public_source_readback_state_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_original_notice_readback_state_counts: {json.dumps(scoreboard.get('stage4_original_notice_readback_state_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_ygp_original_readback_state_counts: {json.dumps(scoreboard.get('stage4_ygp_original_readback_state_counts', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "## Blockers",
    ]
    for key, value in blockers.items():
        if isinstance(value, Mapping):
            lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        else:
            lines.append(f"- {key}: {value}")
    lines.extend(["", "customer_visible_allowed=false; query_miss_is_not_clearance=true; no_legal_conclusion=true"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pressure-root", default=str(DEFAULT_PRESSURE_ROOT))
    parser.add_argument("--pressure-summary-json", default="")
    parser.add_argument("--readiness-json", default="")
    parser.add_argument("--gap-summary-json", default="")
    parser.add_argument("--field-query-root", default=str(DEFAULT_FIELD_QUERY_ROOT))
    parser.add_argument("--field-query-json", default="")
    parser.add_argument("--gdcic-browser-readback-root", default=str(DEFAULT_GDCIC_BROWSER_READBACK_ROOT))
    parser.add_argument("--gdcic-browser-readback-json", default="")
    parser.add_argument("--p13b-company-history-root", default=str(DEFAULT_P13B_COMPANY_HISTORY_ROOT))
    parser.add_argument("--p13b-company-history-json", default="")
    parser.add_argument("--p13b-original-notice-backtrace-root", default=str(DEFAULT_P13B_ORIGINAL_NOTICE_BACKTRACE_ROOT))
    parser.add_argument("--p13b-original-notice-backtrace-json", default="")
    parser.add_argument("--p13b-ygp-original-readback-root", default=str(DEFAULT_P13B_YGP_ORIGINAL_READBACK_ROOT))
    parser.add_argument("--p13b-ygp-original-readback-json", default="")
    parser.add_argument("--stage6-status-root", default=str(DEFAULT_STAGE6_STATUS_ROOT))
    parser.add_argument("--stage6-status-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage1_6_sellable_scoreboard(
        pressure_root=args.pressure_root,
        pressure_summary_json=args.pressure_summary_json or None,
        readiness_json=args.readiness_json or None,
        gap_summary_json=args.gap_summary_json or None,
        field_query_root=args.field_query_root,
        field_query_json=args.field_query_json or None,
        gdcic_browser_readback_root=args.gdcic_browser_readback_root,
        gdcic_browser_readback_json=args.gdcic_browser_readback_json or None,
        p13b_company_history_root=args.p13b_company_history_root,
        p13b_company_history_json=args.p13b_company_history_json or None,
        p13b_original_notice_backtrace_root=args.p13b_original_notice_backtrace_root,
        p13b_original_notice_backtrace_json=args.p13b_original_notice_backtrace_json or None,
        p13b_ygp_original_readback_root=args.p13b_ygp_original_readback_root,
        p13b_ygp_original_readback_json=args.p13b_ygp_original_readback_json or None,
        stage6_status_root=args.stage6_status_root,
        stage6_status_json=args.stage6_status_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["scoreboard"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
