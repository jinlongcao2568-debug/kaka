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
DEFAULT_P13B_OVERLAP_TRIAGE_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/p13b-overlap-triage-closeout-v1")
DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT = Path(
    "tmp/evaluation-real-samples/design-survey-public-registry-readback-v1"
)
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-6-sellable-scoreboard-v1")


def build_stage1_6_sellable_scoreboard(
    *,
    pressure_root: str | Path | None = None,
    pressure_summary_json: str | Path | None = None,
    readiness_json: str | Path | None = None,
    gap_summary_json: str | Path | None = None,
    field_query_root: str | Path | None = None,
    field_query_json: str | Path | None = None,
    supplemental_field_query_root: str | Path | None = None,
    supplemental_field_query_json: str | Path | None = None,
    gdcic_browser_readback_root: str | Path | None = None,
    gdcic_browser_readback_json: str | Path | None = None,
    p13b_company_history_root: str | Path | None = None,
    p13b_company_history_json: str | Path | None = None,
    p13b_original_notice_backtrace_root: str | Path | None = None,
    p13b_original_notice_backtrace_json: str | Path | None = None,
    p13b_ygp_original_readback_root: str | Path | None = None,
    p13b_ygp_original_readback_json: str | Path | None = None,
    p13b_overlap_triage_closeout_root: str | Path | None = None,
    p13b_overlap_triage_closeout_json: str | Path | None = None,
    company_first_stage4_execution_root: str | Path | None = None,
    company_first_stage4_execution_json: str | Path | None = None,
    design_survey_public_registry_readback_root: str | Path | None = None,
    design_survey_public_registry_readback_json: str | Path | None = None,
    stage6_status_root: str | Path | None = None,
    stage6_status_json: str | Path | None = None,
    prior_scoreboard_json: str | Path | None = None,
    incremental_project_ids: list[str] | str | None = None,
    output_root: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    pressure_dir = Path(pressure_root or DEFAULT_PRESSURE_ROOT)
    field_dir = Path(field_query_root or DEFAULT_FIELD_QUERY_ROOT)
    supplemental_field_dir = Path(supplemental_field_query_root) if supplemental_field_query_root else None
    gdcic_readback_dir = Path(gdcic_browser_readback_root or DEFAULT_GDCIC_BROWSER_READBACK_ROOT)
    p13b_company_history_dir = Path(p13b_company_history_root or DEFAULT_P13B_COMPANY_HISTORY_ROOT)
    p13b_original_notice_dir = Path(
        p13b_original_notice_backtrace_root or DEFAULT_P13B_ORIGINAL_NOTICE_BACKTRACE_ROOT
    )
    p13b_ygp_original_dir = Path(p13b_ygp_original_readback_root or DEFAULT_P13B_YGP_ORIGINAL_READBACK_ROOT)
    p13b_overlap_closeout_dir = Path(p13b_overlap_triage_closeout_root or DEFAULT_P13B_OVERLAP_TRIAGE_CLOSEOUT_ROOT)
    design_survey_public_registry_readback_dir = Path(
        design_survey_public_registry_readback_root or DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT
    )
    stage6_dir = Path(stage6_status_root or DEFAULT_STAGE6_STATUS_ROOT)
    out_dir = Path(output_root or DEFAULT_OUTPUT_ROOT)
    out_dir.mkdir(parents=True, exist_ok=True)

    pressure_summary_path = _resolve_path(pressure_summary_json, pressure_dir / "pressure-summary.json")
    readiness_path = _resolve_path(readiness_json, pressure_dir / "stage1-6-readiness-table.json")
    gap_summary_path = _resolve_path(gap_summary_json, pressure_dir / "stage1-6-gap-summary-table.json")
    field_query_path = _resolve_path(field_query_json, field_dir / "guangdong-local-field-query-probe-v1.json")
    supplemental_field_query_path = (
        _resolve_path(
            supplemental_field_query_json,
            (supplemental_field_dir or field_dir) / "guangdong-local-field-query-probe-v1.json",
        )
        if supplemental_field_query_root or supplemental_field_query_json
        else None
    )
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
    p13b_overlap_triage_closeout_path = _resolve_path(
        p13b_overlap_triage_closeout_json,
        p13b_overlap_closeout_dir / "p13b-overlap-triage-closeout-v1.json",
    )
    company_first_stage4_execution_path = _resolve_optional_artifact_path(
        artifact_json=company_first_stage4_execution_json,
        artifact_root=company_first_stage4_execution_root,
        artifact_name="company-first-stage4-execution.json",
    )
    design_survey_public_registry_readback_path = _resolve_optional_artifact_path(
        artifact_json=design_survey_public_registry_readback_json,
        artifact_root=design_survey_public_registry_readback_dir,
        artifact_name="design-survey-public-registry-readback-v1.json",
    )
    stage6_status_path = _resolve_stage6_status_path(stage6_status_json, stage6_dir)

    pressure_summary = _read_json_mapping(pressure_summary_path)
    readiness = _read_json_mapping(readiness_path)
    gap_summary = _read_json_mapping(gap_summary_path)
    field_query = _read_json_mapping(field_query_path)
    supplemental_field_query = (
        _read_json_mapping(supplemental_field_query_path) if supplemental_field_query_path is not None else {}
    )
    field_query = _merge_field_query_payloads(field_query, supplemental_field_query)
    gdcic_browser_readback = _read_json_mapping(gdcic_browser_readback_path)
    p13b_company_history = _read_json_mapping(p13b_company_history_path)
    p13b_original_notice_backtrace = _read_json_mapping(p13b_original_notice_backtrace_path)
    p13b_ygp_original_readback = _read_json_mapping(p13b_ygp_original_readback_path)
    p13b_overlap_triage_closeout = _read_json_mapping(p13b_overlap_triage_closeout_path)
    company_first_stage4_execution = (
        _read_json_mapping(company_first_stage4_execution_path) if company_first_stage4_execution_path else {}
    )
    design_survey_public_registry_readback = (
        _read_json_mapping(design_survey_public_registry_readback_path)
        if design_survey_public_registry_readback_path
        else {}
    )
    stage6_status = _read_json_mapping(stage6_status_path)
    prior_scoreboard = _read_json_mapping(Path(prior_scoreboard_json)) if prior_scoreboard_json else {}
    incremental_targets = _string_set(incremental_project_ids)

    readiness_records = _records(readiness)
    gap_records = _records(gap_summary)
    field_records = _field_task_records(field_query)
    p13b_project_signals = _p13b_project_signals(p13b_company_history)
    p13b_original_notice_project_signals = _p13b_original_notice_project_signals(p13b_original_notice_backtrace)
    p13b_ygp_project_signals = _p13b_ygp_project_signals(p13b_ygp_original_readback)
    p13b_overlap_closeout_project_signals = _p13b_overlap_closeout_project_signals(p13b_overlap_triage_closeout)
    company_first_stage4_execution_signals = _company_first_stage4_execution_project_signals(
        company_first_stage4_execution
    )
    design_survey_public_registry_readback_signals = _design_survey_public_registry_readback_project_signals(
        design_survey_public_registry_readback
    )
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
        list(p13b_overlap_closeout_project_signals.values()),
        list(company_first_stage4_execution_signals.values()),
        list(design_survey_public_registry_readback_signals.values()),
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
            p13b_overlap_closeout_project_signals.get(project_id, {}),
            company_first_stage4_execution_signals.get(project_id, {}),
            design_survey_public_registry_readback_signals.get(project_id, {}),
        )
        for project_id in project_ids
    ]
    project_rows = _merge_incremental_prior_project_rows(
        project_rows,
        prior_scoreboard=prior_scoreboard,
        incremental_project_ids=incremental_targets,
    )
    counts = _scoreboard_counts(
        pressure_summary,
        readiness_records,
        field_query,
        gdcic_browser_readback,
        p13b_company_history,
        p13b_original_notice_backtrace,
        p13b_ygp_original_readback,
        p13b_overlap_triage_closeout,
        company_first_stage4_execution,
        design_survey_public_registry_readback,
        field_records,
        stage6_status,
        stage6_records,
        project_rows,
    )
    counts = _preserve_incremental_prior_topline_counts(
        counts,
        prior_scoreboard=prior_scoreboard,
        incremental_project_ids=incremental_targets,
    )
    blocker_summary = _blocker_summary(
        readiness_records,
        gap_records,
        field_query,
        gdcic_browser_readback,
        p13b_company_history,
        p13b_original_notice_backtrace,
        p13b_ygp_original_readback,
        p13b_overlap_triage_closeout,
        company_first_stage4_execution,
        field_records,
        stage6_records,
        project_rows,
    )
    recommended_next_actions = _recommended_next_actions(blocker_summary, counts)

    input_refs = {
        "pressure_summary_json": str(pressure_summary_path),
        "stage1_6_readiness_json": str(readiness_path),
        "stage1_6_gap_summary_json": str(gap_summary_path),
        "release_field_query_json": str(field_query_path),
        "supplemental_release_field_query_json": str(supplemental_field_query_path)
        if supplemental_field_query_path is not None
        else "",
        "gdcic_browser_authorized_readback_json": str(gdcic_browser_readback_path),
        "p13b_company_history_json": str(p13b_company_history_path),
        "p13b_original_notice_backtrace_json": str(p13b_original_notice_backtrace_path),
        "p13b_ygp_original_readback_json": str(p13b_ygp_original_readback_path),
        "p13b_overlap_triage_closeout_json": str(p13b_overlap_triage_closeout_path),
        "company_first_stage4_execution_json": str(company_first_stage4_execution_path or ""),
        "design_survey_public_registry_readback_json": str(design_survey_public_registry_readback_path or ""),
        "stage6_status_json": str(stage6_status_path),
        "prior_scoreboard_json": str(prior_scoreboard_json or ""),
        "incremental_project_ids": sorted(incremental_targets),
    }
    result = {
        "scoreboard_kind": SCOREBOARD_KIND,
        "scoreboard_version": SCOREBOARD_VERSION,
        "created_at": created,
        "input_refs": input_refs,
        "continuation_input_refs": _scoreboard_continuation_input_refs(input_refs, out_dir),
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


def _preserve_incremental_prior_topline_counts(
    counts: Mapping[str, Any],
    *,
    prior_scoreboard: Mapping[str, Any],
    incremental_project_ids: set[str],
) -> dict[str, Any]:
    out = dict(counts)
    if not incremental_project_ids:
        return out
    prior_counts = prior_scoreboard.get("scoreboard")
    if not isinstance(prior_counts, Mapping):
        return out
    for key in ("candidate_count", "stage2_success_count", "stage3_success_count"):
        out[key] = max(_int(out.get(key)), _int(prior_counts.get(key)))
    denominator = _int(out.get("candidate_count"))
    sellable_or_limited = _int(out.get("sellable_or_limited_review_candidate_count"))
    out["real_public_sellable_pack_rate"] = _ratio(sellable_or_limited, denominator)
    return out


def _scoreboard_counts(
    pressure_summary: Mapping[str, Any],
    readiness_records: list[Mapping[str, Any]],
    field_query: Mapping[str, Any],
    gdcic_browser_readback: Mapping[str, Any],
    p13b_company_history: Mapping[str, Any],
    p13b_original_notice_backtrace: Mapping[str, Any],
    p13b_ygp_original_readback: Mapping[str, Any],
    p13b_overlap_triage_closeout: Mapping[str, Any],
    company_first_stage4_execution: Mapping[str, Any],
    design_survey_public_registry_readback: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    stage6_status: Mapping[str, Any],
    stage6_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    pressure_candidate_count = _int(pressure_summary.get("candidate_count"))
    candidate_count = max(
        pressure_candidate_count,
        len(project_rows),
        len(readiness_records),
        _distinct_count(field_records, "project_id"),
    )
    readiness_stage2_success_count = sum(
        1
        for record in readiness_records
        if str(record.get("stage2_detail_capture_state") or "").upper() in {"FETCHED", "CAPTURED", "DETAIL_CAPTURED", "READBACK_READY"}
    )
    row_stage2_success_count = sum(
        1
        for row in project_rows
        if str(row.get("stage2_detail_capture_state") or "").upper() in {"FETCHED", "CAPTURED", "DETAIL_CAPTURED", "READBACK_READY"}
    )
    stage2_success_count = max(readiness_stage2_success_count, row_stage2_success_count)
    readiness_stage3_success_count = sum(
        1
        for record in readiness_records
        if _stage3_parse_attempt_succeeded(record.get("stage3_field_parse_state"))
    )
    row_stage3_success_count = sum(
        1
        for row in project_rows
        if _stage3_parse_attempt_succeeded(row.get("stage3_field_parse_state"))
    )
    stage3_success_count = max(readiness_stage3_success_count, row_stage3_success_count)
    field_summary = _summary(field_query)
    gdcic_readback_summary = _summary(gdcic_browser_readback)
    p13b_summary = _summary(p13b_company_history)
    p13b_original_summary = _summary(p13b_original_notice_backtrace)
    p13b_ygp_summary = _summary(p13b_ygp_original_readback)
    p13b_overlap_closeout_summary = _summary(p13b_overlap_triage_closeout)
    company_first_summary = _summary(company_first_stage4_execution)
    design_registry_readback_summary = _summary(design_survey_public_registry_readback)
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
        "stage1_6_readiness_state_counts": dict(pressure_summary.get("stage1_6_readiness_state_counts") or {}),
        "stage1_6_bottleneck_stage_counts": dict(pressure_summary.get("stage1_6_bottleneck_stage_counts") or {}),
        "stage1_3_stability_summary": dict(pressure_summary.get("stage1_3_stability_summary") or {}),
        "stage1_3_long_tail_bucket_counts": dict(pressure_summary.get("stage1_3_long_tail_bucket_counts") or {}),
        "stage1_3_long_tail_signal_counts": dict(pressure_summary.get("stage1_3_long_tail_signal_counts") or {}),
        "stage1_3_identity_confirmation_state_counts": dict(
            pressure_summary.get("stage1_3_identity_confirmation_state_counts") or {}
        ),
        "stage4_matched_task_count": stage4_matched_count,
        "stage4_needs_browser_task_count": stage4_needs_browser_count,
        "stage5_review_count": stage5_review_count,
        "stage5_operational_review_bucket_counts": _counts(
            row.get("stage5_operational_review_bucket") for row in project_rows
        ),
        "stage5_operational_review_family_counts": _counts(
            family
            for row in project_rows
            for family in _as_list(row.get("stage5_operational_review_families"))
        ),
        "stage5_operational_signal_counts": _counts(
            signal
            for row in project_rows
            for signal in _as_list(row.get("stage5_operational_signal_flags"))
        ),
        "stage5_operational_review_queue_counts": _counts(
            queue
            for row in project_rows
            for queue in _as_list(row.get("stage5_operational_review_queues"))
        ),
        "stage5_operational_primary_track_counts": _counts(
            row.get("stage5_operational_primary_track") for row in project_rows
        ),
        "stage5_operational_priority_bucket_counts": _counts(
            row.get("stage5_operational_priority_bucket") for row in project_rows
        ),
        "stage5_operational_safety_boundary_counts": _counts(
            row.get("stage5_operational_safety_boundary") for row in project_rows
        ),
        "stage6_fact_ready_count": stage6_fact_ready_count,
        "stage6_limited_sellable_review_candidate_count": _int(
            stage6_summary.get("limited_sellable_review_candidate_count")
        ),
        "stage6_limited_sellable_review_candidate_state_counts": dict(
            stage6_summary.get("limited_sellable_review_candidate_state_counts") or {}
        ),
        "stage6_limited_sellable_review_public_source_chain_counts": dict(
            stage6_summary.get("limited_sellable_review_public_source_chain_counts") or {}
        ),
        "stage6_limited_sellable_review_stage4_bridge_backfill_state_counts": dict(
            stage6_summary.get("limited_sellable_review_stage4_bridge_backfill_state_counts") or {}
        ),
        "stage6_limited_sellable_review_gdcic_project_code_route_policy_counts": dict(
            stage6_summary.get("limited_sellable_review_gdcic_project_code_route_policy_counts") or {}
        ),
        "stage6_strong_lead_candidate_state_counts": dict(
            stage6_summary.get("strong_lead_candidate_state_counts") or {}
        ),
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
        "gdcic_authorized_readback_status": _gdcic_authorized_readback_status(
            gdcic_readback_summary,
            p13b_summary=p13b_summary,
            project_rows=project_rows,
        ),
        "p13b_public_source_readback_status": _p13b_public_source_readback_status(p13b_summary),
        "p13b_original_notice_readback_status": _p13b_original_notice_readback_status(p13b_original_summary),
        "p13b_ygp_original_readback_status": _p13b_ygp_original_readback_status(p13b_ygp_summary),
        "p13b_overlap_triage_closeout_status": _p13b_overlap_triage_closeout_status(
            p13b_overlap_closeout_summary
        ),
        "company_first_stage4_execution_status": _company_first_stage4_execution_status(
            company_first_summary,
            project_rows,
        ),
        "design_survey_public_registry_readback_status": _design_survey_public_registry_readback_status(
            design_registry_readback_summary,
            project_rows,
        ),
        "stage4_ygp_backfill_ready_project_count": sum(
            1 for row in project_rows if _int(row.get("p13b_ygp_stage4_backfill_ready_count")) > 0
        ),
        "stage4_ygp_backfill_ready_task_count": _int(
            p13b_overlap_closeout_summary.get("ygp_stage4_backfill_ready_count")
            or p13b_ygp_summary.get("stage4_ygp_backfill_state_counts", {}).get("YGP_STAGE4_BACKFILL_READY")
        ),
        "stage4_ygp_release_adapter_task_count": _int(
            p13b_overlap_closeout_summary.get("ygp_stage4_release_adapter_task_count")
        ),
        "stage4_ygp_gdcic_route_allowed_count": _int(
            p13b_overlap_closeout_summary.get("ygp_stage4_gdcic_route_allowed_count")
            or p13b_ygp_summary.get("stage4_ygp_gdcic_route_allowed_count")
        ),
        "stage4_project_code_backfill_state_counts": _counts(
            row.get("stage4_project_code_backfill_state") for row in project_rows
        ),
        "stage4_project_code_backfill_gap_detail_counts": _counts(
            row.get("stage4_project_code_backfill_gap_detail") for row in project_rows
        ),
        "stage4_public_identifier_backfill_source_counts": _multi_value_counts(
            row.get("stage4_public_identifier_backfill_source") for row in project_rows
        ),
        "stage4_gdcic_project_code_route_policy_counts": _counts(
            row.get("stage4_gdcic_project_code_route_policy") for row in project_rows
        ),
        "stage4_public_identifier_backfill_project_count": sum(
            1
            for row in project_rows
            if row.get("stage4_project_code_backfill_state")
            in {
                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
            }
        ),
        "stage4_gdcic_project_code_route_ready_project_count": sum(
            1 for row in project_rows if row.get("stage4_project_code_backfill_state") == "GDCIC_PROJECT_CODE_ROUTE_READY"
        ),
        "stage4_gdcic_route_blocked_by_policy_project_count": sum(
            1
            for row in project_rows
            if row.get("stage4_project_code_backfill_state")
            in {
                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
            }
            and not bool(row.get("stage4_gdcic_project_code_route_allowed"))
        ),
        "stage4_public_source_readback_state_counts": _counts(
            row.get("p13b_public_source_readback_state") for row in project_rows
        ),
        "stage4_original_notice_readback_state_counts": _counts(
            row.get("p13b_original_notice_readback_state") for row in project_rows
        ),
        "stage4_ygp_original_readback_state_counts": _counts(
            row.get("p13b_ygp_original_readback_state") for row in project_rows
        ),
        "stage4_public_readback_outcome_counts": _stage4_public_readback_outcome_counts(project_rows),
        "stage4_public_readback_channel_outcome_counts": _stage4_public_readback_channel_outcome_counts(project_rows),
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
    p13b_overlap_closeout_signal: Mapping[str, Any],
    company_first_stage4_execution_signal: Mapping[str, Any],
    design_survey_public_registry_readback_signal: Mapping[str, Any],
) -> dict[str, Any]:
    adapter_counts = _counts(record.get("adapter_result_state") for record in field_records)
    grade_counts = _counts(
        _field_record_downstream_grade(record) for record in field_records
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
        if stage6_strong_lead_state and stage6_strong_lead_state != "NOT_READY"
        else "STRONG_LEAD_REVIEW_CANDIDATE" if has_official_b_or_c else "NOT_READY"
    )
    limited_sellable_review_candidate_state = (
        stage6_limited_review_state
        if stage6_limited_review_state and stage6_limited_review_state != "NOT_READY"
        else "REVIEW_CANDIDATE" if has_official_b_or_c and not stage7_allowed else "NOT_READY"
    )
    stage5_operational_review = _stage5_operational_review(
        readiness_record=readiness_record,
        stage6_record=stage6_record,
        field_records=field_records,
        p13b_project_signal=p13b_project_signal,
        p13b_original_notice_signal=p13b_original_notice_signal,
        p13b_ygp_signal=p13b_ygp_signal,
        p13b_overlap_closeout_signal=p13b_overlap_closeout_signal,
        company_first_stage4_execution_signal=company_first_stage4_execution_signal,
        design_survey_public_registry_readback_signal=design_survey_public_registry_readback_signal,
        adapter_counts=adapter_counts,
        combined_grade_counts=combined_grade_counts,
        has_official_b_or_c=has_official_b_or_c,
    )
    project_code_backfill_state = _stage4_project_code_backfill_state(
        readiness_record=readiness_record,
        p13b_project_signal=p13b_project_signal,
        p13b_ygp_signal=p13b_ygp_signal,
        p13b_overlap_closeout_signal=p13b_overlap_closeout_signal,
    )
    project_code_backfill_gap_detail = _stage4_project_code_backfill_gap_detail(
        project_code_backfill_state=project_code_backfill_state,
        p13b_project_signal=p13b_project_signal,
        p13b_original_notice_signal=p13b_original_notice_signal,
        p13b_overlap_closeout_signal=p13b_overlap_closeout_signal,
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
        "p13b_bid_show_original_notice_url_count": _int(
            p13b_project_signal.get("bid_show_original_notice_url_count")
        ),
        "p13b_bid_show_responsible_person_present_count": _int(
            p13b_project_signal.get("bid_show_responsible_person_present_count")
        ),
        "p13b_overlap_signal_state_counts": dict(p13b_project_signal.get("overlap_signal_state_counts") or {}),
        "p13b_local_authority_source_task_count": _int(
            p13b_project_signal.get("local_authority_source_task_count")
        ),
        "p13b_local_authority_source_task_state_counts": dict(
            p13b_project_signal.get("local_authority_source_task_state_counts") or {}
        ),
        "p13b_local_authority_readback_state_counts": dict(
            p13b_project_signal.get("local_authority_readback_state_counts") or {}
        ),
        "p13b_local_authority_executed_readback_state_counts": dict(
            p13b_project_signal.get("local_authority_executed_readback_state_counts") or {}
        ),
        "p13b_local_authority_source_readback_count": _int(
            p13b_project_signal.get("local_authority_source_readback_count")
        ),
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
        "p13b_overlap_ygp_project_code_variants": _as_list(
            p13b_overlap_closeout_signal.get("ygp_project_code_variants")
        ),
        "p13b_overlap_ygp_biz_code_variants": _as_list(
            p13b_overlap_closeout_signal.get("ygp_biz_code_variants")
        ),
        "p13b_overlap_ygp_site_code_variants": _as_list(
            p13b_overlap_closeout_signal.get("ygp_site_code_variants")
        ),
        "p13b_overlap_ygp_notice_id_variants": _as_list(
            p13b_overlap_closeout_signal.get("ygp_notice_id_variants")
        ),
        "p13b_overlap_triage_state": str(
            p13b_overlap_closeout_signal.get("p13b_overlap_triage_state") or ""
        ),
        "p13b_ygp_stage4_backfill_ready_count": _int(
            p13b_ygp_signal.get("ygp_stage4_backfill_ready_count")
            or p13b_overlap_closeout_signal.get("ygp_stage4_backfill_ready_count")
        ),
        "p13b_ygp_stage4_backfill_state_counts": dict(
            p13b_ygp_signal.get("ygp_stage4_backfill_state_counts")
            or p13b_overlap_closeout_signal.get("ygp_stage4_backfill_state_counts")
            or {}
        ),
        "p13b_ygp_stage4_release_adapter_task_count": _int(
            p13b_overlap_closeout_signal.get("ygp_stage4_release_adapter_task_count")
        ),
        "p13b_ygp_gdcic_route_allowed_count": _int(
            p13b_ygp_signal.get("ygp_stage4_gdcic_route_allowed_count")
            or p13b_overlap_closeout_signal.get("ygp_stage4_gdcic_route_allowed_count")
        ),
        "p13b_ygp_stage4_backfill_recommended_next_actions": _as_list(
            p13b_ygp_signal.get("ygp_stage4_backfill_recommended_next_actions")
            or p13b_overlap_closeout_signal.get("ygp_stage4_backfill_recommended_next_actions")
        ),
        "company_first_stage4_execution_state": str(
            company_first_stage4_execution_signal.get("stage4_execution_state") or ""
        ),
        "company_first_identity_resolution_state": str(
            company_first_stage4_execution_signal.get("identity_resolution_state") or ""
        ),
        "company_first_supplement_after_execution_state": str(
            company_first_stage4_execution_signal.get("supplement_after_execution_state") or ""
        ),
        "company_first_stage4_readiness_state": str(
            company_first_stage4_execution_signal.get("stage4_readiness_state") or ""
        ),
        "company_first_provider_job_count": _int(company_first_stage4_execution_signal.get("provider_job_count")),
        "company_first_stage4_input_count": _int(company_first_stage4_execution_signal.get("stage4_input_count")),
        "company_first_flow_08_targeted_parse_required": bool(
            company_first_stage4_execution_signal.get("flow_08_targeted_parse_required")
        ),
        "company_first_next_actions": _as_list(company_first_stage4_execution_signal.get("next_actions")),
        "design_survey_public_registry_readback_state": str(
            design_survey_public_registry_readback_signal.get("readback_state") or ""
        ),
        "design_survey_public_registry_verification_result": str(
            design_survey_public_registry_readback_signal.get("verification_result") or ""
        ),
        "design_survey_public_registry_provider_result_state": str(
            design_survey_public_registry_readback_signal.get("provider_result_state") or ""
        ),
        "design_survey_public_registry_readback_record_count": _int(
            design_survey_public_registry_readback_signal.get("readback_record_count")
        ),
        "stage4_project_code_backfill_state": project_code_backfill_state,
        "stage4_project_code_backfill_gap_detail": project_code_backfill_gap_detail,
        "stage4_public_identifier_backfill_source": _stage4_public_identifier_backfill_source(
            p13b_project_signal=p13b_project_signal,
            p13b_ygp_signal=p13b_ygp_signal,
            p13b_overlap_closeout_signal=p13b_overlap_closeout_signal,
        ),
        "stage4_gdcic_project_code_route_allowed": project_code_backfill_state == "GDCIC_PROJECT_CODE_ROUTE_READY",
        "stage4_gdcic_project_code_route_policy": _stage4_gdcic_project_code_route_policy(project_code_backfill_state),
        "operator_next_actions": [str(item) for item in _as_list(stage6_record.get("release_field_query_operator_next_actions")) if str(item or "").strip()],
        "blocking_bucket": _project_blocking_bucket(
            readiness_record,
            stage6_record,
            field_records,
            stage5_operational_review.get("stage5_operational_review_bucket"),
        ),
        "strong_lead_candidate_state": strong_lead_candidate_state,
        "limited_sellable_review_candidate_state": limited_sellable_review_candidate_state,
        "limited_sellable_review_reason": str(
            stage6_record.get("limited_sellable_review_reason")
            or (
                "official_b_or_c_readback_requires_manual_stage5_stage6_review"
                if limited_sellable_review_candidate_state == "REVIEW_CANDIDATE"
                else ""
            )
        ),
        "limited_sellable_review_official_readback_task_count": _int(
            stage6_record.get("limited_sellable_review_official_readback_task_count")
        ),
        "limited_sellable_review_evidence_grade_counts": dict(
            stage6_record.get("limited_sellable_review_evidence_grade_counts") or {}
        ),
        "limited_sellable_review_gap_grade_counts": dict(
            stage6_record.get("limited_sellable_review_gap_grade_counts") or {}
        ),
        "limited_sellable_review_required_actions": _as_list(
            stage6_record.get("limited_sellable_review_required_actions")
        ),
        "limited_sellable_review_official_readback_records": _as_list(
            stage6_record.get("limited_sellable_review_official_readback_records")
        ),
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
    p13b_overlap_triage_closeout: Mapping[str, Any],
    company_first_stage4_execution: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    stage6_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    field_summary = _summary(field_query)
    gdcic_readback_summary = _summary(gdcic_browser_readback)
    p13b_summary = _summary(p13b_company_history)
    p13b_original_summary = _summary(p13b_original_notice_backtrace)
    p13b_ygp_summary = _summary(p13b_ygp_original_readback)
    p13b_overlap_closeout_summary = _summary(p13b_overlap_triage_closeout)
    blocker_taxonomy_counts = dict(field_summary.get("blocker_taxonomy_counts") or {})
    if not blocker_taxonomy_counts:
        blocker_taxonomy_counts = _flatten_counts(field_records, "blocker_taxonomy")
    active_fail_closed_reason_counts = _active_fail_closed_reason_counts(readiness_records, project_rows)
    resolved_fail_closed_reason_counts = _resolved_fail_closed_reason_counts(readiness_records, project_rows)
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
        "active_fail_closed_reason_counts": active_fail_closed_reason_counts,
        "resolved_by_public_readback_fail_closed_reason_counts": resolved_fail_closed_reason_counts,
        "gdcic_project_code_candidates_present_but_not_matched_active_count": _int(
            active_fail_closed_reason_counts.get("gdcic_project_code_candidates_present_but_not_matched")
        ),
        "gdcic_project_code_candidates_present_but_not_matched_resolved_by_public_readback_count": _int(
            resolved_fail_closed_reason_counts.get("gdcic_project_code_candidates_present_but_not_matched")
        ),
        "gdcic_project_code_not_resolved_active_count": _int(
            active_fail_closed_reason_counts.get("gdcic_project_code_not_resolved")
        ),
        "gdcic_project_code_not_resolved_resolved_by_public_readback_count": _int(
            resolved_fail_closed_reason_counts.get("gdcic_project_code_not_resolved")
        ),
        "field_blocker_taxonomy_counts": blocker_taxonomy_counts,
        "operator_next_action_counts": dict(field_summary.get("operator_next_action_counts") or {}),
        "gdcic_authorized_readback_blocker": _gdcic_authorized_readback_status(gdcic_readback_summary),
        "p13b_public_source_readback_blocker": _p13b_public_source_readback_status(p13b_summary),
        "p13b_original_notice_readback_blocker": _p13b_original_notice_readback_status(p13b_original_summary),
        "p13b_ygp_original_readback_blocker": _p13b_ygp_original_readback_status(p13b_ygp_summary),
        "p13b_overlap_triage_closeout_blocker": _p13b_overlap_triage_closeout_status(
            p13b_overlap_closeout_summary
        ),
        "stage5_operational_review_bucket_counts": _counts(
            row.get("stage5_operational_review_bucket") for row in project_rows
        ),
        "stage5_operational_review_family_counts": _counts(
            family
            for row in project_rows
            for family in _as_list(row.get("stage5_operational_review_families"))
        ),
        "stage5_operational_signal_counts": _counts(
            signal
            for row in project_rows
            for signal in _as_list(row.get("stage5_operational_signal_flags"))
        ),
        "stage5_operational_review_queue_counts": _counts(
            queue
            for row in project_rows
            for queue in _as_list(row.get("stage5_operational_review_queues"))
        ),
        "company_first_stage4_execution_state_counts": _counts(
            row.get("company_first_stage4_execution_state") for row in project_rows
        ),
        "company_first_supplement_after_execution_state_counts": _counts(
            row.get("company_first_supplement_after_execution_state") for row in project_rows
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
    p13b_overlap_closeout = blocker_summary.get("p13b_overlap_triage_closeout_blocker")
    if isinstance(p13b_overlap_closeout, Mapping) and _int(p13b_overlap_closeout.get("ygp_stage4_backfill_ready_count")):
        actions.append("feed_ygp_stage4_backfill_candidates_to_p13b_or_stage4_bridge_without_gdcic_route_claim")
    if _int(blocker_summary.get("field_missing_or_not_found_task_count")):
        actions.append("extend_stage4_project_code_and_source_readback_before_claiming_clearance")
    if _int(blocker_summary.get("stage4_matched_without_stage7_saleable_project_count")):
        actions.append("review_b_or_c_official_readback_for_limited_sellable_internal_package")
    if _int(counts.get("stage7_sellable_count")) == 0 and _int(counts.get("limited_sellable_review_candidate_count")) == 0:
        actions.append("do_not_expand_stage8_stage9_until_stage4_sellable_inventory_exists")
    return _dedupe(actions)


def _active_fail_closed_reason_counts(
    readiness_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, int]:
    return _classified_fail_closed_reason_counts(
        readiness_records,
        project_rows,
        want_resolved=False,
    )


def _resolved_fail_closed_reason_counts(
    readiness_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, int]:
    return _classified_fail_closed_reason_counts(
        readiness_records,
        project_rows,
        want_resolved=True,
    )


def _classified_fail_closed_reason_counts(
    readiness_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
    *,
    want_resolved: bool,
) -> dict[str, int]:
    rows_by_project = {
        str(row.get("project_id") or "").strip(): row
        for row in project_rows
        if str(row.get("project_id") or "").strip()
    }
    counts: dict[str, int] = {}
    for record in readiness_records:
        project_id = str(record.get("project_id") or "").strip()
        project_row = rows_by_project.get(project_id, {})
        for reason in _as_list(record.get("fail_closed_reasons")):
            reason_text = str(reason or "").strip()
            if not reason_text:
                continue
            resolved = _fail_closed_reason_resolved_by_public_readback(reason_text, project_row)
            if resolved != want_resolved:
                continue
            counts[reason_text] = counts.get(reason_text, 0) + 1
    return counts


def _fail_closed_reason_resolved_by_public_readback(
    reason: str,
    project_row: Mapping[str, Any],
) -> bool:
    if reason not in {
        "gdcic_project_code_candidates_present_but_not_matched",
        "gdcic_project_code_not_resolved",
        "gdcic_project_code_not_resolved_after_project_name_candidate_queries",
    }:
        return False
    if project_row.get("limited_sellable_review_candidate_state") != "REVIEW_CANDIDATE":
        return False
    grade_counts = dict(project_row.get("stage4_downstream_abcd_grade_counts") or {})
    return any(str(key).startswith(("B_", "C_")) and _int(value) > 0 for key, value in grade_counts.items())


def _gdcic_authorized_readback_status(
    summary: Mapping[str, Any],
    *,
    p13b_summary: Mapping[str, Any] | None = None,
    project_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    alternative_count = _gdcic_alternative_public_source_route_count(
        p13b_summary=p13b_summary or {},
        project_rows=project_rows or [],
    )
    alternative_target_type_counts = _gdcic_alternative_public_source_route_target_type_counts(
        p13b_summary=p13b_summary or {},
        project_rows=project_rows or [],
    )
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "authorized_session_input_state": "",
            "authorized_session_input_ready": False,
            "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED" if alternative_count else "",
            "target_real_readback_success_count": 0,
            "target_project_manager_change_real_readback_success_count": 0,
            "real_readback_success_not_faked": True,
            "real_readback_success_proof_state": "NO_REAL_AUTHORIZED_READBACK_SUCCESS",
            "operator_next_action": "build_gdcic_browser_authorized_readback_artifact_then_rerun_scoreboard",
            "alternative_operator_next_action": (
                "continue_alternative_public_source_release_evidence_readback_chain"
                if alternative_count
                else ""
            ),
            "authorization_blocker_is_not_terminal_if_alternative_public_sources_exist": alternative_count > 0,
            "alternative_public_source_route_count": alternative_count,
            "alternative_public_source_route_target_type_counts": alternative_target_type_counts,
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
        }
    authorized_session_ready = bool(summary.get("authorized_session_input_ready"))
    authorized_session_input_state = str(summary.get("authorized_session_input_state") or "")
    raw_overall_state = str(summary.get("gdcic_authorized_session_overall_state") or "")
    overall_state = raw_overall_state
    if (
        not authorized_session_ready
        and authorized_session_input_state == "NO_AUTHORIZED_SESSION_INPUT"
        and raw_overall_state in {"", "NOT_ATTEMPTED_PLAN_ONLY", "NO_BROWSER_READBACK_RECORDS"}
    ):
        overall_state = "LOGIN_OR_SSO_REQUIRED"
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
    explicit_alternative_count = _int(summary.get("alternative_public_source_route_count"))
    alternative_count = max(explicit_alternative_count, alternative_count)
    if not operator_action and (not authorized_session_ready or overall_state == "LOGIN_OR_SSO_REQUIRED"):
        operator_action = "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"
    if not alternative_operator_action and alternative_count:
        alternative_operator_action = "continue_alternative_public_source_release_evidence_readback_chain"
    explicit_target_type_counts = _counts(
        record.get("release_evidence_target_type")
        for record in _as_list(summary.get("alternative_public_source_route_records"))
        if isinstance(record, Mapping)
    )
    if explicit_target_type_counts:
        target_type_counts = explicit_target_type_counts
    else:
        target_type_counts = alternative_target_type_counts
    return {
        "artifact_state": "BUILT",
        "authorized_session_input_state": authorized_session_input_state,
        "authorized_session_input_ready": authorized_session_ready,
        "authorization_readiness_state": overall_state,
        "authorization_readiness_state_raw": raw_overall_state,
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
        )
        or alternative_count > 0,
        "alternative_public_source_route_count": alternative_count,
        "alternative_public_source_route_target_type_counts": target_type_counts,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _gdcic_alternative_public_source_route_count(
    *,
    p13b_summary: Mapping[str, Any],
    project_rows: list[Mapping[str, Any]],
) -> int:
    summary_count = _int(p13b_summary.get("gdcic_alternative_public_source_route_count"))
    row_count = sum(_gdcic_alternative_public_source_route_count_for_row(row) for row in project_rows)
    return max(summary_count, row_count)


def _gdcic_alternative_public_source_route_count_for_row(row: Mapping[str, Any]) -> int:
    count = 0
    count += _int(row.get("p13b_bid_show_original_notice_url_count"))
    count += _int(row.get("p13b_local_authority_source_task_count"))
    count += _int(row.get("p13b_ygp_stage4_release_adapter_task_count")) or _int(
        row.get("p13b_ygp_stage4_backfill_ready_count")
    )
    if str(row.get("p13b_original_notice_readback_state") or "").strip():
        count += 1
    if _int(row.get("design_survey_public_registry_readback_record_count")):
        count += 1
    return count


def _gdcic_alternative_public_source_route_target_type_counts(
    *,
    p13b_summary: Mapping[str, Any],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    _bump(counts, "data_ggzy_bid_show", _int(p13b_summary.get("bid_show_record_count")))
    _bump(counts, "local_authority_public_source", _int(p13b_summary.get("local_authority_source_task_count")))
    _bump(counts, "original_notice_readback", _int(p13b_summary.get("original_notice_backtrace_required_count")))
    row_counts: dict[str, int] = {}
    for row in project_rows:
        _bump(row_counts, "data_ggzy_bid_show", _int(row.get("p13b_bid_show_original_notice_url_count")))
        _bump(row_counts, "local_authority_public_source", _int(row.get("p13b_local_authority_source_task_count")))
        _bump(
            row_counts,
            "ygp_original_readback",
            _int(row.get("p13b_ygp_stage4_release_adapter_task_count"))
            or _int(row.get("p13b_ygp_stage4_backfill_ready_count")),
        )
        if str(row.get("p13b_original_notice_readback_state") or "").strip():
            _bump(row_counts, "original_notice_readback", 1)
        if _int(row.get("design_survey_public_registry_readback_record_count")):
            _bump(row_counts, "design_survey_public_registry", 1)
    for key, value in row_counts.items():
        counts[key] = max(_int(counts.get(key)), _int(value))
    return counts


def _bump(counts: dict[str, int], key: str, amount: int) -> None:
    if amount <= 0:
        return
    counts[key] = counts.get(key, 0) + amount


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
            "ygp_readback_ready_count": 0,
            "browser_readback_ready_count": 0,
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
        "ygp_readback_ready_count": _int(summary.get("ygp_readback_ready_count")),
        "browser_readback_ready_count": _int(summary.get("browser_readback_ready_count")),
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


def _p13b_overlap_triage_closeout_status(summary: Mapping[str, Any]) -> dict[str, Any]:
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "p13b_overlap_triage_closeout_state": "",
            "project_count": 0,
            "ygp_stage4_backfill_candidate_count": 0,
            "ygp_stage4_backfill_ready_count": 0,
            "ygp_stage4_gdcic_route_allowed_count": 0,
            "project_state_counts": {},
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return {
        "artifact_state": "BUILT",
        "p13b_overlap_triage_closeout_state": str(summary.get("p13b_overlap_triage_closeout_state") or ""),
        "project_count": _int(summary.get("project_count")),
        "ygp_stage4_backfill_candidate_count": _int(summary.get("ygp_stage4_backfill_candidate_count")),
        "ygp_stage4_backfill_ready_count": _int(summary.get("ygp_stage4_backfill_ready_count")),
        "ygp_stage4_backfill_state_counts": dict(summary.get("ygp_stage4_backfill_state_counts") or {}),
        "ygp_stage4_release_adapter_task_count": _int(summary.get("ygp_stage4_release_adapter_task_count")),
        "ygp_stage4_release_adapter_task_state_counts": dict(
            summary.get("ygp_stage4_release_adapter_task_state_counts") or {}
        ),
        "ygp_stage4_gdcic_route_allowed_count": _int(summary.get("ygp_stage4_gdcic_route_allowed_count")),
        "project_state_counts": dict(summary.get("project_state_counts") or {}),
        "original_notice_state_counts": dict(summary.get("original_notice_state_counts") or {}),
        "original_notice_backtrace_match_state_counts": dict(
            summary.get("original_notice_backtrace_match_state_counts") or {}
        ),
        "release_evidence_trigger_count": _int(summary.get("release_evidence_trigger_count")),
        "query_miss_is_not_clearance": bool(summary.get("query_miss_is_not_clearance", True)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _company_first_stage4_execution_status(
    summary: Mapping[str, Any],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "project_count": 0,
            "job_count": 0,
            "provider_tasks_ready_project_count": 0,
            "target_fields_missing_project_count": 0,
            "certificate_resolved_project_count": 0,
            "flow_08_targeted_parse_required_project_count": 0,
            "design_survey_public_registry_fallback_required_project_count": 0,
            "stage4_execution_state_counts": {},
            "supplement_after_execution_state_counts": {},
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    supplement_counts = dict(summary.get("supplement_after_execution_state_counts") or {})
    execution_counts = dict(summary.get("stage4_execution_state_counts") or {})
    return {
        "artifact_state": "BUILT",
        "project_count": _int(summary.get("project_count")),
        "job_count": _int(summary.get("job_count")),
        "provider_tasks_ready_project_count": _int(supplement_counts.get("COMPANY_FIRST_PROVIDER_TASKS_READY")),
        "target_fields_missing_project_count": _int(supplement_counts.get("COMPANY_FIRST_TARGET_FIELDS_MISSING")),
        "certificate_resolved_project_count": _int(supplement_counts.get("COMPANY_FIRST_CERTIFICATE_RESOLVED")),
        "flow_08_targeted_parse_required_project_count": _int(
            supplement_counts.get("FLOW_08_TARGETED_PARSE_REQUIRED")
        ),
        "design_survey_public_registry_fallback_required_project_count": _int(
            supplement_counts.get("DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED")
        ),
        "stage4_input_count": _int(summary.get("stage4_input_count")),
        "flow_08_targeted_parse_required_count": _int(summary.get("flow_08_targeted_parse_required_count")),
        "stage4_execution_state_counts": execution_counts,
        "identity_resolution_state_counts": dict(summary.get("identity_resolution_state_counts") or {}),
        "supplement_after_execution_state_counts": supplement_counts,
        "projected_stage5_queue_counts": _counts(
            queue
            for row in project_rows
            for queue in _as_list(row.get("stage5_operational_review_queues"))
            if str(queue).startswith("COMPANY_FIRST_")
            or str(queue) == "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW"
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _design_survey_public_registry_readback_status(
    summary: Mapping[str, Any],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not summary:
        return {
            "artifact_state": "MISSING_OR_NOT_BUILT",
            "readback_record_count": 0,
            "project_count": 0,
            "provider_result_state_counts": {},
            "readback_state_counts": {},
            "verification_result_counts": {},
            "matched_count": 0,
            "review_required_count": 0,
            "projected_stage5_queue_counts": {},
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return {
        "artifact_state": "BUILT",
        "readback_record_count": _int(summary.get("readback_record_count")),
        "project_count": _int(summary.get("project_count")),
        "provider_result_state_counts": dict(summary.get("provider_result_state_counts") or {}),
        "readback_state_counts": dict(summary.get("readback_state_counts") or {}),
        "verification_result_counts": dict(summary.get("verification_result_counts") or {}),
        "matched_count": _int(summary.get("matched_count")),
        "review_required_count": _int(summary.get("review_required_count")),
        "projected_stage5_queue_counts": _counts(
            queue
            for row in project_rows
            for queue in _as_list(row.get("stage5_operational_review_queues"))
            if str(queue).startswith("DESIGN_SURVEY_PUBLIC_REGISTRY_")
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_blocking_bucket(
    readiness_record: Mapping[str, Any],
    stage6_record: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    stage5_operational_review_bucket: object = None,
) -> str:
    if _has_grade(stage6_record, ("B_", "C_")) or any(
        _field_record_downstream_grade(record).startswith(("B_", "C_")) for record in field_records
    ):
        return "stage4_matched_needs_manual_limited_sellable_review"
    stage5_bucket = str(stage5_operational_review_bucket or "")
    stage5_blocking_bucket = {
        "STRONG_LEAD_INTERNAL_REVIEW": "stage4_matched_needs_manual_limited_sellable_review",
        "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW": "weak_lead_official_signal_review",
        "ORIGINAL_NOTICE_BLOCKED_REVIEW": "original_notice_blocked_review",
        "ORIGINAL_NOTICE_NOT_FOUND_REVIEW": "original_notice_not_found_review",
        "ORIGINAL_NOTICE_BACKTRACE_REQUIRED_REVIEW": "original_notice_backtrace_required_review",
        "PUBLIC_SOURCE_BLOCKED_REVIEW": "public_source_blocked_review",
        "PUBLIC_SOURCE_NOT_FOUND_REVIEW": "public_source_not_found_review",
        "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW": "authorization_or_browser_blocked_with_source_not_found",
        "AUTHORIZATION_BLOCKED_REVIEW": "authorization_or_browser_blocked",
        "SOURCE_NOT_FOUND_REVIEW": "source_not_found_review",
        "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": "responsible_person_certificate_gap_review",
        "RESPONSIBLE_ROLE_GAP_REVIEW": "responsible_role_gap_review",
        "PROJECT_CODE_BACKFILL_GAP_REVIEW": "project_code_backfill_gap_review",
        "FIELD_AMBIGUITY_REVIEW": "field_ambiguity_review",
        "EVIDENCE_INSUFFICIENT_REVIEW": "evidence_insufficient_review",
        "YGP_READBACK_READY_REVIEW": "ygp_readback_ready_review",
        "YGP_STAGE4_BACKFILL_READY_REVIEW": "ygp_stage4_backfill_ready_review",
        "YGP_READBACK_BLOCKED_REVIEW": "ygp_readback_blocked_review",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW": "design_survey_public_registry_fallback_review",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_MATCHED_REVIEW": "design_survey_public_registry_matched_review",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW": "design_survey_public_registry_not_found_review",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_BLOCKED_REVIEW": "design_survey_public_registry_blocked_review",
        "LOCAL_AUTHORITY_SOURCE_PLAN_REVIEW": "local_authority_source_plan_review",
        "LOCAL_AUTHORITY_MATCHED_REVIEW": "local_authority_matched_review",
        "LOCAL_AUTHORITY_NOT_FOUND_REVIEW": "local_authority_not_found_review",
        "LOCAL_AUTHORITY_BLOCKED_REVIEW": "local_authority_blocked_review",
    }.get(stage5_bucket)
    if stage5_blocking_bucket:
        return stage5_blocking_bucket
    has_needs_browser = any(str(record.get("adapter_result_state") or "") == "NEEDS_BROWSER" for record in field_records)
    has_not_found = any(str(record.get("adapter_result_state") or "") == "NOT_FOUND" for record in field_records)
    if has_needs_browser and has_not_found:
        return "authorization_or_browser_blocked_with_source_not_found"
    if has_needs_browser:
        return "authorization_or_browser_blocked"
    if has_not_found:
        return "official_source_not_found_or_field_missing"
    if str(readiness_record.get("stage5_rule_gate_status") or "").upper() == "REVIEW":
        return "stage5_rule_review"
    if str(readiness_record.get("stage3_field_parse_state") or "").upper() and not str(readiness_record.get("stage3_field_parse_state") or "").upper().startswith("PARSED"):
        return "stage3_parse_gap"
    return "unclassified_review_required"


def _stage4_project_code_backfill_state(
    *,
    readiness_record: Mapping[str, Any],
    p13b_project_signal: Mapping[str, Any],
    p13b_ygp_signal: Mapping[str, Any],
    p13b_overlap_closeout_signal: Mapping[str, Any],
) -> str:
    if _int(p13b_overlap_closeout_signal.get("ygp_stage4_gdcic_route_allowed_count")) > 0:
        return "GDCIC_PROJECT_CODE_ROUTE_READY"
    if (
        _as_list(p13b_ygp_signal.get("ygp_project_code_variants"))
        or _as_list(p13b_overlap_closeout_signal.get("ygp_project_code_variants"))
        or _as_list(p13b_ygp_signal.get("ygp_biz_code_variants"))
        or _as_list(p13b_overlap_closeout_signal.get("ygp_biz_code_variants"))
        or _as_list(p13b_ygp_signal.get("ygp_site_code_variants"))
        or _as_list(p13b_overlap_closeout_signal.get("ygp_site_code_variants"))
        or _as_list(p13b_ygp_signal.get("ygp_notice_id_variants"))
        or _as_list(p13b_overlap_closeout_signal.get("ygp_notice_id_variants"))
        or _int(p13b_ygp_signal.get("ygp_stage4_backfill_ready_count")) > 0
        or _int(p13b_overlap_closeout_signal.get("ygp_stage4_backfill_ready_count")) > 0
        or _int(p13b_overlap_closeout_signal.get("ygp_stage4_release_adapter_task_count")) > 0
    ):
        return "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
    if _int(p13b_project_signal.get("bid_show_original_notice_url_count")) > 0:
        return "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
    fail_closed_reasons = {str(item) for item in _as_list(readiness_record.get("fail_closed_reasons"))}
    if fail_closed_reasons & {
        "gdcic_project_code_not_resolved",
        "gdcic_project_code_not_resolved_after_project_name_candidate_queries",
        "gdcic_project_code_candidates_present_but_not_matched",
    }:
        return "MISSING_PROJECT_CODE_BACKFILL_INPUT"
    return "NOT_FLAGGED_FOR_PROJECT_CODE_BACKFILL"


def _stage4_project_code_backfill_gap_detail(
    *,
    project_code_backfill_state: str,
    p13b_project_signal: Mapping[str, Any],
    p13b_original_notice_signal: Mapping[str, Any],
    p13b_overlap_closeout_signal: Mapping[str, Any],
) -> str:
    if project_code_backfill_state != "MISSING_PROJECT_CODE_BACKFILL_INPUT":
        return ""
    p13b_state = str(p13b_project_signal.get("p13b_public_source_readback_state") or "")
    original_notice_state = str(p13b_original_notice_signal.get("p13b_original_notice_readback_state") or "")
    overlap_state = str(p13b_overlap_closeout_signal.get("p13b_overlap_triage_state") or "")
    if p13b_state == "PUBLIC_SOURCE_BLOCKED_REVIEW" or _int(p13b_project_signal.get("source_blocked_count")) > 0:
        return "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"
    if original_notice_state == "BLOCKED" or overlap_state == "SOURCE_LIMIT_DEFERRED":
        return "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED"
    if original_notice_state == "NOT_FOUND":
        return "ORIGINAL_NOTICE_NOT_FOUND_FALLBACK_LOCAL_AUTHORITY_REQUIRED"
    if p13b_state == "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW" or overlap_state == "NO_OVERLAP_SIGNAL_REVIEW":
        return "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED"
    if p13b_state == "PUBLIC_SOURCE_READBACK_PENDING_OR_NOT_RUN":
        return "PUBLIC_SOURCE_READBACK_NOT_RUN_REQUIRED"
    return "GDCIC_IDENTIFIER_UNRESOLVED_AFTER_PUBLIC_BACKFILL_REQUIRED"


def _stage4_public_identifier_backfill_source(
    *,
    p13b_project_signal: Mapping[str, Any],
    p13b_ygp_signal: Mapping[str, Any],
    p13b_overlap_closeout_signal: Mapping[str, Any],
) -> str:
    sources: list[str] = []
    if _int(p13b_project_signal.get("bid_show_original_notice_url_count")) > 0:
        sources.append("DATA_GGZY_BID_SHOW_ORIGINAL_URL")
    if _int(p13b_project_signal.get("bid_show_responsible_person_present_count")) > 0:
        sources.append("DATA_GGZY_BID_SHOW_RESPONSIBLE_PERSON")
    if _as_list(p13b_ygp_signal.get("ygp_project_code_variants")) or _as_list(
        p13b_overlap_closeout_signal.get("ygp_project_code_variants")
    ):
        sources.append("YGP_PROJECT_CODE")
    if _as_list(p13b_ygp_signal.get("ygp_biz_code_variants")) or _as_list(
        p13b_overlap_closeout_signal.get("ygp_biz_code_variants")
    ):
        sources.append("YGP_BIZ_CODE")
    if _as_list(p13b_ygp_signal.get("ygp_site_code_variants")) or _as_list(
        p13b_overlap_closeout_signal.get("ygp_site_code_variants")
    ):
        sources.append("YGP_SITE_CODE")
    if _as_list(p13b_ygp_signal.get("ygp_notice_id_variants")) or _as_list(
        p13b_overlap_closeout_signal.get("ygp_notice_id_variants")
    ):
        sources.append("YGP_NOTICE_ID")
    if (
        _int(p13b_ygp_signal.get("ygp_stage4_backfill_ready_count")) > 0
        or _int(p13b_overlap_closeout_signal.get("ygp_stage4_backfill_ready_count")) > 0
    ):
        sources.append("P13B_YGP_STAGE4_BACKFILL")
    return "|".join(_dedupe(sources))


def _stage4_gdcic_project_code_route_policy(project_code_backfill_state: str) -> str:
    if project_code_backfill_state == "GDCIC_PROJECT_CODE_ROUTE_READY":
        return "ONLY_EXPLICIT_PROVINCIAL_OR_URL_PROJECT_CODE_ALLOWED"
    if project_code_backfill_state == "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY":
        return "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE"
    if project_code_backfill_state == "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY":
        return "DATA_GGZY_BID_SHOW_ORIGINAL_URL_NOT_SENT_TO_GDCIC_PROJECT_CODE"
    if project_code_backfill_state == "MISSING_PROJECT_CODE_BACKFILL_INPUT":
        return "BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING"
    return "NO_GDCIC_PROJECT_CODE_ROUTE"


def _field_record_downstream_grade(record: Mapping[str, Any]) -> str:
    return str(
        record.get("downstream_release_evidence_abcd_grade")
        or record.get("release_evidence_downstream_abcd_grade")
        or record.get("downstream_abcd_grade")
        or ""
    )


def _stage5_operational_review(
    *,
    readiness_record: Mapping[str, Any],
    stage6_record: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    p13b_project_signal: Mapping[str, Any],
    p13b_original_notice_signal: Mapping[str, Any],
    p13b_ygp_signal: Mapping[str, Any],
    p13b_overlap_closeout_signal: Mapping[str, Any],
    company_first_stage4_execution_signal: Mapping[str, Any],
    design_survey_public_registry_readback_signal: Mapping[str, Any],
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
    has_local_authority_plan_ready = (
        p13b_state == "LOCAL_AUTHORITY_SOURCE_PLAN_READY"
        or _int(p13b_project_signal.get("local_authority_source_task_count")) > 0
    )
    has_local_authority_match = p13b_state == "LOCAL_AUTHORITY_MATCHED_REVIEW"
    has_local_authority_not_found = p13b_state == "LOCAL_AUTHORITY_NOT_FOUND_REVIEW"
    has_local_authority_blocked = p13b_state == "LOCAL_AUTHORITY_BLOCKED_REVIEW"
    original_notice_state = str(p13b_original_notice_signal.get("p13b_original_notice_readback_state") or "")
    has_original_notice_match = original_notice_state == "MATCHED"
    has_original_notice_not_found = original_notice_state == "NOT_FOUND"
    has_original_notice_blocked = original_notice_state == "BLOCKED"
    ygp_state = str(p13b_ygp_signal.get("p13b_ygp_original_readback_state") or "")
    has_ygp_ready = ygp_state == "YGP_READBACK_READY"
    has_ygp_blocked = ygp_state == "YGP_BLOCKED"
    has_ygp_stage4_backfill_ready = _int(
        p13b_ygp_signal.get("ygp_stage4_backfill_ready_count")
        or p13b_overlap_closeout_signal.get("ygp_stage4_backfill_ready_count")
    ) > 0
    company_first_supplement_state = str(
        company_first_stage4_execution_signal.get("supplement_after_execution_state") or ""
    )
    has_company_first_provider_ready = company_first_supplement_state == "COMPANY_FIRST_PROVIDER_TASKS_READY"
    has_company_first_target_missing = company_first_supplement_state == "COMPANY_FIRST_TARGET_FIELDS_MISSING"
    has_company_first_resolved = company_first_supplement_state == "COMPANY_FIRST_CERTIFICATE_RESOLVED"
    has_company_first_flow08_required = (
        company_first_supplement_state == "FLOW_08_TARGETED_PARSE_REQUIRED"
        or bool(company_first_stage4_execution_signal.get("flow_08_targeted_parse_required"))
    )
    has_design_survey_public_registry_fallback_required = (
        company_first_supplement_state == "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED"
    )
    design_registry_readback_state = str(
        design_survey_public_registry_readback_signal.get("readback_state") or ""
    ).upper()
    design_registry_verification = str(
        design_survey_public_registry_readback_signal.get("verification_result") or ""
    ).upper()
    has_design_survey_public_registry_matched = (
        design_registry_readback_state == "MATCHED" or design_registry_verification == "MATCHED"
    )
    has_design_survey_public_registry_not_found = design_registry_readback_state == "NOT_FOUND"
    has_design_survey_public_registry_blocked = design_registry_readback_state in {
        "FAIL_CLOSED_QUERY_ERROR",
        "PUBLIC_SNAPSHOT_OR_RUNTIME_ADAPTER_REQUIRED",
        "ENTRY_READBACK_READY_PERSON_SEARCH_NOT_EXECUTED",
    }
    has_weak_official_signal = _int(adapter_counts.get("MATCHED")) > 0 and not has_official_b_or_c
    fail_closed_reasons = {str(item) for item in _as_list(readiness_record.get("fail_closed_reasons"))}
    remaining_gaps = {str(item) for item in _as_list(readiness_record.get("remaining_real_world_gaps"))}
    stage3_parse_state = str(readiness_record.get("stage3_field_parse_state") or "").upper()
    responsible_gap_code = str(readiness_record.get("responsible_role_gap_code") or "").strip()
    has_responsible_role_gap = (
        "RESPONSIBLE_ROLE_GAP" in stage3_parse_state
        or bool(responsible_gap_code)
        or "notice_has_company_but_missing_responsible_role_name" in fail_closed_reasons
        or any("responsible_role_missing" in gap for gap in remaining_gaps)
    )
    has_certificate_gap = (
        "notice_has_company_and_project_manager_but_missing_certificate_no" in fail_closed_reasons
        or any("certificate_missing" in gap for gap in remaining_gaps)
    )
    has_field_ambiguity = (
        "same_name_not_disambiguated" in fail_closed_reasons
        or "target_identifier_missing" in fail_closed_reasons
        or any("ambiguous" in reason.lower() or "ambiguity" in reason.lower() for reason in fail_closed_reasons)
    )
    has_project_code_backfill_gap = (
        "gdcic_project_code_not_resolved" in fail_closed_reasons
        or "gdcic_project_code_not_resolved_after_project_name_candidate_queries" in fail_closed_reasons
        or "gdcic_project_code_candidates_present_but_not_matched" in fail_closed_reasons
    )
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
    if has_ygp_stage4_backfill_ready:
        signals.append("ygp_stage4_backfill_ready")
    if has_company_first_resolved:
        signals.append("company_first_certificate_resolved")
    if has_company_first_provider_ready:
        signals.append("company_first_provider_tasks_ready")
    if has_company_first_target_missing:
        signals.append("company_first_target_fields_missing")
    if has_company_first_flow08_required:
        signals.append("company_first_flow08_targeted_parse_required")
    if has_design_survey_public_registry_fallback_required:
        signals.append("design_survey_public_registry_fallback_required")
    if has_design_survey_public_registry_matched:
        signals.append("design_survey_public_registry_matched")
    if has_design_survey_public_registry_not_found:
        signals.append("design_survey_public_registry_not_found")
    if has_design_survey_public_registry_blocked:
        signals.append("design_survey_public_registry_blocked")
    if has_ygp_blocked:
        signals.append("ygp_readback_blocked")
    if has_source_not_found:
        signals.append("source_not_found")
    if has_public_source_not_found:
        signals.append("public_source_not_found")
    if has_local_authority_plan_ready:
        signals.append("local_authority_source_plan_ready")
    if has_local_authority_match:
        signals.append("local_authority_matched")
    if has_local_authority_not_found:
        signals.append("local_authority_not_found")
    if has_local_authority_blocked:
        signals.append("local_authority_blocked")
    if has_responsible_role_gap:
        signals.append("responsible_role_gap")
    if has_certificate_gap:
        signals.append("responsible_person_certificate_gap")
    if has_field_ambiguity:
        signals.append("field_ambiguity")
    if has_project_code_backfill_gap:
        signals.append("project_code_backfill_gap")
    if has_evidence_insufficient:
        signals.append("evidence_insufficient")

    queues: list[str] = []
    if has_official_b_or_c or has_original_notice_match:
        queues.append("STRONG_LEAD_INTERNAL_REVIEW")
    if has_weak_official_signal:
        queues.append("WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW")
    if has_authorization_block:
        queues.append("AUTHORIZATION_BLOCKED_REVIEW")
    if has_public_source_blocked:
        queues.append("PUBLIC_SOURCE_BLOCKED_REVIEW")
    if has_source_not_found:
        queues.append("SOURCE_NOT_FOUND_REVIEW")
    if has_public_source_not_found:
        queues.append("PUBLIC_SOURCE_NOT_FOUND_REVIEW")
    if has_local_authority_plan_ready:
        queues.append("LOCAL_AUTHORITY_SOURCE_PLAN_REVIEW")
    if has_local_authority_match:
        queues.append("LOCAL_AUTHORITY_MATCHED_REVIEW")
    if has_local_authority_not_found:
        queues.append("LOCAL_AUTHORITY_NOT_FOUND_REVIEW")
    if has_local_authority_blocked:
        queues.append("LOCAL_AUTHORITY_BLOCKED_REVIEW")
    if has_certificate_gap:
        queues.append("RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW")
    if has_responsible_role_gap:
        queues.append("RESPONSIBLE_ROLE_GAP_REVIEW")
    if has_field_ambiguity:
        queues.append("FIELD_AMBIGUITY_REVIEW")
    if has_project_code_backfill_gap:
        queues.append("PROJECT_CODE_BACKFILL_GAP_REVIEW")
    if has_original_backtrace_required:
        queues.append("ORIGINAL_NOTICE_BACKTRACE_REQUIRED_REVIEW")
    if has_original_notice_not_found:
        queues.append("ORIGINAL_NOTICE_NOT_FOUND_REVIEW")
    if has_original_notice_blocked:
        queues.append("ORIGINAL_NOTICE_BLOCKED_REVIEW")
    if has_ygp_stage4_backfill_ready:
        queues.append("YGP_STAGE4_BACKFILL_READY_REVIEW")
    if has_company_first_resolved:
        queues.append("COMPANY_FIRST_CERTIFICATE_RESOLVED_REVIEW")
    if has_company_first_provider_ready:
        queues.append("COMPANY_FIRST_PROVIDER_TASKS_READY_REVIEW")
    if has_company_first_target_missing:
        queues.append("COMPANY_FIRST_TARGET_FIELDS_MISSING_REVIEW")
    if has_company_first_flow08_required:
        queues.append("COMPANY_FIRST_FLOW08_TARGETED_PARSE_REVIEW")
    if has_design_survey_public_registry_fallback_required:
        queues.append("DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW")
    if has_design_survey_public_registry_matched:
        queues.append("DESIGN_SURVEY_PUBLIC_REGISTRY_MATCHED_REVIEW")
    if has_design_survey_public_registry_not_found:
        queues.append("DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW")
    if has_design_survey_public_registry_blocked:
        queues.append("DESIGN_SURVEY_PUBLIC_REGISTRY_BLOCKED_REVIEW")
    if has_ygp_ready:
        queues.append("YGP_READBACK_READY_REVIEW")
    if has_ygp_blocked:
        queues.append("YGP_READBACK_BLOCKED_REVIEW")
    if has_evidence_insufficient:
        queues.append("EVIDENCE_INSUFFICIENT_REVIEW")

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
    elif has_ygp_stage4_backfill_ready:
        bucket = "YGP_STAGE4_BACKFILL_READY_REVIEW"
        action = "feed_ygp_stage4_backfill_candidates_to_p13b_or_stage4_bridge_without_gdcic_route_claim"
    elif has_company_first_resolved:
        bucket = "COMPANY_FIRST_CERTIFICATE_RESOLVED_REVIEW"
        action = "feed_company_first_certificate_fields_to_stage4_stage6_internal_review"
    elif has_company_first_provider_ready:
        bucket = "COMPANY_FIRST_PROVIDER_TASKS_READY_REVIEW"
        action = "execute_or_review_company_first_provider_jobs_without_identity_confirmation"
    elif has_company_first_target_missing:
        bucket = "COMPANY_FIRST_TARGET_FIELDS_MISSING_REVIEW"
        action = "repair_responsible_person_or_role_inputs_before_company_first_provider_execution"
    elif has_company_first_flow08_required:
        bucket = "COMPANY_FIRST_FLOW08_TARGETED_PARSE_REVIEW"
        action = "run_flow08_targeted_parse_without_treating_company_first_no_match_as_clearance"
    elif has_design_survey_public_registry_matched:
        bucket = "DESIGN_SURVEY_PUBLIC_REGISTRY_MATCHED_REVIEW"
        action = "manual_stage5_stage6_review_for_registered_surveyor_public_registry_match"
    elif has_design_survey_public_registry_not_found:
        bucket = "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW"
        action = "keep_public_registry_not_found_as_non_clearance_and_retry_or_review_alternate_source"
    elif has_design_survey_public_registry_blocked:
        bucket = "DESIGN_SURVEY_PUBLIC_REGISTRY_BLOCKED_REVIEW"
        action = "provide_public_registry_snapshot_or_retry_public_registry_adapter_without_clearance_claim"
    elif has_design_survey_public_registry_fallback_required:
        bucket = "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW"
        action = "run_design_survey_public_registry_fallback_without_identity_or_clearance_claim"
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
    elif has_local_authority_match:
        bucket = "LOCAL_AUTHORITY_MATCHED_REVIEW"
        action = "manual_stage5_stage6_review_for_local_authority_keyword_match"
    elif has_local_authority_blocked:
        bucket = "LOCAL_AUTHORITY_BLOCKED_REVIEW"
        action = "retry_project_local_authority_source_or_choose_alternate_official_entry"
    elif has_local_authority_not_found:
        bucket = "LOCAL_AUTHORITY_NOT_FOUND_REVIEW"
        action = "keep_not_found_as_non_clearance_and_try_specific_search_endpoint_or_manual_source_path"
    elif has_local_authority_plan_ready:
        bucket = "LOCAL_AUTHORITY_SOURCE_PLAN_REVIEW"
        action = "run_project_local_authority_adapter_or_keep_plan_only_without_clearance_claim"
    elif has_authorization_block and (has_source_not_found or has_public_source_not_found):
        bucket = "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW"
        action = "provide_authorized_session_or_fallback_source_without_treating_not_found_as_clearance"
    elif has_authorization_block:
        bucket = "AUTHORIZATION_BLOCKED_REVIEW"
        action = "provide_authorized_browser_session_then_rerun_release_field_query"
    elif has_source_not_found:
        bucket = "SOURCE_NOT_FOUND_REVIEW"
        action = "try_project_code_backfill_or_jurisdiction_source_without_clearance_claim"
    elif has_public_source_not_found:
        bucket = "PUBLIC_SOURCE_NOT_FOUND_REVIEW"
        action = "keep_no_public_overlap_signal_as_non_clearance_and_manual_review"
    elif has_certificate_gap:
        bucket = "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW"
        action = "run_company_first_certificate_supplement_and_attachment_ocr_without_identity_confirmation"
    elif has_responsible_role_gap:
        bucket = "RESPONSIBLE_ROLE_GAP_REVIEW"
        action = "run_company_first_responsible_role_completion_before_stage4_release_readback"
    elif has_project_code_backfill_gap:
        bucket = "PROJECT_CODE_BACKFILL_GAP_REVIEW"
        action = "backfill_project_code_from_notice_data_ggzy_bid_show_or_local_source_without_digit_guessing"
    elif has_field_ambiguity:
        bucket = "FIELD_AMBIGUITY_REVIEW"
        action = "keep_same_name_or_missing_identifier_as_manual_disambiguation_required"
    elif has_evidence_insufficient:
        bucket = "EVIDENCE_INSUFFICIENT_REVIEW"
        action = "keep_internal_evidence_gap_and_collect_more_official_readback"
    else:
        bucket = "UNCLASSIFIED_STAGE5_REVIEW"
        action = "review_stage5_inputs_and_classifier_coverage"

    primary_track = _stage5_operational_primary_track(bucket)
    priority = _stage5_operational_priority(bucket, queues or [bucket])
    safety_boundary = _stage5_operational_safety_boundary(bucket)
    return {
        "stage5_operational_review_bucket": bucket,
        "stage5_operational_review_family": _stage5_operational_bucket_family(bucket),
        "stage5_operational_review_families": _stage5_operational_queue_families(queues or [bucket]),
        "stage5_operational_review_queues": queues or [bucket],
        "stage5_operational_signal_flags": signals or ["unclassified_review_required"],
        "stage5_operational_review_reason": "|".join(signals) if signals else "stage5_review_requires_manual_triage",
        "stage5_operational_next_action": action,
        "stage5_operational_primary_track": primary_track,
        "stage5_operational_priority_bucket": priority["bucket"],
        "stage5_operational_priority_rank": priority["rank"],
        "stage5_operational_safety_boundary": safety_boundary,
        "stage5_query_miss_is_not_clearance": True,
    }


def _stage5_operational_primary_track(bucket: str) -> str:
    mapping = {
        "STRONG_LEAD_INTERNAL_REVIEW": "strong_lead",
        "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW": "weak_lead",
        "AUTHORIZATION_BLOCKED_REVIEW": "authorization_blocked",
        "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW": "authorization_blocked_with_source_not_found",
        "PUBLIC_SOURCE_BLOCKED_REVIEW": "public_source_blocked",
        "ORIGINAL_NOTICE_BLOCKED_REVIEW": "public_source_blocked",
        "YGP_READBACK_BLOCKED_REVIEW": "public_source_blocked",
        "LOCAL_AUTHORITY_BLOCKED_REVIEW": "public_source_blocked",
        "SOURCE_NOT_FOUND_REVIEW": "source_not_found",
        "PUBLIC_SOURCE_NOT_FOUND_REVIEW": "source_not_found",
        "ORIGINAL_NOTICE_NOT_FOUND_REVIEW": "source_not_found",
        "LOCAL_AUTHORITY_NOT_FOUND_REVIEW": "source_not_found",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW": "source_not_found",
        "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": "responsible_person_certificate_gap",
        "RESPONSIBLE_ROLE_GAP_REVIEW": "responsible_role_gap",
        "FIELD_AMBIGUITY_REVIEW": "field_ambiguity",
        "PROJECT_CODE_BACKFILL_GAP_REVIEW": "project_code_backfill_gap",
        "EVIDENCE_INSUFFICIENT_REVIEW": "evidence_insufficient",
    }
    return mapping.get(str(bucket or ""), _stage5_operational_bucket_family(bucket))


def _stage5_operational_priority(bucket: str, queues: list[str]) -> dict[str, int | str]:
    bucket_text = str(bucket or "")
    queue_set = {str(queue or "") for queue in queues}
    if bucket_text == "STRONG_LEAD_INTERNAL_REVIEW":
        return {"bucket": "P0_LIMITED_SELLABLE_REVIEW", "rank": 0}
    if bucket_text in {
        "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW",
        "YGP_READBACK_READY_REVIEW",
        "YGP_STAGE4_BACKFILL_READY_REVIEW",
        "LOCAL_AUTHORITY_MATCHED_REVIEW",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_MATCHED_REVIEW",
    }:
        return {"bucket": "P1_OFFICIAL_READBACK_DEEPENING", "rank": 1}
    if queue_set & {
        "AUTHORIZATION_BLOCKED_REVIEW",
        "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW",
        "PUBLIC_SOURCE_BLOCKED_REVIEW",
        "ORIGINAL_NOTICE_BLOCKED_REVIEW",
        "YGP_READBACK_BLOCKED_REVIEW",
        "LOCAL_AUTHORITY_BLOCKED_REVIEW",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_BLOCKED_REVIEW",
    }:
        return {"bucket": "P1_BLOCKER_RETRY_OR_ALTERNATE_SOURCE", "rank": 1}
    if queue_set & {
        "SOURCE_NOT_FOUND_REVIEW",
        "PUBLIC_SOURCE_NOT_FOUND_REVIEW",
        "ORIGINAL_NOTICE_NOT_FOUND_REVIEW",
        "LOCAL_AUTHORITY_NOT_FOUND_REVIEW",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW",
    }:
        return {"bucket": "P2_NOT_FOUND_NON_CLEARANCE_DEEPENING", "rank": 2}
    if queue_set & {
        "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW",
        "RESPONSIBLE_ROLE_GAP_REVIEW",
        "FIELD_AMBIGUITY_REVIEW",
        "PROJECT_CODE_BACKFILL_GAP_REVIEW",
    }:
        return {"bucket": "P2_INPUT_REPAIR_AND_DISAMBIGUATION", "rank": 2}
    if "EVIDENCE_INSUFFICIENT_REVIEW" in queue_set:
        return {"bucket": "P3_EVIDENCE_INSUFFICIENT_PARK_OR_SAMPLE", "rank": 3}
    return {"bucket": "P3_UNCLASSIFIED_MANUAL_TRIAGE", "rank": 3}


def _stage5_operational_safety_boundary(bucket: str) -> str:
    if bucket == "STRONG_LEAD_INTERNAL_REVIEW":
        return "INTERNAL_LIMITED_SELLABLE_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE"
    return "INTERNAL_REVIEW_ONLY_NOT_CLEARANCE"


def _stage5_operational_queue_families(queues: list[str]) -> list[str]:
    return _dedupe(_stage5_operational_bucket_family(queue) for queue in queues)


def _stage5_operational_bucket_family(bucket: str) -> str:
    mapping = {
        "STRONG_LEAD_INTERNAL_REVIEW": "strong_lead",
        "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW": "weak_lead",
        "AUTHORIZATION_BLOCKED_REVIEW": "authorization_blocked",
        "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW": "authorization_blocked",
        "PUBLIC_SOURCE_BLOCKED_REVIEW": "public_source_blocked",
        "SOURCE_NOT_FOUND_REVIEW": "source_not_found",
        "PUBLIC_SOURCE_NOT_FOUND_REVIEW": "source_not_found",
        "ORIGINAL_NOTICE_NOT_FOUND_REVIEW": "source_not_found",
        "ORIGINAL_NOTICE_BACKTRACE_REQUIRED_REVIEW": "original_notice_backtrace_required",
        "ORIGINAL_NOTICE_BLOCKED_REVIEW": "public_source_blocked",
        "YGP_READBACK_BLOCKED_REVIEW": "public_source_blocked",
        "YGP_READBACK_READY_REVIEW": "official_readback_ready",
        "YGP_STAGE4_BACKFILL_READY_REVIEW": "official_readback_ready",
        "COMPANY_FIRST_CERTIFICATE_RESOLVED_REVIEW": "responsible_person_certificate_resolved",
        "COMPANY_FIRST_PROVIDER_TASKS_READY_REVIEW": "responsible_person_certificate_gap",
        "COMPANY_FIRST_TARGET_FIELDS_MISSING_REVIEW": "responsible_person_certificate_gap",
        "COMPANY_FIRST_FLOW08_TARGETED_PARSE_REVIEW": "responsible_person_certificate_gap",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW": "public_registration_fallback_required",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_MATCHED_REVIEW": "official_readback_ready",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW": "source_not_found",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_BLOCKED_REVIEW": "public_source_blocked",
        "LOCAL_AUTHORITY_SOURCE_PLAN_REVIEW": "local_authority_source_planned",
        "LOCAL_AUTHORITY_MATCHED_REVIEW": "official_readback_ready",
        "LOCAL_AUTHORITY_NOT_FOUND_REVIEW": "source_not_found",
        "LOCAL_AUTHORITY_BLOCKED_REVIEW": "public_source_blocked",
        "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": "responsible_person_certificate_gap",
        "RESPONSIBLE_ROLE_GAP_REVIEW": "responsible_role_gap",
        "FIELD_AMBIGUITY_REVIEW": "field_ambiguity",
        "PROJECT_CODE_BACKFILL_GAP_REVIEW": "project_code_backfill_gap",
        "EVIDENCE_INSUFFICIENT_REVIEW": "evidence_insufficient",
        "UNCLASSIFIED_STAGE5_REVIEW": "unclassified_review_required",
    }
    return mapping.get(str(bucket or ""), "unclassified_review_required")


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


def _scoreboard_continuation_input_refs(input_refs: Mapping[str, Any], out_dir: Path) -> dict[str, Any]:
    pressure_root = _parent_with_required_sibling(
        input_refs,
        keys=("pressure_summary_json", "stage1_6_readiness_json", "stage1_6_gap_summary_json"),
        required_sibling="stage4-release-adapter-bridge-plan.json",
    )
    release_field_query_root = _existing_file_parent(input_refs.get("release_field_query_json"))
    supplemental_release_field_query_json = input_refs.get("supplemental_release_field_query_json")
    supplemental_release_field_query_root = _existing_file_parent(supplemental_release_field_query_json)
    gdcic_readback_root = _existing_file_parent(input_refs.get("gdcic_browser_authorized_readback_json"))
    stage6_status_root = _existing_file_parent(input_refs.get("stage6_status_json"))
    return {
        "prior_scoreboard_json": str(out_dir / "stage1-6-sellable-scoreboard-v1.json"),
        "effective_pressure_root": pressure_root,
        "effective_release_field_query_root": release_field_query_root,
        "effective_supplemental_release_field_query_json": str(supplemental_release_field_query_json or ""),
        "effective_supplemental_release_field_query_root": supplemental_release_field_query_root,
        "effective_gdcic_browser_readback_root": gdcic_readback_root,
        "effective_stage6_status_root": stage6_status_root,
        "pressure_root_resolution_state": "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if pressure_root else "UNRESOLVED",
        "release_field_query_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if release_field_query_root else "UNRESOLVED"
        ),
        "supplemental_release_field_query_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if supplemental_release_field_query_root else "UNRESOLVED"
        ),
        "gdcic_browser_readback_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if gdcic_readback_root else "UNRESOLVED"
        ),
        "stage6_status_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if stage6_status_root else "UNRESOLVED"
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _parent_with_required_sibling(
    input_refs: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
    required_sibling: str,
) -> str:
    for key in keys:
        root = _existing_file_parent(input_refs.get(key))
        if root and (Path(root) / required_sibling).exists():
            return root
    return ""


def _existing_file_parent(value: Any) -> str:
    path_text = str(value or "").strip()
    if not path_text:
        return ""
    path = Path(path_text)
    if path.exists() and path.is_file():
        return str(path.parent)
    return ""


def _resolve_path(value: str | Path | None, default: Path) -> Path:
    return Path(value) if value else default


def _resolve_optional_artifact_path(
    *,
    artifact_json: str | Path | None,
    artifact_root: str | Path | None,
    artifact_name: str,
) -> Path | None:
    if artifact_json:
        return Path(artifact_json)
    if artifact_root:
        return Path(artifact_root) / artifact_name
    return None


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


def _merge_field_query_payloads(primary: Mapping[str, Any], supplemental: Mapping[str, Any]) -> dict[str, Any]:
    if not supplemental:
        return dict(primary)
    primary_records = _field_task_records(primary)
    supplemental_records = _field_task_records(supplemental)
    merged_records = [
        {**record, "scoreboard_field_query_source": "primary"} for record in primary_records
    ] + [
        {**record, "scoreboard_field_query_source": "supplemental"} for record in supplemental_records
    ]
    primary_manifest = primary.get("manifest") if isinstance(primary.get("manifest"), Mapping) else {}
    merged_manifest = dict(primary_manifest)
    merged_manifest["field_task_records"] = merged_records
    merged = dict(primary)
    merged["manifest"] = merged_manifest
    merged["summary"] = _merged_field_query_summary(primary, supplemental, merged_records)
    return merged


def _merged_field_query_summary(
    primary: Mapping[str, Any],
    supplemental: Mapping[str, Any],
    merged_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    summary = dict(_summary(primary))
    supplemental_summary = _summary(supplemental)
    for key, value in supplemental_summary.items():
        if key.endswith("_counts") and isinstance(value, Mapping):
            summary[key] = _sum_count_maps(summary.get(key), value)
        elif key not in summary:
            summary[key] = value
    summary["field_task_count"] = len(merged_records)
    summary["field_task_source_counts"] = _counts(
        record.get("scoreboard_field_query_source") for record in merged_records
    )
    summary["adapter_result_state_counts"] = _counts(
        record.get("adapter_result_state") for record in merged_records
    )
    summary["release_evidence_downstream_abcd_grade_counts"] = _counts(
        _field_record_downstream_grade(record) for record in merged_records
    )
    summary["authorization_readiness_state_counts"] = _counts(
        record.get("authorization_readiness_state") for record in merged_records
    )
    summary["blocker_taxonomy_counts"] = _flatten_counts(merged_records, "blocker_taxonomy")
    return summary


def _sum_count_maps(left: Any, right: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    if isinstance(left, Mapping):
        for key, value in left.items():
            out[str(key)] = int(out.get(str(key), 0)) + _int(value)
    for key, value in right.items():
        out[str(key)] = int(out.get(str(key), 0)) + _int(value)
    return out


def _p13b_project_signals(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    if not manifest:
        return {}
    project_records = _manifest_records(manifest, "project_task_records")
    query_records = _manifest_records(manifest, "company_history_query_records")
    bid_show_records = _manifest_records(manifest, "bid_show_records")
    overlap_records = _manifest_records(manifest, "overlap_signal_records")
    local_authority_records = _manifest_records(manifest, "local_authority_source_task_records")
    local_authority_readback_records = _manifest_records(manifest, "local_authority_source_readback_records")
    project_ids = _ordered_project_ids(
        project_records,
        query_records,
        bid_show_records,
        overlap_records,
        local_authority_records,
        local_authority_readback_records,
    )
    signals: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_queries = [record for record in query_records if str(record.get("project_id") or "").strip() == project_id]
        project_bid_shows = [record for record in bid_show_records if str(record.get("project_id") or "").strip() == project_id]
        project_overlaps = [record for record in overlap_records if str(record.get("project_id") or "").strip() == project_id]
        project_local_authority = [
            record for record in local_authority_records if str(record.get("project_id") or "").strip() == project_id
        ]
        project_local_authority_readbacks = [
            record for record in local_authority_readback_records if str(record.get("project_id") or "").strip() == project_id
        ]
        company_query_counts = _counts(record.get("query_state") for record in project_queries)
        bid_show_counts = _counts(record.get("bid_show_state") for record in project_bid_shows)
        bid_show_original_notice_url_count = sum(
            1 for record in project_bid_shows if str(record.get("original_notice_url") or "").strip()
        )
        bid_show_responsible_person_present_count = sum(
            1 for record in project_bid_shows if _as_list(record.get("responsible_person_names"))
        )
        overlap_counts = _counts(record.get("overlap_signal_state") for record in project_overlaps)
        local_authority_task_counts = _counts(record.get("source_task_state") for record in project_local_authority)
        local_authority_readback_counts = _counts(record.get("local_authority_readback_state") for record in project_local_authority)
        local_authority_executed_readback_counts = _counts(
            record.get("local_authority_readback_state") for record in project_local_authority_readbacks
        )
        original_backtrace_required = _int(overlap_counts.get("ORIGINAL_NOTICE_BACKTRACE_REQUIRED")) + _int(
            bid_show_counts.get("ORIGINAL_NOTICE_BACKTRACE_REQUIRED")
        )
        source_blocked = _int(company_query_counts.get("SOURCE_BLOCKED_RETRY_REQUIRED"))
        overlap_review_required = _int(overlap_counts.get("OVERLAP_SIGNAL_REVIEW_REQUIRED"))
        no_public_signal = _int(overlap_counts.get("NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"))
        local_authority_plan_ready = _int(local_authority_task_counts.get("LOCAL_AUTHORITY_SOURCE_PLAN_READY")) > 0
        if overlap_review_required:
            readback_state = "MATCHED_OVERLAP_SIGNAL_REVIEW_REQUIRED"
        elif _int(local_authority_executed_readback_counts.get("MATCHED")):
            readback_state = "LOCAL_AUTHORITY_MATCHED_REVIEW"
        elif original_backtrace_required:
            readback_state = "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
        elif _int(local_authority_executed_readback_counts.get("BLOCKED")):
            readback_state = "LOCAL_AUTHORITY_BLOCKED_REVIEW"
        elif _int(local_authority_executed_readback_counts.get("NOT_FOUND")):
            readback_state = "LOCAL_AUTHORITY_NOT_FOUND_REVIEW"
        elif source_blocked:
            readback_state = "PUBLIC_SOURCE_BLOCKED_REVIEW"
        elif local_authority_plan_ready:
            readback_state = "LOCAL_AUTHORITY_SOURCE_PLAN_READY"
        elif no_public_signal or _int(company_query_counts.get("NO_PUBLIC_OVERLAP_SIGNAL_REVIEW")):
            readback_state = "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"
        else:
            readback_state = "PUBLIC_SOURCE_READBACK_PENDING_OR_NOT_RUN"
        signals[project_id] = {
            "project_id": project_id,
            "p13b_public_source_readback_state": readback_state,
            "company_query_state_counts": company_query_counts,
            "bid_show_state_counts": bid_show_counts,
            "bid_show_original_notice_url_count": bid_show_original_notice_url_count,
            "bid_show_responsible_person_present_count": bid_show_responsible_person_present_count,
            "overlap_signal_state_counts": overlap_counts,
            "local_authority_source_task_state_counts": local_authority_task_counts,
            "local_authority_readback_state_counts": local_authority_readback_counts,
            "local_authority_executed_readback_state_counts": local_authority_executed_readback_counts,
            "local_authority_source_task_count": len(project_local_authority),
            "local_authority_source_readback_count": len(project_local_authority_readbacks),
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
    backfill_records = _manifest_records(manifest, "stage4_ygp_project_code_backfill_records")
    project_ids = _ordered_project_ids(readback_records, backfill_records)
    signals: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_records = [record for record in readback_records if str(record.get("project_id") or "").strip() == project_id]
        project_backfills = [
            record for record in backfill_records if str(record.get("project_id") or "").strip() == project_id
        ]
        state_counts = _counts(record.get("ygp_readback_state") for record in project_records)
        backfill_state_counts = _counts(record.get("stage4_ygp_backfill_state") for record in project_backfills)
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
            "ygp_stage4_backfill_ready_count": sum(
                1
                for record in project_backfills
                if str(record.get("stage4_ygp_backfill_state") or "") == "YGP_STAGE4_BACKFILL_READY"
            ),
            "ygp_stage4_backfill_state_counts": backfill_state_counts,
            "ygp_stage4_gdcic_route_allowed_count": sum(
                1 for record in project_backfills if bool(record.get("gdcic_project_code_route_allowed"))
            ),
            "ygp_stage4_backfill_recommended_next_actions": _dedupe(
                record.get("recommended_next_action") for record in project_backfills
            ),
            "ygp_project_code_variants": _dedupe(
                record.get("ygp_project_code") for record in [*project_records, *project_backfills]
            ),
            "ygp_biz_code_variants": _dedupe(
                record.get("ygp_biz_code") for record in [*project_records, *project_backfills]
            ),
            "ygp_site_code_variants": _dedupe(
                record.get("ygp_site_code") for record in [*project_records, *project_backfills]
            ),
            "ygp_notice_id_variants": _dedupe(
                record.get("ygp_notice_id") for record in [*project_records, *project_backfills]
            ),
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return signals


def _p13b_overlap_closeout_project_signals(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    if not manifest:
        return {}
    project_records = _manifest_records(manifest, "project_overlap_triage_records")
    backfill_records = _manifest_records(manifest, "ygp_stage4_backfill_candidate_records")
    adapter_task_records = _manifest_records(manifest, "release_evidence_adapter_task_records")
    project_ids = _ordered_project_ids(project_records, backfill_records, adapter_task_records)
    signals: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_closeouts = [
            record for record in project_records if str(record.get("project_id") or "").strip() == project_id
        ]
        project_backfills = [
            record for record in backfill_records if str(record.get("project_id") or "").strip() == project_id
        ]
        project_adapter_tasks = [
            record for record in adapter_task_records if str(record.get("project_id") or "").strip() == project_id
        ]
        closeout = project_closeouts[0] if project_closeouts else {}
        backfill_state_counts = _counts(
            record.get("p13b_backfill_state") or record.get("stage4_ygp_backfill_state")
            for record in project_backfills
        )
        signals[project_id] = {
            "project_id": project_id,
            "p13b_overlap_triage_state": str(closeout.get("project_overlap_triage_state") or ""),
            "ygp_stage4_backfill_ready_count": sum(
                1
                for record in project_backfills
                if str(record.get("p13b_backfill_state") or record.get("stage4_ygp_backfill_state") or "")
                in {"P13B_YGP_STAGE4_BACKFILL_READY", "YGP_STAGE4_BACKFILL_READY"}
            ),
            "ygp_stage4_backfill_state_counts": backfill_state_counts,
            "ygp_stage4_release_adapter_task_count": len(project_adapter_tasks),
            "ygp_stage4_gdcic_route_allowed_count": sum(
                1 for record in project_backfills if bool(record.get("gdcic_project_code_route_allowed"))
            ),
            "ygp_project_code_variants": _dedupe(record.get("ygp_project_code") for record in project_backfills),
            "ygp_biz_code_variants": _dedupe(record.get("ygp_biz_code") for record in project_backfills),
            "ygp_site_code_variants": _dedupe(record.get("ygp_site_code") for record in project_backfills),
            "ygp_notice_id_variants": _dedupe(record.get("ygp_notice_id") for record in project_backfills),
            "ygp_stage4_backfill_recommended_next_actions": _dedupe(
                record.get("recommended_next_action")
                for record in [*project_backfills, *project_adapter_tasks]
            ),
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return signals


def _company_first_stage4_execution_project_signals(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    records = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    signals: dict[str, dict[str, Any]] = {}
    for project_id in _ordered_project_ids([record for record in records if isinstance(record, Mapping)]):
        project_records = [
            record
            for record in records
            if isinstance(record, Mapping) and str(record.get("project_id") or "").strip() == project_id
        ]
        if not project_records:
            continue
        first = project_records[0]
        execution_counts = _counts(record.get("stage4_execution_state") for record in project_records)
        identity_counts = _counts(record.get("identity_resolution_state") for record in project_records)
        supplement_counts = _counts(record.get("supplement_after_execution_state") for record in project_records)
        resolved = next(
            (
                record
                for record in project_records
                if str(record.get("supplement_after_execution_state") or "") == "COMPANY_FIRST_CERTIFICATE_RESOLVED"
            ),
            {},
        )
        signals[project_id] = {
            "project_id": project_id,
            "stage4_execution_state": _dominant_state(execution_counts),
            "identity_resolution_state": _dominant_state(identity_counts),
            "supplement_after_execution_state": _dominant_state(supplement_counts),
            "stage4_readiness_state": _dominant_state(
                _counts(record.get("stage4_readiness_state") for record in project_records)
            ),
            "stage4_execution_state_counts": execution_counts,
            "identity_resolution_state_counts": identity_counts,
            "supplement_after_execution_state_counts": supplement_counts,
            "provider_job_count": len(project_records),
            "stage4_input_count": sum(
                1
                for record in project_records
                if str(record.get("supplement_after_execution_state") or "")
                == "COMPANY_FIRST_CERTIFICATE_RESOLVED"
            ),
            "flow_08_targeted_parse_required": any(
                bool(record.get("flow_08_targeted_parse_required")) for record in project_records
            ),
            "next_actions": _dedupe(
                action
                for record in project_records
                for action in _as_list(record.get("next_actions"))
            ),
            "resolved_certificate_no_optional": str(resolved.get("resolved_certificate_no_optional") or ""),
            "registered_unit_name_optional": str(resolved.get("registered_unit_name_optional") or ""),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        if not signals[project_id]["supplement_after_execution_state"]:
            signals[project_id]["supplement_after_execution_state"] = str(
                first.get("supplement_after_execution_state") or ""
            )
    return signals


def _design_survey_public_registry_readback_project_signals(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    table = manifest.get("public_registry_readback_table") if isinstance(manifest.get("public_registry_readback_table"), Mapping) else {}
    records = table.get("records") if isinstance(table.get("records"), list) else []
    signals: dict[str, dict[str, Any]] = {}
    for project_id in _ordered_project_ids([record for record in records if isinstance(record, Mapping)]):
        project_records = [
            record
            for record in records
            if isinstance(record, Mapping) and str(record.get("project_id") or "").strip() == project_id
        ]
        if not project_records:
            continue
        provider_counts = _counts(record.get("provider_result_state") for record in project_records)
        readback_counts = _counts(record.get("readback_state") for record in project_records)
        verification_counts = _counts(record.get("verification_result") for record in project_records)
        signals[project_id] = {
            "project_id": project_id,
            "provider_result_state": _dominant_state(provider_counts),
            "readback_state": _dominant_state(readback_counts),
            "verification_result": _dominant_state(verification_counts),
            "readback_record_count": len(project_records),
            "provider_result_state_counts": provider_counts,
            "readback_state_counts": readback_counts,
            "verification_result_counts": verification_counts,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return signals


def _dominant_state(counts: Mapping[str, int]) -> str:
    ranked = [
        (str(key), _int(value))
        for key, value in counts.items()
        if str(key or "").strip() and _int(value) > 0
    ]
    if not ranked:
        return ""
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[0][0]


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


def _merge_incremental_prior_project_rows(
    project_rows: list[Mapping[str, Any]],
    *,
    prior_scoreboard: Mapping[str, Any],
    incremental_project_ids: set[str],
) -> list[dict[str, Any]]:
    if not incremental_project_ids:
        return [dict(row) for row in project_rows]
    prior_rows = prior_scoreboard.get("project_rows")
    if not isinstance(prior_rows, list):
        return [dict(row) for row in project_rows]
    prior_by_project = {
        str(row.get("project_id") or "").strip(): dict(row)
        for row in prior_rows
        if isinstance(row, Mapping) and str(row.get("project_id") or "").strip()
    }
    current_by_project = {
        str(row.get("project_id") or "").strip(): dict(row)
        for row in project_rows
        if str(row.get("project_id") or "").strip()
    }
    ordered_ids = [str(row.get("project_id") or "").strip() for row in project_rows if str(row.get("project_id") or "").strip()]
    for project_id in prior_by_project:
        if project_id not in ordered_ids:
            ordered_ids.append(project_id)

    merged: list[dict[str, Any]] = []
    for project_id in ordered_ids:
        if project_id and project_id not in incremental_project_ids and project_id in prior_by_project:
            row = dict(prior_by_project[project_id])
            row["incremental_scoreboard_merge_state"] = "PRESERVED_FROM_PRIOR_SCOREBOARD_NON_TARGET"
            merged.append(row)
            continue
        row = dict(current_by_project.get(project_id) or prior_by_project.get(project_id) or {})
        if project_id in incremental_project_ids and project_id in prior_by_project:
            row = _merge_incremental_target_prior_public_source_evidence(
                row,
                prior_by_project[project_id],
            )
        if row:
            if project_id in incremental_project_ids:
                row["incremental_scoreboard_merge_state"] = row.get(
                    "incremental_scoreboard_merge_state",
                    "CURRENT_INCREMENTAL_TARGET",
                )
            else:
                row["incremental_scoreboard_merge_state"] = "CURRENT_FULL_OR_NO_PRIOR"
            merged.append(row)
    return merged


def _merge_incremental_target_prior_public_source_evidence(
    current: Mapping[str, Any],
    prior: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(current)
    current_backfill = str(row.get("stage4_project_code_backfill_state") or "")
    prior_backfill = str(prior.get("stage4_project_code_backfill_state") or "")
    if current_backfill != "MISSING_PROJECT_CODE_BACKFILL_INPUT" or not _is_public_identifier_backfilled(prior_backfill):
        return row
    preserve_fields = [
        *_prior_stage5_fields_to_preserve(row),
        "p13b_public_source_readback_state",
        "p13b_original_notice_backtrace_required_count",
        "p13b_company_query_state_counts",
        "p13b_bid_show_state_counts",
        "p13b_bid_show_original_notice_url_count",
        "p13b_bid_show_responsible_person_present_count",
        "p13b_overlap_signal_state_counts",
        "p13b_original_notice_readback_state",
        "p13b_original_notice_fetch_state_counts",
        "p13b_original_notice_match_state_counts",
        "p13b_ygp_original_readback_state",
        "p13b_ygp_readback_state_counts",
        "p13b_ygp_project_code_variants",
        "p13b_ygp_biz_code_variants",
        "p13b_ygp_site_code_variants",
        "p13b_ygp_notice_id_variants",
        "p13b_overlap_ygp_project_code_variants",
        "p13b_overlap_ygp_biz_code_variants",
        "p13b_overlap_ygp_site_code_variants",
        "p13b_overlap_ygp_notice_id_variants",
        "p13b_overlap_triage_state",
        "p13b_ygp_stage4_backfill_ready_count",
        "p13b_ygp_stage4_backfill_state_counts",
        "p13b_ygp_stage4_release_adapter_task_count",
        "p13b_ygp_gdcic_route_allowed_count",
        "p13b_ygp_stage4_backfill_recommended_next_actions",
        "stage4_project_code_backfill_state",
        "stage4_project_code_backfill_gap_detail",
        "stage4_public_identifier_backfill_source",
        "stage4_gdcic_project_code_route_allowed",
        "stage4_gdcic_project_code_route_policy",
        *_prior_blocking_fields_to_preserve(row),
    ]
    for field in preserve_fields:
        if field in prior:
            row[field] = prior[field]
    row["incremental_scoreboard_merge_state"] = "CURRENT_INCREMENTAL_TARGET_WITH_PRIOR_PUBLIC_SOURCE_EVIDENCE"
    row["incremental_scoreboard_preserved_public_source_evidence"] = True
    row["incremental_scoreboard_preservation_reason"] = (
        "current_incremental_public_source_retry_missing_identifier_preserved_prior_backfill"
    )
    return row


def _prior_stage5_fields_to_preserve(current: Mapping[str, Any]) -> list[str]:
    if _has_current_limited_or_strong_lead_projection(current):
        return []
    return [
        "stage5_operational_review_bucket",
        "stage5_operational_review_family",
        "stage5_operational_review_families",
        "stage5_operational_review_queues",
        "stage5_operational_signal_flags",
        "stage5_operational_review_reason",
        "stage5_operational_next_action",
        "stage5_operational_primary_track",
        "stage5_operational_priority_bucket",
        "stage5_operational_priority_rank",
        "stage5_operational_safety_boundary",
    ]


def _prior_blocking_fields_to_preserve(current: Mapping[str, Any]) -> list[str]:
    if _has_current_limited_or_strong_lead_projection(current):
        return []
    return ["blocking_bucket"]


def _has_current_limited_or_strong_lead_projection(current: Mapping[str, Any]) -> bool:
    if str(current.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE":
        return True
    if str(current.get("strong_lead_candidate_state") or "") == "STRONG_LEAD_REVIEW_CANDIDATE":
        return True
    if str(current.get("stage5_operational_primary_track") or "") == "strong_lead":
        return True
    return False


def _is_public_identifier_backfilled(state: str) -> bool:
    return state in {
        "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        "GDCIC_PROJECT_CODE_ROUTE_READY",
    }


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


def _multi_value_counts(values: list[Any]) -> dict[str, int]:
    expanded: list[str] = []
    for value in values:
        for part in str(value or "").split("|"):
            text = part.strip()
            if text:
                expanded.append(text)
    return _counts(expanded)


def _stage4_public_readback_outcome_counts(project_rows: list[Mapping[str, Any]]) -> dict[str, int]:
    outcomes: list[str] = []
    for row in project_rows:
        original_state = str(row.get("p13b_original_notice_readback_state") or "").strip().upper()
        ygp_state = str(row.get("p13b_ygp_original_readback_state") or "").strip().upper()
        local_authority_count = _int(row.get("p13b_local_authority_source_task_count"))
        local_authority_readback_counts = dict(row.get("p13b_local_authority_executed_readback_state_counts") or {})
        design_registry_state = str(row.get("design_survey_public_registry_readback_state") or "").strip().upper()
        if original_state == "MATCHED":
            outcomes.append("MATCHED")
        elif original_state == "NOT_FOUND":
            outcomes.append("NOT_FOUND")
        elif original_state == "BLOCKED":
            outcomes.append("BLOCKED")
        if ygp_state == "YGP_READBACK_READY":
            outcomes.append("READBACK_READY")
        elif ygp_state == "YGP_BLOCKED":
            outcomes.append("BLOCKED")
        if local_authority_count:
            outcomes.append("LOCAL_AUTHORITY_PLAN_READY")
        for state in ("MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"):
            for _ in range(_int(local_authority_readback_counts.get(state))):
                outcomes.append(state)
        if design_registry_state in {"MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"}:
            outcomes.append(design_registry_state)
        elif design_registry_state in {"FAIL_CLOSED_QUERY_ERROR", "PUBLIC_SNAPSHOT_OR_RUNTIME_ADAPTER_REQUIRED"}:
            outcomes.append("BLOCKED")
    return _counts(outcomes)


def _stage4_public_readback_channel_outcome_counts(project_rows: list[Mapping[str, Any]]) -> dict[str, int]:
    outcomes: list[str] = []
    for row in project_rows:
        original_state = str(row.get("p13b_original_notice_readback_state") or "").strip().upper()
        ygp_state = str(row.get("p13b_ygp_original_readback_state") or "").strip().upper()
        local_authority_readback_counts = dict(row.get("p13b_local_authority_executed_readback_state_counts") or {})
        design_registry_state = str(row.get("design_survey_public_registry_readback_state") or "").strip().upper()
        if original_state:
            outcomes.append(f"ORIGINAL_NOTICE:{original_state}")
        if ygp_state:
            outcomes.append(f"YGP:{ygp_state}")
        for state, count in local_authority_readback_counts.items():
            for _ in range(_int(count)):
                outcomes.append(f"LOCAL_AUTHORITY:{state}")
        if design_registry_state:
            outcomes.append(f"DESIGN_SURVEY_PUBLIC_REGISTRY:{design_registry_state}")
    return _counts(outcomes)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_set(value: list[str] | str | None) -> set[str]:
    if value is None:
        return set()
    values = value if isinstance(value, list) else [value]
    out: set[str] = set()
    for item in values:
        for part in str(item or "").replace(";", ",").split(","):
            text = part.strip()
            if text:
                out.add(text)
    return out


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
        f"- stage5_operational_review_family_counts: {json.dumps(scoreboard.get('stage5_operational_review_family_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage5_operational_signal_counts: {json.dumps(scoreboard.get('stage5_operational_signal_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage6_fact_ready_count: {scoreboard.get('stage6_fact_ready_count', 0)}",
        f"- stage7_sellable_count: {scoreboard.get('stage7_sellable_count', 0)}",
        f"- limited_sellable_review_candidate_count: {scoreboard.get('limited_sellable_review_candidate_count', 0)}",
        f"- real_public_sellable_pack_rate: {scoreboard.get('real_public_sellable_pack_rate', 0)}",
        f"- gdcic_authorized_readback_status: {json.dumps(scoreboard.get('gdcic_authorized_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p13b_public_source_readback_status: {json.dumps(scoreboard.get('p13b_public_source_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p13b_original_notice_readback_status: {json.dumps(scoreboard.get('p13b_original_notice_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p13b_ygp_original_readback_status: {json.dumps(scoreboard.get('p13b_ygp_original_readback_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p13b_overlap_triage_closeout_status: {json.dumps(scoreboard.get('p13b_overlap_triage_closeout_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_public_source_readback_state_counts: {json.dumps(scoreboard.get('stage4_public_source_readback_state_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_project_code_backfill_gap_detail_counts: {json.dumps(scoreboard.get('stage4_project_code_backfill_gap_detail_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_original_notice_readback_state_counts: {json.dumps(scoreboard.get('stage4_original_notice_readback_state_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_ygp_original_readback_state_counts: {json.dumps(scoreboard.get('stage4_ygp_original_readback_state_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_public_readback_outcome_counts: {json.dumps(scoreboard.get('stage4_public_readback_outcome_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage4_public_readback_channel_outcome_counts: {json.dumps(scoreboard.get('stage4_public_readback_channel_outcome_counts', {}), ensure_ascii=False, sort_keys=True)}",
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
    parser.add_argument("--supplemental-field-query-root", default="")
    parser.add_argument("--supplemental-field-query-json", default="")
    parser.add_argument("--gdcic-browser-readback-root", default=str(DEFAULT_GDCIC_BROWSER_READBACK_ROOT))
    parser.add_argument("--gdcic-browser-readback-json", default="")
    parser.add_argument("--p13b-company-history-root", default=str(DEFAULT_P13B_COMPANY_HISTORY_ROOT))
    parser.add_argument("--p13b-company-history-json", default="")
    parser.add_argument("--p13b-original-notice-backtrace-root", default=str(DEFAULT_P13B_ORIGINAL_NOTICE_BACKTRACE_ROOT))
    parser.add_argument("--p13b-original-notice-backtrace-json", default="")
    parser.add_argument("--p13b-ygp-original-readback-root", default=str(DEFAULT_P13B_YGP_ORIGINAL_READBACK_ROOT))
    parser.add_argument("--p13b-ygp-original-readback-json", default="")
    parser.add_argument("--p13b-overlap-triage-closeout-root", default=str(DEFAULT_P13B_OVERLAP_TRIAGE_CLOSEOUT_ROOT))
    parser.add_argument("--p13b-overlap-triage-closeout-json", default="")
    parser.add_argument("--company-first-stage4-execution-root", default="")
    parser.add_argument("--company-first-stage4-execution-json", default="")
    parser.add_argument(
        "--design-survey-public-registry-readback-root",
        default=str(DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT),
    )
    parser.add_argument("--design-survey-public-registry-readback-json", default="")
    parser.add_argument("--stage6-status-root", default=str(DEFAULT_STAGE6_STATUS_ROOT))
    parser.add_argument("--stage6-status-json", default="")
    parser.add_argument("--prior-scoreboard-json", default="")
    parser.add_argument("--incremental-project-ids", default="")
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
        supplemental_field_query_root=args.supplemental_field_query_root or None,
        supplemental_field_query_json=args.supplemental_field_query_json or None,
        gdcic_browser_readback_root=args.gdcic_browser_readback_root,
        gdcic_browser_readback_json=args.gdcic_browser_readback_json or None,
        p13b_company_history_root=args.p13b_company_history_root,
        p13b_company_history_json=args.p13b_company_history_json or None,
        p13b_original_notice_backtrace_root=args.p13b_original_notice_backtrace_root,
        p13b_original_notice_backtrace_json=args.p13b_original_notice_backtrace_json or None,
        p13b_ygp_original_readback_root=args.p13b_ygp_original_readback_root,
        p13b_ygp_original_readback_json=args.p13b_ygp_original_readback_json or None,
        p13b_overlap_triage_closeout_root=args.p13b_overlap_triage_closeout_root,
        p13b_overlap_triage_closeout_json=args.p13b_overlap_triage_closeout_json or None,
        company_first_stage4_execution_root=args.company_first_stage4_execution_root or None,
        company_first_stage4_execution_json=args.company_first_stage4_execution_json or None,
        design_survey_public_registry_readback_root=args.design_survey_public_registry_readback_root or None,
        design_survey_public_registry_readback_json=args.design_survey_public_registry_readback_json or None,
        stage6_status_root=args.stage6_status_root,
        stage6_status_json=args.stage6_status_json or None,
        prior_scoreboard_json=args.prior_scoreboard_json or None,
        incremental_project_ids=args.incremental_project_ids or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["scoreboard"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
