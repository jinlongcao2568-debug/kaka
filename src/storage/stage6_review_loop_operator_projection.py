from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from storage.runtime_closeout_precedence import (
    runtime_blocker_record_subqueues as _runtime_blocker_record_subqueues,
    runtime_blocker_subqueue_routes as _runtime_blocker_subqueue_routes,
)


STAGE6_REVIEW_LOOP_OPERATOR_PROJECTION_VERSION = 1
STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME = "stage6-review-loop-project-status-table.json"
DEFAULT_STAGE6_REVIEW_LOOP_SEARCH_ROOT = Path("tmp/evaluation-real-samples")

MANUAL_HOLD_REOPEN_CONDITIONS = (
    "new_official_original_notice_source_or_snapshot_available",
    "operator_confirms_manual_retry_scope_and_budget",
    "new_release_evidence_source_or_project_local_authority_path_available",
    "prior_blocker_resolved_without_clearance_claim",
)

ACTIONABLE_AUTOMATED_STATES = {
    "NEXT_CYCLE_DISPATCH_READY",
    "RESULT_COMMAND_READY_NOT_EXECUTED",
    "RESULT_COMMAND_READY_DRY_RUN",
    "WAITING_FOR_DISPATCH_EXECUTION",
    "RELEASE_EVIDENCE_QUERY_READY_FROM_ORIGINAL_READBACK",
    "NEXT_ORIGINAL_READBACK_SUBQUEUE_READY",
    "P13B_CONTINUATION_READY",
}

BLOCKED_OR_MANUAL_STATES = {
    "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
    "BLOCKED_OR_MANUAL_REVIEW_REQUIRED",
    "MANUAL_ROUTING_REVIEW_REQUIRED",
    "RESULT_EXECUTION_FAILED",
    "RESULT_COMMAND_BLOCKED_BY_ALLOWLIST",
    "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
    "RELEASE_FIELD_QUERY_PENDING_OR_NEEDS_BROWSER",
    "RELEASE_FIELD_QUERY_RESULT_MISSING",
    "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW",
    "ORIGINAL_READBACK_MANUAL_HOLD",
    "P13B_CONTINUATION_OPERATOR_HOLD",
}


def load_stage6_review_loop_operator_projection(
    *,
    status_table_path: str | Path | None = None,
    search_root: str | Path = DEFAULT_STAGE6_REVIEW_LOOP_SEARCH_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    explicit_status_path = Path(status_table_path) if status_table_path else None
    effective_search_root = Path(search_root)
    if explicit_status_path and not search_root:
        effective_search_root = explicit_status_path.parent
    elif explicit_status_path and str(search_root) == str(DEFAULT_STAGE6_REVIEW_LOOP_SEARCH_ROOT):
        default_root = Path(DEFAULT_STAGE6_REVIEW_LOOP_SEARCH_ROOT)
        if not _path_under(explicit_status_path, default_root):
            effective_search_root = explicit_status_path.parent
    batch_options = list_stage6_review_loop_status_table_options(effective_search_root)
    resolved = explicit_status_path if explicit_status_path else _select_default_status_table_from_options(batch_options)
    selection_mode = "EXPLICIT_STATUS_TABLE" if explicit_status_path else "DEFAULT_OWNER_OVERVIEW"
    if not resolved:
        surface = build_stage6_review_loop_operator_projection(
            {},
            source_path="",
            source_readback_state="EMPTY",
            created_at=created_at,
        )
        _attach_batch_options(surface, batch_options, selected_path=None, selection_mode=selection_mode)
        return surface
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        surface = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [],
                "readback_error": str(exc),
            },
            source_path=str(resolved),
            source_readback_state="READBACK_FAILED",
            created_at=created_at,
        )
        _attach_batch_options(surface, batch_options, selected_path=resolved, selection_mode=selection_mode)
        return surface
    surface = build_stage6_review_loop_operator_projection(
        payload,
        source_path=str(resolved),
        source_readback_state="READBACK_READY",
        created_at=created_at,
    )
    _attach_batch_options(surface, batch_options, selected_path=resolved, selection_mode=selection_mode)
    return surface


def find_latest_stage6_review_loop_status_table(
    search_root: str | Path = DEFAULT_STAGE6_REVIEW_LOOP_SEARCH_ROOT,
) -> Path | None:
    root = Path(search_root)
    if not root.exists():
        return None
    candidates = [path for path in root.rglob(STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME) if path.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def list_stage6_review_loop_status_table_options(
    search_root: str | Path = DEFAULT_STAGE6_REVIEW_LOOP_SEARCH_ROOT,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    root = Path(search_root)
    if not root.exists():
        return []
    candidates = [path for path in root.rglob(STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME) if path.is_file()]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [_status_table_option(path, root) for path in candidates[: max(0, limit)]]


def _select_default_status_table_from_options(batch_options: list[Mapping[str, Any]]) -> Path | None:
    if not batch_options:
        return None
    latest = batch_options[0]
    if int(latest.get("project_count") or 0) > 1:
        return Path(str(latest.get("status_table_path") or ""))
    for option in batch_options:
        if int(option.get("project_count") or 0) > 1:
            return Path(str(option.get("status_table_path") or ""))
    return Path(str(latest.get("status_table_path") or ""))


def build_stage6_review_loop_operator_projection(
    status_table_payload: Mapping[str, Any] | None,
    *,
    source_path: str = "",
    source_readback_state: str = "READBACK_READY",
    created_at: str | None = None,
) -> dict[str, Any]:
    payload = dict(status_table_payload or {})
    summary_in, records_in = _extract_status_table(payload)
    owner_context = _owner_assignment_context(summary_in)
    project_rows = [_project_row(record, owner_context=owner_context) for record in records_in]
    terminal_state_counts = _counts(row["loop_terminal_state"] for row in project_rows)
    owner_state = _owner_batch_state(project_rows)
    summary = {
        "operator_batch_state": owner_state,
        "operator_batch_state_label": _owner_batch_state_label(owner_state),
        "project_count": len(project_rows),
        "manual_hold_count": sum(1 for row in project_rows if row["manual_review_hold"]),
        "automated_dispatch_available_count": sum(1 for row in project_rows if row["automated_dispatch_available"]),
        "stage7_commercial_input_allowed_count": sum(
            1 for row in project_rows if row["stage7_commercial_input_allowed"]
        ),
        "waiting_for_controlled_execution_count": sum(
            1 for row in project_rows if row["loop_terminal_state"] == "WAITING_FOR_DISPATCH_EXECUTION"
        ),
        "blocked_or_manual_review_count": sum(
            1 for row in project_rows if row["loop_terminal_state"] in BLOCKED_OR_MANUAL_STATES
        ),
        "owner_assignment_state_counts": _counts(row.get("owner_assignment_state") for row in project_rows),
        "assigned_owner_counts": _counts(row.get("assigned_owner") for row in project_rows),
        "unassigned_owner_count": sum(
            1 for row in project_rows if row.get("owner_assignment_state") == "UNASSIGNED_OWNER_REVIEW_REQUIRED"
        ),
        "runtime_blocker_ledger_count": sum(
            len(_list(row.get("runtime_blocker_ledger_records"))) for row in project_rows
        ),
        "runtime_blocker_ledger_state_counts": _counts(
            state
            for row in project_rows
            for state, count in dict(row.get("runtime_blocker_ledger_state_counts") or {}).items()
            for _ in range(int(count or 0))
        ),
        "runtime_blocker_ledger_layer_counts": _counts(
            layer
            for row in project_rows
            for layer, count in dict(row.get("runtime_blocker_ledger_layer_counts") or {}).items()
            for _ in range(int(count or 0))
        ),
        "runtime_blocker_ledger_scope_counts": _counts(
            scope
            for row in project_rows
            for item in _list(row.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
            for scope in _ledger_scope_values(item)
        ),
        "runtime_blocker_ledger_required_input_counts": _counts(
            required_input
            for row in project_rows
            for item in _list(row.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
            for required_input in _list(item.get("required_input"))
        ),
        "runtime_blocker_ledger_retry_policy_counts": _counts(
            item.get("retry_policy")
            for row in project_rows
            for item in _list(row.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_ledger_operator_next_action_counts": _counts(
            item.get("operator_next_action") or item.get("next_action")
            for row in project_rows
            for item in _list(row.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_ledger_reopen_condition_counts": _counts(
            condition
            for row in project_rows
            for item in _list(row.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
            for condition in _list(item.get("reopen_conditions"))
        ),
        "runtime_blocker_subqueue_counts": _counts(
            route
            for row in project_rows
            for route in _list(row.get("runtime_blocker_subqueue_routes"))
        ),
        "runtime_blocker_worker_followup_count": sum(
            len(_list(row.get("runtime_blocker_worker_followup_records"))) for row in project_rows
        ),
        "runtime_blocker_worker_followup_project_count": sum(
            1 for row in project_rows if row.get("runtime_blocker_worker_followup_available")
        ),
        "runtime_blocker_worker_followup_entrypoint_counts": _counts(
            item.get("formal_entrypoint_id")
            for row in project_rows
            for item in _list(row.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_worker_followup_task_type_counts": _counts(
            item.get("followup_task_type")
            for row in project_rows
            for item in _list(row.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_worker_followup_readiness_state_counts": _counts(
            item.get("followup_readiness_state")
            for row in project_rows
            for item in _list(row.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_worker_followup_next_action_counts": _counts(
            item.get("next_action")
            for row in project_rows
            for item in _list(row.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "release_field_query_source_hit_summary_count": sum(
            len(_list(row.get("release_field_query_source_hit_summaries"))) for row in project_rows
        ),
        "stage5_calibration_sample_count": sum(
            1 for row in project_rows if str(row.get("stage5_calibration_review_bucket") or "").strip()
        ),
        "stage5_calibration_truth_label_required_count": sum(
            1 for row in project_rows if bool(row.get("stage5_calibration_truth_label_required"))
        ),
        "stage5_calibration_review_bucket_counts": _counts(
            row.get("stage5_calibration_review_bucket") for row in project_rows
        ),
        "stage5_calibration_suggested_action_counts": _counts(
            row.get("stage5_calibration_suggested_action") for row in project_rows
        ),
        "next_cycle_dispatch_ready_count": sum(
            1 for row in project_rows if row["loop_terminal_state"] == "NEXT_CYCLE_DISPATCH_READY"
        ),
        "terminal_state_counts": terminal_state_counts,
        "source_summary": dict(summary_in),
    }
    surface = {
        "surface_id": "stage6_review_loop_operator_status",
        "surface_mode": "internal-readback",
        "surface_state": owner_state,
        "capability_state": "INTERNAL_READY" if project_rows else "EMPTY",
        "projection_version": STAGE6_REVIEW_LOOP_OPERATOR_PROJECTION_VERSION,
        "created_at": created_at or utc_now_iso(),
        "source_path": source_path,
        "source_readback_state": source_readback_state,
        "source_status_table_filename": STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME,
        "internal_only": True,
        "readiness_only": False,
        "projection_only": True,
        "owner_can_observe_without_raw_json": True,
        "raw_json_required": False,
        "raw_json_fallback_required": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "public_software_release": False,
        "real_provider_call_enabled": False,
        "stage8_real_execution_enabled": False,
        "stage9_real_payment_delivery_refund_enabled": False,
        "automated_refund_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "summary": summary,
        "operator_decision": _operator_decision(summary, project_rows),
        "project_status_rows": project_rows,
        "safe_display_contract": {
            "source_url_visible": False,
            "raw_snapshot_visible": False,
            "complete_verification_path_visible": False,
            "internal_score_model_visible": False,
            "customer_visible_publication_enabled": False,
            "external_send_enabled": False,
            "customer_download_enabled": False,
        },
    }
    surface["projection_sha256"] = _fingerprint(
        {key: value for key, value in surface.items() if key != "projection_sha256"}
    )
    return surface


def _extract_status_table(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    records = payload.get("records") if isinstance(payload.get("records"), list) else None
    if records is not None:
        return dict(summary), [record for record in records if isinstance(record, Mapping)]

    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    manifest_summary = manifest.get("summary") if isinstance(manifest.get("summary"), Mapping) else summary
    project_status_table = (
        manifest.get("project_status_table") if isinstance(manifest.get("project_status_table"), Mapping) else {}
    )
    manifest_records = project_status_table.get("records") if isinstance(project_status_table.get("records"), list) else []
    return dict(manifest_summary), [record for record in manifest_records if isinstance(record, Mapping)]


def _attach_batch_options(
    surface: dict[str, Any],
    batch_options: list[Mapping[str, Any]],
    *,
    selected_path: Path | None,
    selection_mode: str,
) -> None:
    surface.pop("projection_sha256", None)
    selected_index = -1
    for index, option in enumerate(batch_options):
        if selected_path is not None and _same_path(option.get("status_table_path"), selected_path):
            selected_index = index
            break
    latest_option = dict(batch_options[0]) if batch_options else {}
    selected_option = dict(batch_options[selected_index]) if selected_index >= 0 else {}
    recommended_multi_project_option = next(
        (dict(option) for option in batch_options if int(option.get("project_count") or 0) > 1),
        {},
    )
    selected_is_latest = selected_index == 0 if selected_index >= 0 else False
    surface["batch_options"] = [dict(option) for option in batch_options]
    surface["batch_option_count"] = len(batch_options)
    surface["selected_batch_path"] = str(selected_path or surface.get("source_path") or "")
    surface["selected_batch_index"] = selected_index
    surface["selected_batch_is_latest"] = selected_is_latest
    surface["latest_batch_option"] = latest_option
    surface["recommended_multi_project_batch_option"] = recommended_multi_project_option
    surface["batch_default_selection_mode"] = selection_mode
    surface["batch_default_selection_strategy"] = _batch_default_selection_strategy(
        selection_mode=selection_mode,
        selected_option=selected_option,
        latest_option=latest_option,
        recommended_multi_project_option=recommended_multi_project_option,
        selected_is_latest=selected_is_latest,
    )
    surface["batch_default_selection_label"] = _batch_default_selection_label(
        str(surface["batch_default_selection_strategy"])
    )
    surface["batch_selector_visible"] = bool(batch_options)
    surface["multi_batch_review_available"] = len(batch_options) > 1
    surface["multi_project_batch_available"] = any(
        int(option.get("project_count") or 0) > 1 for option in batch_options
    )
    surface["projection_sha256"] = _fingerprint(surface)


def _batch_default_selection_strategy(
    *,
    selection_mode: str,
    selected_option: Mapping[str, Any],
    latest_option: Mapping[str, Any],
    recommended_multi_project_option: Mapping[str, Any],
    selected_is_latest: bool,
) -> str:
    if not selected_option:
        return "NO_STATUS_TABLE"
    if selection_mode == "EXPLICIT_STATUS_TABLE":
        return "EXPLICIT_OPERATOR_SELECTED_STATUS_TABLE"
    if selected_is_latest:
        return "LATEST_STATUS_TABLE"
    selected_path = str(selected_option.get("status_table_path") or "")
    recommended_path = str(recommended_multi_project_option.get("status_table_path") or "")
    if (
        selected_path
        and recommended_path
        and selected_path == recommended_path
        and int(latest_option.get("project_count") or 0) <= 1
    ):
        return "LATEST_MULTI_PROJECT_OVERVIEW_OVER_NEWER_SINGLE_PROJECT_TERMINAL"
    return "DEFAULT_OWNER_OVERVIEW_STATUS_TABLE"


def _batch_default_selection_label(strategy: str) -> str:
    return {
        "NO_STATUS_TABLE": "没有读到第六阶段批次状态表。",
        "EXPLICIT_OPERATOR_SELECTED_STATUS_TABLE": "正在查看你手动选择的历史批次。",
        "LATEST_STATUS_TABLE": "默认查看最新批次状态表。",
        "LATEST_MULTI_PROJECT_OVERVIEW_OVER_NEWER_SINGLE_PROJECT_TERMINAL": (
            "默认优先显示最新多项目批次；较新的单项目终态仍可在历史批次里切换查看。"
        ),
        "DEFAULT_OWNER_OVERVIEW_STATUS_TABLE": "默认按 owner 总览策略选择批次状态表。",
    }.get(strategy, strategy)


def _status_table_option(path: Path, root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary, records = _extract_status_table(payload if isinstance(payload, Mapping) else {})
        owner_context = _owner_assignment_context(summary)
        project_rows = [_project_row(record, owner_context=owner_context) for record in records]
        readback_state = "READBACK_READY"
        readback_error = ""
    except (OSError, json.JSONDecodeError) as exc:
        summary = {}
        project_rows = []
        readback_state = "READBACK_FAILED"
        readback_error = str(exc)
    operator_state = _owner_batch_state(project_rows)
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "batch_id": path.parent.name,
        "status_table_path": str(path),
        "status_table_path_label": _relative_path_label(path, root),
        "modified_at": modified_at,
        "readback_state": readback_state,
        "readback_error": readback_error,
        "operator_batch_state": operator_state,
        "operator_batch_state_label": _owner_batch_state_label(operator_state),
        "project_count": len(project_rows),
        "project_ids": [row["project_id"] for row in project_rows if row.get("project_id")],
        "project_names": [row["project_name"] for row in project_rows if row.get("project_name")],
        "manual_hold_count": sum(1 for row in project_rows if row["manual_review_hold"]),
        "automated_dispatch_available_count": sum(
            1 for row in project_rows if row["automated_dispatch_available"]
        ),
        "stage7_commercial_input_allowed_count": sum(
            1 for row in project_rows if row["stage7_commercial_input_allowed"]
        ),
        "source_summary": dict(summary),
    }


def _relative_path_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _same_path(left: Any, right: Path) -> bool:
    try:
        return Path(str(left)).resolve() == right.resolve()
    except (OSError, RuntimeError, ValueError):
        return str(left) == str(right)


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _owner_assignment_context(summary: Mapping[str, Any]) -> dict[str, Any]:
    roster = summary.get("operator_assignment_roster") if isinstance(summary.get("operator_assignment_roster"), Mapping) else {}
    stage6_roster = _first_mapping(
        summary.get("stage6_owner_assignment"),
        summary.get("owner_assignment"),
        roster.get("stage6"),
        roster.get("stage6_review"),
        roster.get("default"),
    )
    return {
        "assigned_owner": _first_text(
            stage6_roster.get("assigned_owner"),
            stage6_roster.get("owner"),
            summary.get("assigned_owner"),
            summary.get("project_owner"),
            summary.get("operator_owner"),
        ),
        "assigned_owner_role": _first_text(
            stage6_roster.get("assigned_owner_role"),
            stage6_roster.get("owner_role"),
            summary.get("assigned_owner_role"),
            summary.get("project_owner_role"),
            summary.get("operator_owner_role"),
        ),
        "reviewer": _first_text(stage6_roster.get("reviewer"), summary.get("reviewer")),
        "reviewer_role": _first_text(stage6_roster.get("reviewer_role"), summary.get("reviewer_role")),
        "owner_assignment_source_ref": _first_text(
            stage6_roster.get("source_ref"),
            summary.get("owner_assignment_source_ref"),
            summary.get("operator_assignment_roster_source_ref"),
        ),
    }


def _project_owner_assignment(
    record: Mapping[str, Any],
    *,
    owner_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = owner_context if isinstance(owner_context, Mapping) else {}
    direct = _first_mapping(record.get("owner_assignment"), record.get("operator_assignment"))
    assigned_owner = _first_text(
        direct.get("assigned_owner"),
        direct.get("owner"),
        record.get("assigned_owner"),
        record.get("project_owner"),
        record.get("operator_owner"),
        record.get("owner"),
        context.get("assigned_owner"),
    )
    owner_role = _first_text(
        direct.get("assigned_owner_role"),
        direct.get("owner_role"),
        record.get("assigned_owner_role"),
        record.get("project_owner_role"),
        record.get("operator_owner_role"),
        record.get("owner_role"),
        context.get("assigned_owner_role"),
    )
    reviewer = _first_text(direct.get("reviewer"), record.get("reviewer"), context.get("reviewer"))
    reviewer_role = _first_text(direct.get("reviewer_role"), record.get("reviewer_role"), context.get("reviewer_role"))
    source_ref = _first_text(
        direct.get("source_ref"),
        record.get("owner_assignment_source_ref"),
        record.get("operator_assignment_source_ref"),
        context.get("owner_assignment_source_ref"),
    )
    state = "ASSIGNED_OWNER_READY" if assigned_owner else "UNASSIGNED_OWNER_REVIEW_REQUIRED"
    required_input = [] if assigned_owner else ["assigned_owner", "assigned_owner_role"]
    next_action = (
        "owner_reviews_project_status_and_records_decision"
        if assigned_owner
        else "assign_project_owner_before_next_runtime_cycle"
    )
    return {
        "assigned_owner": assigned_owner,
        "assigned_owner_role": owner_role,
        "reviewer": reviewer,
        "reviewer_role": reviewer_role,
        "owner_assignment_source_ref": source_ref,
        "owner_assignment_state": state,
        "owner_assignment_state_label": _owner_assignment_state_label(state),
        "owner_assignment_required_inputs": required_input,
        "owner_assignment_required_input_labels": [_required_input_label(item) for item in required_input],
        "owner_assignment_next_action": next_action,
        "owner_assignment_next_action_label": _owner_assignment_next_action_label(next_action),
        "project_owner_label": _project_owner_label(assigned_owner=assigned_owner, owner_role=owner_role),
    }


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _project_row(record: Mapping[str, Any], *, owner_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    runtime_followup_rows = [
        _operator_worker_followup_row(item)
        for item in _list(record.get("runtime_blocker_worker_followup_records"))
        if isinstance(item, Mapping)
    ]
    terminal_state = str(record.get("loop_terminal_state") or "NO_PROJECT_STATUS_RECORD")
    if runtime_followup_rows and terminal_state == "NO_PROJECT_STATUS_RECORD":
        terminal_state = "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY"
    next_action = _first_text(
        record.get("next_recommended_action"),
        *(item.get("next_action") for item in runtime_followup_rows),
        "review_project_status_inputs",
    )
    manual_hold = terminal_state == "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH"
    stage7_allowed = bool(record.get("stage7_commercial_input_allowed", False))
    automated_available = terminal_state in ACTIONABLE_AUTOMATED_STATES
    blocker_reason_detail = _first_text(
        record.get("next_cycle_dispatch_block_reason"),
        record.get("result_runner_skip_reason"),
        record.get("dispatch_closeout_state"),
        record.get("dispatch_readback_state"),
    )
    current_stage = _current_stage(record, terminal_state, stage7_allowed)
    evidence_grade = _evidence_grade(record, terminal_state)
    blocker_reason = _blocker_reason(
        record=record,
        terminal_state=terminal_state,
        stage7_allowed=stage7_allowed,
        automated_available=automated_available,
    )
    owner_assignment = _project_owner_assignment(record, owner_context=owner_context)
    runtime_blocker_rows = [
        _operator_blocker_ledger_row(item)
        for item in _list(record.get("runtime_blocker_ledger_records"))
        if isinstance(item, Mapping)
    ]
    runtime_blocker_routes = _runtime_blocker_subqueue_routes(runtime_blocker_rows)
    return {
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        **owner_assignment,
        "dispatch_task_type": str(record.get("dispatch_task_type") or ""),
        "dispatch_task_type_label": _dispatch_task_type_label(str(record.get("dispatch_task_type") or "")),
        "current_stage": current_stage,
        "current_stage_label": _current_stage_label(current_stage),
        "evidence_grade": evidence_grade,
        "evidence_grade_label": _evidence_grade_label(evidence_grade),
        "blocker_reason": blocker_reason,
        "blocker_reason_label": _blocker_reason_label(blocker_reason),
        "blocker_reason_detail": blocker_reason_detail,
        "loop_terminal_state": terminal_state,
        "owner_status_label": _terminal_state_label(terminal_state),
        "next_recommended_action": next_action,
        "owner_next_action_label": _next_action_label(next_action),
        "automated_dispatch_available": automated_available,
        "manual_review_hold": manual_hold,
        "manual_hold_reason": blocker_reason_detail if manual_hold else "",
        "closeout_precedence_state": str(record.get("closeout_precedence_state") or ""),
        "closeout_precedence_suppressed": bool(record.get("closeout_precedence_suppressed")),
        "closeout_precedence_blocker_taxonomy": list(record.get("closeout_precedence_blocker_taxonomy") or []),
        "runtime_blocker_ledger_records": runtime_blocker_rows,
        "runtime_blocker_ledger_state_counts": dict(record.get("runtime_blocker_ledger_state_counts") or {})
        if isinstance(record.get("runtime_blocker_ledger_state_counts"), Mapping)
        else {},
        "runtime_blocker_ledger_layer_counts": dict(record.get("runtime_blocker_ledger_layer_counts") or {})
        if isinstance(record.get("runtime_blocker_ledger_layer_counts"), Mapping)
        else {},
        "runtime_blocker_subqueue_routes": runtime_blocker_routes,
        "runtime_blocker_subqueue_labels": [_runtime_blocker_subqueue_label(route) for route in runtime_blocker_routes],
        "runtime_blocker_subqueue_counts": _counts(runtime_blocker_routes),
        "runtime_blocker_worker_followup_available": bool(runtime_followup_rows),
        "runtime_blocker_worker_followup_count": len(runtime_followup_rows),
        "runtime_blocker_worker_followup_records": runtime_followup_rows,
        "runtime_blocker_worker_followup_entrypoint_counts": _counts(
            item.get("formal_entrypoint_id") for item in runtime_followup_rows
        ),
        "runtime_blocker_worker_followup_task_type_counts": _counts(
            item.get("followup_task_type") for item in runtime_followup_rows
        ),
        "runtime_blocker_worker_followup_readiness_state_counts": _counts(
            item.get("followup_readiness_state") for item in runtime_followup_rows
        ),
        "runtime_blocker_worker_followup_next_action_counts": _counts(
            item.get("next_action") for item in runtime_followup_rows
        ),
        "runtime_blocker_worker_followup_labels": [
            item.get("owner_followup_label") for item in runtime_followup_rows if item.get("owner_followup_label")
        ],
        "stage6_fact_package_state": str(record.get("stage6_fact_package_state") or ""),
        "stage6_ready": bool(record.get("stage6_ready", False)),
        "stage7_commercial_input_allowed": stage7_allowed,
        "stage7_gate_label": "允许进入第七阶段内部商业承接" if stage7_allowed else "暂不进入第七阶段，先复核证据缺口",
        "release_field_query_state": str(record.get("release_field_query_state") or ""),
        "release_field_query_task_count": int(record.get("release_field_query_task_count") or 0),
        "release_field_query_adapter_result_state_counts": dict(
            record.get("release_field_query_adapter_result_state_counts") or {}
        )
        if isinstance(record.get("release_field_query_adapter_result_state_counts"), Mapping)
        else {},
        "release_field_query_downstream_abcd_grade_counts": dict(
            record.get("release_field_query_downstream_abcd_grade_counts") or {}
        )
        if isinstance(record.get("release_field_query_downstream_abcd_grade_counts"), Mapping)
        else {},
        "release_field_query_authorized_session_input_state_counts": dict(
            record.get("release_field_query_authorized_session_input_state_counts") or {}
        )
        if isinstance(record.get("release_field_query_authorized_session_input_state_counts"), Mapping)
        else {},
        "release_field_query_authorization_state_counts": dict(
            record.get("release_field_query_authorization_state_counts") or {}
        )
        if isinstance(record.get("release_field_query_authorization_state_counts"), Mapping)
        else {},
        "release_field_query_operator_next_actions": _list(record.get("release_field_query_operator_next_actions")),
        "release_field_query_operator_next_action_labels": [
            _release_field_query_operator_action_label(action)
            for action in _list(record.get("release_field_query_operator_next_actions"))
        ],
        "release_field_query_source_hit_summaries": [
            dict(summary)
            for summary in _list(record.get("release_field_query_source_hit_summaries"))
            if isinstance(summary, Mapping)
        ],
        "release_field_query_source_hit_summary_labels": _list(
            record.get("release_field_query_source_hit_summary_labels")
        ),
        "stage5_calibration_sample_id": str(record.get("stage5_calibration_sample_id") or ""),
        "stage5_calibration_review_bucket": str(record.get("stage5_calibration_review_bucket") or ""),
        "stage5_calibration_review_bucket_label": _stage5_calibration_bucket_label(
            str(record.get("stage5_calibration_review_bucket") or "")
        ),
        "stage5_calibration_review_reasons": _list(record.get("stage5_calibration_review_reasons")),
        "stage5_calibration_review_reason_labels": [
            _stage5_calibration_reason_label(reason)
            for reason in _list(record.get("stage5_calibration_review_reasons"))
        ],
        "stage5_calibration_truth_label_required": bool(record.get("calibration_truth_label_required")),
        "stage5_calibration_suggested_action": str(record.get("suggested_calibration_action") or ""),
        "stage5_calibration_suggested_action_label": _stage5_calibration_action_label(
            str(record.get("suggested_calibration_action") or "")
        ),
        "stage5_calibration_gate_status_label": _stage5_calibration_gate_status_label(
            rule_status=str(record.get("stage5_rule_gate_status") or ""),
            evidence_status=str(record.get("stage5_evidence_gate_status") or ""),
        ),
        "input_refs": _operator_input_refs(record),
        "output_artifact_refs": _operator_output_artifact_refs(record),
        "reopen_conditions": _reopen_conditions(
            terminal_state=terminal_state,
            next_action=next_action,
            stage7_allowed=stage7_allowed,
        ),
        "reopen_condition_labels": [
            _reopen_condition_label(condition)
            for condition in _reopen_conditions(
                terminal_state=terminal_state,
                next_action=next_action,
                stage7_allowed=stage7_allowed,
            )
        ],
        "lineage": {
            "dispatch_readback_state": str(record.get("dispatch_readback_state") or ""),
            "dispatch_closeout_state": str(record.get("dispatch_closeout_state") or ""),
            "result_routing_state": str(record.get("result_routing_state") or ""),
            "result_runner_execution_state": str(record.get("result_runner_execution_state") or ""),
            "next_cycle_dispatch_readiness_state": str(record.get("next_cycle_dispatch_readiness_state") or ""),
            "next_cycle_manual_only_action_family": str(record.get("next_cycle_manual_only_action_family") or ""),
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
}


def _operator_blocker_ledger_row(record: Mapping[str, Any]) -> dict[str, Any]:
    operator_next_action = str(record.get("operator_next_action") or record.get("next_action") or "")
    return {
        "blocker_ledger_id": str(record.get("blocker_ledger_id") or ""),
        "ledger_scope": str(record.get("ledger_scope") or ""),
        "ledger_scope_label": _ledger_scope_label(str(record.get("ledger_scope") or "")),
        "task_scope": str(record.get("task_scope") or ""),
        "task_scope_label": _task_scope_label(str(record.get("task_scope") or "")),
        "task_type": str(record.get("task_type") or ""),
        "blocker_state": str(record.get("blocker_state") or ""),
        "blocker_state_label": _runtime_blocker_state_label(str(record.get("blocker_state") or "")),
        "blocker_reason": str(record.get("blocker_reason") or ""),
        "runtime_layer": str(record.get("runtime_layer") or ""),
        "runtime_layer_label": _runtime_layer_label(str(record.get("runtime_layer") or "")),
        "source_ledger_scopes": _list(record.get("source_ledger_scopes")),
        "source_ledger_scope_labels": [
            _ledger_scope_label(scope) for scope in _list(record.get("source_ledger_scopes"))
        ],
        "source_blocker_ledger_ids": _list(record.get("source_blocker_ledger_ids")),
        "source_runtime_layers": _list(record.get("source_runtime_layers")),
        "source_runtime_layer_labels": [
            _runtime_layer_label(layer) for layer in _list(record.get("source_runtime_layers"))
        ],
        "source_blocker_reasons": _list(record.get("source_blocker_reasons")),
        "required_input": _list(record.get("required_input")),
        "required_input_labels": [_required_input_label(item) for item in _list(record.get("required_input"))],
        "retry_policy": str(record.get("retry_policy") or ""),
        "retry_policy_label": _retry_policy_label(str(record.get("retry_policy") or "")),
        "reopen_conditions": _list(record.get("reopen_conditions")),
        "reopen_condition_labels": [
            _reopen_condition_label(condition) for condition in _list(record.get("reopen_conditions"))
        ],
        "operator_next_action": operator_next_action,
        "operator_next_action_label": _runtime_blocker_operator_action_label(operator_next_action),
        "source_trace_label": _runtime_blocker_source_trace_label(record),
        "artifact_ref": str(record.get("artifact_ref") or ""),
        "subqueue_routes": _runtime_blocker_record_subqueues(record),
        "subqueue_labels": [
            _runtime_blocker_subqueue_label(route) for route in _runtime_blocker_record_subqueues(record)
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _operator_worker_followup_row(record: Mapping[str, Any]) -> dict[str, Any]:
    formal_entrypoint_id = str(record.get("formal_entrypoint_id") or "")
    followup_task_type = str(record.get("followup_task_type") or "")
    followup_readiness_state = str(record.get("followup_readiness_state") or "")
    next_action = str(record.get("next_action") or "")
    input_artifact_refs = _dedupe(
        [
            record.get("release_evidence_adapter_plan_json"),
            record.get("gdcic_browser_readback_json"),
            *[
                item
                for item in _list(record.get("input_artifact_refs"))
            ],
        ]
    )
    output_artifact_refs = _dedupe(
        [
            record.get("output_root"),
            record.get("expected_output_artifact"),
            record.get("expected_output_artifact_path"),
        ]
    )
    return {
        "runtime_blocker_followup_task_id": str(record.get("runtime_blocker_followup_task_id") or ""),
        "source_runtime_blocker_dispatch_runner_task_id": str(
            record.get("source_runtime_blocker_dispatch_runner_task_id") or ""
        ),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "assigned_owner": str(record.get("assigned_owner") or ""),
        "assigned_owner_role": str(record.get("assigned_owner_role") or ""),
        "formal_entrypoint_id": formal_entrypoint_id,
        "formal_entrypoint_label": _formal_entrypoint_label(formal_entrypoint_id),
        "followup_task_type": followup_task_type,
        "followup_task_type_label": _worker_followup_task_type_label(followup_task_type),
        "followup_readiness_state": followup_readiness_state,
        "followup_readiness_state_label": _worker_followup_readiness_state_label(followup_readiness_state),
        "recommended_script": str(record.get("recommended_script") or ""),
        "recommended_command": str(record.get("recommended_command") or ""),
        "recommended_command_argv": _list(record.get("recommended_command_argv")),
        "recommended_command_available": bool(_list(record.get("recommended_command_argv")) or record.get("recommended_command")),
        "release_evidence_adapter_plan_json": str(record.get("release_evidence_adapter_plan_json") or ""),
        "gdcic_browser_readback_json": str(record.get("gdcic_browser_readback_json") or ""),
        "input_artifact_refs": input_artifact_refs,
        "expected_output_artifact": str(record.get("expected_output_artifact") or ""),
        "output_root": str(record.get("output_root") or ""),
        "output_artifact_refs": output_artifact_refs,
        "next_action": next_action,
        "next_action_label": _worker_followup_next_action_label(next_action),
        "execution_mode": str(record.get("execution_mode") or ""),
        "live_execution_enabled": bool(record.get("live_execution_enabled", False)),
        "requires_operator_action_before_live": bool(record.get("requires_operator_action_before_live", False)),
        "requires_operator_approval_before_execution": bool(
            record.get("requires_operator_approval_before_execution", False)
        ),
        "owner_followup_label": _worker_followup_owner_label(
            entrypoint_id=formal_entrypoint_id,
            task_type=followup_task_type,
            readiness_state=followup_readiness_state,
            next_action=next_action,
        ),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _operator_input_refs(record: Mapping[str, Any]) -> dict[str, Any]:
    marker = (
        dict(record.get("closeout_precedence_terminal_marker"))
        if isinstance(record.get("closeout_precedence_terminal_marker"), Mapping)
        else {}
    )
    return {
        "project_id": str(record.get("project_id") or ""),
        "dispatch_task_type": str(record.get("dispatch_task_type") or record.get("next_cycle_dispatch_task_type") or ""),
        "terminal_marker_task_id": str(marker.get("task_id") or ""),
        "original_notice_task_id": str(marker.get("original_notice_task_id") or ""),
        "marker_state": str(marker.get("marker_state") or marker.get("terminal_state") or ""),
        "marker_source_refs": [
            dict(item)
            for item in _list(record.get("closeout_precedence_marker_source_refs"))
            if isinstance(item, Mapping)
        ],
        "runtime_blocker_worker_followup_input_artifact_refs": _dedupe(
            ref
            for item in _list(record.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
            for ref in [
                item.get("release_evidence_adapter_plan_json"),
                item.get("gdcic_browser_readback_json"),
                *[
                    nested_ref
                    for nested_ref in _list(item.get("input_artifact_refs"))
                ],
            ]
        ),
        "runtime_blocker_worker_followup_entrypoints": _dedupe(
            item.get("formal_entrypoint_id")
            for item in _list(record.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "source_input_artifact_refs": _dedupe(_list(record.get("input_artifact_refs"))),
    }


def _operator_output_artifact_refs(record: Mapping[str, Any]) -> list[str]:
    marker = (
        record.get("closeout_precedence_terminal_marker")
        if isinstance(record.get("closeout_precedence_terminal_marker"), Mapping)
        else {}
    )
    return _dedupe(
        [
            *_list(record.get("output_artifact_refs")),
            record.get("release_field_query_result_json"),
            marker.get("artifact_ref") if isinstance(marker, Mapping) else "",
            *[
                item.get("artifact_ref")
                for item in _list(record.get("closeout_precedence_marker_source_refs"))
                if isinstance(item, Mapping)
            ],
            *[
                item.get("artifact_ref")
                for item in _list(record.get("runtime_blocker_ledger_records"))
                if isinstance(item, Mapping)
            ],
            *[
                item.get("output_root")
                for item in _list(record.get("runtime_blocker_worker_followup_records"))
                if isinstance(item, Mapping)
            ],
            *[
                item.get("expected_output_artifact")
                for item in _list(record.get("runtime_blocker_worker_followup_records"))
                if isinstance(item, Mapping)
            ],
        ]
    )


def _ledger_scope_values(record: Mapping[str, Any]) -> list[str]:
    scopes = _list(record.get("source_ledger_scopes"))
    if scopes:
        return [str(scope) for scope in scopes if str(scope or "").strip()]
    scope = str(record.get("ledger_scope") or "").strip()
    return [scope] if scope else []


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _current_stage(record: Mapping[str, Any], terminal_state: str, stage7_allowed: bool) -> str:
    if str(record.get("stage5_calibration_review_bucket") or "").strip():
        return "Stage5_RULE_GATE_CALIBRATION"
    if stage7_allowed:
        return "Stage7_INTERNAL_COMMERCIAL_REVIEW"
    if _list(record.get("runtime_blocker_worker_followup_records")):
        return "Stage4_RELEASE_EVIDENCE_FIELD_QUERY"
    release_state = str(record.get("release_field_query_state") or "")
    if release_state:
        return "Stage4_RELEASE_EVIDENCE_FIELD_QUERY"
    task_text = " ".join(
        str(record.get(key) or "")
        for key in ("dispatch_task_type", "next_task_type", "next_cycle_dispatch_task_type")
    )
    if "P13B" in task_text or terminal_state.startswith("P13B_CONTINUATION"):
        return "Stage4_P13B_CONTINUATION"
    if "DESIGN_SURVEY" in task_text:
        return "Stage4_DESIGN_SURVEY_PUBLIC_REGISTRY"
    if "RELEASE_EVIDENCE" in task_text:
        return "Stage4_RELEASE_EVIDENCE_CHAIN"
    if "ORIGINAL_NOTICE" in task_text or "BACKTRACE" in task_text:
        return "Stage4_ORIGINAL_NOTICE_BACKTRACE"
    if terminal_state == "NEXT_CYCLE_DISPATCH_READY":
        return "Stage6_NEXT_CYCLE_DISPATCH"
    if terminal_state == "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH":
        return "Stage6_MANUAL_REVIEW_HOLD"
    if terminal_state.startswith("RESULT_"):
        return "Stage6_RESULT_CLOSEOUT"
    return "Stage6_REVIEW_LOOP"


def _current_stage_label(stage: str) -> str:
    return {
        "Stage4_DESIGN_SURVEY_PUBLIC_REGISTRY": "Stage4 设计/测绘公开资质与服务期复核",
        "Stage4_P13B_CONTINUATION": "Stage4 P13B 历史重叠与续跑控制",
        "Stage4_RELEASE_EVIDENCE_CHAIN": "Stage4 释放证据链：施工许可/竣工/变更/合同履约",
        "Stage4_RELEASE_EVIDENCE_FIELD_QUERY": "Stage4 释放证据字段查询读回",
        "Stage4_ORIGINAL_NOTICE_BACKTRACE": "Stage4 原文回溯或定向补字段",
        "Stage5_RULE_GATE_CALIBRATION": "Stage5 规则门/证据门真实样本校准",
        "Stage6_NEXT_CYCLE_DISPATCH": "Stage6 下一轮受控续跑已生成",
        "Stage6_MANUAL_REVIEW_HOLD": "Stage6 人工复核停机",
        "Stage6_RESULT_CLOSEOUT": "Stage6 结果读回与收口",
        "Stage6_REVIEW_LOOP": "Stage6 复核循环",
        "Stage7_INTERNAL_COMMERCIAL_REVIEW": "Stage7 内部商业承接复核",
    }.get(stage, stage)


def _evidence_grade(record: Mapping[str, Any], terminal_state: str) -> str:
    direct_grade = _first_text(
        record.get("evidence_grade"),
        record.get("evidence_abcd_grade"),
        record.get("current_evidence_grade"),
        record.get("downstream_abcd_grade"),
        record.get("initial_abcd_grade"),
    )
    if direct_grade:
        return direct_grade
    downstream_counts = record.get("release_field_query_downstream_abcd_grade_counts")
    if isinstance(downstream_counts, Mapping) and downstream_counts:
        for prefix in ("A_", "B_", "C_", "D_"):
            match = next((str(key) for key in downstream_counts if str(key).startswith(prefix)), "")
            if match:
                return match
    if terminal_state == "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH":
        return "D_INSUFFICIENT_OR_BLOCKED_READBACK"
    return "GRADE_NOT_PROJECTED_TO_STATUS_TABLE"


def _evidence_grade_label(grade: str) -> str:
    if grade.startswith("A_"):
        return "A 级强线索：同人/同主体/时间窗口重叠，需继续释放证据补查。"
    if grade.startswith("B_"):
        return "B 级增强证据：施工许可、合同履约等官方读回可补强。"
    if grade.startswith("C_"):
        return "C 级反向解释：竣工、变更、退出等材料可解释或切分窗口。"
    if grade.startswith("D_"):
        return "D 级证据不足/来源阻断：不能写成没问题。"
    return {
        "GRADE_NOT_PROJECTED_TO_STATUS_TABLE": "当前状态表未投影证据等级，需回看 batch closeout 或 evidence state。",
    }.get(grade, grade)


def _blocker_reason(
    *,
    record: Mapping[str, Any],
    terminal_state: str,
    stage7_allowed: bool,
    automated_available: bool,
) -> str:
    if automated_available:
        return "not_blocked_controlled_dispatch_ready"
    if stage7_allowed:
        return "not_blocked_stage7_internal_review_allowed"
    explicit = _first_text(record.get("next_cycle_dispatch_block_reason"), record.get("result_runner_skip_reason"))
    if explicit:
        return explicit
    if terminal_state == "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH":
        return "manual_hold_requires_new_source_or_operator_override"
    if terminal_state == "RESULT_EXECUTED_NO_NEXT_DISPATCH":
        return "result_executed_no_next_automated_task"
    if terminal_state == "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW":
        return "release_field_query_gap_or_blocker"
    if terminal_state == "RELEASE_FIELD_QUERY_PENDING_OR_NEEDS_BROWSER":
        return "release_field_query_needs_browser_or_authorization"
    if terminal_state == "RELEASE_FIELD_QUERY_RESULT_MISSING":
        return "release_field_query_result_missing"
    if terminal_state == "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY":
        return "runtime_blocker_worker_followup_ready"
    if terminal_state == "P13B_CONTINUATION_OPERATOR_HOLD":
        return "p13b_continuation_operator_hold"
    if terminal_state in BLOCKED_OR_MANUAL_STATES:
        return "blocked_or_manual_review_required"
    return "stage7_gate_not_allowed_pending_evidence_review"


def _blocker_reason_label(reason: str) -> str:
    return {
        "not_blocked_controlled_dispatch_ready": "没有停死：已有下一轮内部受控续跑任务。",
        "not_blocked_stage7_internal_review_allowed": "没有停死：允许进入 Stage7 内部商业承接复核。",
        "stage6_review_cycle_bootstrap_registry_missing_or_invalid": (
            "Stage6 cycle bootstrap registry 缺失或不可解析，需先恢复 registry 再续跑。"
        ),
        "stage6_review_cycle_bootstrap_registry_schema_invalid": (
            "Stage6 cycle bootstrap registry schema 不合法，需先修复配置再续跑。"
        ),
        "same_recommended_command_already_selected": "同一组命令已执行/已选中，避免重复跑。",
        "terminal_source_gap_no_delta_manual_review_only": "官方来源缺口且本轮没有新增证据，已转人工复核。",
        "manual_hold_requires_new_source_or_operator_override": "人工停机：需要新官方来源，或操作者确认重开范围和预算。",
        "result_executed_no_next_automated_task": "本轮结果已执行，暂时没有下一条自动任务，需要复核产物后决定关闭或重开。",
        "release_field_query_gap_or_blocker": "释放证据字段查询仍是缺口或来源阻断，不能写成已排除风险。",
        "release_field_query_needs_browser_or_authorization": "释放证据字段查询需要授权浏览器、同会话重试或继续人工停机。",
        "release_field_query_result_missing": "释放证据字段查询结果产物缺失，需要补齐 readback 或重跑受控任务。",
        "runtime_blocker_worker_followup_ready": "browser worker 已产出可回灌读回，下一步进入字段查询回灌。",
        "original_notice_backtrace_budget_deferred_or_incomplete": (
            "原文回溯预算不足或本轮预算已耗尽，需补预算或新来源后继续。"
        ),
        "BLOCKED_OR_SOURCE_UNSUPPORTED": "原文来源受阻或入口不受支持，需人工复核或改走定向读回。",
        "LOW_VALUE_COMPANY_ONLY_REVIEW": "当前只有公司级弱信号，需暂存或在价值足够时转定向读回。",
        "PARK_TARGETED_PERSON_NOT_FOUND": "责任人定向读回未找到目标人，只能暂存线索，不能写成已排除风险。",
        "PARK_DIFFERENT_PERSON_WITH_PERIOD": "读回命中的是不同责任人且带履约周期，需人工复核后再决定是否保留线索。",
        "PARK_DIFFERENT_PERSON_NO_PERIOD": "读回命中的是不同责任人且缺周期信息，先低优先级暂存或人工复核。",
        "PARK_NO_EXTRACTED_MATCH_FIELDS": "原文未抽到公司/责任人/周期匹配字段，只能暂存并保留证据不足结论。",
        "p13b_continuation_operator_hold": "P13B 续跑暂挂，需操作者确认预算或重开条件。",
        "blocked_or_manual_review_required": "阻断或需人工复核，不能继续自动空转。",
        "stage7_gate_not_allowed_pending_evidence_review": "Stage7 暂未放行，需先复核证据缺口。",
    }.get(reason, reason)


def _dispatch_task_type_label(task_type: str) -> str:
    return {
        "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW": "原文回溯重试/人工复核",
        "RUN_DATA_GGZY_COMPANY_HISTORY_OVERLAP_TRIAGE": "P13B company history 重叠排查",
        "RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW": "设计测绘资质与服务期复核",
        "RUN_RELEASE_EVIDENCE_ADAPTER_PLAN": "释放证据 adapter 任务计划",
        "RUN_RELEASE_EVIDENCE_FIELD_QUERY": "释放证据字段查询",
        "": "无当前派发任务",
    }.get(task_type, task_type)


def _formal_entrypoint_label(entrypoint_id: str) -> str:
    return {
        "guangdong_local_field_query_probe": "广东本地释放证据字段查询",
        "guangdong_gdcic_openplatform_query_probe": "广东 GDCIC 匿名公开源查询",
        "stage6_review_loop_runner": "Stage6 复核循环",
        "stage16_p13b_continuation_runner": "P13B 续跑控制器",
    }.get(entrypoint_id, entrypoint_id)


def _worker_followup_task_type_label(task_type: str) -> str:
    return {
        "RUN_GUANGDONG_LOCAL_FIELD_QUERY_WITH_GDCIC_BROWSER_READBACK": (
            "使用 GDCIC 浏览器读回执行广东本地字段查询回灌"
        ),
    }.get(task_type, task_type)


def _worker_followup_readiness_state_label(state: str) -> str:
    return {
        "READY_FOR_CONTROLLED_FIELD_QUERY_BACKFILL": "已具备受控字段查询回灌输入。",
    }.get(state, state)


def _worker_followup_next_action_label(action: str) -> str:
    return {
        "run_guangdong_local_field_query_probe_then_stage6_review_loop_backfill": (
            "运行广东本地字段查询回灌，再回到 Stage6 复核循环。"
        ),
    }.get(action, action)


def _worker_followup_owner_label(
    *,
    entrypoint_id: str,
    task_type: str,
    readiness_state: str,
    next_action: str,
) -> str:
    parts = [
        _formal_entrypoint_label(entrypoint_id),
        _worker_followup_task_type_label(task_type),
        _worker_followup_readiness_state_label(readiness_state),
        _worker_followup_next_action_label(next_action),
    ]
    return "；".join(_dedupe(parts))


def _ledger_scope_label(scope: Any) -> str:
    text = str(scope or "").strip()
    return {
        "stage4_release_evidence_query": "Stage4 释放证据字段查询结果",
        "stage6_review_action_plan": "Stage6 动作计划",
        "stage6_review_loop": "Stage6 复核循环",
        "stage6_review_cycle_bootstrap_registry": "Stage6 cycle bootstrap registry 阻断",
        "p13b_continuation": "P13B 续跑控制器",
        "p13b_original_readback": "P13B 原文回溯读回",
        "original_readback": "原文公告读回",
        "release_evidence_query": "释放证据查询",
    }.get(text, text)


def _task_scope_label(scope: Any) -> str:
    text = str(scope or "").strip()
    return {
        "p13b_follow_up": "P13B 历史重叠续跑",
        "original_readback": "原文公告读回",
        "release_evidence_query": "释放证据字段查询",
        "stage4_field_task": "Stage4 字段任务",
        "stage6_review_cycle_bootstrap_registry": "Stage6 cycle bootstrap registry 校验",
        "project": "项目状态",
    }.get(text, text)


def _runtime_layer_label(layer: Any) -> str:
    text = str(layer or "").strip()
    return {
        "controller decision": "controller 判定",
        "worker execution": "worker 执行",
        "queue persistence": "queue 持久化",
        "closeout": "closeout 收口",
        "backfill": "backfill 回灌",
        "scheduler": "scheduler 调度",
        "audit log": "audit log 审计",
        "retry policy": "retry policy 重试策略",
        "suspend/dead-letter": "suspend/dead-letter 停机队列",
        "blocker taxonomy": "blocker taxonomy 阻断分类",
        "source adapter": "source adapter 来源适配器",
        "browser worker": "browser worker 浏览器任务",
        "approval gate": "approval gate 审批门",
        "schema/contract": "schema/contract 契约",
        "schema/contract:stage6_review_cycle_bootstrap_registry": (
            "schema/contract 契约：Stage6 cycle bootstrap registry"
        ),
        "operator projection": "operator projection 操作者投影",
    }.get(text, text)


def _runtime_blocker_state_label(state: Any) -> str:
    text = str(state or "").strip()
    return {
        "STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_BLOCKED": (
            "Stage6 cycle bootstrap registry 阻断：修复 registry 前不能继续下一轮控制器路由。"
        ),
        "ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED": (
            "原文回溯重试/续跑已入队，需等预算或新来源满足后再继续。"
        ),
        "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": "已有 terminal closeout/backfill，已抑制重复派发。",
        "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION": (
            "授权阻断：需要浏览器 worker 或操作者提供已授权会话。"
        ),
        "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED": (
            "公开源未命中：只能记录未命中事实，需 fallback source 或项目所在地主管部门来源。"
        ),
        "RELEASE_FIELD_QUERY_RESULT_MISSING": "释放证据字段查询产物缺失，需要找回 readback 或重跑受控任务。",
    }.get(text, text)


def _runtime_blocker_subqueue_label(route: Any) -> str:
    text = str(route or "").strip()
    return {
        "browser_worker": "进入 browser worker / 授权会话队列。",
        "fallback_source": "进入 fallback source / 项目所在地公开源队列。",
        "retry": "进入受控 retry 队列。",
        "manual_hold": "进入 manual hold，等待新输入或人工确认。",
        "suspend_dead_letter": "进入 suspend/dead-letter，禁止重复派发同类 worker。",
        "operator_action": "进入 operator action 队列。",
    }.get(text, text)


def _owner_assignment_state_label(state: Any) -> str:
    text = str(state or "").strip()
    return {
        "ASSIGNED_OWNER_READY": "项目 owner 已分配。",
        "UNASSIGNED_OWNER_REVIEW_REQUIRED": "项目 owner 未分配；下一轮运行前需要写入 owner。",
    }.get(text, text)


def _owner_assignment_next_action_label(action: Any) -> str:
    text = str(action or "").strip()
    return {
        "owner_reviews_project_status_and_records_decision": "项目 owner 复核当前状态并记录下一步决定。",
        "assign_project_owner_before_next_runtime_cycle": "先在状态表或 roster 中分配项目 owner，再进入下一轮运行。",
    }.get(text, text)


def _project_owner_label(*, assigned_owner: str, owner_role: str) -> str:
    owner = str(assigned_owner or "").strip()
    role = str(owner_role or "").strip()
    if owner and role:
        return f"{role}：{owner}"
    if owner:
        return owner
    return "待分配 owner"


def _required_input_label(required_input: Any) -> str:
    text = str(required_input or "").strip()
    return {
        "assigned_owner": "项目 owner",
        "assigned_owner_role": "项目 owner 角色",
        "operator_retry_budget": "操作者确认的续跑预算",
        "continuation_budget_reason": "续跑预算原因",
        "new_official_original_notice_source_or_snapshot": "新的官方原文来源或可回放快照",
        "operator_retry_scope": "操作者确认的重试范围",
        "authorized_browser_storage_state_or_user_data_dir": "已授权浏览器 storage_state 或 user_data_dir",
        "fallback_source_or_project_local_authority_path": "fallback source 或项目所在地主管部门入口",
        "new_machine_readable_input_artifact_available": "新的机器可读输入 artifact",
        "next_original_notice_backtrace_budget_or_new_source_snapshot": (
            "下一批原文回溯预算或新的官方原文来源快照"
        ),
        "operator_override_reason_or_new_machine_readable_input": "操作者 override 原因或新的机器可读输入",
        "valid_stage6_review_cycle_bootstrap_registry_yaml": "有效的 Stage6 cycle bootstrap registry YAML",
    }.get(text, text)


def _retry_policy_label(policy: Any) -> str:
    text = str(policy or "").strip()
    return {
        "retry_next_original_backtrace_batch_with_bounded_budget": (
            "只在拿到下一批原文回溯预算或新的官方原文来源后继续。"
        ),
        "retry_only_after_budget_increase_or_new_source": "只在增加预算或补充新来源后重试。",
        "retry_only_after_authorized_session_available": "只在已授权浏览器会话可用后重试。",
        "retry_only_with_fallback_source_or_more_precise_identifiers": (
            "只在有 fallback source 或更精确标识后重试。"
        ),
        "retry_only_after_blocker_resolved_or_browser_worker_ready": (
            "只在阻断解除或 browser worker 就绪后重试。"
        ),
        "manual_reopen_requires_new_official_source_or_operator_budget": (
            "人工重开必须有新官方来源或操作者确认预算。"
        ),
        "manual_reopen_requires_registry_fix_or_schema_repair": (
            "必须先修复 Stage6 cycle bootstrap registry 或其 schema，再人工重开。"
        ),
        "do_not_retry_same_worker_without_new_input_or_operator_override": (
            "没有新输入或操作者 override 时，不重跑同一 worker。"
        ),
    }.get(text, text)


def _runtime_blocker_operator_action_label(action: Any) -> str:
    text = str(action or "").strip()
    return {
        "restore_stage6_review_cycle_bootstrap_registry_yaml_then_rerun_cycle": (
            "恢复 Stage6 cycle bootstrap registry YAML 后再重跑。"
        ),
        "fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle": (
            "修复 Stage6 cycle bootstrap registry schema 后再重跑。"
        ),
        "build_release_evidence_regional_adapter_plan": "基于当前原文读回，继续生成释放证据计划。",
        "operator_confirms_higher_budget_before_retry": "操作者确认提高预算后再重试。",
        "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": (
            "提供 GDCIC 已授权浏览器会话后重跑。"
        ),
        "record_not_found_without_clearance_claim_or_try_project_local_authority": (
            "记录未命中事实；如有项目所在地主管部门来源，再补查。"
        ),
        "operator_adds_new_official_original_source_or_confirms_manual_retry_scope": (
            "补新官方原文来源，或确认人工重试范围。"
        ),
        "operator_reviews_retry_budget_or_keeps_original_readback_suspended": (
            "操作者复核原文回溯预算，或继续保持原文读回挂起。"
        ),
        "operator_reviews_terminal_projection_before_reopen": "复核 terminal 投影后再决定是否重开。",
        "route_to_blocker_ledger_or_operator_action_without_duplicate_dispatch": (
            "进入阻断账本或 operator action，不重复派发。"
        ),
        "operator_provides_authorized_browser_session_or_keeps_manual_hold": (
            "提供已授权浏览器会话，或保持人工停机。"
        ),
        "operator_reviews_source_gap_or_approves_retry_scope_without_clearance_claim": (
            "复核来源缺口，或确认重试范围；不能写成排除性结论。"
        ),
    }.get(text, text)


def _runtime_blocker_source_trace_label(record: Mapping[str, Any]) -> str:
    labels = [_ledger_scope_label(scope) for scope in _ledger_scope_values(record)]
    labels = _dedupe(labels)
    if not labels:
        return ""
    if len(labels) == 1:
        return f"该阻断来源：{labels[0]}。"
    return f"同一阻断已由{_join_cn(labels)}记录，当前按一条阻断处理。"


def _join_cn(values: Iterable[Any]) -> str:
    items = _dedupe(values)
    if len(items) <= 1:
        return "".join(items)
    return "、".join(items[:-1]) + "和" + items[-1]


def _reopen_conditions(*, terminal_state: str, next_action: str, stage7_allowed: bool) -> list[str]:
    if terminal_state == "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH":
        return list(MANUAL_HOLD_REOPEN_CONDITIONS)
    if stage7_allowed:
        return ["operator_reviews_stage7_commercial_boundary_before_sales_use"]
    if terminal_state in ACTIONABLE_AUTOMATED_STATES:
        return ["operator_runs_internal_allowlisted_dispatch_or_keeps_dry_run"]
    if next_action:
        return ["operator_reviews_next_action_and_records_decision"]
    return ["operator_reviews_project_status_inputs"]


def _owner_batch_state(project_rows: list[Mapping[str, Any]]) -> str:
    if not project_rows:
        return "EMPTY"
    if any(bool(row.get("automated_dispatch_available")) for row in project_rows):
        return "ACTION_READY"
    if any(bool(row.get("runtime_blocker_worker_followup_available")) for row in project_rows):
        return "ACTION_READY"
    if any(bool(row.get("stage7_commercial_input_allowed")) for row in project_rows):
        return "STAGE7_INTERNAL_REVIEW_READY"
    if all(bool(row.get("manual_review_hold")) for row in project_rows):
        return "MANUAL_REVIEW_HOLD"
    return "MIXED_REVIEW_REQUIRED"


def _owner_batch_state_label(state: str) -> str:
    return {
        "EMPTY": "暂无第六阶段批次复核产物",
        "ACTION_READY": "有项目可继续受控续跑",
        "STAGE7_INTERNAL_REVIEW_READY": "有项目可进入第七阶段内部商业承接复核",
        "MANUAL_REVIEW_HOLD": "全部项目停在人工复核",
        "MIXED_REVIEW_REQUIRED": "批次需要人工分拣复核",
    }.get(state, state)


def _operator_decision(summary: Mapping[str, Any], project_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not project_rows:
        return {
            "decision_state": "NO_STAGE6_LOOP_STATUS_TABLE",
            "decision_label": "还没有可读的第六阶段批次状态表",
            "next_actions": ["run_stage6_review_loop_or_select_existing_status_table"],
            "next_action_labels": ["先运行第六阶段复核循环，或选择已有批次状态表"],
        }
    next_actions: list[str] = []
    if int(summary.get("automated_dispatch_available_count") or 0):
        next_actions.append("run_ready_internal_dispatch_or_keep_dry_run")
    if int(summary.get("runtime_blocker_worker_followup_count") or 0):
        next_actions.append("run_ready_worker_followup_or_keep_operator_hold")
    if int(summary.get("stage5_calibration_truth_label_required_count") or 0):
        next_actions.append("review_stage5_calibration_samples_before_rule_change")
    if int(summary.get("manual_hold_count") or 0):
        next_actions.append("manual_review_hold_requires_new_source_or_operator_override")
    if int(summary.get("stage7_commercial_input_allowed_count") or 0):
        next_actions.append("review_stage7_commercial_boundary_before_sales_use")
    if not next_actions:
        next_actions.append("review_project_status_rows")
    return {
        "decision_state": str(summary.get("operator_batch_state") or ""),
        "decision_label": str(summary.get("operator_batch_state_label") or ""),
        "next_actions": next_actions,
        "next_action_labels": [_operator_decision_action_label(action) for action in next_actions],
    }


def _terminal_state_label(state: str) -> str:
    return {
        "NEXT_CYCLE_DISPATCH_READY": "下一轮受控任务已准备",
        "WAITING_FOR_DISPATCH_EXECUTION": "等待受控执行",
        "RESULT_COMMAND_READY_NOT_EXECUTED": "结果回灌命令待执行",
        "RESULT_COMMAND_READY_DRY_RUN": "结果命令已生成，当前未执行",
        "RESULT_DUPLICATE_COMMAND_SKIPPED": "重复结果命令已跳过",
        "RESULT_EXECUTED_NO_NEXT_DISPATCH": "结果已执行，暂无下一轮自动任务",
        "RESULT_EXECUTION_FAILED": "结果执行失败，需排障",
        "RESULT_COMMAND_BLOCKED_BY_ALLOWLIST": "命令未过白名单，需要修正",
        "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH": "人工停机：需要新来源或人工确认后再开",
        "PARKED_OPERATOR_SKIPPED_THIS_ROUND": "本轮由操作者跳过",
        "BLOCKED_OR_MANUAL_REVIEW_REQUIRED": "阻断或需人工复核",
        "MANUAL_ROUTING_REVIEW_REQUIRED": "路由需要人工复核",
        "RELEASE_FIELD_QUERY_REVIEW_READY": "释放证据字段查询已有 B/C 读回，需人工复核后再决定是否进入 Stage7",
        "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY": (
            "公开源字段已有读回，需人工补齐证据等级后再决定是否进入 Stage7"
        ),
        "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW": "释放证据字段查询仍是缺口或来源阻断，不能写成已排除风险",
        "RELEASE_FIELD_QUERY_PENDING_OR_NEEDS_BROWSER": "释放证据字段查询待补浏览器/授权环境后重跑",
        "RELEASE_FIELD_QUERY_RESULT_MISSING": "释放证据字段查询结果缺失，需先找回或重跑产物",
        "RELEASE_FIELD_QUERY_NO_PROJECT_TASKS": "释放证据字段查询没有项目任务",
        "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY": "阻断 worker 已产出后续字段查询回灌任务",
        "RELEASE_EVIDENCE_QUERY_READY_FROM_ORIGINAL_READBACK": "原文读回已具备释放证据下一步，可继续进入 release evidence query",
        "NEXT_ORIGINAL_READBACK_SUBQUEUE_READY": "原文读回下一子队列已准备，可继续跑 targeted/route-specific/retry",
        "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW": "原文读回进入阻断账本复核，不能写成已排除风险",
        "ORIGINAL_READBACK_MANUAL_HOLD": "原文读回停在人工复核，需新来源或人工确认后再开",
        "P13B_CONTINUATION_READY": "P13B 续跑已具备下一步，可继续进入 data.ggzy 历史重叠排查",
        "P13B_CONTINUATION_OPERATOR_HOLD": "P13B 续跑进入人工挂起，需预算或重开条件后再继续",
    }.get(state, state)


def _next_action_label(action: str) -> str:
    return {
        "restore_stage6_review_cycle_bootstrap_registry_yaml_then_rerun_cycle": (
            "恢复 Stage6 cycle bootstrap registry YAML 后再重跑。"
        ),
        "fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle": (
            "修复 Stage6 cycle bootstrap registry schema 后再重跑。"
        ),
        "run_next_cycle_dispatch_or_keep_internal_review_dry_run": "运行下一轮受控任务，或保持内部 dry-run 复核",
        "manual_review_or_new_source_override_required_before_retry": "补新官方来源或记录人工确认后再重开",
        "run_controlled_dispatch_task_or_record_operator_skip": "执行受控任务，或记录本轮人工跳过",
        "execute_result_runner_or_keep_dry_run": "执行结果回灌，或保持 dry-run",
        "use_first_identical_result_runner_output_for_this_project_group": "使用同组首个结果，避免重复执行",
        "review_result_artifact_and_close_project_or_generate_next_cycle_if_needed": "复核结果产物，再决定关闭或开下一轮",
        "inspect_result_runner_failure_then_retry_or_park": "排查执行失败，再重试或暂存",
        "fix_structured_command_allowlist_before_execution": "先修结构化命令白名单再执行",
        "manual_review_release_evidence_b_or_c_readback_before_stage7_preview": (
            "先人工复核释放证据 B/C 读回，再决定是否进入 Stage7 内部预览。"
        ),
        "manual_review_public_field_readback_before_stage7_preview": (
            "先人工复核公开源字段读回，补齐证据等级后再决定是否进入 Stage7 内部预览。"
        ),
        "record_release_evidence_gap_or_retry_jurisdiction_source_without_clearance_claim": (
            "记录释放证据缺口或阻断；可重试项目所在地主管部门来源，但不能写成已排除风险。"
        ),
        "authorize_browser_or_live_release_field_query_or_keep_plan_only": (
            "补授权浏览器环境后重跑释放证据字段查询，或者保持计划态。"
        ),
        "inspect_release_field_query_result_before_next_stage6_cycle": (
            "先检查释放证据字段查询产物，再决定下一轮 Stage6 动作。"
        ),
        "operator_reviews_retry_budget_or_keeps_original_readback_suspended": (
            "操作者复核原文回溯预算，或继续保持原文读回挂起。"
        ),
        "run_guangdong_local_field_query_probe_then_stage6_review_loop_backfill": (
            "运行广东本地字段查询回灌，再回到 Stage6 复核循环。"
        ),
        "build_release_evidence_regional_adapter_plan": "基于当前原文读回，继续生成释放证据计划。",
        "run_next_live_original_notice_backtrace_batch": "继续运行下一批原文回溯任务。",
        "run_browser_or_attachment_ocr_readback_for_responsible_person": "转到责任人定向读回或附件 OCR 续跑。",
        "run_route_specific_readback_before_direct_live_retry": "先按路由专用读回，再决定是否重跑 live 原文回溯。",
        "run_ygp_original_readback_before_original_backtrace": (
            "先跑 YGP 原文读回，再决定是否进入 direct live 原文回溯。"
        ),
        "run_live_original_notice_backtrace_for_unattempted_task": "继续运行未尝试过的原文回溯任务。",
        "manual_review_or_retry_targeted_person_readback_without_clearance_claim": (
            "责任人定向读回受阻；先人工复核，必要时补预算或新输入后再重开，不能写成已排除风险。"
        ),
        "manual_review_missing_or_invalid_original_notice_url_without_clearance_claim": (
            "原文链接缺失或无效；先人工复核并补正确入口，不能写成已排除风险。"
        ),
        "manual_review_or_route_specific_readback_without_clearance_claim": (
            "原文抓取受阻；先人工复核或转路由专用读回，不能写成已排除风险。"
        ),
        "park_or_manual_review_without_release_probe": (
            "当前提取到的是不同责任人；先暂存或人工复核，不直接进入 release probe。"
        ),
        "park_low_priority_or_manual_review_without_clearance_claim": (
            "当前只有低价值差异信号；先低优先级暂存或人工复核，不能写成已排除风险。"
        ),
        "park_or_targeted_readback_if_value_justifies": (
            "当前只命中公司级弱信号；先暂存，或在价值足够时转责任人定向读回。"
        ),
        "park_without_clearance_claim": "保留事实，不输出排除性结论，转人工停机复核。",
        "run_data_ggzy_company_history_overlap_triage": "继续运行 data.ggzy 公司历史重叠排查。",
        "operator_confirms_higher_budget_before_retry": "操作者确认提高预算后再继续 P13B 续跑。",
    }.get(action, action)


def _release_field_query_operator_action_label(action: str) -> str:
    return {
        "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": (
            "提供 GDCIC 已授权浏览器会话后重跑。"
        ),
        "do_not_treat_http_dynamic_stealthy_as_login_state_replacement": (
            "不要把 HTTP/Dynamic/Stealthy 当作登录态替代；登录态缺口必须单独处理。"
        ),
        "review_gdcic_authorized_query_terms_or_capture_more_precise_field_page": (
            "复核 GDCIC 查询关键词，或捕获更精确的字段页面。"
        ),
        "install_or_enable_playwright_browser_runtime_then_rerun": "安装或启用 Playwright 浏览器运行时后重跑。",
        "increase_max_live_browser_tasks_or_run_specific_task": "提高浏览器任务预算，或只运行指定任务。",
        "rerun_with_headed_browser_or_longer_wait_budget": "用可视浏览器或更长等待预算重跑。",
        "review_gdcic_browser_execution_blocker_then_rerun": "复核 GDCIC 浏览器执行阻断后重跑。",
    }.get(action, action)


def _stage5_calibration_bucket_label(bucket: str) -> str:
    return {
        "STAGE5_PASS_WITH_NO_ACTIVE_GAP_BASELINE": (
            "Stage5 通过且当前没有显式 Stage4 缺口，可作为通过基线样本。"
        ),
        "STAGE5_REVIEW_WITH_ACTIVE_SOURCE_GAP_BASELINE": (
            "Stage5 复核与 Stage4 来源缺口一致，可作为缺口基线样本。"
        ),
        "POTENTIAL_FALSE_POSITIVE_REVIEW": (
            "Stage5 已通过但 Stage4/运行链仍有缺口，需复核是否潜在误放。"
        ),
        "POTENTIAL_FALSE_NEGATIVE_REVIEW": (
            "Stage5 复核/阻断但主链已内部 ready，需复核是否潜在误拦。"
        ),
        "STAGE5_REVIEW_WITHOUT_EXPLICIT_GAP_REVIEW": (
            "Stage5 需要复核但未投影明确 Stage4 缺口，需补复核原因。"
        ),
        "STAGE5_CALIBRATION_INPUT_INCOMPLETE": (
            "Stage5 校准输入不完整，需先补 gate 状态或重跑。"
        ),
    }.get(bucket, bucket)


def _stage5_calibration_reason_label(reason: Any) -> str:
    text = str(reason or "")
    if text.startswith("missing_stage4_5_source_type:"):
        source_type = text.split(":", 1)[1]
        return f"Stage4/5 缺少公开来源类型：{source_type}。"
    return {
        "stage5_passed_while_stage4_or_runtime_gap_still_exists": (
            "Stage5 通过时仍存在 Stage4 来源缺口或运行阻断。"
        ),
        "stage5_review_or_block_without_explicit_stage4_gap_on_internal_ready_chain": (
            "Stage5 复核/阻断但未看到明确 Stage4 缺口，且主链已内部 ready。"
        ),
        "stage5_gate_status_missing_or_incomplete": "Stage5 rule/evidence gate 状态缺失或不完整。",
        "source_gap_review_required": "公开来源缺口仍需复核。",
        "stage2_detail_capture_pending": "Stage2 详情采集仍待完成。",
        "stage1_6_loop_time_budget_pending": "Stage1-6 批量运行预算不足或待继续。",
    }.get(text, text)


def _stage5_calibration_action_label(action: str) -> str:
    return {
        "review_stage5_pass_against_stage4_source_gap_before_rule_relaxation": (
            "先复核 Stage5 通过样本与 Stage4 来源缺口是否冲突，再决定是否放宽规则。"
        ),
        "review_stage5_review_or_block_against_internal_ready_sample_before_rule_tightening": (
            "先复核 Stage5 复核/阻断样本是否误拦，再决定是否收紧规则。"
        ),
        "keep_review_until_stage4_source_gap_resolved_or_truth_label_added": (
            "保持复核，直到 Stage4 来源缺口解决或补充人工 truth label。"
        ),
        "rerun_or_backfill_stage5_gate_status_before_calibration": (
            "先重跑或回填 Stage5 gate 状态，再进入校准。"
        ),
        "keep_as_stage5_calibration_baseline": "保留为 Stage5 校准基线样本。",
    }.get(action, action)


def _stage5_calibration_gate_status_label(*, rule_status: str, evidence_status: str) -> str:
    if not rule_status and not evidence_status:
        return "Stage5 rule/evidence gate 状态未投影。"
    return f"规则门：{rule_status or '未投影'}；证据门：{evidence_status or '未投影'}。"


def _operator_decision_action_label(action: str) -> str:
    return {
        "run_ready_internal_dispatch_or_keep_dry_run": "运行已准备好的内部受控续跑任务，或者保持试运行复核。",
        "manual_review_hold_requires_new_source_or_operator_override": "人工停机项目需要补新官方来源，或由操作者确认重开范围和预算。",
        "review_stage7_commercial_boundary_before_sales_use": "进入第七阶段前先复核商业展示边界，不能外发客户。",
        "run_ready_worker_followup_or_keep_operator_hold": (
            "运行已准备的 worker follow-up，或继续保持 operator hold。"
        ),
        "review_stage5_calibration_samples_before_rule_change": (
            "先复核 Stage5 校准样本并补人工 truth label，再决定是否调整规则。"
        ),
        "review_project_status_rows": "逐个查看项目卡片，确认下一步动作。",
        "run_stage6_review_loop_or_select_existing_status_table": "先运行第六阶段复核循环，或选择已有批次状态表。",
    }.get(action, action)


def _reopen_condition_label(condition: str) -> str:
    return {
        "valid_bootstrap_registry_available_and_audited": (
            "有效的 bootstrap registry 已恢复，并完成基本审计/校验。"
        ),
        "bounded_original_notice_backtrace_budget_available": "已拿到下一批原文回溯预算。",
        "new_machine_readable_original_notice_source_available": "已补到新的机器可读原文来源。",
        "new_machine_readable_input_artifact_available": "已补到新的机器可读输入 artifact。",
        "new_official_original_notice_source_or_snapshot_available": "拿到新的官方原文来源或可回放快照。",
        "operator_confirms_manual_retry_scope_and_budget": "操作者确认本次人工重试范围和预算。",
        "operator_override_records_scope_budget_and_reason": "操作者已记录 override 范围、预算和原因。",
        "new_release_evidence_source_or_project_local_authority_path_available": "找到新的释放证据来源，或项目所在地主管部门公开查询入口。",
        "prior_blocker_resolved_without_clearance_claim": "前一轮阻断已解决，但不能写成排除性结论。",
        "operator_reviews_stage7_commercial_boundary_before_sales_use": "操作者先复核第七阶段商业展示边界。",
        "operator_runs_internal_allowlisted_dispatch_or_keeps_dry_run": "执行内部白名单受控任务，或继续保持试运行。",
        "operator_reviews_next_action_and_records_decision": "操作者复核下一步动作并记录决定。",
        "operator_reviews_project_status_inputs": "操作者复核项目状态输入。",
    }.get(condition, condition)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "DEFAULT_STAGE6_REVIEW_LOOP_SEARCH_ROOT",
    "STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME",
    "build_stage6_review_loop_operator_projection",
    "find_latest_stage6_review_loop_status_table",
    "list_stage6_review_loop_status_table_options",
    "load_stage6_review_loop_operator_projection",
]
