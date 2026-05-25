from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ATTRIBUTION_KIND = "stage1_6_limited_success_attribution_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-6-limited-success-attribution-v1")
DEFAULT_SEARCH_ROOT = Path("tmp/evaluation-real-samples")
DEFAULT_SCOREBOARD_FILENAME = "stage1-6-sellable-scoreboard-v1.json"


def build_stage1_6_limited_success_attribution(
    *,
    success_scoreboard_json: str | Path | None = None,
    target_scoreboard_json: str | Path | None = None,
    search_root: str | Path = DEFAULT_SEARCH_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    explicit_success_path = Path(success_scoreboard_json) if success_scoreboard_json else None
    explicit_target_path = Path(target_scoreboard_json) if target_scoreboard_json else None
    discovery = (
        _explicit_attribution_context(
            search_root=search_root,
            success_scoreboard_json=explicit_success_path,
            target_scoreboard_json=explicit_target_path,
        )
        if explicit_success_path is not None and explicit_target_path is not None
        else discover_limited_success_attribution_context(search_root=search_root)
    )
    success_path = Path(success_scoreboard_json) if success_scoreboard_json else _path_or_none(
        discovery.get("success_scoreboard_json")
    )
    target_path = Path(target_scoreboard_json) if target_scoreboard_json else _path_or_none(
        discovery.get("target_scoreboard_json")
    )
    if success_path is None:
        raise ValueError("success_scoreboard_json_required_or_discoverable")
    if target_path is None:
        raise ValueError("target_scoreboard_json_required_or_discoverable")
    success = _read_json(success_path)
    target = _read_json(target_path)
    success_rows = _rows(success)
    target_rows = _rows(target)
    success_limited_rows = [
        row for row in success_rows if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE"
    ]
    target_not_limited_rows = [
        row
        for row in target_rows
        if str(row.get("limited_sellable_review_candidate_state") or "") != "REVIEW_CANDIDATE"
    ]
    result = {
        "attribution_kind": ATTRIBUTION_KIND,
        "attribution_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "success_scoreboard_json": str(success_path),
            "target_scoreboard_json": str(target_path),
            "search_root": str(search_root),
        },
        "discovery": {
            **discovery,
            "discovery_state": (
                "EXPLICIT_SCOREBOARDS"
                if success_scoreboard_json and target_scoreboard_json
                else "AUTO_DISCOVERED_LIMITED_SUCCESS_ATTRIBUTION_CONTEXT"
            ),
        },
        "success_run": _run_summary(success),
        "target_run": _run_summary(target),
        "success_limited_path": _success_limited_path(success_limited_rows),
        "target_not_limited_path": _target_not_limited_path(target_not_limited_rows),
        "attribution_summary": _attribution_summary(success_limited_rows, target_not_limited_rows),
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
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "stage1-6-limited-success-attribution-v1.json", result)
    _write_markdown(out_dir / "stage1-6-limited-success-attribution-v1.md", result)
    return result


def _explicit_attribution_context(
    *,
    search_root: str | Path,
    success_scoreboard_json: Path,
    target_scoreboard_json: Path,
) -> dict[str, Any]:
    success = _candidate_from_path(success_scoreboard_json)
    target = _candidate_from_path(target_scoreboard_json)
    return {
        "search_root": str(search_root),
        "success_scoreboard_json": str(success_scoreboard_json),
        "target_scoreboard_json": str(target_scoreboard_json),
        "scoreboard_candidate_count": 2,
        "success_selection_state": "EXPLICIT_SUCCESS_SCOREBOARD",
        "target_selection_state": "EXPLICIT_TARGET_SCOREBOARD",
        "success_candidate_summary": _candidate_summary(success),
        "target_candidate_summary": _candidate_summary(target),
    }


def discover_limited_success_attribution_context(
    *,
    search_root: str | Path = DEFAULT_SEARCH_ROOT,
) -> dict[str, Any]:
    root = Path(search_root)
    candidates = _scoreboard_candidates(root)
    success = _select_success_candidate(candidates)
    target = _select_target_candidate(candidates, success)
    return {
        "search_root": str(root),
        "success_scoreboard_json": str(success.get("path") or "") if success else "",
        "target_scoreboard_json": str(target.get("path") or "") if target else "",
        "scoreboard_candidate_count": len(candidates),
        "success_selection_state": success.get("selection_state", "") if success else "NO_LIMITED_SUCCESS_SCOREBOARD_FOUND",
        "target_selection_state": target.get("selection_state", "") if target else "NO_ZERO_OR_LOWER_LIMITED_TARGET_FOUND",
        "success_candidate_summary": _candidate_summary(success),
        "target_candidate_summary": _candidate_summary(target),
    }


def _candidate_from_path(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    board = _scoreboard(payload)
    return {
        "path": path,
        "mtime": path.stat().st_mtime if path.exists() else 0,
        "candidate_count": _int(board.get("candidate_count")),
        "limited_count": _int(board.get("limited_sellable_review_candidate_count")),
        "real_public_sellable_pack_rate": float(board.get("real_public_sellable_pack_rate") or 0),
        "stage4_matched_task_count": _int(board.get("stage4_matched_task_count")),
        "stage4_needs_browser_task_count": _int(board.get("stage4_needs_browser_task_count")),
    }


def _run_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    board = _scoreboard(payload)
    return {
        "candidate_count": _int(board.get("candidate_count")),
        "limited_sellable_review_candidate_count": _int(board.get("limited_sellable_review_candidate_count")),
        "real_public_sellable_pack_rate": float(board.get("real_public_sellable_pack_rate") or 0),
        "stage5_operational_primary_track_counts": dict(board.get("stage5_operational_primary_track_counts") or {}),
        "stage5_operational_priority_bucket_counts": dict(board.get("stage5_operational_priority_bucket_counts") or {}),
        "stage4_public_readback_channel_outcome_counts": dict(
            board.get("stage4_public_readback_channel_outcome_counts") or {}
        ),
        "stage4_adapter_result_state_counts": dict(board.get("stage4_adapter_result_state_counts") or {}),
        "stage4_downstream_abcd_grade_counts": dict(board.get("stage4_downstream_abcd_grade_counts") or {}),
        "stage4_public_identifier_backfill_source_counts": dict(
            board.get("stage4_public_identifier_backfill_source_counts") or {}
        ),
        "stage6_limited_sellable_review_candidate_state_counts": dict(
            board.get("stage6_limited_sellable_review_candidate_state_counts") or {}
        ),
        "stage6_limited_sellable_review_public_source_chain_counts": dict(
            board.get("stage6_limited_sellable_review_public_source_chain_counts") or {}
        ),
        "stage6_limited_sellable_review_stage4_bridge_backfill_state_counts": dict(
            board.get("stage6_limited_sellable_review_stage4_bridge_backfill_state_counts") or {}
        ),
    }


def _success_limited_path(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len(rows),
        "primary_track_counts": _counts(row.get("stage5_operational_primary_track") for row in rows),
        "review_bucket_counts": _counts(row.get("stage5_operational_review_bucket") for row in rows),
        "evidence_grade_counts": _merge_count_maps(row.get("limited_sellable_review_evidence_grade_counts") for row in rows),
        "gap_grade_counts": _merge_count_maps(row.get("limited_sellable_review_gap_grade_counts") for row in rows),
        "stage4_adapter_result_state_counts": _merge_count_maps(row.get("stage4_adapter_result_state_counts") for row in rows),
        "stage4_downstream_abcd_grade_counts": _merge_count_maps(row.get("stage4_downstream_abcd_grade_counts") for row in rows),
        "stage4_backfill_state_counts": _counts(row.get("stage4_project_code_backfill_state") for row in rows),
        "public_identifier_backfill_source_counts": _split_source_counts(
            row.get("stage4_public_identifier_backfill_source") for row in rows
        ),
        "official_readback_task_count": sum(_int(row.get("limited_sellable_review_official_readback_task_count")) for row in rows),
        "official_readback_public_source_chain_counts": _official_readback_source_chain_counts(rows),
        "success_factor_counts": _success_factor_counts(rows),
        "project_records": [_limited_record(row) for row in rows],
    }


def _target_not_limited_path(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len(rows),
        "review_blocker_state_counts": _counts(_target_blocker(row) for row in rows),
        "failure_mode_counts": _failure_mode_counts(rows),
        "primary_track_counts": _counts(row.get("stage5_operational_primary_track") for row in rows),
        "review_bucket_counts": _counts(row.get("stage5_operational_review_bucket") for row in rows),
        "stage4_adapter_result_state_counts": _merge_count_maps(row.get("stage4_adapter_result_state_counts") for row in rows),
        "stage4_downstream_abcd_grade_counts": _merge_count_maps(row.get("stage4_downstream_abcd_grade_counts") for row in rows),
        "limited_sellable_gap_grade_counts": _merge_count_maps(row.get("limited_sellable_review_gap_grade_counts") for row in rows),
        "stage4_backfill_state_counts": _counts(row.get("stage4_project_code_backfill_state") for row in rows),
        "public_identifier_backfill_source_counts": _split_source_counts(
            row.get("stage4_public_identifier_backfill_source") for row in rows
        ),
        "local_authority_executed_readback_state_counts": _merge_count_maps(
            row.get("p13b_local_authority_executed_readback_state_counts") for row in rows
        ),
        "project_records": [_target_record(row) for row in rows],
    }


def _attribution_summary(
    success_limited_rows: list[Mapping[str, Any]],
    target_official_ready_not_limited: list[Mapping[str, Any]],
) -> dict[str, Any]:
    success_grades = _merge_count_maps(
        row.get("limited_sellable_review_evidence_grade_counts") for row in success_limited_rows
    )
    target_blockers = _counts(_target_blocker(row) for row in target_official_ready_not_limited)
    target_failure_modes = _failure_mode_counts(target_official_ready_not_limited)
    success_factors = _success_factor_counts(success_limited_rows)
    return {
        "success_required_b_or_c_grade_count": _int(success_grades.get("B_ENHANCEMENT_OFFICIAL_READBACK"))
        + _int(success_grades.get("C_REVERSE_EXPLANATION_OFFICIAL_READBACK")),
        "target_public_identifier_ready_not_release_evidence_count": _int(
            target_blockers.get("PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE")
        ),
        "target_failure_mode_counts": target_failure_modes,
        "success_factor_counts": success_factors,
        "primary_difference": _primary_difference(success_grades, target_blockers, target_failure_modes),
        "recommended_next_action": _recommended_next_action(target_failure_modes),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _primary_difference(
    success_grades: Mapping[str, Any],
    target_blockers: Mapping[str, Any],
    target_failure_modes: Mapping[str, Any],
) -> str:
    if _int(target_failure_modes.get("TARGET_EXECUTED_BUT_ONLY_D_OR_BROWSER_BLOCKED")):
        return "TARGET_EXECUTED_BUT_ONLY_D_OR_BROWSER_BLOCKED"
    if _int(success_grades.get("B_ENHANCEMENT_OFFICIAL_READBACK")) or _int(
        success_grades.get("C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
    ):
        if _int(target_blockers.get("PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE")):
            return "SUCCESS_HAS_B_OR_C_RELEASE_EVIDENCE_TARGET_ONLY_HAS_PUBLIC_IDENTIFIER_READY"
    return "LIMITED_SUCCESS_DIFFERENCE_REQUIRES_MANUAL_REVIEW"


def _recommended_next_action(target_failure_modes: Mapping[str, Any]) -> str:
    if _int(target_failure_modes.get("TARGET_EXECUTED_BUT_ONLY_D_OR_BROWSER_BLOCKED")):
        return "continue_fallback_readback_or_browser_authorized_replay_before_limited_review"
    if _int(target_failure_modes.get("PUBLIC_IDENTIFIER_ONLY")):
        return "route_target_public_identifiers_to_b_or_c_release_evidence_adapter_before_limited_review"
    return "inspect_target_not_limited_rows_and_build_next_public_source_followup_queue"


def _limited_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "stage5_operational_primary_track": str(row.get("stage5_operational_primary_track") or ""),
        "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
        "limited_sellable_review_evidence_grade_counts": dict(
            row.get("limited_sellable_review_evidence_grade_counts") or {}
        ),
        "limited_sellable_review_gap_grade_counts": dict(row.get("limited_sellable_review_gap_grade_counts") or {}),
        "stage4_adapter_result_state_counts": dict(row.get("stage4_adapter_result_state_counts") or {}),
        "stage4_downstream_abcd_grade_counts": dict(row.get("stage4_downstream_abcd_grade_counts") or {}),
        "limited_sellable_review_official_readback_task_count": _int(
            row.get("limited_sellable_review_official_readback_task_count")
        ),
        "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
        "stage4_public_identifier_backfill_source": str(row.get("stage4_public_identifier_backfill_source") or ""),
        "p13b_ygp_project_code_variant_count": len(row.get("p13b_ygp_project_code_variants") or []),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _target_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
        "review_blocker_state": _target_blocker(row),
        "failure_modes": _row_failure_modes(row),
        "stage4_adapter_result_state_counts": dict(row.get("stage4_adapter_result_state_counts") or {}),
        "stage4_downstream_abcd_grade_counts": dict(row.get("stage4_downstream_abcd_grade_counts") or {}),
        "limited_sellable_review_gap_grade_counts": dict(row.get("limited_sellable_review_gap_grade_counts") or {}),
        "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
        "stage4_public_identifier_backfill_source": str(row.get("stage4_public_identifier_backfill_source") or ""),
        "p13b_overlap_triage_state": str(row.get("p13b_overlap_triage_state") or ""),
        "p13b_local_authority_executed_readback_state_counts": dict(
            row.get("p13b_local_authority_executed_readback_state_counts") or {}
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _target_blocker(row: Mapping[str, Any]) -> str:
    if str(row.get("p13b_overlap_triage_state") or "") == "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE":
        return "PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE"
    if "evidence_insufficient" in set(row.get("stage5_operational_review_families") or []):
        return "EVIDENCE_INSUFFICIENT_NOT_LIMITED_SELLABLE"
    return "B_OR_C_RELEASE_EVIDENCE_REVIEW_REQUIRED"


def _row_failure_modes(row: Mapping[str, Any]) -> list[str]:
    modes: list[str] = []
    adapter_counts = dict(row.get("stage4_adapter_result_state_counts") or {})
    downstream_grades = dict(row.get("stage4_downstream_abcd_grade_counts") or {})
    gap_grades = dict(row.get("limited_sellable_review_gap_grade_counts") or {})
    families = set(row.get("stage5_operational_review_families") or [])
    local_authority_counts = dict(row.get("p13b_local_authority_executed_readback_state_counts") or {})

    if (
        _int(downstream_grades.get("D_INSUFFICIENT_OR_BLOCKED_READBACK"))
        or _int(gap_grades.get("D_INSUFFICIENT_OR_BLOCKED_READBACK"))
    ) and (
        _int(adapter_counts.get("NEEDS_BROWSER"))
        or _int(adapter_counts.get("BLOCKED"))
        or _int(adapter_counts.get("NOT_FOUND"))
    ):
        modes.append("TARGET_EXECUTED_BUT_ONLY_D_OR_BROWSER_BLOCKED")
    if str(row.get("p13b_overlap_triage_state") or "") == "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE":
        modes.append("PUBLIC_IDENTIFIER_ONLY")
    if _int(adapter_counts.get("NEEDS_BROWSER")) or "authorization_blocked" in families:
        modes.append("NEEDS_BROWSER_OR_AUTH_SESSION")
    if (
        _int(local_authority_counts.get("BLOCKED"))
        or _int(local_authority_counts.get("NOT_FOUND"))
        or str(row.get("stage5_operational_primary_track") or "") == "public_source_blocked"
    ):
        modes.append("LOCAL_AUTHORITY_BLOCKED_OR_NOT_FOUND")
    if _int(adapter_counts.get("NOT_FOUND")) or "source_not_found" in families:
        modes.append("SOURCE_NOT_FOUND_NON_CLEARANCE")
    if not modes:
        modes.append(_target_blocker(row))
    return modes


def _failure_mode_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for mode in _row_failure_modes(row):
            counts[mode] = counts.get(mode, 0) + 1
    return counts


def _success_factor_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        grades = dict(row.get("limited_sellable_review_evidence_grade_counts") or {})
        if _int(grades.get("B_ENHANCEMENT_OFFICIAL_READBACK")) or _int(
            grades.get("C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
        ):
            counts["B_OR_C_OFFICIAL_READBACK"] = counts.get("B_OR_C_OFFICIAL_READBACK", 0) + 1
        if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE":
            counts["STAGE6_LIMITED_REVIEW_CANDIDATE"] = counts.get("STAGE6_LIMITED_REVIEW_CANDIDATE", 0) + 1
        if str(row.get("stage5_operational_primary_track") or "") == "strong_lead":
            counts["STAGE5_STRONG_LEAD_PRIMARY_TRACK"] = counts.get("STAGE5_STRONG_LEAD_PRIMARY_TRACK", 0) + 1
        source = str(row.get("stage4_public_identifier_backfill_source") or "")
        if "YGP_" in source or "DATA_GGZY" in source:
            counts["PUBLIC_SOURCE_IDENTIFIER_CHAIN"] = counts.get("PUBLIC_SOURCE_IDENTIFIER_CHAIN", 0) + 1
    return counts


def _official_readback_source_chain_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        records = row.get("limited_sellable_review_official_readback_records")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, Mapping):
                continue
            key = str(record.get("public_source_chain") or record.get("release_evidence_target_type") or "")
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _split_source_counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for part in str(value or "").split("|"):
            key = part.strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _scoreboard(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    board = payload.get("scoreboard")
    return board if isinstance(board, Mapping) else {}


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = payload.get("project_rows")
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _merge_count_maps(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key, count in value.items():
            counts[str(key)] = counts.get(str(key), 0) + _int(count)
    return counts


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _path_or_none(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def _scoreboard_candidates(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    candidates: list[dict[str, Any]] = []
    for path in root.rglob(DEFAULT_SCOREBOARD_FILENAME):
        if not path.is_file():
            continue
        payload = _read_json(path)
        if not _scoreboard(payload):
            continue
        candidates.append(_candidate_from_path(path))
    return sorted(candidates, key=lambda item: (float(item["mtime"]), str(item["path"])), reverse=True)


def _select_success_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates if _int(item.get("candidate_count")) and _int(item.get("limited_count")) > 0]
    if not eligible:
        return {}
    selected = sorted(
        eligible,
        key=lambda item: (
            _int(item.get("limited_count")),
            float(item.get("real_public_sellable_pack_rate") or 0),
            float(item.get("mtime") or 0),
            str(item.get("path") or ""),
        ),
        reverse=True,
    )[0]
    return {**selected, "selection_state": "HIGHEST_LIMITED_SELLABLE_SUCCESS_SCOREBOARD"}


def _select_target_candidate(candidates: list[dict[str, Any]], success: Mapping[str, Any]) -> dict[str, Any]:
    if not success:
        return {}
    success_path = str(success.get("path") or "")
    success_limited = _int(success.get("limited_count"))
    zero_limited = [
        item
        for item in candidates
        if str(item.get("path") or "") != success_path
        and _int(item.get("candidate_count")) > 0
        and _int(item.get("limited_count")) == 0
    ]
    if zero_limited:
        selected = sorted(
            zero_limited,
            key=lambda item: (
                _int(item.get("candidate_count")),
                float(item.get("mtime") or 0),
                str(item.get("path") or ""),
            ),
            reverse=True,
        )[0]
        return {**selected, "selection_state": "LATEST_ZERO_LIMITED_TARGET_SCOREBOARD"}
    lower_limited = [
        item
        for item in candidates
        if str(item.get("path") or "") != success_path
        and _int(item.get("candidate_count")) > 0
        and _int(item.get("limited_count")) < success_limited
    ]
    if lower_limited:
        selected = sorted(
            lower_limited,
            key=lambda item: (
                -_int(item.get("limited_count")),
                _int(item.get("candidate_count")),
                float(item.get("mtime") or 0),
                str(item.get("path") or ""),
            ),
            reverse=True,
        )[0]
        return {**selected, "selection_state": "LOWER_LIMITED_TARGET_SCOREBOARD"}
    return {}


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not candidate:
        return {}
    return {
        "path": str(candidate.get("path") or ""),
        "candidate_count": _int(candidate.get("candidate_count")),
        "limited_sellable_review_candidate_count": _int(candidate.get("limited_count")),
        "real_public_sellable_pack_rate": float(candidate.get("real_public_sellable_pack_rate") or 0),
        "stage4_matched_task_count": _int(candidate.get("stage4_matched_task_count")),
        "stage4_needs_browser_task_count": _int(candidate.get("stage4_needs_browser_task_count")),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    lines = [
        "# Stage1-6 Limited Success Attribution v1",
        "",
        f"- success_run: {json.dumps(payload.get('success_run', {}), ensure_ascii=False, sort_keys=True)}",
        f"- target_run: {json.dumps(payload.get('target_run', {}), ensure_ascii=False, sort_keys=True)}",
        f"- attribution_summary: {json.dumps(payload.get('attribution_summary', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "customer_visible_allowed=false; query_miss_is_not_clearance=true; no_legal_conclusion=true",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--success-scoreboard-json", default="")
    parser.add_argument("--target-scoreboard-json", default="")
    parser.add_argument("--search-root", default=str(DEFAULT_SEARCH_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage1_6_limited_success_attribution(
        success_scoreboard_json=args.success_scoreboard_json or None,
        target_scoreboard_json=args.target_scoreboard_json or None,
        search_root=args.search_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result.get("attribution_summary") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
