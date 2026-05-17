from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from api.routes.operator_customer_access import run_operator_autonomous_opportunity_search
from shared.utils import utc_now_iso
from storage.real_public_stage4_9_pressure_report import (
    build_real_public_stage4_9_pressure_report,
    build_real_public_stage4_9_pressure_summary,
)


GUANGZHOU_STAGE4_9_REMEDIATION_DELTA_KIND = "guangzhou_stage4_9_remediation_delta_report_v1_manifest"
GUANGZHOU_STAGE4_9_REMEDIATION_DELTA_VERSION = 1
GUANGZHOU_STAGE4_9_REMEDIATION_DELTA_ADAPTER_ID = "guangzhou-stage4-9-remediation-delta-report-v1-builder"

DEFAULT_BASELINE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-real-public-stage4-9-pressure-v1")
DEFAULT_BASELINE_RUN_RESULT_JSON = DEFAULT_BASELINE_ROOT / "run-result.json"
DEFAULT_BASELINE_CANDIDATE_PRESSURE_JSON = DEFAULT_BASELINE_ROOT / "candidate-pressure-table.json"
DEFAULT_COMPANY_FIRST_REMEDIATION_JSON = Path(
    "tmp/evaluation-real-samples/guangzhou-stage4-company-first-remediation-v1/company-first-remediation-v1.json"
)
DEFAULT_SOURCE_GAP_PROBE_JSON = Path(
    "tmp/evaluation-real-samples/guangzhou-stage4-source-gap-probe-v1/stage4-source-gap-probe-v1.json"
)
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-stage4-9-remediation-replay-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
SearchRunner = Callable[[Mapping[str, Any]], dict[str, Any]]


def run_guangzhou_stage4_9_remediation_replay(
    *,
    baseline_run_result_json: str | Path = DEFAULT_BASELINE_RUN_RESULT_JSON,
    baseline_candidate_pressure_json: str | Path = DEFAULT_BASELINE_CANDIDATE_PRESSURE_JSON,
    company_first_remediation_json: str | Path = DEFAULT_COMPANY_FIRST_REMEDIATION_JSON,
    source_gap_probe_json: str | Path = DEFAULT_SOURCE_GAP_PROBE_JSON,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    candidate_limit: int = 10,
    detail_capture_limit: int = 10,
    attachment_capture_limit: int = 20,
    stage2_detail_capture_time_budget_seconds: float = 600,
    stage1_6_time_budget_seconds: float = 600,
    search_runner: SearchRunner | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_run_path = Path(baseline_run_result_json)
    baseline_candidate_path = Path(baseline_candidate_pressure_json)
    remediation_path = Path(company_first_remediation_json)
    source_gap_path = Path(source_gap_probe_json)

    blocking_reasons: list[str] = []
    baseline_run = _load_json(baseline_run_path, blocking_reasons, "baseline_run_result_missing")
    baseline_candidate_table = _load_json(baseline_candidate_path, blocking_reasons, "baseline_candidate_pressure_missing")
    remediation = _load_json(remediation_path, blocking_reasons, "company_first_remediation_missing")
    source_gap = _load_json(source_gap_path, blocking_reasons, "source_gap_probe_missing")

    replay_candidates = _build_replay_candidates(
        baseline_run_result=baseline_run,
        baseline_candidate_table=baseline_candidate_table,
        remediation=remediation,
        source_gap=source_gap,
    )
    payload = {
        "region_codes": ["CN-GD"],
        "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
        "project_types": ["construction", "municipal", "water_conservancy", "highway"],
        "query": "中标候选人公示",
        "notice_stage": "candidate_notice",
        "candidate_limit": candidate_limit,
        "detail_capture_limit": detail_capture_limit,
        "attachment_capture_limit": attachment_capture_limit,
        "stage2_detail_capture_time_budget_seconds": stage2_detail_capture_time_budget_seconds,
        "stage1_6_time_budget_seconds": stage1_6_time_budget_seconds,
        "allow_offline_sample_candidates": False,
        "trace_mode": "GUANGZHOU_STAGE4_9_REMEDIATION_REPLAY",
        "notice_candidates": replay_candidates,
        "now": created,
    }
    runner = search_runner or run_operator_autonomous_opportunity_search
    _seed_replay_storage_from_baseline(
        baseline_root=baseline_run_path.parent,
        replay_root=out_dir,
    )
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
        replay_result = runner(payload)
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

    replay_summary = build_real_public_stage4_9_pressure_summary(
        replay_result,
        payload=payload,
        target_accepted_candidate_count=candidate_limit,
    )
    _write_json(out_dir / "replay-input-candidates.json", {"records": replay_candidates})
    _write_json(out_dir / "run-result.json", replay_result)
    _write_json(out_dir / "pressure-summary.json", replay_summary)
    build_real_public_stage4_9_pressure_report(
        run_result_json=out_dir / "run-result.json",
        output_root=out_dir,
        target_accepted_candidate_count=candidate_limit,
    )
    delta_report = build_guangzhou_stage4_9_remediation_delta_report(
        baseline_run_result_json=baseline_run_path,
        baseline_candidate_pressure_json=baseline_candidate_path,
        company_first_remediation_json=remediation_path,
        source_gap_probe_json=source_gap_path,
        replay_run_result_json=out_dir / "run-result.json",
        replay_candidate_pressure_json=out_dir / "candidate-pressure-table.json",
        output_root=out_dir,
        target_accepted_candidate_count=candidate_limit,
    )
    return {
        "mode": "RUN_REPLAY_AND_BUILD_DELTA",
        "safe_to_execute": not blocking_reasons and bool(delta_report.get("safe_to_execute", True)),
        "blocking_reasons": [*blocking_reasons, *list(delta_report.get("blocking_reasons") or [])],
        "output_root": str(out_dir),
        "replay_result": replay_result,
        "replay_summary": replay_summary,
        "delta_report": delta_report,
        "summary": dict(delta_report.get("summary") or replay_summary),
    }


def build_guangzhou_stage4_9_remediation_delta_report(
    *,
    baseline_run_result_json: str | Path = DEFAULT_BASELINE_RUN_RESULT_JSON,
    baseline_candidate_pressure_json: str | Path = DEFAULT_BASELINE_CANDIDATE_PRESSURE_JSON,
    company_first_remediation_json: str | Path = DEFAULT_COMPANY_FIRST_REMEDIATION_JSON,
    source_gap_probe_json: str | Path = DEFAULT_SOURCE_GAP_PROBE_JSON,
    replay_run_result_json: str | Path,
    replay_candidate_pressure_json: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    target_accepted_candidate_count: int = 10,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    baseline_run = _load_json(Path(baseline_run_result_json), blocking_reasons, "baseline_run_result_missing")
    replay_run = _load_json(Path(replay_run_result_json), blocking_reasons, "replay_run_result_missing")
    baseline_candidate_table = _load_json(Path(baseline_candidate_pressure_json), blocking_reasons, "baseline_candidate_pressure_missing")
    replay_candidate_table = _load_json(Path(replay_candidate_pressure_json), blocking_reasons, "replay_candidate_pressure_missing")
    remediation = _load_json(Path(company_first_remediation_json), blocking_reasons, "company_first_remediation_missing")
    source_gap = _load_json(Path(source_gap_probe_json), blocking_reasons, "source_gap_probe_missing")

    baseline_summary = build_real_public_stage4_9_pressure_summary(
        baseline_run,
        payload=dict(baseline_run.get("search_scope") or {}),
        target_accepted_candidate_count=target_accepted_candidate_count,
    )
    replay_summary = build_real_public_stage4_9_pressure_summary(
        replay_run,
        payload=dict(replay_run.get("search_scope") or {}),
        target_accepted_candidate_count=target_accepted_candidate_count,
    )
    remediation_summary = dict(remediation.get("summary") or {})
    source_gap_summary = dict(source_gap.get("summary") or {})
    project_code_resolution_failure_counts_before = _project_code_resolution_failure_counts_from_summary(
        baseline_summary
    )
    project_code_resolution_failure_counts_after = _project_code_resolution_failure_counts_from_summary(
        replay_summary,
        fallback_counts=dict(source_gap_summary.get("project_code_resolution_failure_counts") or {}),
    )

    baseline_candidates = _candidate_table_by_project(baseline_candidate_table)
    replay_candidates = _candidate_table_by_project(replay_candidate_table)
    remediation_candidates = _candidate_table_by_project(remediation)
    source_gap_candidates = _candidate_table_by_project(source_gap)
    source_gap_project_code_failure_counts = _project_code_resolution_failure_counts_from_candidates(
        source_gap_candidates.values()
    )
    if not project_code_resolution_failure_counts_after and source_gap_project_code_failure_counts:
        project_code_resolution_failure_counts_after = source_gap_project_code_failure_counts

    candidate_delta_records = [
        _candidate_delta_record(
            project_id=project_id,
            baseline=baseline_candidates.get(project_id, {}),
            replay=replay_candidates.get(project_id, {}),
            remediation=remediation_candidates.get(project_id, {}),
            source_gap=source_gap_candidates.get(project_id, {}),
        )
        for project_id in sorted(set(baseline_candidates) | set(replay_candidates))
    ]
    gap_delta_records = _gap_delta_records(
        baseline_summary=baseline_summary,
        replay_summary=replay_summary,
        baseline_candidates=baseline_candidates,
        replay_candidates=replay_candidates,
    )
    summary = {
        "baseline_summary": baseline_summary,
        "replay_summary": replay_summary,
        "company_first_remediation_summary": remediation_summary,
        "source_gap_probe_summary": source_gap_summary,
        "company_first_identity_resolution_required_count_before": _as_int(
            baseline_summary.get("company_first_identity_resolution_required_count")
        ),
        "company_first_identity_resolution_required_count_after": _as_int(
            replay_summary.get("company_first_identity_resolution_required_count")
        ),
        "responsible_role_gap_code_count_before": sum(
            1 for row in baseline_candidates.values() if str(row.get("responsible_role_gap_code") or "").strip()
        ),
        "responsible_role_gap_code_count_after": sum(
            1 for row in replay_candidates.values() if str(row.get("responsible_role_gap_code") or "").strip()
        ),
        "stage5_evidence_gate_status_counts_before": dict(
            baseline_summary.get("stage5_evidence_gate_status_counts") or {}
        ),
        "stage5_evidence_gate_status_counts_after": dict(
            replay_summary.get("stage5_evidence_gate_status_counts") or {}
        ),
        "remaining_real_world_gap_counts_before": dict(
            baseline_summary.get("remaining_real_world_gap_counts") or {}
        ),
        "remaining_real_world_gap_counts_after": dict(
            replay_summary.get("remaining_real_world_gap_counts") or {}
        ),
        "project_code_resolution_failure_counts_before": project_code_resolution_failure_counts_before,
        "project_code_resolution_failure_counts_after": project_code_resolution_failure_counts_after,
        "candidate_delta_count": len(candidate_delta_records),
        "gap_delta_count": len(gap_delta_records),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PENDING",
    }
    manifest = {
        "manifest_version": GUANGZHOU_STAGE4_9_REMEDIATION_DELTA_VERSION,
        "manifest_kind": GUANGZHOU_STAGE4_9_REMEDIATION_DELTA_KIND,
        "adapter_id": GUANGZHOU_STAGE4_9_REMEDIATION_DELTA_ADAPTER_ID,
        "pipeline_stage": "GuangzhouStage49RemediationDeltaV1",
        "manifest_id": f"GUANGZHOU-STAGE49-DELTA-{_fingerprint({'summary': summary, 'candidates': candidate_delta_records})[:16]}",
        "created_at": created,
        "source_baseline_run_result_json": str(baseline_run_result_json),
        "source_replay_run_result_json": str(replay_run_result_json),
        "source_company_first_remediation_json": str(company_first_remediation_json),
        "source_source_gap_probe_json": str(source_gap_probe_json),
        "summary": summary,
        "candidate_delta_records": candidate_delta_records,
        "gap_delta_records": gap_delta_records,
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
    result = {
        "guangzhou_stage4_9_remediation_delta_report_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _apply_forbidden_term_scan(result)
    _write_json(out_dir / "stage4-9-remediation-delta-report-v1.json", result)
    _write_json(out_dir / "candidate-delta-table.json", {"summary": summary, "records": candidate_delta_records})
    _write_json(out_dir / "gap-delta-table.json", {"summary": summary, "records": gap_delta_records})
    return result


def _build_replay_candidates(
    *,
    baseline_run_result: Mapping[str, Any],
    baseline_candidate_table: Mapping[str, Any],
    remediation: Mapping[str, Any],
    source_gap: Mapping[str, Any],
) -> list[dict[str, Any]]:
    baseline_candidates = [
        dict(item)
        for item in list(baseline_run_result.get("candidate_options") or [])
        if isinstance(item, Mapping)
    ]
    remediation_by_project = _candidate_table_by_project(remediation)
    source_gap_by_project = _candidate_table_by_project(source_gap)
    baseline_table_by_project = _candidate_table_by_project(baseline_candidate_table)
    replay_rows: list[dict[str, Any]] = []
    for candidate in baseline_candidates:
        project_id = str(candidate.get("project_id") or "")
        row = dict(candidate)
        applied_fields: list[str] = []
        source_gap_row = dict(source_gap_by_project.get(project_id) or {})
        project_code_candidates = _project_code_candidates_for_replay(source_gap_row)
        if project_code_candidates:
            for key in ("projectCode", "project_code", "gdcic_project_code", "project_public_code"):
                row[key] = project_code_candidates[0]
                applied_fields.append(key)
            row["project_code_candidates"] = project_code_candidates
            row["replay_identifier_hints"] = {
                **dict(row.get("replay_identifier_hints") or {}),
                "project_code_candidates": project_code_candidates,
            }
        source_writeback = dict(source_gap_row.get("replay_field_writeback") or {})
        if source_writeback:
            for key, value in source_writeback.items():
                row[key] = value
                if value not in (None, ""):
                    applied_fields.append(key)
            if source_writeback:
                row["responsible_role_gap_code"] = ""
        remediation_row = dict(remediation_by_project.get(project_id) or {})
        remediation_writeback = dict(remediation_row.get("replay_field_writeback") or {})
        if remediation_writeback:
            for key, value in remediation_writeback.items():
                row[key] = value
                if value not in (None, "") or key == "responsible_role_gap_code":
                    applied_fields.append(key)
        baseline_row = dict(baseline_table_by_project.get(project_id) or {})
        row["source_candidate_mode"] = "REAL_PUBLIC_SOURCE_CANDIDATES"
        row["is_offline_sample_candidate"] = False
        if not str(row.get("notice_stage") or "").strip():
            row["notice_stage"] = "candidate_notice"
        if not _as_int(row.get("candidate_count")) and not _as_int(row.get("competitor_count")):
            row["candidate_count"] = 1
            row["competitor_count"] = 1
        row["key_fields_present"] = _normalized_key_fields(row)
        row["p2_replay_writeback_fields_applied"] = sorted(set(applied_fields))
        row["p2_company_first_remediation_state"] = remediation_row.get("remediation_state", "")
        row["p2_source_gap_probe_action"] = source_gap_row.get("recommended_next_action", "")
        row["p2_baseline_real_public_stage4_9_chain_state"] = baseline_row.get("real_public_stage4_9_chain_state", "")
        replay_rows.append(row)
    return replay_rows


def _seed_replay_storage_from_baseline(*, baseline_root: Path, replay_root: Path) -> None:
    baseline_store = baseline_root / "store.json"
    replay_store = replay_root / "store.json"
    if baseline_store.exists():
        replay_store.parent.mkdir(parents=True, exist_ok=True)
        replay_store.write_bytes(baseline_store.read_bytes())
    baseline_objects = baseline_root / "objects"
    replay_objects = replay_root / "objects"
    if baseline_objects.exists():
        shutil.copytree(baseline_objects, replay_objects, dirs_exist_ok=True)


def _project_code_candidates_for_replay(source_gap_row: Mapping[str, Any]) -> list[str]:
    candidates = _string_list(source_gap_row.get("project_code_candidates"))
    hints = source_gap_row.get("replay_identifier_hints")
    if isinstance(hints, Mapping):
        candidates.extend(_string_list(hints.get("project_code_candidates")))
        candidates.extend(_string_list(hints.get("project_codes")))
    candidates.extend(_string_list(source_gap_row.get("project_codes")))
    return _dedupe_strings(candidates)


def _normalized_key_fields(candidate: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    if str(candidate.get("project_name") or "").strip():
        keys.append("project_name")
    if str(candidate.get("notice_stage") or "").strip():
        keys.append("notice_stage")
    if str(candidate.get("candidate_company") or "").strip():
        keys.append("candidate_company")
    existing = candidate.get("key_fields_present")
    if isinstance(existing, list):
        for value in existing:
            text = str(value or "").strip()
            if text and text not in keys:
                keys.append(text)
    return keys


def _candidate_delta_record(
    *,
    project_id: str,
    baseline: Mapping[str, Any],
    replay: Mapping[str, Any],
    remediation: Mapping[str, Any],
    source_gap: Mapping[str, Any],
) -> dict[str, Any]:
    before_company_first = bool(baseline.get("jzsc_company_first_identity_resolution_required"))
    after_company_first = bool(replay.get("jzsc_company_first_identity_resolution_required"))
    before_gap = str(baseline.get("responsible_role_gap_code") or "")
    after_gap = str(replay.get("responsible_role_gap_code") or "")
    delta_state = (
        "COMPANY_FIRST_IMPROVED"
        if before_company_first and not after_company_first
        else "ROLE_GAP_IMPROVED"
        if before_gap and not after_gap
        else "CHAIN_STATE_CHANGED"
        if str(baseline.get("real_public_stage4_9_chain_state") or "") != str(replay.get("real_public_stage4_9_chain_state") or "")
        else "UNCHANGED_OR_STILL_REVIEW"
    )
    return {
        "project_id": project_id,
        "project_name": _first_non_empty(replay.get("project_name"), baseline.get("project_name")),
        "baseline_real_public_stage4_9_chain_state": baseline.get("real_public_stage4_9_chain_state", ""),
        "replay_real_public_stage4_9_chain_state": replay.get("real_public_stage4_9_chain_state", ""),
        "baseline_stage5_rule_gate_status": baseline.get("stage5_rule_gate_status", ""),
        "replay_stage5_rule_gate_status": replay.get("stage5_rule_gate_status", ""),
        "baseline_stage5_evidence_gate_status": baseline.get("stage5_evidence_gate_status", ""),
        "replay_stage5_evidence_gate_status": replay.get("stage5_evidence_gate_status", ""),
        "baseline_company_first_required": before_company_first,
        "replay_company_first_required": after_company_first,
        "company_first_remediation_state": remediation.get("remediation_state", ""),
        "source_gap_probe_next_action": source_gap.get("recommended_next_action", ""),
        "source_gap_project_code_candidates": _string_list(source_gap.get("project_code_candidates")),
        "source_gap_project_code_resolution_failure_reasons": _string_list(
            source_gap.get("project_code_resolution_failure_reasons")
        ),
        "source_gap_stage4_responsible_role_writeback_state": source_gap.get(
            "stage4_responsible_role_writeback_state", ""
        ),
        "source_gap_person_directory_same_company_candidate_found": bool(
            source_gap.get("person_directory_same_company_candidate_found")
        ),
        "source_gap_certificate_verification_state": source_gap.get("certificate_verification_state", ""),
        "responsible_role_gap_code_before": before_gap,
        "responsible_role_gap_code_after": after_gap,
        "remaining_real_world_gap_count_before": len(_string_list(baseline.get("remaining_real_world_gaps"))),
        "remaining_real_world_gap_count_after": len(_string_list(replay.get("remaining_real_world_gaps"))),
        "fail_closed_reason_count_before": len(_string_list(baseline.get("fail_closed_reasons"))),
        "fail_closed_reason_count_after": len(_string_list(replay.get("fail_closed_reasons"))),
        "replay_writeback_applied_fields": _string_list(replay.get("p2_replay_writeback_fields_applied")),
        "delta_state": delta_state,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _gap_delta_records(
    *,
    baseline_summary: Mapping[str, Any],
    replay_summary: Mapping[str, Any],
    baseline_candidates: Mapping[str, Mapping[str, Any]],
    replay_candidates: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family, before_counts, after_counts in (
        (
            "remaining_real_world_gap",
            dict(baseline_summary.get("remaining_real_world_gap_counts") or {}),
            dict(replay_summary.get("remaining_real_world_gap_counts") or {}),
        ),
        (
            "fail_closed_reason",
            dict(baseline_summary.get("fail_closed_reason_counts") or {}),
            dict(replay_summary.get("fail_closed_reason_counts") or {}),
        ),
    ):
        for gap_value in sorted(set(before_counts) | set(after_counts)):
            before = _as_int(before_counts.get(gap_value))
            after = _as_int(after_counts.get(gap_value))
            rows.append(
                {
                    "gap_family": family,
                    "gap_value": gap_value,
                    "before_count": before,
                    "after_count": after,
                    "delta": after - before,
                    "trend": "IMPROVED" if after < before else "WORSENED" if after > before else "UNCHANGED",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    rows.append(
        {
            "gap_family": "responsible_role_gap_code_count",
            "gap_value": "non_empty",
            "before_count": sum(1 for row in baseline_candidates.values() if str(row.get("responsible_role_gap_code") or "").strip()),
            "after_count": sum(1 for row in replay_candidates.values() if str(row.get("responsible_role_gap_code") or "").strip()),
            "delta": sum(1 for row in replay_candidates.values() if str(row.get("responsible_role_gap_code") or "").strip())
            - sum(1 for row in baseline_candidates.values() if str(row.get("responsible_role_gap_code") or "").strip()),
            "trend": "DERIVED",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    )
    return rows


def _project_code_resolution_failure_counts_from_summary(
    summary: Mapping[str, Any],
    *,
    fallback_counts: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source_key in ("fail_closed_reason_counts", "remaining_real_world_gap_counts"):
        source_counts = dict(summary.get(source_key) or {})
        for key, value in source_counts.items():
            text = str(key or "")
            if "gdcic_project_code" in text or "gdcic_project_lookup" in text:
                counts[text] = counts.get(text, 0) + _as_int(value)
    if not counts and fallback_counts:
        counts = {str(key): _as_int(value) for key, value in fallback_counts.items() if str(key or "").strip()}
    return dict(sorted(counts.items()))


def _project_code_resolution_failure_counts_from_candidates(
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        for reason in _string_list(candidate.get("project_code_resolution_failure_reasons")):
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _candidate_table_by_project(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    records = list(payload.get("records") or manifest.get("candidate_records") or manifest.get("candidate_pressure_records") or manifest.get("candidate_delta_records") or [])
    out: dict[str, dict[str, Any]] = {}
    for item in records:
        if not isinstance(item, Mapping):
            continue
        project_id = str(item.get("project_id") or "")
        if project_id:
            out[project_id] = dict(item)
    return out


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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item or "").strip()]
    return []


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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


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
    parser = argparse.ArgumentParser(description="Run Guangzhou Stage4-9 remediation replay and build delta report.")
    parser.add_argument("--mode", choices=("run-replay", "build-delta"), required=True)
    parser.add_argument("--baseline-run-result-json", default=str(DEFAULT_BASELINE_RUN_RESULT_JSON))
    parser.add_argument("--baseline-candidate-pressure-json", default=str(DEFAULT_BASELINE_CANDIDATE_PRESSURE_JSON))
    parser.add_argument("--company-first-remediation-json", default=str(DEFAULT_COMPANY_FIRST_REMEDIATION_JSON))
    parser.add_argument("--source-gap-probe-json", default=str(DEFAULT_SOURCE_GAP_PROBE_JSON))
    parser.add_argument("--replay-run-result-json", default="")
    parser.add_argument("--replay-candidate-pressure-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--detail-capture-limit", type=int, default=10)
    parser.add_argument("--attachment-capture-limit", type=int, default=20)
    parser.add_argument("--stage2-detail-capture-time-budget-seconds", type=float, default=600)
    parser.add_argument("--stage1-6-time-budget-seconds", type=float, default=600)
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.mode == "run-replay":
        result = run_guangzhou_stage4_9_remediation_replay(
            baseline_run_result_json=args.baseline_run_result_json,
            baseline_candidate_pressure_json=args.baseline_candidate_pressure_json,
            company_first_remediation_json=args.company_first_remediation_json,
            source_gap_probe_json=args.source_gap_probe_json,
            output_root=args.output_root,
            candidate_limit=args.candidate_limit,
            detail_capture_limit=args.detail_capture_limit,
            attachment_capture_limit=args.attachment_capture_limit,
            stage2_detail_capture_time_budget_seconds=args.stage2_detail_capture_time_budget_seconds,
            stage1_6_time_budget_seconds=args.stage1_6_time_budget_seconds,
        )
    else:
        replay_run_result_json = args.replay_run_result_json or str(Path(args.output_root) / "run-result.json")
        replay_candidate_pressure_json = args.replay_candidate_pressure_json or str(Path(args.output_root) / "candidate-pressure-table.json")
        result = build_guangzhou_stage4_9_remediation_delta_report(
            baseline_run_result_json=args.baseline_run_result_json,
            baseline_candidate_pressure_json=args.baseline_candidate_pressure_json,
            company_first_remediation_json=args.company_first_remediation_json,
            source_gap_probe_json=args.source_gap_probe_json,
            replay_run_result_json=replay_run_result_json,
            replay_candidate_pressure_json=replay_candidate_pressure_json,
            output_root=args.output_root,
            target_accepted_candidate_count=args.candidate_limit,
        )
    print(json.dumps(result if args.emit_json else result.get("summary", {}), ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
