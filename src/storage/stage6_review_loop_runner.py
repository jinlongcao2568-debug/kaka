from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso
from storage.evidence_stage6_fact_package import build_evidence_stage6_fact_package
from storage.stage6_review_action_dispatch import build_stage6_review_action_dispatch
from storage.stage6_review_action_dispatch_closeout import build_stage6_review_action_dispatch_closeout
from storage.stage6_review_action_dispatch_readback import build_stage6_review_action_dispatch_readback
from storage.stage6_review_action_dispatch_runner import (
    TASK_TYPE_DESIGN_SURVEY,
    TASK_TYPE_ORIGINAL,
    TASK_TYPE_RELEASE_PLAN,
    run_stage6_review_action_dispatch_runner,
)
from storage.stage6_review_action_result_routing import build_stage6_review_action_result_routing
from storage.stage6_review_action_result_runner import run_stage6_review_action_result_runner
from storage.stage6_review_cycle_runner import run_stage6_review_cycle_runner


STAGE6_REVIEW_LOOP_RUNNER_KIND = "stage6_review_loop_runner_v1_manifest"
STAGE6_REVIEW_LOOP_RUNNER_VERSION = 1
STAGE6_REVIEW_LOOP_RUNNER_ADAPTER_ID = "stage6-review-loop-runner-v1"

DEFAULT_DISPATCH_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-v1")
DEFAULT_BATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")
DEFAULT_BATCH_CLOSEOUT_DISCOVERY_ROOT = Path("tmp/evaluation-real-samples")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-loop-runner-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

CommandExecutor = Callable[[list[str], Path], Mapping[str, Any]]


def run_stage6_review_loop_runner(
    *,
    dispatch_json: str | Path | None = None,
    dispatch_root: str | Path = DEFAULT_DISPATCH_ROOT,
    batch_closeout_json: str | Path | None = None,
    batch_closeout_root: str | Path = DEFAULT_BATCH_CLOSEOUT_ROOT,
    baseline_evidence_state_json: str | Path | None = None,
    baseline_evidence_state_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    auto_bootstrap_from_batch_closeout: bool = True,
    auto_discover_latest_batch_closeout: bool = False,
    execute_dispatch: bool = False,
    execute_results: bool = False,
    execute_next_cycle_dispatch: bool = False,
    dispatch_max_groups: int | None = None,
    result_max_commands: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    cwd: str | Path | None = None,
    created_at: str | None = None,
    command_executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    dispatch_run_root = out_dir / "1-dispatch-run"
    readback_root = out_dir / "2-readback"
    closeout_root = out_dir / "3-closeout"
    routing_root = out_dir / "4-routing"
    evidence_state_rebuild_root = out_dir / "5-state"
    batch_closeout_rebuild_root = out_dir / "5-batch"
    release_field_query_root = out_dir / "5-field"
    result_run_root = out_dir / "6-result-run"
    next_cycle_root = out_dir / "7-cycle"
    out_dir.mkdir(parents=True, exist_ok=True)

    bootstrap = _prepare_dispatch_input(
        dispatch_json=dispatch_json,
        dispatch_root=dispatch_root,
        batch_closeout_json=batch_closeout_json,
        batch_closeout_root=batch_closeout_root,
        output_root=out_dir / "0-bootstrap",
        auto_bootstrap_from_batch_closeout=auto_bootstrap_from_batch_closeout,
        auto_discover_latest_batch_closeout=auto_discover_latest_batch_closeout,
        project_ids=project_ids,
        baseline_evidence_state_json=baseline_evidence_state_json,
        created_at=created,
    )
    effective_dispatch_json = str(bootstrap.get("effective_dispatch_json") or "")
    effective_dispatch_root = str(bootstrap.get("effective_dispatch_root") or dispatch_root)
    loop_input_state = str(bootstrap.get("loop_input_state") or "")
    input_blocked = loop_input_state.startswith("INPUT_BLOCKED")
    bootstrap_no_automated_tasks = loop_input_state == "BOOTSTRAPPED_DISPATCH_NO_AUTOMATED_TASKS"

    dispatch_runner: dict[str, Any] = {}
    readback: dict[str, Any] = {}
    closeout: dict[str, Any] = {}
    routing: dict[str, Any] = {}
    result_runner: dict[str, Any] = {}
    next_cycle: dict[str, Any] = {}
    next_cycle_skip_reason = ""

    if input_blocked:
        next_cycle_skip_reason = "dispatch_or_batch_closeout_input_missing"
    elif bootstrap_no_automated_tasks:
        next_cycle_skip_reason = "bootstrap_dispatch_has_no_automated_tasks"
    else:
        dispatch_runner = _run_loop_children(
            dispatch_json=effective_dispatch_json,
            dispatch_root=effective_dispatch_root,
            baseline_evidence_state_json=baseline_evidence_state_json,
            baseline_evidence_state_root=baseline_evidence_state_root,
            dispatch_run_root=dispatch_run_root,
            readback_root=readback_root,
            closeout_root=closeout_root,
            routing_root=routing_root,
            evidence_state_rebuild_root=evidence_state_rebuild_root,
            batch_closeout_rebuild_root=batch_closeout_rebuild_root,
            release_field_query_root=release_field_query_root,
            result_run_root=result_run_root,
            execute_dispatch=execute_dispatch,
            execute_results=execute_results,
            execute_next_cycle_dispatch=execute_next_cycle_dispatch,
            dispatch_max_groups=dispatch_max_groups,
            result_max_commands=result_max_commands,
            project_ids=project_ids,
            cwd=cwd,
            created_at=created,
            command_executor=command_executor,
        )
        readback = dict(dispatch_runner.pop("_loop_readback"))
        closeout = dict(dispatch_runner.pop("_loop_closeout"))
        routing = dict(dispatch_runner.pop("_loop_routing"))
        result_runner = dict(dispatch_runner.pop("_loop_result_runner"))
        next_cycle = dict(dispatch_runner.pop("_loop_next_cycle"))
        next_cycle_skip_reason = str(dispatch_runner.pop("_loop_next_cycle_skip_reason"))

    blocking_reasons = [
        *_list(bootstrap.get("blocking_reasons")),
        *_all_blocking_reasons(
            dispatch_runner,
            readback,
            closeout,
            routing,
            result_runner,
            next_cycle,
        ),
    ]
    release_field_query_results = _release_field_query_results_by_project(result_runner)
    project_status_records = [
        *[
            dict(record)
            for record in _list(bootstrap.get("bootstrap_project_status_records"))
            if isinstance(record, Mapping)
        ],
        *_project_status_records(
            readback=readback,
            closeout=closeout,
            routing=routing,
            result_runner=result_runner,
            next_cycle=next_cycle,
            release_field_query_results=release_field_query_results,
        ),
    ]
    summary = _summary(
        dispatch_runner=dispatch_runner,
        readback=readback,
        closeout=closeout,
        routing=routing,
        result_runner=result_runner,
        next_cycle=next_cycle,
        project_status_records=project_status_records,
        next_cycle_skip_reason=next_cycle_skip_reason,
        bootstrap=bootstrap,
        blocking_reasons=blocking_reasons,
        execute_dispatch=execute_dispatch,
        execute_results=execute_results,
        execute_next_cycle_dispatch=execute_next_cycle_dispatch,
    )
    dispatch_path = Path(effective_dispatch_json) if effective_dispatch_json else Path(effective_dispatch_root) / "stage6-review-action-dispatch-v1.json"
    initial_dispatch_path = Path(dispatch_json) if dispatch_json else Path(dispatch_root) / "stage6-review-action-dispatch-v1.json"
    manifest = {
        "manifest_version": STAGE6_REVIEW_LOOP_RUNNER_VERSION,
        "manifest_kind": STAGE6_REVIEW_LOOP_RUNNER_KIND,
        "adapter_id": STAGE6_REVIEW_LOOP_RUNNER_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewLoopRunnerV1",
        "manifest_id": f"STAGE6-REVIEW-LOOP-RUNNER-{_fingerprint({'summary': summary})[:16]}",
        "created_at": created,
        "source_dispatch_json": str(dispatch_path),
        "initial_dispatch_json": str(initial_dispatch_path),
        "source_batch_closeout_json": str(bootstrap.get("source_batch_closeout_json") or ""),
        "bootstrap": bootstrap,
        "baseline_evidence_state_json": str(baseline_evidence_state_json or ""),
        "baseline_evidence_state_root": str(baseline_evidence_state_root or ""),
        "roots": {
            "bootstrap": str(out_dir / "0-bootstrap"),
            "dispatch_runner": str(dispatch_run_root),
            "dispatch_readback": str(readback_root),
            "dispatch_closeout": str(closeout_root),
            "result_routing": str(routing_root),
            "evidence_state_rebuild": str(evidence_state_rebuild_root),
            "batch_closeout_rebuild": str(batch_closeout_rebuild_root),
            "release_field_query": str(release_field_query_root),
            "result_runner": str(result_run_root),
            "next_cycle": str(next_cycle_root),
        },
        "source_manifest_ids": {
            "bootstrap_stage6_fact_package": str(bootstrap.get("bootstrap_stage6_fact_package_manifest_id") or ""),
            "bootstrap_dispatch": str(bootstrap.get("bootstrap_dispatch_manifest_id") or ""),
            "dispatch_runner": _manifest_id(dispatch_runner),
            "dispatch_readback": _manifest_id(readback),
            "dispatch_closeout": _manifest_id(closeout),
            "result_routing": _manifest_id(routing),
            "result_runner": _manifest_id(result_runner),
            "next_cycle": _manifest_id(next_cycle),
        },
        "project_status_table": {"records": project_status_records},
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "stage7_to_stage9_live_execution_enabled": False,
            "dispatch_execution_enabled": bool(execute_dispatch or execute_next_cycle_dispatch),
            "result_execution_enabled": bool(execute_results),
            "bootstrap_from_batch_closeout_enabled": bool(auto_bootstrap_from_batch_closeout),
            "auto_discover_latest_batch_closeout_enabled": bool(auto_discover_latest_batch_closeout),
            "execution_is_internal_allowlisted": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage6_review_loop_runner_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED_OR_PARTIAL",
        "safe_to_execute": not input_blocked
        and (
            bootstrap_no_automated_tasks
            or (
                _safe(dispatch_runner)
                and _safe(readback)
                and _safe(closeout)
                and _safe(routing)
                and _safe(result_runner)
                and (not next_cycle or _safe(next_cycle))
            )
        )
        and not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result)
    return result


def _run_loop_children(
    *,
    dispatch_json: str | Path | None,
    dispatch_root: str | Path,
    baseline_evidence_state_json: str | Path | None,
    baseline_evidence_state_root: str | Path | None,
    dispatch_run_root: Path,
    readback_root: Path,
    closeout_root: Path,
    routing_root: Path,
    evidence_state_rebuild_root: Path,
    batch_closeout_rebuild_root: Path,
    release_field_query_root: Path,
    result_run_root: Path,
    execute_dispatch: bool,
    execute_results: bool,
    execute_next_cycle_dispatch: bool,
    dispatch_max_groups: int | None,
    result_max_commands: int | None,
    project_ids: list[str] | tuple[str, ...],
    cwd: str | Path | None,
    created_at: str,
    command_executor: CommandExecutor | None,
) -> dict[str, Any]:
    loop_root = dispatch_run_root.parent
    dispatch_runner = run_stage6_review_action_dispatch_runner(
        dispatch_json=dispatch_json,
        dispatch_root=dispatch_root,
        baseline_evidence_state_json=baseline_evidence_state_json,
        output_root=dispatch_run_root,
        execute_commands=execute_dispatch,
        max_groups=dispatch_max_groups,
        project_ids=project_ids,
        cwd=cwd,
        created_at=created_at,
        command_executor=command_executor,
    )
    result_roots = _result_roots_by_task_type(dispatch_runner)

    readback = build_stage6_review_action_dispatch_readback(
        dispatch_json=dispatch_json,
        dispatch_root=dispatch_root,
        release_evidence_adapter_plan_root=result_roots.get(TASK_TYPE_RELEASE_PLAN) or loop_root / "missing-release-plan",
        evidence_orchestration_continuation_root=result_roots.get(TASK_TYPE_ORIGINAL) or loop_root / "missing-continuation",
        design_survey_public_registry_readback_root=result_roots.get(TASK_TYPE_DESIGN_SURVEY) or loop_root / "missing-design",
        output_root=readback_root,
        created_at=created_at,
    )
    closeout = build_stage6_review_action_dispatch_closeout(
        dispatch_readback_root=readback_root,
        output_root=closeout_root,
        created_at=created_at,
    )
    routing = build_stage6_review_action_result_routing(
        dispatch_closeout_root=closeout_root,
        baseline_evidence_state_json=baseline_evidence_state_json,
        baseline_evidence_state_root=baseline_evidence_state_root,
        evidence_state_rebuild_output_root=evidence_state_rebuild_root,
        release_evidence_field_query_output_root=release_field_query_root,
        batch_closeout_rebuild_output_root=batch_closeout_rebuild_root,
        output_root=routing_root,
        created_at=created_at,
    )
    result_runner = run_stage6_review_action_result_runner(
        result_routing_root=routing_root,
        output_root=result_run_root,
        execute_commands=execute_results,
        max_commands=result_max_commands,
        project_ids=project_ids,
        cwd=cwd,
        created_at=created_at,
        command_executor=command_executor,
    )

    next_cycle: dict[str, Any] = {}
    next_cycle_skip_reason = ""
    batch_closeout_json = batch_closeout_rebuild_root / "evidence-batch-closeout-v1.json"
    if batch_closeout_json.exists():
        next_cycle = run_stage6_review_cycle_runner(
            batch_closeout_root=batch_closeout_rebuild_root,
            output_root=loop_root / "7-cycle",
            execute_dispatch=execute_next_cycle_dispatch,
            dispatch_max_groups=dispatch_max_groups,
            project_ids=project_ids,
            baseline_evidence_state_json=baseline_evidence_state_json,
            cwd=cwd,
            created_at=created_at,
            command_executor=command_executor,
        )
    else:
        next_cycle_skip_reason = "batch_closeout_rebuild_output_missing_or_results_not_executed"
    dispatch_runner["_loop_readback"] = readback
    dispatch_runner["_loop_closeout"] = closeout
    dispatch_runner["_loop_routing"] = routing
    dispatch_runner["_loop_result_runner"] = result_runner
    dispatch_runner["_loop_next_cycle"] = next_cycle
    dispatch_runner["_loop_next_cycle_skip_reason"] = next_cycle_skip_reason
    return dispatch_runner


def _prepare_dispatch_input(
    *,
    dispatch_json: str | Path | None,
    dispatch_root: str | Path,
    batch_closeout_json: str | Path | None,
    batch_closeout_root: str | Path,
    output_root: Path,
    auto_bootstrap_from_batch_closeout: bool,
    auto_discover_latest_batch_closeout: bool,
    project_ids: list[str] | tuple[str, ...],
    baseline_evidence_state_json: str | Path | None,
    created_at: str,
) -> dict[str, Any]:
    dispatch_path = _dispatch_path(dispatch_json, dispatch_root)
    explicit_dispatch = bool(dispatch_json)
    batch_path, batch_selection_state = _batch_closeout_path(
        batch_closeout_json=batch_closeout_json,
        batch_closeout_root=batch_closeout_root,
        auto_discover_latest_batch_closeout=auto_discover_latest_batch_closeout,
    )
    base = {
        "loop_input_state": "",
        "initial_dispatch_json": str(dispatch_path),
        "initial_dispatch_exists": dispatch_path.exists(),
        "effective_dispatch_json": "",
        "effective_dispatch_root": str(dispatch_path.parent),
        "source_batch_closeout_json": str(batch_path),
        "source_batch_closeout_exists": batch_path.exists(),
        "batch_closeout_selection_state": batch_selection_state,
        "auto_bootstrap_from_batch_closeout": bool(auto_bootstrap_from_batch_closeout),
        "auto_discover_latest_batch_closeout": bool(auto_discover_latest_batch_closeout),
        "bootstrap_output_root": str(output_root),
        "bootstrap_stage6_fact_package_root": "",
        "bootstrap_stage6_fact_package_json": "",
        "bootstrap_stage6_fact_package_manifest_id": "",
        "bootstrap_dispatch_root": "",
        "bootstrap_dispatch_json": "",
        "bootstrap_dispatch_manifest_id": "",
        "bootstrap_dispatch_task_count": 0,
        "bootstrap_manual_only_action_plan_count": 0,
        "bootstrap_project_status_records": [],
        "blocking_reasons": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    if dispatch_path.exists():
        return {
            **base,
            "loop_input_state": "DISPATCH_INPUT_READY_NO_BOOTSTRAP",
            "effective_dispatch_json": str(dispatch_path),
        }
    if explicit_dispatch:
        return {
            **base,
            "loop_input_state": "INPUT_BLOCKED_EXPLICIT_DISPATCH_MISSING",
            "blocking_reasons": ["explicit_stage6_dispatch_json_missing"],
        }
    if not auto_bootstrap_from_batch_closeout:
        return {
            **base,
            "loop_input_state": "INPUT_BLOCKED_DISPATCH_MISSING_BOOTSTRAP_DISABLED",
            "blocking_reasons": ["stage6_dispatch_missing_and_batch_closeout_bootstrap_disabled"],
        }
    if not batch_path.exists():
        return {
            **base,
            "loop_input_state": "INPUT_BLOCKED_NO_DISPATCH_OR_BATCH_CLOSEOUT",
            "blocking_reasons": ["stage6_loop_input_missing_dispatch_or_batch_closeout"],
        }

    stage6_root = output_root / "1-stage6-fact-package"
    dispatch_out_root = output_root / "2-stage6-dispatch"
    stage6_result = build_evidence_stage6_fact_package(
        batch_closeout_json=batch_path,
        output_root=stage6_root,
        created_at=created_at,
    )
    dispatch_result: dict[str, Any] = {}
    if _safe(stage6_result):
        dispatch_result = build_stage6_review_action_dispatch(
            stage6_fact_package_root=stage6_root,
            output_root=dispatch_out_root,
            created_at=created_at,
        )
    dispatch_out_path = dispatch_out_root / "stage6-review-action-dispatch-v1.json"
    dispatch_summary = _result_summary(dispatch_result)
    dispatch_manifest = _source_manifest(dispatch_result)
    dispatch_task_count = int(dispatch_summary.get("dispatch_task_count") or 0)
    manual_only_records = [
        record
        for record in _list(
            (dispatch_manifest.get("manual_only_action_plan_table") or {}).get("records")
            if isinstance(dispatch_manifest.get("manual_only_action_plan_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    blocking_reasons = [
        *_list(stage6_result.get("blocking_reasons")),
        *_list(dispatch_result.get("blocking_reasons")),
    ]
    if not _safe(stage6_result):
        blocking_reasons.append("bootstrap_stage6_fact_package_not_safe")
    if stage6_result and not dispatch_result:
        blocking_reasons.append("bootstrap_dispatch_not_built")
    elif dispatch_result and not _safe(dispatch_result):
        blocking_reasons.append("bootstrap_stage6_dispatch_not_safe")
    if not dispatch_out_path.exists():
        blocking_reasons.append("bootstrap_stage6_dispatch_json_missing")
    if blocking_reasons:
        return {
            **base,
            "loop_input_state": "INPUT_BLOCKED_BOOTSTRAP_FAILED",
            "bootstrap_stage6_fact_package_root": str(stage6_root),
            "bootstrap_stage6_fact_package_json": str(stage6_root / "stage6-fact-package-v1.json"),
            "bootstrap_stage6_fact_package_manifest_id": _manifest_id(stage6_result),
            "bootstrap_dispatch_root": str(dispatch_out_root),
            "bootstrap_dispatch_json": str(dispatch_out_path),
            "bootstrap_dispatch_manifest_id": _manifest_id(dispatch_result),
            "bootstrap_dispatch_task_count": dispatch_task_count,
            "bootstrap_manual_only_action_plan_count": len(manual_only_records),
            "bootstrap_project_status_records": _bootstrap_manual_project_status_records(manual_only_records),
            "blocking_reasons": _dedupe(blocking_reasons),
        }
    if dispatch_task_count == 0:
        return {
            **base,
            "loop_input_state": "BOOTSTRAPPED_DISPATCH_NO_AUTOMATED_TASKS",
            "effective_dispatch_json": str(dispatch_out_path),
            "effective_dispatch_root": str(dispatch_out_root),
            "bootstrap_stage6_fact_package_root": str(stage6_root),
            "bootstrap_stage6_fact_package_json": str(stage6_root / "stage6-fact-package-v1.json"),
            "bootstrap_stage6_fact_package_manifest_id": _manifest_id(stage6_result),
            "bootstrap_dispatch_root": str(dispatch_out_root),
            "bootstrap_dispatch_json": str(dispatch_out_path),
            "bootstrap_dispatch_manifest_id": _manifest_id(dispatch_result),
            "bootstrap_dispatch_task_count": dispatch_task_count,
            "bootstrap_manual_only_action_plan_count": len(manual_only_records),
            "bootstrap_project_status_records": _bootstrap_manual_project_status_records(manual_only_records),
            "project_ids": list(project_ids),
            "baseline_evidence_state_json": str(baseline_evidence_state_json or ""),
            "blocking_reasons": [],
        }
    return {
        **base,
        "loop_input_state": "BOOTSTRAPPED_DISPATCH_FROM_BATCH_CLOSEOUT",
        "effective_dispatch_json": str(dispatch_out_path),
        "effective_dispatch_root": str(dispatch_out_root),
        "bootstrap_stage6_fact_package_root": str(stage6_root),
        "bootstrap_stage6_fact_package_json": str(stage6_root / "stage6-fact-package-v1.json"),
        "bootstrap_stage6_fact_package_manifest_id": _manifest_id(stage6_result),
        "bootstrap_dispatch_root": str(dispatch_out_root),
        "bootstrap_dispatch_json": str(dispatch_out_path),
        "bootstrap_dispatch_manifest_id": _manifest_id(dispatch_result),
        "bootstrap_dispatch_task_count": dispatch_task_count,
        "bootstrap_manual_only_action_plan_count": len(manual_only_records),
        "bootstrap_project_status_records": _bootstrap_manual_project_status_records(manual_only_records),
        "project_ids": list(project_ids),
        "baseline_evidence_state_json": str(baseline_evidence_state_json or ""),
        "blocking_reasons": [],
    }


def _dispatch_path(dispatch_json: str | Path | None, dispatch_root: str | Path) -> Path:
    return Path(dispatch_json) if dispatch_json else Path(dispatch_root) / "stage6-review-action-dispatch-v1.json"


def _batch_closeout_path(
    *,
    batch_closeout_json: str | Path | None,
    batch_closeout_root: str | Path,
    auto_discover_latest_batch_closeout: bool,
) -> tuple[Path, str]:
    if batch_closeout_json:
        return Path(batch_closeout_json), "EXPLICIT_BATCH_CLOSEOUT_JSON"
    root_path = Path(batch_closeout_root) / "evidence-batch-closeout-v1.json"
    if root_path.exists():
        return root_path, "BATCH_CLOSEOUT_ROOT_READY"
    if auto_discover_latest_batch_closeout and Path(batch_closeout_root) == DEFAULT_BATCH_CLOSEOUT_ROOT:
        latest = _latest_batch_closeout_path(DEFAULT_BATCH_CLOSEOUT_DISCOVERY_ROOT)
        if latest:
            return latest, "AUTO_DISCOVERED_LATEST_BATCH_CLOSEOUT"
    return root_path, "BATCH_CLOSEOUT_MISSING"


def _latest_batch_closeout_path(search_root: Path) -> Path | None:
    if not search_root.exists():
        return None
    candidates: list[Path] = []
    try:
        candidates = [path for path in search_root.rglob("evidence-batch-closeout-v1.json") if path.is_file()]
    except OSError:
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, str(path)))


def _bootstrap_manual_project_status_records(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        dispatch_block_reason = str(record.get("dispatch_block_reason") or "").strip()
        out.append(
            {
                "project_id": project_id,
                "project_name": str(record.get("project_name") or ""),
                "dispatch_task_type": "",
                "dispatch_readback_state": "",
                "dispatch_closeout_state": "",
                "result_routing_state": "",
                "next_task_type": "",
                "stage6_fact_package_state": "",
                "stage6_ready": False,
                "stage7_commercial_input_allowed": False,
                "result_runner_execution_state": "",
                "result_runner_skip_reason": "",
                "release_field_query_state": "",
                "release_field_query_result_json": "",
                "release_field_query_manifest_id": "",
                "release_field_query_task_count": 0,
                "release_field_query_adapter_result_state_counts": {},
                "release_field_query_downstream_abcd_grade_counts": {},
                "release_field_query_authorization_state_counts": {},
                "release_field_query_operator_next_actions": [],
                "next_cycle_dispatch_task_type": "",
                "next_cycle_dispatch_readiness_state": "",
                "next_cycle_manual_only_action_family": str(record.get("action_family") or ""),
                "next_cycle_dispatch_block_reason": dispatch_block_reason,
                "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                "next_recommended_action": "manual_review_or_new_source_override_required_before_retry"
                if dispatch_block_reason
                else "no_automated_stage6_dispatch_task_keep_internal_review",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return out


def _project_status_records(
    *,
    readback: Mapping[str, Any],
    closeout: Mapping[str, Any],
    routing: Mapping[str, Any],
    result_runner: Mapping[str, Any],
    next_cycle: Mapping[str, Any],
    release_field_query_results: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    readbacks = _records_by_project(readback, "dispatch_readback_table")
    closeouts = _records_by_project(closeout, "dispatch_closeout_table")
    routings = _records_by_project(routing, "result_routing_table")
    runners = _records_by_project(result_runner, "result_runner_table")
    next_dispatch = _next_cycle_dispatch_records_by_project(next_cycle)
    next_manual = _next_cycle_manual_only_records_by_project(next_cycle)
    project_ids = sorted(
        {
            *readbacks.keys(),
            *closeouts.keys(),
            *routings.keys(),
            *runners.keys(),
            *next_dispatch.keys(),
            *next_manual.keys(),
            *release_field_query_results.keys(),
        }
    )
    records: list[dict[str, Any]] = []
    for project_id in project_ids:
        readback_record = readbacks.get(project_id, {})
        closeout_record = closeouts.get(project_id, {})
        routing_record = routings.get(project_id, {})
        runner_record = runners.get(project_id, {})
        next_dispatch_record = next_dispatch.get(project_id, {})
        next_manual_record = next_manual.get(project_id, {})
        release_field_query_result = dict(release_field_query_results.get(project_id) or {})
        records.append(
            {
                "project_id": project_id,
                "project_name": _first_text(
                    readback_record.get("project_name"),
                    closeout_record.get("project_name"),
                    routing_record.get("project_name"),
                    runner_record.get("project_name"),
                    next_dispatch_record.get("project_name"),
                ),
                "dispatch_task_type": _first_text(
                    readback_record.get("dispatch_task_type"),
                    closeout_record.get("dispatch_task_type"),
                    routing_record.get("dispatch_task_type"),
                    runner_record.get("dispatch_task_type"),
                    next_dispatch_record.get("dispatch_task_type"),
                ),
                "dispatch_readback_state": str(readback_record.get("dispatch_readback_state") or ""),
                "dispatch_closeout_state": str(closeout_record.get("dispatch_closeout_state") or ""),
                "result_routing_state": str(routing_record.get("result_routing_state") or ""),
                "next_task_type": str(routing_record.get("next_task_type") or ""),
                "stage6_fact_package_state": str(closeout_record.get("stage6_fact_package_state") or ""),
                "stage6_ready": bool(closeout_record.get("stage6_ready", False)),
                "stage7_commercial_input_allowed": bool(
                    closeout_record.get("stage7_commercial_input_allowed", False)
                ),
                "result_runner_execution_state": str(runner_record.get("execution_state") or ""),
                "result_runner_skip_reason": str(runner_record.get("skip_reason") or ""),
                "release_field_query_state": str(release_field_query_result.get("release_field_query_state") or ""),
                "release_field_query_result_json": str(release_field_query_result.get("result_json_path") or ""),
                "release_field_query_manifest_id": str(release_field_query_result.get("result_manifest_id") or ""),
                "release_field_query_task_count": int(release_field_query_result.get("field_query_task_count") or 0),
                "release_field_query_adapter_result_state_counts": dict(
                    release_field_query_result.get("adapter_result_state_counts") or {}
                ),
                "release_field_query_downstream_abcd_grade_counts": dict(
                    release_field_query_result.get("downstream_release_evidence_abcd_grade_counts") or {}
                ),
                "release_field_query_authorization_state_counts": dict(
                    release_field_query_result.get("authorization_readiness_state_counts") or {}
                ),
                "release_field_query_operator_next_actions": _list(
                    release_field_query_result.get("operator_next_actions")
                ),
                "next_cycle_dispatch_task_type": str(next_dispatch_record.get("dispatch_task_type") or ""),
                "next_cycle_dispatch_readiness_state": str(next_dispatch_record.get("dispatch_readiness_state") or ""),
                "next_cycle_manual_only_action_family": str(next_manual_record.get("action_family") or ""),
                "next_cycle_dispatch_block_reason": str(next_manual_record.get("dispatch_block_reason") or ""),
                "loop_terminal_state": _loop_terminal_state(
                    readback_record=readback_record,
                    closeout_record=closeout_record,
                    routing_record=routing_record,
                    runner_record=runner_record,
                    next_dispatch_record=next_dispatch_record,
                    next_manual_record=next_manual_record,
                    release_field_query_result=release_field_query_result,
                ),
                "next_recommended_action": _loop_next_action(
                    readback_record=readback_record,
                    closeout_record=closeout_record,
                    runner_record=runner_record,
                    routing_record=routing_record,
                    next_dispatch_record=next_dispatch_record,
                    next_manual_record=next_manual_record,
                    release_field_query_result=release_field_query_result,
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return records


def _release_field_query_results_by_project(result_runner: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = _table_records(result_runner, "result_runner_table")
    by_project: dict[str, dict[str, Any]] = {}
    for runner_record in records:
        if str(runner_record.get("next_task_type") or "") != "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE":
            continue
        result_path = str(runner_record.get("expected_output_artifact_path") or "").strip()
        if not result_path or not Path(result_path).exists():
            project_id = str(runner_record.get("project_id") or "").strip()
            if project_id and str(runner_record.get("execution_state") or "") == "EXECUTED_SUCCEEDED":
                by_project[project_id] = _release_field_query_missing_result(runner_record, result_path)
            continue
        payload = _load_json_if_exists(Path(result_path))
        manifest = _source_manifest(payload)
        field_tasks = [
            task
            for task in _list(manifest.get("field_task_records"))
            if isinstance(task, Mapping)
        ]
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for task in field_tasks:
            project_id = str(task.get("project_id") or "").strip()
            if project_id:
                grouped.setdefault(project_id, []).append(task)
        if not grouped:
            project_id = str(runner_record.get("project_id") or "").strip()
            if project_id:
                by_project[project_id] = _release_field_query_project_result(
                    runner_record=runner_record,
                    result_path=result_path,
                    result_manifest=manifest,
                    tasks=[],
                )
            continue
        for project_id, tasks in grouped.items():
            by_project[project_id] = _release_field_query_project_result(
                runner_record=runner_record,
                result_path=result_path,
                result_manifest=manifest,
                tasks=tasks,
            )
    return by_project


def _release_field_query_missing_result(runner_record: Mapping[str, Any], result_path: str) -> dict[str, Any]:
    return {
        "release_field_query_state": "RELEASE_FIELD_QUERY_RESULT_MISSING",
        "result_json_path": result_path,
        "result_manifest_id": "",
        "field_query_task_count": 0,
        "adapter_result_state_counts": {},
        "downstream_release_evidence_abcd_grade_counts": {},
        "authorization_readiness_state_counts": {},
        "operator_next_actions": [],
        "source_result_runner_execution_state": str(runner_record.get("execution_state") or ""),
    }


def _release_field_query_project_result(
    *,
    runner_record: Mapping[str, Any],
    result_path: str,
    result_manifest: Mapping[str, Any],
    tasks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    adapter_counts = _counts(task.get("adapter_result_state") for task in tasks)
    downstream_counts = _counts(task.get("downstream_release_evidence_abcd_grade") for task in tasks)
    authorization_counts = _field_query_authorization_counts(tasks)
    operator_next_actions = _field_query_operator_next_actions(tasks)
    return {
        "release_field_query_state": _release_field_query_state(adapter_counts, downstream_counts, task_count=len(tasks)),
        "result_json_path": result_path,
        "result_manifest_id": str(result_manifest.get("manifest_id") or ""),
        "field_query_task_count": len(tasks),
        "adapter_result_state_counts": adapter_counts,
        "downstream_release_evidence_abcd_grade_counts": downstream_counts,
        "authorization_readiness_state_counts": authorization_counts,
        "operator_next_actions": operator_next_actions,
        "source_result_runner_execution_state": str(runner_record.get("execution_state") or ""),
    }


def _field_query_authorization_counts(tasks: list[Mapping[str, Any]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    fallback_states: list[Any] = []
    for task in tasks:
        field_summary = task.get("field_summary") if isinstance(task.get("field_summary"), Mapping) else {}
        counts = field_summary.get("authorization_readiness_state_counts") if isinstance(field_summary, Mapping) else {}
        if isinstance(counts, Mapping):
            for key, value in counts.items():
                text = str(key or "").strip()
                if text:
                    merged[text] = merged.get(text, 0) + _int(value)
        field_match_summary = task.get("field_match_summary") if isinstance(task.get("field_match_summary"), Mapping) else {}
        if isinstance(field_match_summary, Mapping):
            fallback_states.append(field_match_summary.get("authorization_readiness_state"))
    return merged or _counts(fallback_states)


def _field_query_operator_next_actions(tasks: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        action
        for task in tasks
        for action in _list(
            (task.get("field_summary") if isinstance(task.get("field_summary"), Mapping) else {}).get(
                "operator_next_actions"
            )
        )
    )


def _release_field_query_state(
    adapter_counts: Mapping[str, int],
    downstream_counts: Mapping[str, int],
    *,
    task_count: int,
) -> str:
    if task_count <= 0:
        return "RELEASE_FIELD_QUERY_NO_PROJECT_TASKS"
    if int(downstream_counts.get("B_ENHANCEMENT_OFFICIAL_READBACK") or 0) or int(
        downstream_counts.get("C_REVERSE_EXPLANATION_OFFICIAL_READBACK") or 0
    ):
        return "RELEASE_FIELD_QUERY_REVIEW_READY"
    if int(downstream_counts.get("D_INSUFFICIENT_OR_BLOCKED_READBACK") or 0) or int(
        adapter_counts.get("BLOCKED") or 0
    ) or int(adapter_counts.get("NOT_FOUND") or 0):
        return "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW"
    return "RELEASE_FIELD_QUERY_PENDING_OR_NEEDS_BROWSER"


def _records_by_project(result: Mapping[str, Any], table_name: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for record in _table_records(result, table_name):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out[project_id] = dict(record)
    return out


def _table_records(result: Mapping[str, Any], table_name: str) -> list[Mapping[str, Any]]:
    manifest = result.get("manifest") if isinstance(result, Mapping) else {}
    table = manifest.get(table_name) if isinstance(manifest, Mapping) else {}
    return [record for record in _list(table.get("records") if isinstance(table, Mapping) else []) if isinstance(record, Mapping)]


def _next_cycle_dispatch_records_by_project(next_cycle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return _next_cycle_records_by_project(next_cycle, "dispatch_task_table")


def _next_cycle_manual_only_records_by_project(next_cycle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return _next_cycle_records_by_project(next_cycle, "manual_only_action_plan_table")


def _next_cycle_records_by_project(next_cycle: Mapping[str, Any], table_name: str) -> dict[str, dict[str, Any]]:
    manifest = next_cycle.get("manifest") if isinstance(next_cycle, Mapping) else {}
    dispatch_json = str(manifest.get("stage6_dispatch_json") or "").strip() if isinstance(manifest, Mapping) else ""
    if not dispatch_json:
        return {}
    try:
        payload = json.loads(Path(dispatch_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    payload_manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    table = payload_manifest.get(table_name) if isinstance(payload_manifest, Mapping) else {}
    records = _list(table.get("records") if isinstance(table, Mapping) else [])
    out: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out[project_id] = dict(record)
    return out


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _loop_terminal_state(
    *,
    readback_record: Mapping[str, Any],
    closeout_record: Mapping[str, Any],
    routing_record: Mapping[str, Any],
    runner_record: Mapping[str, Any],
    next_dispatch_record: Mapping[str, Any],
    next_manual_record: Mapping[str, Any],
    release_field_query_result: Mapping[str, Any],
) -> str:
    if str(next_dispatch_record.get("dispatch_readiness_state") or "").strip():
        return "NEXT_CYCLE_DISPATCH_READY"
    if str(next_manual_record.get("dispatch_block_reason") or "").strip():
        return "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH"
    release_state = str(release_field_query_result.get("release_field_query_state") or "").strip()
    if release_state:
        return release_state

    execution_state = str(runner_record.get("execution_state") or "").strip()
    if execution_state == "EXECUTED_SUCCEEDED":
        return "RESULT_EXECUTED_NO_NEXT_DISPATCH"
    if execution_state == "DRY_RUN_READY":
        return "RESULT_COMMAND_READY_DRY_RUN"
    if execution_state == "SKIPPED_DUPLICATE_COMMAND":
        return "RESULT_DUPLICATE_COMMAND_SKIPPED"
    if execution_state == "EXECUTED_FAILED":
        return "RESULT_EXECUTION_FAILED"
    if execution_state == "BLOCKED_BY_ALLOWLIST":
        return "RESULT_COMMAND_BLOCKED_BY_ALLOWLIST"
    if execution_state.startswith("SKIPPED_") and execution_state != "SKIPPED_NOT_READY":
        return execution_state

    routing_state = str(routing_record.get("result_routing_state") or "").strip()
    if routing_state in {
        "READY_FOR_EVIDENCE_STATE_REBUILD",
        "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY",
        "READY_FOR_BATCH_CLOSEOUT_REBUILD",
    }:
        return "RESULT_COMMAND_READY_NOT_EXECUTED"
    if routing_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return "WAITING_FOR_DISPATCH_EXECUTION"
    if routing_state in {"PARKED_OPERATOR_SKIPPED_THIS_ROUND", "BLOCKED_OR_MANUAL_REVIEW_REQUIRED", "MANUAL_ROUTING_REVIEW_REQUIRED"}:
        return routing_state

    closeout_state = str(closeout_record.get("dispatch_closeout_state") or "").strip()
    if closeout_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return "WAITING_FOR_DISPATCH_EXECUTION"
    if closeout_state:
        return closeout_state

    readback_state = str(readback_record.get("dispatch_readback_state") or "").strip()
    if readback_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return "WAITING_FOR_DISPATCH_EXECUTION"
    if readback_state:
        return readback_state
    return "NO_PROJECT_STATUS_RECORD"


def _loop_next_action(
    *,
    readback_record: Mapping[str, Any],
    closeout_record: Mapping[str, Any],
    runner_record: Mapping[str, Any],
    routing_record: Mapping[str, Any],
    next_dispatch_record: Mapping[str, Any],
    next_manual_record: Mapping[str, Any],
    release_field_query_result: Mapping[str, Any],
) -> str:
    if str(next_dispatch_record.get("dispatch_readiness_state") or "").strip():
        return "run_next_cycle_dispatch_or_keep_internal_review_dry_run"
    if str(next_manual_record.get("dispatch_block_reason") or "").strip():
        return "manual_review_or_new_source_override_required_before_retry"
    release_state = str(release_field_query_result.get("release_field_query_state") or "").strip()
    if release_state == "RELEASE_FIELD_QUERY_REVIEW_READY":
        return "manual_review_release_evidence_b_or_c_readback_before_stage7_preview"
    if release_state == "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW":
        return "record_release_evidence_gap_or_retry_jurisdiction_source_without_clearance_claim"
    if release_state == "RELEASE_FIELD_QUERY_PENDING_OR_NEEDS_BROWSER":
        return "authorize_browser_or_live_release_field_query_or_keep_plan_only"
    if release_state:
        return "inspect_release_field_query_result_before_next_stage6_cycle"

    execution_state = str(runner_record.get("execution_state") or "").strip()
    if execution_state == "EXECUTED_SUCCEEDED":
        return "review_result_artifact_and_close_project_or_generate_next_cycle_if_needed"
    if execution_state == "DRY_RUN_READY":
        return "execute_result_runner_or_keep_dry_run"
    if execution_state == "SKIPPED_DUPLICATE_COMMAND":
        return "use_first_identical_result_runner_output_for_this_project_group"
    if execution_state == "EXECUTED_FAILED":
        return "inspect_result_runner_failure_then_retry_or_park"
    if execution_state == "BLOCKED_BY_ALLOWLIST":
        return "fix_structured_command_allowlist_before_execution"
    if execution_state.startswith("SKIPPED_") and execution_state != "SKIPPED_NOT_READY":
        return str(runner_record.get("skip_reason") or "review_result_runner_skip_reason")

    routing_action = str(routing_record.get("next_recommended_action") or "").strip()
    if routing_action:
        return routing_action

    closeout_action = str(closeout_record.get("next_recommended_action") or "").strip()
    if closeout_action:
        return closeout_action

    readback_action = str(readback_record.get("next_recommended_action") or "").strip()
    if readback_action:
        return readback_action
    return "review_project_status_inputs"


def _summary(
    *,
    dispatch_runner: Mapping[str, Any],
    readback: Mapping[str, Any],
    closeout: Mapping[str, Any],
    routing: Mapping[str, Any],
    result_runner: Mapping[str, Any],
    next_cycle: Mapping[str, Any],
    project_status_records: list[Mapping[str, Any]],
    next_cycle_skip_reason: str,
    bootstrap: Mapping[str, Any],
    blocking_reasons: list[str],
    execute_dispatch: bool,
    execute_results: bool,
    execute_next_cycle_dispatch: bool,
) -> dict[str, Any]:
    dispatch_runner_summary = _result_summary(dispatch_runner)
    readback_summary = _result_summary(readback)
    closeout_summary = _result_summary(closeout)
    routing_summary = _result_summary(routing)
    result_runner_summary = _result_summary(result_runner)
    next_cycle_summary = _result_summary(next_cycle)
    return {
        "stage6_review_loop_runner_state": (
            "STAGE6_REVIEW_LOOP_READY" if not blocking_reasons else "STAGE6_REVIEW_LOOP_PARTIAL_OR_BLOCKED"
        ),
        "loop_input_state": str(bootstrap.get("loop_input_state") or ""),
        "bootstrap_batch_closeout_selection_state": str(bootstrap.get("batch_closeout_selection_state") or ""),
        "bootstrap_from_batch_closeout_count": 1
        if str(bootstrap.get("loop_input_state") or "").startswith("BOOTSTRAPPED_")
        else 0,
        "bootstrap_dispatch_task_count": int(bootstrap.get("bootstrap_dispatch_task_count") or 0),
        "bootstrap_manual_only_action_plan_count": int(bootstrap.get("bootstrap_manual_only_action_plan_count") or 0),
        "source_batch_closeout_json": str(bootstrap.get("source_batch_closeout_json") or ""),
        "execution_mode": _execution_mode(execute_dispatch, execute_results, execute_next_cycle_dispatch),
        "dispatch_runner_safe": _safe(dispatch_runner),
        "readback_safe": _safe(readback),
        "closeout_safe": _safe(closeout),
        "routing_safe": _safe(routing),
        "result_runner_safe": _safe(result_runner),
        "next_cycle_safe": _safe(next_cycle) if next_cycle else False,
        "dispatch_executed_success_group_count": int(dispatch_runner_summary.get("executed_success_group_count") or 0),
        "dispatch_dry_run_ready_group_count": int(dispatch_runner_summary.get("dry_run_ready_group_count") or 0),
        "readback_execution_output_ready_count": int(readback_summary.get("execution_output_ready_count") or 0),
        "readback_waiting_for_controlled_execution_count": int(
            readback_summary.get("waiting_for_controlled_execution_count") or 0
        ),
        "closeout_ready_to_feed_back_count": int(closeout_summary.get("ready_to_feed_back_count") or 0),
        "routing_recommended_command_ready_count": int(routing_summary.get("recommended_command_ready_count") or 0),
        "routing_batch_closeout_rebuild_ready_count": int(routing_summary.get("batch_closeout_rebuild_ready_count") or 0),
        "routing_evidence_state_rebuild_ready_count": int(routing_summary.get("evidence_state_rebuild_ready_count") or 0),
        "result_runner_executed_success_count": int(result_runner_summary.get("executed_success_count") or 0),
        "result_runner_dry_run_ready_count": int(result_runner_summary.get("dry_run_ready_count") or 0),
        "result_runner_skipped_duplicate_command_count": int(
            result_runner_summary.get("skipped_duplicate_command_count") or 0
        ),
        "next_cycle_skip_reason": next_cycle_skip_reason,
        "next_cycle_stage6_project_fact_count": int(next_cycle_summary.get("stage6_project_fact_count") or 0),
        "next_cycle_dispatch_task_count": int(next_cycle_summary.get("dispatch_task_count") or 0),
        "project_status_record_count": len(project_status_records),
        "release_field_query_project_count": sum(
            1 for record in project_status_records if str(record.get("release_field_query_state") or "").strip()
        ),
        "release_field_query_state_counts": _counts(
            record.get("release_field_query_state") for record in project_status_records
        ),
        "release_field_query_authorization_state_counts": _merge_count_maps(
            record.get("release_field_query_authorization_state_counts") for record in project_status_records
        ),
        "release_field_query_operator_next_action_counts": _counts(
            action
            for record in project_status_records
            for action in _list(record.get("release_field_query_operator_next_actions"))
        ),
        "loop_terminal_state_counts": _counts(record.get("loop_terminal_state") for record in project_status_records),
        "project_next_action_counts": _counts(record.get("next_recommended_action") for record in project_status_records),
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "blocking_reasons": list(blocking_reasons),
        "forbidden_term_scan_state": "PENDING",
    }


def _execution_mode(execute_dispatch: bool, execute_results: bool, execute_next_cycle_dispatch: bool) -> str:
    if execute_dispatch or execute_results or execute_next_cycle_dispatch:
        return "CONTROLLED_INTERNAL_ONE_PASS_EXECUTION"
    return "DRY_RUN_ONE_PASS_NOT_EXECUTED"


def _result_roots_by_task_type(dispatch_runner: Mapping[str, Any]) -> dict[str, str]:
    manifest = dispatch_runner.get("manifest") if isinstance(dispatch_runner, Mapping) else {}
    roots = manifest.get("result_roots_by_task_type") if isinstance(manifest, Mapping) else {}
    return {str(key): str(value) for key, value in dict(roots or {}).items()}


def _all_blocking_reasons(*results: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for result in results:
        reasons.extend(_list(result.get("blocking_reasons")) if isinstance(result, Mapping) else [])
    return [str(reason) for reason in reasons if str(reason or "").strip()]


def _result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result, Mapping) else {}
    return dict(summary) if isinstance(summary, Mapping) else {}


def _manifest_id(result: Mapping[str, Any]) -> str:
    manifest = result.get("manifest") if isinstance(result, Mapping) else {}
    return str(manifest.get("manifest_id") or "") if isinstance(manifest, Mapping) else ""


def _safe(result: Mapping[str, Any]) -> bool:
    if not result:
        return False
    return bool(result.get("safe_to_execute"))


def _finalize_and_write(out_dir: Path, result: dict[str, Any]) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *list(result.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    result["manifest"]["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result["manifest"].items() if key != "manifest_sha256"}
    )
    _write_json(
        out_dir / "stage6-review-loop-project-status-table.json",
        {
            "summary": result["summary"],
            "records": result["manifest"]["project_status_table"]["records"],
        },
    )
    _write_json(out_dir / "stage6-review-loop-runner-v1.json", result)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _merge_count_maps(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key, count in value.items():
            text = str(key or "").strip()
            if text:
                counts[text] = counts.get(text, 0) + _int(count)
    return dict(sorted(counts.items()))


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one controlled Stage6 review loop pass.")
    parser.add_argument("--dispatch-json", default="")
    parser.add_argument("--dispatch-root", default=str(DEFAULT_DISPATCH_ROOT))
    parser.add_argument("--batch-closeout-json", default="")
    parser.add_argument("--batch-closeout-root", default=str(DEFAULT_BATCH_CLOSEOUT_ROOT))
    parser.add_argument("--baseline-evidence-state-json", default="")
    parser.add_argument("--baseline-evidence-state-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--disable-bootstrap-from-batch-closeout", action="store_true")
    parser.add_argument("--auto-discover-latest-batch-closeout", action="store_true")
    parser.add_argument("--execute-dispatch", action="store_true")
    parser.add_argument("--execute-results", action="store_true")
    parser.add_argument("--execute-next-cycle-dispatch", action="store_true")
    parser.add_argument("--dispatch-max-groups", type=int, default=None)
    parser.add_argument("--result-max-commands", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_stage6_review_loop_runner(
        dispatch_json=args.dispatch_json or None,
        dispatch_root=args.dispatch_root,
        batch_closeout_json=args.batch_closeout_json or None,
        batch_closeout_root=args.batch_closeout_root,
        baseline_evidence_state_json=args.baseline_evidence_state_json or None,
        baseline_evidence_state_root=args.baseline_evidence_state_root or None,
        output_root=args.output_root,
        auto_bootstrap_from_batch_closeout=not bool(args.disable_bootstrap_from_batch_closeout),
        auto_discover_latest_batch_closeout=bool(args.auto_discover_latest_batch_closeout),
        execute_dispatch=bool(args.execute_dispatch),
        execute_results=bool(args.execute_results),
        execute_next_cycle_dispatch=bool(args.execute_next_cycle_dispatch),
        dispatch_max_groups=args.dispatch_max_groups,
        result_max_commands=args.result_max_commands,
        project_ids=_parse_csv(args.project_ids),
        cwd=args.cwd or None,
        created_at=args.created_at or None,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "STAGE6_REVIEW_LOOP_RUNNER_KIND",
    "run_stage6_review_loop_runner",
]
