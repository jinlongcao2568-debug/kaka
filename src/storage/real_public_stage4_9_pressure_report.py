from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from api.routes.operator_customer_access import run_operator_autonomous_opportunity_search
from shared.utils import utc_now_iso


REAL_PUBLIC_STAGE4_9_PRESSURE_REPORT_KIND = "real_public_stage4_9_pressure_report_v1_manifest"
REAL_PUBLIC_STAGE4_9_PRESSURE_REPORT_VERSION = 1
REAL_PUBLIC_STAGE4_9_PRESSURE_REPORT_ADAPTER_ID = "real-public-stage4-9-pressure-report-v1-builder"

DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-real-public-stage4-9-pressure-v1")
DEFAULT_RUN_RESULT_JSON = DEFAULT_OUTPUT_ROOT / "run-result.json"
DEFAULT_PRESSURE_SUMMARY_JSON = DEFAULT_OUTPUT_ROOT / "pressure-summary.json"
DEFAULT_SOURCE_PROFILE_IDS = ("GUANGZHOU-YWTB-CONSTRUCTION-LIST",)
DEFAULT_PROJECT_TYPES = ("construction", "municipal", "water_conservancy", "highway")
DEFAULT_TARGET_ACCEPTED_CANDIDATE_COUNT = 10
DEFAULT_DETAIL_CAPTURE_LIMIT = 10
DEFAULT_ATTACHMENT_CAPTURE_LIMIT = 20
DEFAULT_STAGE2_DETAIL_CAPTURE_TIME_BUDGET_SECONDS = 600
DEFAULT_STAGE1_6_TIME_BUDGET_SECONDS = 600

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
SearchRunner = Callable[[Mapping[str, Any]], dict[str, Any]]


def run_real_public_stage4_9_pressure(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    region_codes: list[str] | tuple[str, ...] = ("CN-GD",),
    source_profile_ids: list[str] | tuple[str, ...] = DEFAULT_SOURCE_PROFILE_IDS,
    project_types: list[str] | tuple[str, ...] = DEFAULT_PROJECT_TYPES,
    query: str = "中标候选人公示",
    candidate_limit: int = DEFAULT_TARGET_ACCEPTED_CANDIDATE_COUNT,
    detail_capture_limit: int = DEFAULT_DETAIL_CAPTURE_LIMIT,
    attachment_capture_limit: int = DEFAULT_ATTACHMENT_CAPTURE_LIMIT,
    stage2_detail_capture_time_budget_seconds: float = DEFAULT_STAGE2_DETAIL_CAPTURE_TIME_BUDGET_SECONDS,
    stage1_6_time_budget_seconds: float = DEFAULT_STAGE1_6_TIME_BUDGET_SECONDS,
    discovery_profile_limit_per_region: int = 1,
    search_runner: SearchRunner | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "region_codes": list(region_codes),
        "source_profile_ids": list(source_profile_ids),
        "project_types": list(project_types),
        "query": query,
        "notice_stage": "candidate_notice",
        "discovery_profile_limit_per_region": discovery_profile_limit_per_region,
        "candidate_limit": candidate_limit,
        "detail_capture_limit": detail_capture_limit,
        "attachment_capture_limit": attachment_capture_limit,
        "stage2_detail_capture_time_budget_seconds": stage2_detail_capture_time_budget_seconds,
        "stage1_6_time_budget_seconds": stage1_6_time_budget_seconds,
        "allow_offline_sample_candidates": False,
        "trace_mode": "GUANGZHOU_REAL_PUBLIC_STAGE4_9_PRESSURE",
        "now": created,
    }
    runner = search_runner or run_operator_autonomous_opportunity_search
    env_updates = {
        "KAKA_STORAGE_BACKEND": "json-file",
        "KAKA_STORAGE_PATH": str(out_dir / "store.json"),
        "KAKA_OBJECT_STORAGE_PATH": str(out_dir / "objects"),
    }
    old_env = {key: os.environ.get(key) for key in env_updates}
    old_database_url = os.environ.get("KAKA_STORAGE_DATABASE_URL")
    try:
        for key, value in env_updates.items():
            os.environ[key] = value
        os.environ.pop("KAKA_STORAGE_DATABASE_URL", None)
        result = runner(payload)
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if old_database_url is None:
            os.environ.pop("KAKA_STORAGE_DATABASE_URL", None)
        else:
            os.environ["KAKA_STORAGE_DATABASE_URL"] = old_database_url

    summary = build_real_public_stage4_9_pressure_summary(
        result,
        payload=payload,
        target_accepted_candidate_count=candidate_limit,
    )
    _write_json(out_dir / "run-result.json", result)
    _write_json(out_dir / "pressure-summary.json", summary)
    return {
        "mode": "RUN",
        "output_root": str(out_dir),
        "run_result_path": str(out_dir / "run-result.json"),
        "pressure_summary_path": str(out_dir / "pressure-summary.json"),
        "result": result,
        "summary": summary,
    }


def build_real_public_stage4_9_pressure_summary(
    result: Mapping[str, Any],
    *,
    payload: Mapping[str, Any],
    target_accepted_candidate_count: int = DEFAULT_TARGET_ACCEPTED_CANDIDATE_COUNT,
) -> dict[str, Any]:
    search_scope = dict(result.get("search_scope") or {})
    raw_candidates = [
        dict(item)
        for item in list(result.get("candidate_options") or [])
        if isinstance(item, Mapping)
    ]
    closed_loop_results = [
        dict(item)
        for item in list(result.get("closed_loop_results") or [])
        if isinstance(item, Mapping)
    ]
    readbacks = [
        dict(item.get("real_public_stage4_9_readback") or {})
        for item in closed_loop_results
        if isinstance(item.get("real_public_stage4_9_readback"), Mapping)
    ]
    remaining_real_world_gap_counts = _flatten_count(
        readbacks, "remaining_real_world_gaps"
    )
    fail_closed_reason_counts = _flatten_count(readbacks, "fail_closed_reasons")
    stage1_6_readiness_records = _stage1_6_readiness_records(result)
    stage1_6_gap_summary_records = _stage1_6_gap_summary_records(stage1_6_readiness_records)
    company_first_required_count = sum(
        1 for readback in readbacks if bool(readback.get("jzsc_company_first_identity_resolution_required"))
    )
    selected_candidate_count = _as_int(search_scope.get("selected_candidate_count"), len(raw_candidates))
    coverage_state = (
        "FULL_TARGET_COVERAGE"
        if selected_candidate_count >= target_accepted_candidate_count
        else "PARTIAL_SOURCE_COVERAGE"
    )
    summary = {
        "surface_id": "guangzhou_real_public_stage4_9_pressure_summary",
        "generated_at": utc_now_iso(),
        "target_accepted_candidate_count": target_accepted_candidate_count,
        "coverage_state": coverage_state,
        "candidate_count": _as_int(search_scope.get("candidate_count"), len(raw_candidates)),
        "selected_candidate_count": selected_candidate_count,
        "closed_loop_results_count": len(closed_loop_results),
        "real_public_stage4_9_chain_state_counts": _status_counts(closed_loop_results, "real_public_stage4_9_chain_state"),
        "real_public_stage1_6_chain_state_counts": _status_counts(closed_loop_results, "real_public_stage1_6_chain_state"),
        "real_world_hard_defect_gate_state_counts": _status_counts(closed_loop_results, "real_world_hard_defect_gate_state"),
        "stage5_rule_gate_status_counts": _status_counts(readbacks, "stage5_rule_gate_status"),
        "stage5_evidence_gate_status_counts": _status_counts(readbacks, "stage5_evidence_gate_status"),
        "company_first_identity_resolution_required_count": company_first_required_count,
        "remaining_real_world_gap_counts": remaining_real_world_gap_counts,
        "fail_closed_reason_counts": fail_closed_reason_counts,
        "stage1_6_readiness_state_counts": _status_counts(stage1_6_readiness_records, "stage1_6_readiness_state"),
        "stage1_6_bottleneck_stage_counts": _status_counts(stage1_6_readiness_records, "bottleneck_stage"),
        "stage1_6_readiness_record_count": len(stage1_6_readiness_records),
        "stage1_6_gap_summary_record_count": len(stage1_6_gap_summary_records),
        "customer_sellable_evidence_ready_count": sum(
            1 for readback in readbacks if bool(readback.get("customer_sellable_evidence_ready"))
        ),
        "input_payload": dict(payload),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PENDING",
    }
    _apply_forbidden_term_scan(summary)
    return summary


def build_real_public_stage4_9_pressure_report(
    *,
    run_result_json: str | Path = DEFAULT_RUN_RESULT_JSON,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    target_accepted_candidate_count: int = DEFAULT_TARGET_ACCEPTED_CANDIDATE_COUNT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    run_result_path = Path(run_result_json)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    result = _load_json(run_result_path, blocking_reasons, "run_result_missing")
    payload = dict(result.get("search_scope") or {})
    summary = build_real_public_stage4_9_pressure_summary(
        result,
        payload=payload,
        target_accepted_candidate_count=target_accepted_candidate_count,
    )
    candidate_records = _candidate_pressure_records(result)
    stage1_6_readiness_records = _stage1_6_readiness_records(result)
    stage1_6_gap_summary_records = _stage1_6_gap_summary_records(stage1_6_readiness_records)
    gap_records = _gap_summary_records(candidate_records)
    manifest = {
        "manifest_version": REAL_PUBLIC_STAGE4_9_PRESSURE_REPORT_VERSION,
        "manifest_kind": REAL_PUBLIC_STAGE4_9_PRESSURE_REPORT_KIND,
        "adapter_id": REAL_PUBLIC_STAGE4_9_PRESSURE_REPORT_ADAPTER_ID,
        "pipeline_stage": "GuangzhouRealPublicStage49PressureV1",
        "manifest_id": f"REAL-PUBLIC-STAGE49-PRESSURE-{_fingerprint({'summary': summary, 'candidates': candidate_records})[:16]}",
        "created_at": created,
        "source_run_result_json": str(run_result_path),
        "summary": summary,
        "candidate_pressure_records": candidate_records,
        "stage1_6_readiness_records": stage1_6_readiness_records,
        "stage1_6_gap_summary_records": stage1_6_gap_summary_records,
        "gap_summary_records": gap_records,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    report = {
        "real_public_stage4_9_pressure_report_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _apply_forbidden_term_scan(report)
    _write_json(out_dir / "real-public-stage4-9-pressure-report-v1.json", report)
    _write_json(out_dir / "candidate-pressure-table.json", {"summary": summary, "records": candidate_records})
    _write_json(out_dir / "stage1-6-readiness-table.json", {"summary": summary, "records": stage1_6_readiness_records})
    _write_json(out_dir / "stage1-6-gap-summary-table.json", {"summary": summary, "records": stage1_6_gap_summary_records})
    _write_json(out_dir / "gap-summary-table.json", {"summary": summary, "records": gap_records})
    return report


def _candidate_pressure_records(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    closed_loop_by_project_id = {
        str(item.get("project_id") or ""): dict(item)
        for item in list(result.get("closed_loop_results") or [])
        if isinstance(item, Mapping) and str(item.get("project_id") or "").strip()
    }
    rows: list[dict[str, Any]] = []
    for option in list(result.get("candidate_options") or []):
        if not isinstance(option, Mapping):
            continue
        row = dict(option)
        project_id = str(row.get("project_id") or "")
        closed_loop = dict(closed_loop_by_project_id.get(project_id) or {})
        readback = dict(closed_loop.get("real_public_stage4_9_readback") or {})
        rows.append(
            {
                "project_id": project_id,
                "project_name": str(row.get("project_name") or ""),
                "source_url": str(row.get("source_url") or ""),
                "notice_stage": str(row.get("notice_stage") or ""),
                "candidate_company": str(row.get("candidate_company") or row.get("winner_name") or ""),
                "stage2_detail_capture_state": str(row.get("stage2_detail_capture_state") or ""),
                "stage3_parse_state": str(row.get("stage3_parse_state") or ""),
                "real_public_stage4_9_chain_state": str(
                    row.get("real_public_stage4_9_chain_state") or closed_loop.get("real_public_stage4_9_chain_state") or ""
                ),
                "real_public_stage1_6_chain_state": str(
                    row.get("real_public_stage1_6_chain_state") or closed_loop.get("real_public_stage1_6_chain_state") or ""
                ),
                "real_world_hard_defect_gate_state": str(
                    row.get("real_world_hard_defect_gate_state") or closed_loop.get("real_world_hard_defect_gate_state") or ""
                ),
                "stage5_rule_gate_status": str(readback.get("stage5_rule_gate_status") or ""),
                "stage5_evidence_gate_status": str(readback.get("stage5_evidence_gate_status") or ""),
                "stage2_detail_capture_pending": bool(row.get("stage2_detail_capture_pending")),
                "stage1_6_time_budget_pending": bool(row.get("stage1_6_time_budget_pending")),
                "customer_sellable_evidence_ready": bool(
                    row.get("customer_sellable_evidence_ready") or closed_loop.get("customer_sellable_evidence_ready")
                ),
                "jzsc_company_first_identity_resolution_required": bool(
                    readback.get("jzsc_company_first_identity_resolution_required")
                ),
                "responsible_role_gap_code": str(row.get("responsible_role_gap_code") or ""),
                "remaining_real_world_gaps": _string_list(readback.get("remaining_real_world_gaps")),
                "fail_closed_reasons": _string_list(closed_loop.get("fail_closed_reasons") or readback.get("fail_closed_reasons")),
                "recommended_next_action": _candidate_next_action(
                    row=row,
                    closed_loop=closed_loop,
                    readback=readback,
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _candidate_next_action(
    *,
    row: Mapping[str, Any],
    closed_loop: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> str:
    if bool(row.get("stage2_detail_capture_pending")):
        return "increase_detail_capture_limit_or_stage2_detail_capture_time_budget"
    if bool(row.get("stage1_6_time_budget_pending")):
        return "increase_stage1_6_time_budget"
    if bool(readback.get("jzsc_company_first_identity_resolution_required")):
        return "run_company_first_identifier_resolution_before_sellable_evidence"
    if _string_list(readback.get("remaining_real_world_gaps")):
        return "keep_internal_review_and_register_source_gap"
    if str(closed_loop.get("real_public_stage4_9_chain_state") or "") == "INTERNAL_READY" and not bool(
        closed_loop.get("customer_sellable_evidence_ready")
    ):
        return "advance_to_stage7_9_internal_review"
    return "keep_internal_review_and_register_source_gap"


def _gap_summary_records(candidate_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in candidate_records:
        project_id = str(row.get("project_id") or "")
        if row.get("responsible_role_gap_code"):
            _accumulate_gap(
                grouped,
                gap_family="responsible_role_gap_code",
                gap_value=str(row.get("responsible_role_gap_code") or ""),
                project_id=project_id,
                next_action="run_company_first_identifier_resolution_before_sellable_evidence",
            )
        for gap in _string_list(row.get("remaining_real_world_gaps")):
            _accumulate_gap(
                grouped,
                gap_family="remaining_real_world_gap",
                gap_value=gap,
                project_id=project_id,
                next_action="keep_internal_review_and_register_source_gap",
            )
        for reason in _string_list(row.get("fail_closed_reasons")):
            next_action = (
                "increase_detail_capture_limit_or_stage2_detail_capture_time_budget"
                if "detail_capture" in reason
                else "increase_stage1_6_time_budget"
                if "time_budget" in reason
                else "keep_internal_review_and_register_source_gap"
            )
            _accumulate_gap(
                grouped,
                gap_family="fail_closed_reason",
                gap_value=reason,
                project_id=project_id,
                next_action=next_action,
            )
    return sorted(grouped.values(), key=lambda item: (-_as_int(item.get("count")), item.get("gap_family"), item.get("gap_value")))


def _stage1_6_readiness_records(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    closed_loop_by_project_id = {
        str(item.get("project_id") or ""): dict(item)
        for item in list(result.get("closed_loop_results") or [])
        if isinstance(item, Mapping) and str(item.get("project_id") or "").strip()
    }
    rows: list[dict[str, Any]] = []
    for option in list(result.get("candidate_options") or []):
        if not isinstance(option, Mapping):
            continue
        row = dict(option)
        project_id = str(row.get("project_id") or "")
        closed_loop = dict(closed_loop_by_project_id.get(project_id) or {})
        readback = dict(closed_loop.get("real_public_stage4_9_readback") or {})
        stage_states = _stage1_6_stage_states(row=row, closed_loop=closed_loop, readback=readback)
        bottleneck_stage = _stage1_6_bottleneck_stage(stage_states)
        readiness_state = _stage1_6_readiness_state(
            row=row,
            closed_loop=closed_loop,
            readback=readback,
            bottleneck_stage=bottleneck_stage,
        )
        rows.append(
            {
                "project_id": project_id,
                "project_name": str(row.get("project_name") or ""),
                "source_url": str(row.get("source_url") or ""),
                "notice_stage": str(row.get("notice_stage") or ""),
                "candidate_company": str(row.get("candidate_company") or row.get("winner_name") or ""),
                "stage1_candidate_discovery_state": stage_states["stage1"],
                "stage2_detail_capture_state": stage_states["stage2"],
                "stage3_field_parse_state": stage_states["stage3"],
                "stage4_public_verification_state": stage_states["stage4"],
                "stage5_gate_state": stage_states["stage5"],
                "stage6_fact_package_state": stage_states["stage6"],
                "bottleneck_stage": bottleneck_stage,
                "stage1_6_readiness_state": readiness_state,
                "stage1_6_closed_loop_ready": bool(
                    row.get("stage1_6_closed_loop_ready")
                    or closed_loop.get("stage1_6_closed_loop_ready")
                    or str(closed_loop.get("real_public_stage1_6_chain_state") or "") == "INTERNAL_READY"
                    or str(row.get("real_public_stage1_6_chain_state") or "") == "INTERNAL_READY"
                ),
                "responsible_role_gap_code": str(row.get("responsible_role_gap_code") or ""),
                "remaining_real_world_gaps": _string_list(readback.get("remaining_real_world_gaps")),
                "fail_closed_reasons": _string_list(closed_loop.get("fail_closed_reasons") or readback.get("fail_closed_reasons")),
                "stage5_rule_gate_status": str(readback.get("stage5_rule_gate_status") or ""),
                "stage5_evidence_gate_status": str(readback.get("stage5_evidence_gate_status") or ""),
                "recommended_next_action": _stage1_6_next_action(
                    row=row,
                    closed_loop=closed_loop,
                    readback=readback,
                    bottleneck_stage=bottleneck_stage,
                    readiness_state=readiness_state,
                ),
                "query_miss_is_not_clearance": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _stage1_6_stage_states(
    *,
    row: Mapping[str, Any],
    closed_loop: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> dict[str, str]:
    stage2_state = str(row.get("stage2_detail_capture_state") or "")
    stage3_state = str(row.get("stage3_parse_state") or "")
    chain_state = str(
        row.get("real_public_stage1_6_chain_state")
        or closed_loop.get("real_public_stage1_6_chain_state")
        or ""
    )
    hard_gate_state = str(
        row.get("real_world_hard_defect_gate_state")
        or closed_loop.get("real_world_hard_defect_gate_state")
        or ""
    )
    rule_gate = str(readback.get("stage5_rule_gate_status") or "")
    evidence_gate = str(readback.get("stage5_evidence_gate_status") or "")
    remaining_gaps = _string_list(readback.get("remaining_real_world_gaps"))
    fail_reasons = _string_list(closed_loop.get("fail_closed_reasons") or readback.get("fail_closed_reasons"))
    stage1 = "CANDIDATE_DISCOVERED" if row.get("project_id") or row.get("source_url") else "CANDIDATE_SOURCE_MISSING"
    if bool(row.get("stage2_detail_capture_pending")) or "PENDING_STAGE2_DETAIL_CAPTURE" in chain_state:
        stage2 = "PENDING_DETAIL_CAPTURE"
    elif "FAIL" in stage2_state.upper() or any("detail_capture" in reason and "pending" not in reason for reason in fail_reasons):
        stage2 = "DETAIL_CAPTURE_FAILED_REVIEW_REQUIRED"
    elif stage2_state:
        stage2 = stage2_state
    else:
        stage2 = "DETAIL_CAPTURE_STATE_UNKNOWN_REVIEW_REQUIRED"
    if stage2 == "PENDING_DETAIL_CAPTURE":
        stage3 = "PENDING_DETAIL_CAPTURE"
    elif "FAIL" in stage3_state.upper():
        stage3 = "FIELD_PARSE_FAILED_REVIEW_REQUIRED"
    elif str(row.get("responsible_role_gap_code") or ""):
        stage3 = "RESPONSIBLE_ROLE_GAP_REVIEW_REQUIRED"
    elif stage3_state:
        stage3 = stage3_state
    else:
        stage3 = "FIELD_PARSE_STATE_UNKNOWN_REVIEW_REQUIRED"
    if bool(row.get("stage1_6_time_budget_pending")) or "PENDING_TIME_BUDGET" in chain_state:
        stage4 = "PENDING_TIME_BUDGET"
    elif remaining_gaps:
        stage4 = "SOURCE_GAP_REVIEW_REQUIRED"
    elif hard_gate_state:
        stage4 = hard_gate_state
    else:
        stage4 = "PUBLIC_VERIFICATION_STATE_UNKNOWN_REVIEW_REQUIRED"
    if rule_gate == "PASS" and evidence_gate == "PASS":
        stage5 = "PASS"
    elif rule_gate or evidence_gate:
        stage5 = "REVIEW_REQUIRED"
    elif chain_state == "INTERNAL_READY":
        stage5 = "PASS_OR_NOT_REQUIRED_BY_CURRENT_READBACK"
    else:
        stage5 = "GATE_STATE_UNKNOWN_REVIEW_REQUIRED"
    if chain_state:
        stage6 = chain_state
    elif closed_loop:
        stage6 = "CHAIN_STATE_UNKNOWN_REVIEW_REQUIRED"
    else:
        stage6 = "NOT_ATTEMPTED"
    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "stage4": stage4,
        "stage5": stage5,
        "stage6": stage6,
    }


def _stage1_6_bottleneck_stage(stage_states: Mapping[str, str]) -> str:
    if stage_states.get("stage1") != "CANDIDATE_DISCOVERED":
        return "Stage1"
    stage2 = str(stage_states.get("stage2") or "")
    if "PENDING" in stage2 or "FAILED" in stage2 or "UNKNOWN" in stage2:
        return "Stage2"
    stage3 = str(stage_states.get("stage3") or "")
    if "PENDING" in stage3 or "FAILED" in stage3 or "GAP" in stage3 or "UNKNOWN" in stage3:
        return "Stage3"
    stage4 = str(stage_states.get("stage4") or "")
    if "PENDING" in stage4 or "GAP" in stage4 or "UNKNOWN" in stage4:
        return "Stage4"
    stage5 = str(stage_states.get("stage5") or "")
    if stage5 not in {"PASS", "PASS_OR_NOT_REQUIRED_BY_CURRENT_READBACK"}:
        return "Stage5"
    stage6 = str(stage_states.get("stage6") or "")
    if stage6 != "INTERNAL_READY":
        return "Stage6"
    return "READY"


def _stage1_6_readiness_state(
    *,
    row: Mapping[str, Any],
    closed_loop: Mapping[str, Any],
    readback: Mapping[str, Any],
    bottleneck_stage: str,
) -> str:
    if bool(row.get("stage2_detail_capture_pending")):
        return "PENDING_STAGE2_DETAIL_CAPTURE"
    if bool(row.get("stage1_6_time_budget_pending")):
        return "PENDING_TIME_BUDGET"
    if bool(row.get("stage1_6_closed_loop_ready") or closed_loop.get("stage1_6_closed_loop_ready")):
        return "STAGE1_6_INTERNAL_READY"
    if str(row.get("real_public_stage1_6_chain_state") or closed_loop.get("real_public_stage1_6_chain_state") or "") == "INTERNAL_READY":
        return "STAGE1_6_INTERNAL_READY"
    if bottleneck_stage == "Stage3":
        return "STAGE3_FIELD_OR_ROLE_REVIEW_REQUIRED"
    if bottleneck_stage == "Stage4":
        return "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED"
    if bottleneck_stage == "Stage5":
        return "STAGE5_GATE_REVIEW_REQUIRED"
    if bottleneck_stage == "Stage6":
        return "STAGE6_FACT_PACKAGE_REVIEW_REQUIRED"
    if _string_list(readback.get("remaining_real_world_gaps")):
        return "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED"
    return "REVIEW_REQUIRED"


def _stage1_6_next_action(
    *,
    row: Mapping[str, Any],
    closed_loop: Mapping[str, Any],
    readback: Mapping[str, Any],
    bottleneck_stage: str,
    readiness_state: str,
) -> str:
    if readiness_state == "PENDING_STAGE2_DETAIL_CAPTURE":
        return "increase_detail_capture_limit_or_stage2_detail_capture_time_budget"
    if readiness_state == "PENDING_TIME_BUDGET":
        return "increase_stage1_6_time_budget"
    if str(row.get("responsible_role_gap_code") or "") or bool(readback.get("jzsc_company_first_identity_resolution_required")):
        return "run_company_first_identifier_resolution_before_stage4_or_stage6"
    if bottleneck_stage == "Stage4":
        return "run_release_evidence_or_source_gap_adapter_for_stage4"
    if bottleneck_stage == "Stage5":
        return "review_stage5_rule_and_evidence_gate_inputs"
    if bottleneck_stage == "Stage6":
        return "rebuild_stage6_fact_package_and_review_queue"
    if bottleneck_stage == "READY":
        return "eligible_for_stage7_internal_review_only"
    return _candidate_next_action(row=row, closed_loop=closed_loop, readback=readback)


def _stage1_6_gap_summary_records(readiness_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in readiness_records:
        project_id = str(row.get("project_id") or "")
        bottleneck = str(row.get("bottleneck_stage") or "UNKNOWN")
        if bottleneck != "READY":
            _accumulate_gap(
                grouped,
                gap_family="stage1_6_bottleneck_stage",
                gap_value=bottleneck,
                project_id=project_id,
                next_action=str(row.get("recommended_next_action") or "review_stage1_6_bottleneck"),
            )
        readiness_state = str(row.get("stage1_6_readiness_state") or "")
        if readiness_state and readiness_state != "STAGE1_6_INTERNAL_READY":
            _accumulate_gap(
                grouped,
                gap_family="stage1_6_readiness_state",
                gap_value=readiness_state,
                project_id=project_id,
                next_action=str(row.get("recommended_next_action") or "review_stage1_6_readiness_state"),
            )
        if row.get("responsible_role_gap_code"):
            _accumulate_gap(
                grouped,
                gap_family="responsible_role_gap_code",
                gap_value=str(row.get("responsible_role_gap_code") or ""),
                project_id=project_id,
                next_action="run_company_first_identifier_resolution_before_stage4_or_stage6",
            )
        for gap in _string_list(row.get("remaining_real_world_gaps")):
            _accumulate_gap(
                grouped,
                gap_family="remaining_real_world_gap",
                gap_value=gap,
                project_id=project_id,
                next_action="run_release_evidence_or_source_gap_adapter_for_stage4",
            )
        for reason in _string_list(row.get("fail_closed_reasons")):
            _accumulate_gap(
                grouped,
                gap_family="fail_closed_reason",
                gap_value=reason,
                project_id=project_id,
                next_action=str(row.get("recommended_next_action") or "review_stage1_6_fail_closed_reason"),
            )
    return sorted(grouped.values(), key=lambda item: (-_as_int(item.get("count")), item.get("gap_family"), item.get("gap_value")))


def _accumulate_gap(
    grouped: dict[tuple[str, str], dict[str, Any]],
    *,
    gap_family: str,
    gap_value: str,
    project_id: str,
    next_action: str,
) -> None:
    key = (gap_family, gap_value)
    row = grouped.setdefault(
        key,
        {
            "gap_family": gap_family,
            "gap_value": gap_value,
            "count": 0,
            "project_ids": [],
            "recommended_next_action": next_action,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    )
    row["count"] = _as_int(row.get("count")) + 1
    row["project_ids"] = _dedupe_strings([*list(row.get("project_ids") or []), project_id])


def _status_counts(rows: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "UNKNOWN").strip() or "UNKNOWN"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _flatten_count(rows: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for value in _string_list(row.get(key)):
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _apply_forbidden_term_scan(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    target = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else payload
    if forbidden_hits:
        target["forbidden_term_scan_state"] = "FAIL"
        target["forbidden_term_hits"] = forbidden_hits
        payload["safe_to_execute"] = False
        payload["blocking_reasons"] = [
            *list(payload.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
    else:
        target["forbidden_term_scan_state"] = "PASS"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or build Guangzhou real-public Stage4-9 pressure artifacts.")
    parser.add_argument("--mode", choices=("run", "build"), required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-result-json", default=str(DEFAULT_RUN_RESULT_JSON))
    parser.add_argument("--query", default="中标候选人公示")
    parser.add_argument("--project-type", action="append", default=[])
    parser.add_argument("--source-profile-id", action="append", default=[])
    parser.add_argument("--candidate-limit", type=int, default=DEFAULT_TARGET_ACCEPTED_CANDIDATE_COUNT)
    parser.add_argument("--detail-capture-limit", type=int, default=DEFAULT_DETAIL_CAPTURE_LIMIT)
    parser.add_argument("--attachment-capture-limit", type=int, default=DEFAULT_ATTACHMENT_CAPTURE_LIMIT)
    parser.add_argument(
        "--stage2-detail-capture-time-budget-seconds",
        type=float,
        default=DEFAULT_STAGE2_DETAIL_CAPTURE_TIME_BUDGET_SECONDS,
    )
    parser.add_argument(
        "--stage1-6-time-budget-seconds",
        type=float,
        default=DEFAULT_STAGE1_6_TIME_BUDGET_SECONDS,
    )
    parser.add_argument("--discovery-profile-limit-per-region", type=int, default=1)
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.mode == "run":
        result = run_real_public_stage4_9_pressure(
            output_root=args.output_root,
            query=args.query,
            source_profile_ids=args.source_profile_id or list(DEFAULT_SOURCE_PROFILE_IDS),
            project_types=args.project_type or list(DEFAULT_PROJECT_TYPES),
            candidate_limit=args.candidate_limit,
            detail_capture_limit=args.detail_capture_limit,
            attachment_capture_limit=args.attachment_capture_limit,
            stage2_detail_capture_time_budget_seconds=args.stage2_detail_capture_time_budget_seconds,
            stage1_6_time_budget_seconds=args.stage1_6_time_budget_seconds,
            discovery_profile_limit_per_region=args.discovery_profile_limit_per_region,
        )
        payload: Mapping[str, Any] = result if args.emit_json else result["summary"]
    else:
        result = build_real_public_stage4_9_pressure_report(
            run_result_json=args.run_result_json,
            output_root=args.output_root,
            target_accepted_candidate_count=args.candidate_limit,
        )
        payload = result if args.emit_json else result["summary"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
