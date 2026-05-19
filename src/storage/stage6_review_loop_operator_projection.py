from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


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
}

BLOCKED_OR_MANUAL_STATES = {
    "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
    "BLOCKED_OR_MANUAL_REVIEW_REQUIRED",
    "MANUAL_ROUTING_REVIEW_REQUIRED",
    "RESULT_EXECUTION_FAILED",
    "RESULT_COMMAND_BLOCKED_BY_ALLOWLIST",
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
    resolved = explicit_status_path if explicit_status_path else find_latest_stage6_review_loop_status_table(effective_search_root)
    if not resolved:
        surface = build_stage6_review_loop_operator_projection(
            {},
            source_path="",
            source_readback_state="EMPTY",
            created_at=created_at,
        )
        _attach_batch_options(surface, batch_options, selected_path=None)
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
        _attach_batch_options(surface, batch_options, selected_path=resolved)
        return surface
    surface = build_stage6_review_loop_operator_projection(
        payload,
        source_path=str(resolved),
        source_readback_state="READBACK_READY",
        created_at=created_at,
    )
    _attach_batch_options(surface, batch_options, selected_path=resolved)
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


def build_stage6_review_loop_operator_projection(
    status_table_payload: Mapping[str, Any] | None,
    *,
    source_path: str = "",
    source_readback_state: str = "READBACK_READY",
    created_at: str | None = None,
) -> dict[str, Any]:
    payload = dict(status_table_payload or {})
    summary_in, records_in = _extract_status_table(payload)
    project_rows = [_project_row(record) for record in records_in]
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
) -> None:
    surface.pop("projection_sha256", None)
    selected_index = -1
    for index, option in enumerate(batch_options):
        if selected_path is not None and _same_path(option.get("status_table_path"), selected_path):
            selected_index = index
            break
    surface["batch_options"] = [dict(option) for option in batch_options]
    surface["batch_option_count"] = len(batch_options)
    surface["selected_batch_path"] = str(selected_path or surface.get("source_path") or "")
    surface["selected_batch_index"] = selected_index
    surface["batch_selector_visible"] = bool(batch_options)
    surface["multi_batch_review_available"] = len(batch_options) > 1
    surface["multi_project_batch_available"] = any(
        int(option.get("project_count") or 0) > 1 for option in batch_options
    )
    surface["projection_sha256"] = _fingerprint(surface)


def _status_table_option(path: Path, root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary, records = _extract_status_table(payload if isinstance(payload, Mapping) else {})
        project_rows = [_project_row(record) for record in records]
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


def _project_row(record: Mapping[str, Any]) -> dict[str, Any]:
    terminal_state = str(record.get("loop_terminal_state") or "NO_PROJECT_STATUS_RECORD")
    next_action = str(record.get("next_recommended_action") or "review_project_status_inputs")
    manual_hold = terminal_state == "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH"
    stage7_allowed = bool(record.get("stage7_commercial_input_allowed", False))
    automated_available = terminal_state in ACTIONABLE_AUTOMATED_STATES
    hold_reason = _first_text(
        record.get("next_cycle_dispatch_block_reason"),
        record.get("result_runner_skip_reason"),
        record.get("dispatch_closeout_state"),
        record.get("dispatch_readback_state"),
    )
    return {
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "dispatch_task_type": str(record.get("dispatch_task_type") or ""),
        "loop_terminal_state": terminal_state,
        "owner_status_label": _terminal_state_label(terminal_state),
        "next_recommended_action": next_action,
        "owner_next_action_label": _next_action_label(next_action),
        "automated_dispatch_available": automated_available,
        "manual_review_hold": manual_hold,
        "manual_hold_reason": hold_reason if manual_hold else "",
        "stage6_fact_package_state": str(record.get("stage6_fact_package_state") or ""),
        "stage6_ready": bool(record.get("stage6_ready", False)),
        "stage7_commercial_input_allowed": stage7_allowed,
        "stage7_gate_label": "允许进入第七阶段内部商业承接" if stage7_allowed else "暂不进入第七阶段，先复核证据缺口",
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
    }.get(state, state)


def _next_action_label(action: str) -> str:
    return {
        "run_next_cycle_dispatch_or_keep_internal_review_dry_run": "运行下一轮受控任务，或保持内部 dry-run 复核",
        "manual_review_or_new_source_override_required_before_retry": "补新官方来源或记录人工确认后再重开",
        "run_controlled_dispatch_task_or_record_operator_skip": "执行受控任务，或记录本轮人工跳过",
        "execute_result_runner_or_keep_dry_run": "执行结果回灌，或保持 dry-run",
        "use_first_identical_result_runner_output_for_this_project_group": "使用同组首个结果，避免重复执行",
        "review_result_artifact_and_close_project_or_generate_next_cycle_if_needed": "复核结果产物，再决定关闭或开下一轮",
        "inspect_result_runner_failure_then_retry_or_park": "排查执行失败，再重试或暂存",
        "fix_structured_command_allowlist_before_execution": "先修结构化命令白名单再执行",
    }.get(action, action)


def _operator_decision_action_label(action: str) -> str:
    return {
        "run_ready_internal_dispatch_or_keep_dry_run": "运行已准备好的内部受控续跑任务，或者保持试运行复核。",
        "manual_review_hold_requires_new_source_or_operator_override": "人工停机项目需要补新官方来源，或由操作者确认重开范围和预算。",
        "review_stage7_commercial_boundary_before_sales_use": "进入第七阶段前先复核商业展示边界，不能外发客户。",
        "review_project_status_rows": "逐个查看项目卡片，确认下一步动作。",
        "run_stage6_review_loop_or_select_existing_status_table": "先运行第六阶段复核循环，或选择已有批次状态表。",
    }.get(action, action)


def _reopen_condition_label(condition: str) -> str:
    return {
        "new_official_original_notice_source_or_snapshot_available": "拿到新的官方原文来源或可回放快照。",
        "operator_confirms_manual_retry_scope_and_budget": "操作者确认本次人工重试范围和预算。",
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
