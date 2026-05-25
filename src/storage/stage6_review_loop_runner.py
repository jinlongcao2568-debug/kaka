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
from storage.stage6_review_cycle_continuation_refs import build_stage6_review_cycle_continuation_input_refs
from storage.stage6_status_projection import (
    limited_sellable_review_projection,
    runtime_blocker_projection_fields,
)
from storage.runtime_closeout_precedence import (
    build_runtime_blocker_next_subqueue_table,
    is_original_readback_projection_only_terminal_state,
    runtime_blocker_subqueue_routes as _runtime_blocker_subqueue_routes,
)


STAGE6_REVIEW_LOOP_RUNNER_KIND = "stage6_review_loop_runner_v1_manifest"
STAGE6_REVIEW_LOOP_RUNNER_VERSION = 1
STAGE6_REVIEW_LOOP_RUNNER_ADAPTER_ID = "stage6-review-loop-runner-v1"

DEFAULT_DISPATCH_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-v1")
DEFAULT_BATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")
DEFAULT_BATCH_CLOSEOUT_DISCOVERY_ROOT = Path("tmp/evaluation-real-samples")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-loop-runner-v1")
DEFAULT_RELEASE_FIELD_QUERY_FILENAME = "guangdong-local-field-query-probe-v1.json"
DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_FILENAME = "release-evidence-adapter-plan-v1.json"
DEFAULT_ORIGINAL_BACKTRACE_CONTINUATION_FILENAME = "p13b-original-backtrace-continuation-controller-v2.json"
DEFAULT_STAGE16_P13B_CONTINUATION_FILENAME = "stage16-p13b-continuation-controller-v1.json"
DEFAULT_STAGE5_CALIBRATION_SAMPLE_FILENAME = "stage5-calibration-sample-table.json"

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
    release_field_query_json: str | Path | None = None,
    release_field_query_root: str | Path | None = None,
    supplemental_release_field_query_json: str | Path | None = None,
    supplemental_release_field_query_root: str | Path | None = None,
    release_evidence_adapter_plan_json: str | Path | None = None,
    release_evidence_adapter_plan_root: str | Path | None = None,
    original_backtrace_continuation_json: str | Path | None = None,
    original_backtrace_continuation_root: str | Path | None = None,
    stage16_p13b_continuation_json: str | Path | None = None,
    stage16_p13b_continuation_root: str | Path | None = None,
    stage5_calibration_sample_json: str | Path | None = None,
    stage5_calibration_sample_root: str | Path | None = None,
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
    release_field_query_result_root = out_dir / "5-field"
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
            release_field_query_root=release_field_query_result_root,
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

    standalone_release_field_query_path = _release_field_query_path(
        release_field_query_json=release_field_query_json,
        release_field_query_root=release_field_query_root,
    )
    standalone_supplemental_release_field_query_paths = _release_field_query_paths(
        release_field_query_json=supplemental_release_field_query_json,
        release_field_query_root=supplemental_release_field_query_root,
    )
    standalone_release_evidence_adapter_plan_path = _release_evidence_adapter_plan_path(
        release_evidence_adapter_plan_json=release_evidence_adapter_plan_json,
        release_evidence_adapter_plan_root=release_evidence_adapter_plan_root,
    )
    standalone_original_backtrace_continuation_path = _original_backtrace_continuation_path(
        original_backtrace_continuation_json=original_backtrace_continuation_json,
        original_backtrace_continuation_root=original_backtrace_continuation_root,
    )
    standalone_stage16_p13b_continuation_path = _stage16_p13b_continuation_path(
        stage16_p13b_continuation_json=stage16_p13b_continuation_json,
        stage16_p13b_continuation_root=stage16_p13b_continuation_root,
    )
    standalone_stage5_calibration_sample_path = _stage5_calibration_sample_path(
        stage5_calibration_sample_json=stage5_calibration_sample_json,
        stage5_calibration_sample_root=stage5_calibration_sample_root,
    )
    standalone_release_field_query_results = _standalone_release_field_query_results_by_project(
        standalone_release_field_query_path,
        supplemental_paths=standalone_supplemental_release_field_query_paths,
    )
    standalone_release_evidence_adapter_plan_status_records = (
        []
        if standalone_release_field_query_results
        else _standalone_release_evidence_adapter_plan_status_records(
            standalone_release_evidence_adapter_plan_path
        )
    )
    standalone_original_backtrace_continuation_status_records = (
        []
        if standalone_release_field_query_results or standalone_release_evidence_adapter_plan_status_records
        else _standalone_original_backtrace_continuation_status_records(
            standalone_original_backtrace_continuation_path
        )
    )
    standalone_stage16_p13b_continuation_status_records = (
        []
        if (
            standalone_release_field_query_results
            or standalone_release_evidence_adapter_plan_status_records
            or standalone_original_backtrace_continuation_status_records
        )
        else _standalone_stage16_p13b_continuation_status_records(
            standalone_stage16_p13b_continuation_path
        )
    )
    standalone_stage5_calibration_status_records = _standalone_stage5_calibration_status_records(
        standalone_stage5_calibration_sample_path
    )
    release_field_query_results = {
        **standalone_release_field_query_results,
        **_release_field_query_results_by_project(result_runner),
    }
    standalone_status_only = input_blocked and bool(
        standalone_release_field_query_results
        or standalone_release_evidence_adapter_plan_status_records
        or standalone_original_backtrace_continuation_status_records
        or standalone_stage16_p13b_continuation_status_records
        or standalone_stage5_calibration_status_records
    )
    summary_bootstrap = dict(bootstrap)
    if input_blocked and standalone_release_field_query_results:
        summary_bootstrap["loop_input_state"] = "STANDALONE_RELEASE_FIELD_QUERY_STATUS_ONLY"
        summary_bootstrap["blocking_reasons"] = []
        next_cycle_skip_reason = "standalone_release_field_query_status_only"
    elif input_blocked and standalone_release_evidence_adapter_plan_status_records:
        summary_bootstrap["loop_input_state"] = "STANDALONE_RELEASE_EVIDENCE_PLAN_STATUS_ONLY"
        summary_bootstrap["blocking_reasons"] = []
        next_cycle_skip_reason = "standalone_release_evidence_plan_status_only"
    elif input_blocked and standalone_original_backtrace_continuation_status_records:
        summary_bootstrap["loop_input_state"] = "STANDALONE_ORIGINAL_READBACK_STATUS_ONLY"
        summary_bootstrap["blocking_reasons"] = []
        next_cycle_skip_reason = "standalone_original_readback_status_only"
    elif input_blocked and standalone_stage16_p13b_continuation_status_records:
        summary_bootstrap["loop_input_state"] = "STANDALONE_P13B_CONTINUATION_STATUS_ONLY"
        summary_bootstrap["blocking_reasons"] = []
        next_cycle_skip_reason = "standalone_p13b_continuation_status_only"
    elif input_blocked and standalone_stage5_calibration_status_records:
        summary_bootstrap["loop_input_state"] = "STANDALONE_STAGE5_CALIBRATION_STATUS_ONLY"
        summary_bootstrap["blocking_reasons"] = []
        next_cycle_skip_reason = "standalone_stage5_calibration_status_only"

    blocking_reasons = [
        *_list(summary_bootstrap.get("blocking_reasons")),
        *_all_blocking_reasons(
            dispatch_runner,
            readback,
            closeout,
            routing,
            result_runner,
            next_cycle,
        ),
    ]
    project_status_records = [
        *[
            dict(record)
            for record in _list(summary_bootstrap.get("bootstrap_project_status_records"))
            if isinstance(record, Mapping)
        ],
        *[dict(record) for record in standalone_release_evidence_adapter_plan_status_records],
        *[dict(record) for record in standalone_original_backtrace_continuation_status_records],
        *[dict(record) for record in standalone_stage16_p13b_continuation_status_records],
        *_project_status_records(
            readback=readback,
            closeout=closeout,
            routing=routing,
            result_runner=result_runner,
            next_cycle=next_cycle,
            release_field_query_results=release_field_query_results,
        ),
    ]
    project_status_records = _merge_stage5_calibration_status_records(
        project_status_records,
        standalone_stage5_calibration_status_records,
    )
    summary = _summary(
        dispatch_runner=dispatch_runner,
        readback=readback,
        closeout=closeout,
        routing=routing,
        result_runner=result_runner,
        next_cycle=next_cycle,
        project_status_records=project_status_records,
        next_cycle_skip_reason=next_cycle_skip_reason,
        bootstrap=summary_bootstrap,
        blocking_reasons=blocking_reasons,
        execute_dispatch=execute_dispatch,
        execute_results=execute_results,
        execute_next_cycle_dispatch=execute_next_cycle_dispatch,
    )
    project_status_table_path = out_dir / "stage6-review-loop-project-status-table.json"
    runtime_blocker_next_subqueue_table = build_runtime_blocker_next_subqueue_table(
        project_status_records,
        source_status_table_ref=str(project_status_table_path),
    )
    next_subqueue_summary = dict(runtime_blocker_next_subqueue_table.get("summary") or {})
    summary["runtime_blocker_next_subqueue_record_count"] = int(
        next_subqueue_summary.get("next_subqueue_record_count") or 0
    )
    summary["runtime_blocker_next_subqueue_route_counts"] = dict(
        next_subqueue_summary.get("subqueue_route_counts") or {}
    )
    summary["runtime_blocker_next_subqueue_state_counts"] = dict(
        next_subqueue_summary.get("subqueue_state_counts") or {}
    )
    continuation_input_refs = build_stage6_review_cycle_continuation_input_refs(
        output_root=out_dir,
        release_field_query_json=standalone_release_field_query_path,
        supplemental_release_field_query_json=_joined_existing_paths(*standalone_supplemental_release_field_query_paths),
        runtime_blocker_next_subqueue_json=out_dir / "stage6-review-loop-runtime-blocker-next-subqueues.json",
        stage6_review_loop_status_json=project_status_table_path,
    )
    summary["continuation_input_refs"] = continuation_input_refs
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
        "source_batch_closeout_json": str(summary_bootstrap.get("source_batch_closeout_json") or ""),
        "bootstrap": summary_bootstrap,
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
            "release_field_query": str(release_field_query_result_root),
            "result_runner": str(result_run_root),
            "next_cycle": str(next_cycle_root),
            "standalone_release_field_query": str(
                standalone_release_field_query_path.parent if standalone_release_field_query_path else ""
            ),
            "standalone_release_evidence_adapter_plan": str(
                standalone_release_evidence_adapter_plan_path.parent
                if standalone_release_evidence_adapter_plan_path
                else ""
            ),
            "standalone_original_backtrace_continuation": str(
                standalone_original_backtrace_continuation_path.parent
                if standalone_original_backtrace_continuation_path
                else ""
            ),
            "standalone_stage16_p13b_continuation": str(
                standalone_stage16_p13b_continuation_path.parent
                if standalone_stage16_p13b_continuation_path
                else ""
            ),
            "standalone_stage5_calibration_sample": str(
                standalone_stage5_calibration_sample_path.parent
                if standalone_stage5_calibration_sample_path
                else ""
            ),
        },
        "source_standalone_release_field_query_json": str(standalone_release_field_query_path or ""),
        "source_standalone_supplemental_release_field_query_json": str(
            _joined_existing_paths(*standalone_supplemental_release_field_query_paths)
        ),
        "standalone_release_field_query_imported_project_count": len(standalone_release_field_query_results),
        "source_standalone_release_evidence_adapter_plan_json": str(
            standalone_release_evidence_adapter_plan_path or ""
        ),
        "standalone_release_evidence_adapter_plan_imported_project_count": len(
            standalone_release_evidence_adapter_plan_status_records
        ),
        "source_standalone_original_backtrace_continuation_json": str(
            standalone_original_backtrace_continuation_path or ""
        ),
        "standalone_original_backtrace_continuation_imported_project_count": len(
            standalone_original_backtrace_continuation_status_records
        ),
        "source_standalone_stage16_p13b_continuation_json": str(
            standalone_stage16_p13b_continuation_path or ""
        ),
        "standalone_stage16_p13b_continuation_imported_project_count": len(
            standalone_stage16_p13b_continuation_status_records
        ),
        "source_standalone_stage5_calibration_sample_json": str(
            standalone_stage5_calibration_sample_path or ""
        ),
        "standalone_stage5_calibration_imported_project_count": len(
            standalone_stage5_calibration_status_records
        ),
        "runtime_blocker_next_subqueue_json": str(out_dir / "stage6-review-loop-runtime-blocker-next-subqueues.json"),
        "continuation_input_refs": continuation_input_refs,
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
        "runtime_blocker_next_subqueue_table": runtime_blocker_next_subqueue_table,
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
        "safe_to_execute": (
            standalone_status_only
            or (
                not input_blocked
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
        dispatch_runner_root=dispatch_run_root,
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
        closeout_precedence = record.get("closeout_precedence") if isinstance(record.get("closeout_precedence"), Mapping) else {}
        runtime_blockers = _runtime_blocker_ledger_records_from_sources(record, closeout_precedence=closeout_precedence)
        operator_next_action = str(
            record.get("operator_next_action")
            or closeout_precedence.get("operator_next_action")
            or closeout_precedence.get("next_action")
            or ""
        )
        runtime_blocker_projection = runtime_blocker_projection_fields(runtime_blockers)
        out.append(
            {
                "project_id": project_id,
                "project_name": str(record.get("project_name") or ""),
                **_owner_assignment_fields_from_sources(record),
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
                "release_field_query_authorized_session_input_state_counts": {},
                "release_field_query_authorization_state_counts": {},
                "release_field_query_operator_next_actions": [],
                "release_field_query_source_hit_summaries": [],
                "release_field_query_source_hit_summary_labels": [],
                "next_cycle_dispatch_task_type": "",
                "next_cycle_dispatch_readiness_state": "",
                "next_cycle_manual_only_action_family": str(record.get("action_family") or ""),
                "next_cycle_dispatch_block_reason": dispatch_block_reason,
                "closeout_precedence": dict(record.get("closeout_precedence") or {}),
                "closeout_precedence_state": str(record.get("closeout_precedence_state") or ""),
                "closeout_precedence_suppressed": bool(record.get("closeout_precedence_suppressed")),
                "closeout_precedence_blocker_taxonomy": _list(
                    (record.get("closeout_precedence") or {}).get("blocker_taxonomy")
                    if isinstance(record.get("closeout_precedence"), Mapping)
                    else []
                ),
                "closeout_precedence_marker_source_refs": _list(closeout_precedence.get("marker_source_refs")),
                "closeout_precedence_terminal_marker": dict(closeout_precedence.get("terminal_marker") or {}),
                **runtime_blocker_projection,
                "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                "next_recommended_action": operator_next_action
                or (
                    "manual_review_or_new_source_override_required_before_retry"
                    if dispatch_block_reason
                    else "no_automated_stage6_dispatch_task_keep_internal_review"
                ),
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
    runtime_followups = _runtime_blocker_worker_followup_records_by_project(next_cycle)
    project_ids = sorted(
        {
            *readbacks.keys(),
            *closeouts.keys(),
            *routings.keys(),
            *runners.keys(),
            *next_dispatch.keys(),
            *next_manual.keys(),
            *runtime_followups.keys(),
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
        runtime_followup_records = runtime_followups.get(project_id, [])
        release_field_query_result = dict(release_field_query_results.get(project_id) or {})
        closeout_precedence = (
            next_manual_record.get("closeout_precedence")
            if isinstance(next_manual_record.get("closeout_precedence"), Mapping)
            else routing_record.get("closeout_precedence")
            if isinstance(routing_record.get("closeout_precedence"), Mapping)
            else {}
        )
        runtime_blockers = _runtime_blocker_ledger_records_from_sources(
            closeout_record,
            routing_record,
            next_manual_record,
            release_field_query_result,
            closeout_precedence=closeout_precedence,
        )
        stage7_commercial_input_allowed = bool(closeout_record.get("stage7_commercial_input_allowed", False))
        limited_sellable_projection = limited_sellable_review_projection(
            release_field_query_result.get("downstream_release_evidence_abcd_grade_counts") or {},
            stage7_commercial_input_allowed=stage7_commercial_input_allowed,
            field_tasks=release_field_query_result.get("field_query_tasks") or [],
        )
        runtime_blocker_projection = runtime_blocker_projection_fields(runtime_blockers)
        records.append(
            {
                "project_id": project_id,
                "project_name": _first_text(
                    readback_record.get("project_name"),
                    closeout_record.get("project_name"),
                    routing_record.get("project_name"),
                    runner_record.get("project_name"),
                    next_dispatch_record.get("project_name"),
                    next_manual_record.get("project_name"),
                    *(item.get("project_name") for item in runtime_followup_records if isinstance(item, Mapping)),
                ),
                **_owner_assignment_fields_from_sources(
                    readback_record,
                    closeout_record,
                    routing_record,
                    runner_record,
                    next_dispatch_record,
                    next_manual_record,
                    release_field_query_result,
                    *runtime_followup_records,
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
                "stage7_commercial_input_allowed": stage7_commercial_input_allowed,
                **limited_sellable_projection,
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
                "release_field_query_authorized_session_input_state_counts": dict(
                    release_field_query_result.get("authorized_session_input_state_counts") or {}
                ),
                "release_field_query_authorization_state_counts": dict(
                    release_field_query_result.get("authorization_readiness_state_counts") or {}
                ),
                "release_field_query_operator_next_actions": _list(
                    release_field_query_result.get("operator_next_actions")
                ),
                "release_field_query_source_hit_summaries": _list(
                    release_field_query_result.get("source_hit_summaries")
                ),
                "release_field_query_source_hit_summary_labels": _list(
                    release_field_query_result.get("source_hit_summary_labels")
                ),
                "next_cycle_dispatch_task_type": str(next_dispatch_record.get("dispatch_task_type") or ""),
                "next_cycle_dispatch_readiness_state": str(next_dispatch_record.get("dispatch_readiness_state") or ""),
                "next_cycle_manual_only_action_family": str(next_manual_record.get("action_family") or ""),
                "next_cycle_dispatch_block_reason": str(next_manual_record.get("dispatch_block_reason") or ""),
                "closeout_precedence": dict(closeout_precedence),
                "closeout_precedence_state": _first_text(
                    next_manual_record.get("closeout_precedence_state"),
                    routing_record.get("closeout_precedence_state"),
                ),
                "closeout_precedence_suppressed": bool(
                    next_manual_record.get("closeout_precedence_suppressed")
                    or routing_record.get("closeout_precedence_suppressed")
                ),
                "closeout_precedence_blocker_taxonomy": _list(closeout_precedence.get("blocker_taxonomy")),
                "closeout_precedence_marker_source_refs": _list(closeout_precedence.get("marker_source_refs")),
                "closeout_precedence_terminal_marker": dict(closeout_precedence.get("terminal_marker") or {}),
                **runtime_blocker_projection,
                "runtime_blocker_worker_followup_records": runtime_followup_records,
                "runtime_blocker_worker_followup_count": len(runtime_followup_records),
                "loop_terminal_state": _loop_terminal_state(
                    readback_record=readback_record,
                    closeout_record=closeout_record,
                    routing_record=routing_record,
                    runner_record=runner_record,
                    next_dispatch_record=next_dispatch_record,
                    next_manual_record=next_manual_record,
                    runtime_blocker_worker_followup_records=runtime_followup_records,
                    release_field_query_result=release_field_query_result,
                ),
                "next_recommended_action": _loop_next_action(
                    readback_record=readback_record,
                    closeout_record=closeout_record,
                    runner_record=runner_record,
                    routing_record=routing_record,
                    next_dispatch_record=next_dispatch_record,
                    next_manual_record=next_manual_record,
                    runtime_blocker_worker_followup_records=runtime_followup_records,
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


def _release_field_query_path(
    *,
    release_field_query_json: str | Path | None,
    release_field_query_root: str | Path | None,
) -> Path | None:
    if release_field_query_json:
        return Path(release_field_query_json)
    if release_field_query_root:
        return Path(release_field_query_root) / DEFAULT_RELEASE_FIELD_QUERY_FILENAME
    return None


def _release_field_query_paths(
    *,
    release_field_query_json: str | Path | None,
    release_field_query_root: str | Path | None,
) -> list[Path]:
    paths: list[Path] = []
    if release_field_query_json:
        for part in str(release_field_query_json).split(";"):
            text = part.strip()
            if text:
                paths.append(Path(text))
    elif release_field_query_root:
        paths.append(Path(release_field_query_root) / DEFAULT_RELEASE_FIELD_QUERY_FILENAME)
    return paths


def _release_evidence_adapter_plan_path(
    *,
    release_evidence_adapter_plan_json: str | Path | None,
    release_evidence_adapter_plan_root: str | Path | None,
) -> Path | None:
    if release_evidence_adapter_plan_json:
        return Path(release_evidence_adapter_plan_json)
    if release_evidence_adapter_plan_root:
        return Path(release_evidence_adapter_plan_root) / DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_FILENAME
    return None


def _original_backtrace_continuation_path(
    *,
    original_backtrace_continuation_json: str | Path | None,
    original_backtrace_continuation_root: str | Path | None,
) -> Path | None:
    if original_backtrace_continuation_json:
        return Path(original_backtrace_continuation_json)
    if original_backtrace_continuation_root:
        return Path(original_backtrace_continuation_root) / DEFAULT_ORIGINAL_BACKTRACE_CONTINUATION_FILENAME
    return None


def _stage16_p13b_continuation_path(
    *,
    stage16_p13b_continuation_json: str | Path | None,
    stage16_p13b_continuation_root: str | Path | None,
) -> Path | None:
    if stage16_p13b_continuation_json:
        return Path(stage16_p13b_continuation_json)
    if stage16_p13b_continuation_root:
        return Path(stage16_p13b_continuation_root) / DEFAULT_STAGE16_P13B_CONTINUATION_FILENAME
    return None


def _stage5_calibration_sample_path(
    *,
    stage5_calibration_sample_json: str | Path | None,
    stage5_calibration_sample_root: str | Path | None,
) -> Path | None:
    if stage5_calibration_sample_json:
        return Path(stage5_calibration_sample_json)
    if stage5_calibration_sample_root:
        return Path(stage5_calibration_sample_root) / DEFAULT_STAGE5_CALIBRATION_SAMPLE_FILENAME
    return None


def _standalone_release_field_query_results_by_project(
    path: Path | None,
    *,
    supplemental_paths: list[Path] | None = None,
) -> dict[str, dict[str, Any]]:
    supplemental_paths = supplemental_paths or []
    existing_supplemental_paths = [item for item in supplemental_paths if item.exists()]
    if (path is None or not path.exists()) and not existing_supplemental_paths:
        return {}
    primary_path = path if path is not None and path.exists() else existing_supplemental_paths[0] if existing_supplemental_paths else None
    if primary_path is None:
        return {}
    field_tasks, manifest_by_path = _release_field_query_tasks_from_paths(primary_path, *existing_supplemental_paths)
    manifest = manifest_by_path.get(str(primary_path), {})
    field_tasks = [
        task
        for task in field_tasks
        if isinstance(task, Mapping)
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for task in field_tasks:
        project_id = str(task.get("project_id") or "").strip()
        if project_id:
            grouped.setdefault(project_id, []).append(task)
    runner_record = {"execution_state": "IMPORTED_STANDALONE_RELEASE_FIELD_QUERY"}
    return {
        project_id: _release_field_query_project_result(
            runner_record=runner_record,
            result_path=_joined_existing_paths(path, *existing_supplemental_paths),
            result_manifest=manifest,
            tasks=tasks,
        )
        for project_id, tasks in grouped.items()
    }


def _release_field_query_tasks_from_paths(
    primary_path: Path,
    *supplemental_paths: Path,
) -> tuple[list[dict[str, Any]], dict[str, Mapping[str, Any]]]:
    out: list[dict[str, Any]] = []
    manifests: dict[str, Mapping[str, Any]] = {}
    source_paths: list[tuple[str, Path | None]] = [("primary", primary_path)]
    source_paths.extend((f"supplemental_{index}", path) for index, path in enumerate(supplemental_paths, start=1))
    for source_label, candidate_path in source_paths:
        if candidate_path is None or not candidate_path.exists():
            continue
        payload = _load_json_if_exists(candidate_path)
        manifest = _source_manifest(payload)
        manifests[str(candidate_path)] = manifest
        for task in _list(manifest.get("field_task_records")):
            if isinstance(task, Mapping):
                out.append(
                    {
                        **dict(task),
                        "stage6_release_field_query_source": source_label,
                        "stage6_release_field_query_source_json": str(candidate_path),
                    }
                )
    return out, manifests


def _joined_existing_paths(*paths: Path | None) -> str:
    return ";".join(str(path) for path in paths if path is not None and path.exists())


def _standalone_stage5_calibration_status_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = _load_json_if_exists(path)
    records = [record for record in _list(payload.get("records")) if isinstance(record, Mapping)]
    out: list[dict[str, Any]] = []
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        truth_label_required = bool(record.get("calibration_truth_label_required"))
        abcd_bucket = _stage5_abcd_calibration_bucket(record)
        out.append(
            {
                "project_id": project_id,
                "project_name": str(record.get("project_name") or ""),
                "stage5_calibration_sample_id": str(record.get("stage5_calibration_sample_id") or ""),
                "stage5_calibration_review_bucket": str(record.get("stage5_calibration_review_bucket") or ""),
                "stage5_abcd_calibration_bucket": abcd_bucket,
                "stage5_calibration_evidence_strength": str(
                    record.get("stage5_calibration_evidence_strength")
                    or record.get("calibration_evidence_strength")
                    or ""
                ),
                "stage5_calibration_review_family": str(
                    record.get("stage5_calibration_review_family")
                    or record.get("calibration_review_family")
                    or ""
                ),
                "stage5_calibration_review_reasons": _list(record.get("stage5_calibration_review_reasons")),
                "calibration_truth_label_required": truth_label_required,
                "suggested_calibration_action": str(record.get("suggested_calibration_action") or ""),
                "stage5_rule_gate_status": str(record.get("stage5_rule_gate_status") or ""),
                "stage5_evidence_gate_status": str(record.get("stage5_evidence_gate_status") or ""),
                "stage5_gate_result_state": str(record.get("stage5_gate_result_state") or ""),
                "stage5_calibration_source_json": str(path),
                "loop_terminal_state": "STAGE5_CALIBRATION_REVIEW_READY",
                "next_recommended_action": (
                    "review_stage5_calibration_samples_before_rule_change"
                    if truth_label_required
                    else "keep_stage5_calibration_sample_as_baseline"
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return out


def _merge_stage5_calibration_status_records(
    project_status_records: list[dict[str, Any]],
    stage5_calibration_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not stage5_calibration_records:
        return project_status_records
    merged = [dict(record) for record in project_status_records]
    index_by_project = {
        str(record.get("project_id") or ""): index
        for index, record in enumerate(merged)
        if str(record.get("project_id") or "").strip()
    }
    for calibration_record in stage5_calibration_records:
        project_id = str(calibration_record.get("project_id") or "").strip()
        if not project_id:
            continue
        if project_id not in index_by_project:
            index_by_project[project_id] = len(merged)
            merged.append(dict(calibration_record))
            continue
        existing = dict(merged[index_by_project[project_id]])
        for key, value in calibration_record.items():
            if key in {"project_id", "project_name"} and existing.get(key):
                continue
            existing[key] = value
        if str(existing.get("loop_terminal_state") or "") == "NO_PROJECT_STATUS_RECORD":
            existing["loop_terminal_state"] = "STAGE5_CALIBRATION_REVIEW_READY"
        if not str(existing.get("next_recommended_action") or "").strip():
            existing["next_recommended_action"] = str(calibration_record.get("next_recommended_action") or "")
        merged[index_by_project[project_id]] = existing
    return merged


def _standalone_release_evidence_adapter_plan_status_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = _load_json_if_exists(path)
    manifest = _source_manifest(payload)
    plan_records = [
        dict(record)
        for record in _list(manifest.get("project_release_evidence_plan_records"))
        if isinstance(record, Mapping)
    ]
    out: list[dict[str, Any]] = []
    for record in plan_records:
        closeout_precedence = (
            record.get("closeout_precedence")
            if isinstance(record.get("closeout_precedence"), Mapping)
            else {}
        )
        suppressed = bool(
            record.get("closeout_precedence_suppressed")
            or closeout_precedence.get("suppressed_dispatch")
            or closeout_precedence.get("should_suppress_dispatch")
        )
        if not suppressed:
            continue
        runtime_blockers = _runtime_blocker_ledger_records_from_sources(
            record,
            closeout_precedence=closeout_precedence,
        )
        next_action = _first_text(
            record.get("recommended_next_action"),
            record.get("operator_projection", {}).get("next_action")
            if isinstance(record.get("operator_projection"), Mapping)
            else "",
            closeout_precedence.get("operator_next_action")
            if isinstance(closeout_precedence, Mapping)
            else "",
            closeout_precedence.get("next_action") if isinstance(closeout_precedence, Mapping) else "",
            "project_to_review_ready_status_projection_without_duplicate_dispatch",
        )
        out.append(
            {
                "project_id": str(record.get("project_id") or ""),
                "project_name": str(record.get("project_name") or ""),
                **_owner_assignment_fields_from_sources(record),
                "dispatch_task_type": "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE",
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
                "release_field_query_authorized_session_input_state_counts": {},
                "release_field_query_authorization_state_counts": {},
                "release_field_query_operator_next_actions": [],
                "release_field_query_source_hit_summaries": [],
                "release_field_query_source_hit_summary_labels": [],
                "next_cycle_dispatch_task_type": "",
                "next_cycle_dispatch_readiness_state": "",
                "next_cycle_manual_only_action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "next_cycle_dispatch_block_reason": str(
                    closeout_precedence.get("suppression_reason")
                    or "terminal_closeout_or_backfill_marker_present"
                ),
                "closeout_precedence": dict(closeout_precedence),
                "closeout_precedence_state": str(record.get("closeout_precedence_state") or ""),
                "closeout_precedence_suppressed": True,
                "closeout_precedence_blocker_taxonomy": _list(closeout_precedence.get("blocker_taxonomy")),
                "closeout_precedence_marker_source_refs": _list(closeout_precedence.get("marker_source_refs")),
                "closeout_precedence_terminal_marker": dict(closeout_precedence.get("terminal_marker") or {}),
                "runtime_blocker_ledger_records": runtime_blockers,
                "runtime_blocker_ledger_state_counts": _counts(
                    item.get("blocker_state") for item in runtime_blockers
                ),
                "runtime_blocker_ledger_layer_counts": _counts(
                    item.get("runtime_layer") for item in runtime_blockers
                ),
                "runtime_blocker_subqueue_routes": _runtime_blocker_subqueue_routes(runtime_blockers),
                "runtime_blocker_subqueue_counts": _counts(_runtime_blocker_subqueue_routes(runtime_blockers)),
                "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                "next_recommended_action": next_action,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return out


def _standalone_original_backtrace_continuation_status_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = _load_json_if_exists(path)
    manifest = _source_manifest(payload)
    continuation_records = [
        dict(record)
        for record in _list(manifest.get("continuation_plan_records"))
        if isinstance(record, Mapping)
    ]
    out: list[dict[str, Any]] = []
    for record in continuation_records:
        closeout_precedence = (
            record.get("closeout_precedence")
            if isinstance(record.get("closeout_precedence"), Mapping)
            else {}
        )
        runtime_blockers = _runtime_blocker_ledger_records_from_sources(
            record,
            closeout_precedence=closeout_precedence,
        )
        if _is_original_readback_projection_only_terminal(closeout_precedence):
            runtime_blockers = []
        projection = (
            record.get("operator_projection")
            if isinstance(record.get("operator_projection"), Mapping)
            else {}
        )
        next_queue = str(record.get("next_queue") or "").strip()
        out.append(
            {
                "project_id": str(record.get("project_id") or ""),
                "project_name": str(record.get("project_name") or ""),
                **_owner_assignment_fields_from_sources(record),
                "dispatch_task_type": _original_readback_dispatch_task_type(next_queue),
                "dispatch_readback_state": "",
                "dispatch_closeout_state": "",
                "result_routing_state": "",
                "next_task_type": next_queue,
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
                "release_field_query_authorized_session_input_state_counts": {},
                "release_field_query_authorization_state_counts": {},
                "release_field_query_operator_next_actions": [],
                "release_field_query_source_hit_summaries": [],
                "release_field_query_source_hit_summary_labels": [],
                "next_cycle_dispatch_task_type": "",
                "next_cycle_dispatch_readiness_state": "",
                "next_cycle_manual_only_action_family": "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW",
                "next_cycle_dispatch_block_reason": str(
                    closeout_precedence.get("suppression_reason")
                    or record.get("continuation_state")
                    or ""
                ),
                "closeout_precedence": dict(closeout_precedence),
                "closeout_precedence_state": str(record.get("closeout_precedence_state") or ""),
                "closeout_precedence_suppressed": bool(record.get("closeout_precedence_suppressed")),
                "closeout_precedence_blocker_taxonomy": _list(closeout_precedence.get("blocker_taxonomy")),
                "closeout_precedence_marker_source_refs": _list(closeout_precedence.get("marker_source_refs")),
                "closeout_precedence_terminal_marker": dict(closeout_precedence.get("terminal_marker") or {}),
                "runtime_blocker_ledger_records": runtime_blockers,
                "runtime_blocker_ledger_state_counts": _counts(
                    item.get("blocker_state") for item in runtime_blockers
                ),
                "runtime_blocker_ledger_layer_counts": _counts(
                    item.get("runtime_layer") for item in runtime_blockers
                ),
                "runtime_blocker_subqueue_routes": _runtime_blocker_subqueue_routes(runtime_blockers),
                "runtime_blocker_subqueue_counts": _counts(_runtime_blocker_subqueue_routes(runtime_blockers)),
                "loop_terminal_state": str(
                    projection.get("projection_state")
                    or (
                        "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH"
                        if record.get("closeout_precedence_suppressed")
                        else "ORIGINAL_READBACK_STATUS_IMPORTED"
                    )
                ),
                "next_recommended_action": _first_text(
                    projection.get("next_action"),
                    record.get("recommended_next_action"),
                    "review_original_readback_status_inputs",
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return out


def _standalone_stage16_p13b_continuation_status_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = _load_json_if_exists(path)
    manifest = _source_manifest(payload)
    continuation_records = [
        dict(record)
        for record in _list(manifest.get("project_continuation_records"))
        if isinstance(record, Mapping)
    ]
    out: list[dict[str, Any]] = []
    for record in continuation_records:
        closeout_precedence = (
            record.get("closeout_precedence")
            if isinstance(record.get("closeout_precedence"), Mapping)
            else {}
        )
        runtime_blockers = _runtime_blocker_ledger_records_from_sources(
            record,
            closeout_precedence=closeout_precedence,
        )
        projection = (
            record.get("operator_projection")
            if isinstance(record.get("operator_projection"), Mapping)
            else {}
        )
        next_action = _first_text(
            projection.get("next_action"),
            record.get("recommended_next_action"),
            "review_p13b_continuation_status_inputs",
        )
        out.append(
            {
                "project_id": str(record.get("project_id") or ""),
                "project_name": str(record.get("project_name") or ""),
                **_owner_assignment_fields_from_sources(record),
                "dispatch_task_type": _stage16_p13b_dispatch_task_type(str(record.get("continuation_state") or "")),
                "dispatch_readback_state": "",
                "dispatch_closeout_state": "",
                "result_routing_state": "",
                "next_task_type": "p13b_follow_up",
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
                "release_field_query_authorized_session_input_state_counts": {},
                "release_field_query_authorization_state_counts": {},
                "release_field_query_operator_next_actions": [],
                "release_field_query_source_hit_summaries": [],
                "release_field_query_source_hit_summary_labels": [],
                "next_cycle_dispatch_task_type": "",
                "next_cycle_dispatch_readiness_state": "",
                "next_cycle_manual_only_action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "next_cycle_dispatch_block_reason": str(
                    closeout_precedence.get("suppression_reason")
                    or record.get("continuation_state")
                    or ""
                ),
                "closeout_precedence": dict(closeout_precedence),
                "closeout_precedence_state": str(record.get("closeout_precedence_state") or ""),
                "closeout_precedence_suppressed": bool(record.get("closeout_precedence_suppressed")),
                "closeout_precedence_blocker_taxonomy": _list(closeout_precedence.get("blocker_taxonomy")),
                "closeout_precedence_marker_source_refs": _list(closeout_precedence.get("marker_source_refs")),
                "closeout_precedence_terminal_marker": dict(closeout_precedence.get("terminal_marker") or {}),
                "runtime_blocker_ledger_records": runtime_blockers,
                "runtime_blocker_ledger_state_counts": _counts(
                    item.get("blocker_state") for item in runtime_blockers
                ),
                "runtime_blocker_ledger_layer_counts": _counts(
                    item.get("runtime_layer") for item in runtime_blockers
                ),
                "runtime_blocker_subqueue_routes": _runtime_blocker_subqueue_routes(runtime_blockers),
                "runtime_blocker_subqueue_counts": _counts(_runtime_blocker_subqueue_routes(runtime_blockers)),
                "loop_terminal_state": str(
                    projection.get("projection_state")
                    or (
                        "P13B_CONTINUATION_OPERATOR_HOLD"
                        if record.get("closeout_precedence_suppressed")
                        else "P13B_CONTINUATION_READY"
                    )
                ),
                "next_recommended_action": next_action,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return out


def _original_readback_dispatch_task_type(next_queue: str) -> str:
    queue = str(next_queue or "").strip()
    return {
        "release_evidence_query": "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
        "original_readback_retry": "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
        "targeted_person_readback": "RUN_P13B_TARGETED_PERSON_READBACK",
        "route_specific_original_readback": "RUN_ORIGINAL_NOTICE_ROUTE_SPECIFIC_READBACK",
        "manual_hold": "",
    }.get(queue, "")


def _stage16_p13b_dispatch_task_type(state: str) -> str:
    continuation_state = str(state or "").strip()
    if continuation_state == "READY_FOR_P13B_DATA_GGZY":
        return "RUN_DATA_GGZY_COMPANY_HISTORY_OVERLAP_TRIAGE"
    return ""


def _release_field_query_missing_result(runner_record: Mapping[str, Any], result_path: str) -> dict[str, Any]:
    return {
        **_owner_assignment_fields_from_sources(runner_record),
        "release_field_query_state": "RELEASE_FIELD_QUERY_RESULT_MISSING",
        "result_json_path": result_path,
        "result_manifest_id": "",
        "field_query_task_count": 0,
        "adapter_result_state_counts": {},
        "downstream_release_evidence_abcd_grade_counts": {},
        "authorized_session_input_state_counts": {},
        "authorization_readiness_state_counts": {},
        "operator_next_actions": [],
        "source_hit_summaries": [],
        "source_hit_summary_labels": [],
        "runtime_blocker_ledger_records": [
            _release_field_query_missing_result_ledger(runner_record=runner_record, result_path=result_path)
        ],
        "runtime_blocker_ledger_state_counts": {"RELEASE_FIELD_QUERY_RESULT_MISSING": 1},
        "runtime_blocker_ledger_layer_counts": {"closeout": 1},
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
    session_input_counts = _field_query_authorized_session_input_state_counts(tasks)
    authorization_counts = _field_query_authorization_counts(tasks)
    operator_next_actions = _field_query_operator_next_actions(tasks)
    source_hit_summaries = _field_query_source_hit_summaries(tasks)
    runtime_blockers = _field_query_runtime_blocker_ledger_records(tasks, result_path=result_path)
    operator_next_actions = _dedupe(
        [
            *operator_next_actions,
            *(record.get("operator_next_action") for record in runtime_blockers if isinstance(record, Mapping)),
        ]
    )
    return {
        **_owner_assignment_fields_from_sources(*tasks),
        "release_field_query_state": _release_field_query_state(adapter_counts, downstream_counts, task_count=len(tasks)),
        "result_json_path": result_path,
        "result_manifest_id": str(result_manifest.get("manifest_id") or ""),
        "field_query_task_count": len(tasks),
        "field_query_tasks": [dict(task) for task in tasks],
        "adapter_result_state_counts": adapter_counts,
        "downstream_release_evidence_abcd_grade_counts": downstream_counts,
        "authorized_session_input_state_counts": session_input_counts,
        "authorization_readiness_state_counts": authorization_counts,
        "operator_next_actions": operator_next_actions,
        "source_hit_summaries": source_hit_summaries,
        "source_hit_summary_labels": _field_query_source_hit_summary_labels(source_hit_summaries),
        "runtime_blocker_ledger_records": runtime_blockers,
        "runtime_blocker_ledger_state_counts": _counts(record.get("blocker_state") for record in runtime_blockers),
        "runtime_blocker_ledger_layer_counts": _counts(record.get("runtime_layer") for record in runtime_blockers),
        "source_result_runner_execution_state": str(runner_record.get("execution_state") or ""),
    }


def _release_field_query_missing_result_ledger(*, runner_record: Mapping[str, Any], result_path: str) -> dict[str, Any]:
    project_id = str(runner_record.get("project_id") or "")
    return {
        **_owner_assignment_fields_from_sources(runner_record),
        "blocker_ledger_id": _stable_id("RUNTIME-BLOCKER", "stage4_release_evidence_query", project_id, result_path),
        "ledger_scope": "stage4_release_evidence_query",
        "project_id": project_id,
        "project_name": str(runner_record.get("project_name") or ""),
        "task_id": str(runner_record.get("result_runner_id") or runner_record.get("dispatch_task_id") or project_id),
        "task_scope": "release_evidence_query",
        "task_type": "release_field_query_result_readback",
        "blocker_state": "RELEASE_FIELD_QUERY_RESULT_MISSING",
        "blocker_reason": "expected_release_field_query_result_artifact_missing",
        "runtime_layer": "closeout",
        "required_input": ["release_field_query_result_json_or_rerun_artifact"],
        "retry_policy": "rerun_result_worker_or_rebuild_release_field_query_artifact",
        "reopen_conditions": [
            "expected_output_artifact_path_exists",
            "operator_reruns_controlled_result_worker",
        ],
        "operator_next_action": "inspect_release_field_query_result_before_next_stage6_cycle",
        "next_action": "inspect_release_field_query_result_before_next_stage6_cycle",
        "artifact_ref": result_path,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _field_query_runtime_blocker_ledger_records(tasks: list[Mapping[str, Any]], *, result_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        rows.extend(_runtime_blocker_ledger_records_from_sources(task))
        synthesized = _field_query_synthesized_blocker_ledger(task, result_path=result_path)
        if synthesized:
            rows.append(synthesized)
    return _dedupe_ledger_records(rows)


def _field_query_synthesized_blocker_ledger(task: Mapping[str, Any], *, result_path: str) -> dict[str, Any]:
    adapter_state = str(task.get("adapter_result_state") or "").strip()
    downstream_grade = str(task.get("downstream_release_evidence_abcd_grade") or "").strip()
    if adapter_state not in {"NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"} and not downstream_grade.startswith("D_"):
        return {}
    field_summary = task.get("field_summary") if isinstance(task.get("field_summary"), Mapping) else {}
    field_match_summary = task.get("field_match_summary") if isinstance(task.get("field_match_summary"), Mapping) else {}
    authorization_state = _first_text(
        task.get("authorization_readiness_state"),
        field_summary.get("authorization_readiness_state") if isinstance(field_summary, Mapping) else "",
        field_match_summary.get("authorization_readiness_state") if isinstance(field_match_summary, Mapping) else "",
    )
    source_profile_id = str(task.get("source_profile_id") or "")
    task_id = str(task.get("field_query_task_id") or task.get("release_evidence_adapter_task_id") or "")
    blocker_state, runtime_layer = _field_query_blocker_state_and_layer(
        adapter_state=adapter_state,
        downstream_grade=downstream_grade,
        authorization_state=authorization_state,
    )
    operator_next_action = _first_text(
        *_list(field_summary.get("operator_next_actions") if isinstance(field_summary, Mapping) else []),
        _field_query_default_operator_next_action(blocker_state),
    )
    return {
        "blocker_ledger_id": _stable_id(
            "RUNTIME-BLOCKER",
            "stage4_release_evidence_query",
            task.get("project_id"),
            task_id,
            adapter_state,
            authorization_state,
            downstream_grade,
        ),
        "ledger_scope": "stage4_release_evidence_query",
        "project_id": str(task.get("project_id") or ""),
        "project_name": str(task.get("project_name") or ""),
        "task_id": task_id,
        "task_scope": "release_evidence_query",
        "task_type": _first_text(task.get("release_evidence_target_type"), source_profile_id, "release_field_query"),
        "blocker_state": blocker_state,
        "blocker_reason": _field_query_blocker_reason(
            adapter_state=adapter_state,
            downstream_grade=downstream_grade,
            authorization_state=authorization_state,
        ),
        "runtime_layer": runtime_layer,
        "required_input": _field_query_required_input(blocker_state),
        "retry_policy": _field_query_retry_policy(blocker_state),
        "reopen_conditions": _field_query_reopen_conditions(blocker_state),
        "operator_next_action": operator_next_action,
        "next_action": operator_next_action,
        "artifact_ref": result_path,
        "source_profile_id": source_profile_id,
        "authorization_readiness_state": authorization_state,
        "adapter_result_state": adapter_state,
        "downstream_release_evidence_abcd_grade": downstream_grade,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _field_query_blocker_state_and_layer(
    *,
    adapter_state: str,
    downstream_grade: str,
    authorization_state: str,
) -> tuple[str, str]:
    if authorization_state == "LOGIN_OR_SSO_REQUIRED":
        return "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION", "browser worker"
    if adapter_state == "NEEDS_BROWSER":
        return "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED", "browser worker"
    if adapter_state == "BLOCKED":
        return "SOURCE_BLOCKED_RETRY_OR_FALLBACK_REQUIRED", "source adapter"
    if adapter_state == "NOT_FOUND":
        return "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED", "source adapter"
    if downstream_grade.startswith("D_"):
        return "RELEASE_FIELD_QUERY_GAP_REVIEW", "closeout"
    return "RELEASE_FIELD_QUERY_REVIEW_REQUIRED", "closeout"


def _field_query_blocker_reason(*, adapter_state: str, downstream_grade: str, authorization_state: str) -> str:
    if authorization_state == "LOGIN_OR_SSO_REQUIRED":
        return "login_or_sso_required_for_release_field_query"
    if adapter_state == "NEEDS_BROWSER":
        return "browser_or_same_session_required_for_release_field_query"
    if adapter_state == "BLOCKED":
        return "release_field_query_source_blocked"
    if adapter_state == "NOT_FOUND":
        return "release_field_query_not_found_not_clearance"
    if downstream_grade.startswith("D_"):
        return "release_field_query_d_grade_gap_or_blocker"
    return "release_field_query_requires_review"


def _field_query_default_operator_next_action(blocker_state: str) -> str:
    if blocker_state == "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION":
        return "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"
    if blocker_state == "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED":
        return "route_to_browser_worker_or_same_session_retry"
    if blocker_state == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return "record_not_found_without_clearance_claim_or_try_project_local_authority"
    if blocker_state == "SOURCE_BLOCKED_RETRY_OR_FALLBACK_REQUIRED":
        return "retry_after_blocker_resolved_or_route_fallback_source"
    return "record_release_evidence_gap_or_retry_jurisdiction_source_without_clearance_claim"


def _field_query_required_input(blocker_state: str) -> list[str]:
    if blocker_state == "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION":
        return ["authorized_browser_storage_state_or_user_data_dir"]
    if blocker_state == "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED":
        return ["browser_worker_session_or_same_session_retry_budget"]
    if blocker_state == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return ["fallback_source_or_project_local_authority_path"]
    if blocker_state == "SOURCE_BLOCKED_RETRY_OR_FALLBACK_REQUIRED":
        return ["resolved_source_blocker_or_fallback_source"]
    return ["operator_review_scope_or_new_release_evidence_source"]


def _field_query_retry_policy(blocker_state: str) -> str:
    if blocker_state == "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION":
        return "retry_only_after_authorized_session_available"
    if blocker_state == "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED":
        return "retry_with_browser_worker_or_same_session_budget"
    if blocker_state == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return "retry_only_with_fallback_source_or_more_precise_identifiers"
    if blocker_state == "SOURCE_BLOCKED_RETRY_OR_FALLBACK_REQUIRED":
        return "retry_after_source_blocker_resolved_or_fallback_source_selected"
    return "manual_reopen_requires_new_source_or_operator_scope"


def _field_query_reopen_conditions(blocker_state: str) -> list[str]:
    if blocker_state == "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION":
        return ["authorized_browser_storage_state_available", "operator_approves_same_session_retry"]
    if blocker_state == "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED":
        return ["browser_worker_available", "same_session_retry_budget_available"]
    if blocker_state == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return ["fallback_public_source_available", "more_precise_project_identifier_available"]
    if blocker_state == "SOURCE_BLOCKED_RETRY_OR_FALLBACK_REQUIRED":
        return ["source_blocker_resolved", "fallback_source_available"]
    return ["new_machine_readable_input_artifact_available", "operator_override_records_scope_budget_and_reason"]


def _field_query_source_hit_summaries(tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        field_summary = task.get("field_summary") if isinstance(task.get("field_summary"), Mapping) else {}
        field_match_summary = (
            task.get("field_match_summary") if isinstance(task.get("field_match_summary"), Mapping) else {}
        )
        adapter_id = _first_text(
            task.get("source_specific_adapter_id"),
            field_summary.get("source_specific_adapter_id") if isinstance(field_summary, Mapping) else "",
            field_match_summary.get("source_specific_adapter_id") if isinstance(field_match_summary, Mapping) else "",
        )
        source_profile_id = _first_text(
            task.get("source_profile_id"),
            field_summary.get("source_profile_id") if isinstance(field_summary, Mapping) else "",
            field_match_summary.get("source_profile_id") if isinstance(field_match_summary, Mapping) else "",
        )
        is_openplatform_source = _is_gdcic_openplatform_source(adapter_id=adapter_id, source_profile_id=source_profile_id)
        is_browser_authorized_source = _is_gdcic_browser_authorized_source(
            adapter_id=adapter_id,
            source_profile_id=source_profile_id,
        )
        if not is_openplatform_source and not is_browser_authorized_source:
            continue
        adapter_state = str(task.get("adapter_result_state") or "").strip()
        field_state = _first_text(
            task.get("field_query_probe_state"),
            field_summary.get("gdcic_query_probe_state") if isinstance(field_summary, Mapping) else "",
            field_summary.get("field_query_probe_state") if isinstance(field_summary, Mapping) else "",
        )
        if adapter_state != "MATCHED" and field_state != "FIELD_READBACK_READY_PUBLIC_SOURCE":
            continue
        source_specific_records = [
            record
            for record in _list(field_match_summary.get("source_specific_records"))
            if isinstance(record, Mapping)
        ]
        specific_person_names = (
            _gdcic_openplatform_specific_person_names(source_specific_records)
            if is_openplatform_source
            else _gdcic_browser_authorized_specific_person_names(source_specific_records)
        )
        specific_certificate_nos = (
            _gdcic_openplatform_specific_certificate_nos(source_specific_records)
            if is_openplatform_source
            else []
        )
        specific_permit_codes = (
            _gdcic_openplatform_specific_permit_codes(source_specific_records)
            if is_openplatform_source
            else []
        )
        original_project_managers = _gdcic_browser_authorized_original_project_managers(source_specific_records)
        new_project_managers = _gdcic_browser_authorized_new_project_managers(source_specific_records)
        change_dates = _gdcic_browser_authorized_change_dates(source_specific_records)
        change_interpretations = _gdcic_browser_authorized_change_interpretations(source_specific_records)
        person_names = _dedupe(specific_person_names) or _dedupe(
            [
                *_list(field_summary.get("sample_person_names") if isinstance(field_summary, Mapping) else []),
                *_list(field_match_summary.get("matched_person_names") if isinstance(field_match_summary, Mapping) else []),
                *_list(task.get("matched_person_names")),
            ]
        )
        certificate_nos = _dedupe(
            [
                *specific_certificate_nos,
                *_list(field_summary.get("sample_certificate_nos") if isinstance(field_summary, Mapping) else []),
                *_list(field_match_summary.get("sample_certificate_nos") if isinstance(field_match_summary, Mapping) else []),
            ]
        )
        project_codes = _field_query_project_codes(task, source_specific_records)
        permit_codes = _dedupe(
            [
                *specific_permit_codes,
                *_list(field_summary.get("sample_permit_codes") if isinstance(field_summary, Mapping) else []),
                *_list(field_match_summary.get("sample_permit_codes") if isinstance(field_match_summary, Mapping) else []),
            ]
        )
        ready_count = _int(
            field_summary.get("gdcic_publicity_period_readback_ready_count")
            if isinstance(field_summary, Mapping)
            else 0
        )
        key = "|".join(
            [
                source_profile_id,
                adapter_id,
                ",".join(person_names),
                ",".join(project_codes),
                ",".join(certificate_nos),
                ",".join(permit_codes),
                ",".join(original_project_managers),
                ",".join(new_project_managers),
                ",".join(change_dates),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        summaries.append(
            {
                "source_profile_id": source_profile_id or (
                    "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM" if is_openplatform_source else "GUANGDONG-GDCIC-HOME"
                ),
                "source_specific_adapter_id": adapter_id or (
                    "guangdong_gdcic_openplatform_public_api_query_v1"
                    if is_openplatform_source
                    else "guangdong_gdcic_browser_authorized_readback_v1"
                ),
                "source_label": (
                    "广东建设信息网三库一平台匿名公开源"
                    if is_openplatform_source
                    else "广东建设信息网三库一平台授权浏览器读回"
                ),
                "match_state": (
                    "MATCHED_PUBLIC_READBACK"
                    if is_openplatform_source
                    else "MATCHED_BROWSER_AUTHORIZED_READBACK"
                ),
                "match_label": (
                    "GDCIC 匿名公开源命中：公开记录可读回，目标字段仍需按记录类型复核"
                    if is_openplatform_source
                    else "GDCIC 授权浏览器读回命中：项目经理变更字段需人工复核窗口解释"
                ),
                "matched_person_names": person_names[:5],
                "sample_person_names": person_names[:5],
                "sample_project_codes": project_codes[:5],
                "sample_certificate_nos": certificate_nos[:5],
                "sample_permit_codes": permit_codes[:5],
                "original_project_manager_names": original_project_managers[:5],
                "new_project_manager_names": new_project_managers[:5],
                "project_manager_change_dates": change_dates[:5],
                "project_manager_change_interpretations": change_interpretations[:5],
                "gdcic_publicity_period_readback_ready_count": ready_count,
                "pii_redaction_state": "ID_CARD_HASH_OR_REDACTED_ONLY",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return summaries


def _field_query_project_codes(task: Mapping[str, Any], source_specific_records: list[Mapping[str, Any]]) -> list[str]:
    query_params = task.get("query_params") if isinstance(task.get("query_params"), Mapping) else {}
    values: list[Any] = [
        query_params.get("projectCode"),
        query_params.get("sourceProjectCode"),
        query_params.get("tradeProjectCode"),
        query_params.get("projectId"),
        *_list(query_params.get("projectCodeVariants")),
        *_list(query_params.get("gdcicProjectCodeVariants")),
        *_list(query_params.get("projectCodes")),
    ]
    for record in source_specific_records:
        values.extend(
            [
                record.get("projectCode"),
                record.get("project_code"),
                record.get("sourceProjectCode"),
                record.get("tradeProjectCode"),
            ]
        )
    return _dedupe(str(value).strip() for value in values if str(value or "").strip())


def _gdcic_openplatform_specific_person_names(records: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        _first_text(record.get("name"), record.get("memberName"), record.get("personName"))
        for record in records
        if _is_gdcic_openplatform_specific_record(record)
    )


def _gdcic_browser_authorized_specific_person_names(records: list[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        if not _is_gdcic_browser_authorized_specific_record(record):
            continue
        values.extend(
            [
                _first_text(record.get("project_manager_name_probe"), record.get("project_manager_name")),
                _first_text(record.get("original_project_manager_name_probe"), record.get("original_project_manager_name")),
                _first_text(record.get("new_project_manager_name_probe"), record.get("new_project_manager_name")),
            ]
        )
    return _dedupe(values)


def _gdcic_browser_authorized_original_project_managers(records: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        _first_text(record.get("original_project_manager_name_probe"), record.get("original_project_manager_name"))
        for record in records
        if _is_gdcic_browser_authorized_specific_record(record)
    )


def _gdcic_browser_authorized_new_project_managers(records: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        _first_text(record.get("new_project_manager_name_probe"), record.get("new_project_manager_name"))
        for record in records
        if _is_gdcic_browser_authorized_specific_record(record)
    )


def _gdcic_browser_authorized_change_dates(records: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        _first_text(record.get("change_date_probe"), record.get("change_date"))
        for record in records
        if _is_gdcic_browser_authorized_specific_record(record)
    )


def _gdcic_browser_authorized_change_interpretations(records: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        str(record.get("project_manager_change_release_window_interpretation") or "")
        for record in records
        if _is_gdcic_browser_authorized_specific_record(record)
    )


def _gdcic_openplatform_specific_certificate_nos(records: list[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        if not _is_gdcic_openplatform_specific_record(record):
            continue
        values.extend(
            [
                _first_text(record.get("regCertNum"), record.get("certNum"), record.get("certNo"), record.get("certificateNo")),
            ]
        )
    return _dedupe(values)


def _gdcic_openplatform_specific_permit_codes(records: list[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        if not _is_gdcic_openplatform_specific_record(record):
            continue
        values.extend(
            [
                _first_text(record.get("permitCode"), record.get("certNum"), record.get("施工许可证号")),
            ]
        )
    return _dedupe(values)


def _is_gdcic_openplatform_specific_record(record: Mapping[str, Any]) -> bool:
    route_id = str(record.get("route_id") or "")
    record_type = str(record.get("record_type") or "")
    return route_id.startswith("publicity_period_") or record_type in {
        "personnel_public_record",
        "construction_permit_public_record",
    }


def _is_gdcic_browser_authorized_specific_record(record: Mapping[str, Any]) -> bool:
    adapter_id = str(record.get("source_specific_adapter_id") or "")
    source_profile_id = str(record.get("source_profile_id") or "")
    record_type = str(record.get("record_type") or "")
    return (
        adapter_id == "guangdong_gdcic_browser_authorized_readback_v1"
        or source_profile_id == "GUANGDONG-GDCIC-HOME"
        or record_type == "project_manager_change_browser_authorized_record"
    )


def _is_gdcic_openplatform_source(*, adapter_id: str, source_profile_id: str) -> bool:
    return adapter_id == "guangdong_gdcic_openplatform_public_api_query_v1" or (
        source_profile_id == "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"
    )


def _is_gdcic_browser_authorized_source(*, adapter_id: str, source_profile_id: str) -> bool:
    return adapter_id == "guangdong_gdcic_browser_authorized_readback_v1" or (
        source_profile_id == "GUANGDONG-GDCIC-HOME"
    )


def _field_query_source_hit_summary_labels(source_hit_summaries: list[Mapping[str, Any]]) -> list[str]:
    labels: list[str] = []
    for summary in source_hit_summaries:
        parts = [str(summary.get("source_label") or "公开源")]
        person_names = _list(summary.get("matched_person_names"))
        project_codes = _list(summary.get("sample_project_codes"))
        certificate_nos = _list(summary.get("sample_certificate_nos"))
        permit_codes = _list(summary.get("sample_permit_codes"))
        original_project_managers = _list(summary.get("original_project_manager_names"))
        new_project_managers = _list(summary.get("new_project_manager_names"))
        change_dates = _list(summary.get("project_manager_change_dates"))
        change_interpretations = _list(summary.get("project_manager_change_interpretations"))
        if person_names and not (original_project_managers or new_project_managers):
            parts.append("样例人员：" + "、".join(str(name) for name in person_names[:3] if str(name or "").strip()))
        if project_codes:
            parts.append("项目编码：" + "、".join(str(code) for code in project_codes[:3] if str(code or "").strip()))
        if certificate_nos:
            parts.append("证书：" + "、".join(str(no) for no in certificate_nos[:3] if str(no or "").strip()))
        if permit_codes:
            parts.append("施工许可：" + "、".join(str(code) for code in permit_codes[:3] if str(code or "").strip()))
        if original_project_managers:
            parts.append(
                "原项目经理："
                + "、".join(str(name) for name in original_project_managers[:3] if str(name or "").strip())
            )
        if new_project_managers:
            parts.append(
                "新项目经理："
                + "、".join(str(name) for name in new_project_managers[:3] if str(name or "").strip())
            )
        if change_dates:
            parts.append("变更日期：" + "、".join(str(date) for date in change_dates[:3] if str(date or "").strip()))
        if change_interpretations:
            parts.append(
                "窗口解释："
                + "、".join(str(item) for item in change_interpretations[:3] if str(item or "").strip())
            )
        labels.append("；".join(part for part in parts if part))
    return _dedupe(labels)


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
        fallback_states.append(task.get("authorization_readiness_state"))
        if isinstance(field_summary, Mapping):
            fallback_states.append(field_summary.get("authorization_readiness_state"))
    return merged or _counts(fallback_states)


def _field_query_authorized_session_input_state_counts(tasks: list[Mapping[str, Any]]) -> dict[str, int]:
    return _counts(
        (task.get("field_summary") if isinstance(task.get("field_summary"), Mapping) else {}).get(
            "authorized_session_input_state"
        )
        for task in tasks
    )


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
    if int(adapter_counts.get("MATCHED") or 0):
        return "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY"
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


def _owner_assignment_fields_from_sources(*sources: Mapping[str, Any]) -> dict[str, str]:
    return {
        "assigned_owner": _first_text(*(source.get("assigned_owner") for source in sources if isinstance(source, Mapping))),
        "assigned_owner_role": _first_text(
            *(source.get("assigned_owner_role") for source in sources if isinstance(source, Mapping))
        ),
        "reviewer": _first_text(*(source.get("reviewer") for source in sources if isinstance(source, Mapping))),
        "reviewer_role": _first_text(*(source.get("reviewer_role") for source in sources if isinstance(source, Mapping))),
        "owner_assignment_source_ref": _first_text(
            *(source.get("owner_assignment_source_ref") for source in sources if isinstance(source, Mapping))
        ),
    }


def _table_records(result: Mapping[str, Any], table_name: str) -> list[Mapping[str, Any]]:
    manifest = result.get("manifest") if isinstance(result, Mapping) else {}
    table = manifest.get(table_name) if isinstance(manifest, Mapping) else {}
    return [record for record in _list(table.get("records") if isinstance(table, Mapping) else []) if isinstance(record, Mapping)]


def _next_cycle_dispatch_records_by_project(next_cycle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return _next_cycle_records_by_project(next_cycle, "dispatch_task_table")


def _next_cycle_manual_only_records_by_project(next_cycle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return _next_cycle_records_by_project(next_cycle, "manual_only_action_plan_table")


def _runtime_blocker_worker_followup_records_by_project(next_cycle: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    manifest = next_cycle.get("manifest") if isinstance(next_cycle, Mapping) else {}
    queue = manifest.get("runtime_blocker_worker_followup_queue") if isinstance(manifest, Mapping) else {}
    records = _list(queue.get("records") if isinstance(queue, Mapping) else [])
    out: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out.setdefault(project_id, []).append(dict(record))
    return out


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


def _runtime_blocker_ledger_records_from_sources(
    *sources: Mapping[str, Any],
    closeout_precedence: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        direct = source.get("runtime_blocker_ledger_record")
        if isinstance(direct, Mapping) and direct:
            rows.append(dict(direct))
        for record in _list(source.get("runtime_blocker_ledger_records")):
            if isinstance(record, Mapping) and record:
                rows.append(dict(record))
    if _is_release_evidence_projection_only_terminal(closeout_precedence):
        rows = [row for row in rows if not _is_release_evidence_projection_only_blocker(row)]
    elif _is_original_readback_projection_only_terminal(closeout_precedence):
        rows = [row for row in rows if not _is_original_readback_projection_only_blocker(row)]
    elif isinstance(closeout_precedence, Mapping) and closeout_precedence.get("should_suppress_dispatch"):
        rows.append(_closeout_precedence_blocker_ledger(closeout_precedence, sources=sources))
    return _dedupe_ledger_records(rows)


def _closeout_precedence_blocker_ledger(
    closeout_precedence: Mapping[str, Any],
    *,
    sources: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    terminal_marker = (
        closeout_precedence.get("terminal_marker")
        if isinstance(closeout_precedence.get("terminal_marker"), Mapping)
        else {}
    )
    project_id = _first_text(*(source.get("project_id") for source in sources if isinstance(source, Mapping)))
    project_name = _first_text(*(source.get("project_name") for source in sources if isinstance(source, Mapping)))
    task_id = _first_text(
        terminal_marker.get("task_id") if isinstance(terminal_marker, Mapping) else "",
        *(source.get("review_action_plan_id") for source in sources if isinstance(source, Mapping)),
        *(source.get("dispatch_task_id") for source in sources if isinstance(source, Mapping)),
        project_id,
    )
    reason = str(closeout_precedence.get("suppression_reason") or "terminal_closeout_marker_present")
    subqueue_routes = _closeout_precedence_subqueue_routes(closeout_precedence)
    return {
        "blocker_ledger_id": _stable_id("RUNTIME-BLOCKER", "stage6_review_loop", project_id, task_id, reason),
        "ledger_scope": "stage6_review_loop",
        "project_id": project_id,
        "project_name": project_name,
        "task_id": task_id,
        "task_scope": str(closeout_precedence.get("task_scope") or ""),
        "task_type": str(closeout_precedence.get("task_type") or ""),
        "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
        "blocker_reason": reason,
        "runtime_layer": str(closeout_precedence.get("runtime_layer") or "controller decision"),
        "required_input": list(closeout_precedence.get("required_input") or []),
        "retry_policy": str(closeout_precedence.get("retry_policy") or ""),
        "reopen_conditions": list(closeout_precedence.get("reopen_conditions") or []),
        "operator_next_action": str(closeout_precedence.get("operator_next_action") or ""),
        "next_action": str(closeout_precedence.get("next_action") or ""),
        "terminal_marker": dict(terminal_marker),
        "subqueue_routes": subqueue_routes,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _closeout_precedence_subqueue_routes(closeout_precedence: Mapping[str, Any]) -> list[str]:
    explicit = _dedupe(_list(closeout_precedence.get("subqueue_routes")))
    if explicit:
        return explicit
    terminal_marker = (
        closeout_precedence.get("terminal_marker")
        if isinstance(closeout_precedence.get("terminal_marker"), Mapping)
        else {}
    )
    task_scope = str(closeout_precedence.get("task_scope") or "")
    terminal_state = str(
        terminal_marker.get("terminal_state") or terminal_marker.get("terminal_grade") or ""
    ).strip()
    if task_scope == "release_evidence_query" and (
        terminal_state in {
            "MATCHED",
            "REVIEW_READY",
            "RELEASE_FIELD_QUERY_REVIEW_READY",
            "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
        }
        or terminal_state.startswith(("B_", "C_"))
    ):
        return ["manual_hold", "operator_action"]
    return []


def _is_release_evidence_projection_only_terminal(closeout_precedence: Mapping[str, Any] | None) -> bool:
    if not isinstance(closeout_precedence, Mapping):
        return False
    task_scope = str(closeout_precedence.get("task_scope") or "")
    terminal_marker = (
        closeout_precedence.get("terminal_marker")
        if isinstance(closeout_precedence.get("terminal_marker"), Mapping)
        else {}
    )
    terminal_state = str(
        terminal_marker.get("terminal_state") or terminal_marker.get("terminal_grade") or ""
    ).strip()
    return bool(
        task_scope == "release_evidence_query"
        and (
            terminal_state in {
                "MATCHED",
                "REVIEW_READY",
                "RELEASE_FIELD_QUERY_REVIEW_READY",
                "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
            }
            or terminal_state.startswith(("B_", "C_"))
        )
    )


def _is_release_evidence_projection_only_blocker(record: Mapping[str, Any]) -> bool:
    task_scope = str(record.get("task_scope") or "")
    blocker_state = str(record.get("blocker_state") or "")
    terminal_marker = record.get("terminal_marker") if isinstance(record.get("terminal_marker"), Mapping) else {}
    terminal_state = str(
        terminal_marker.get("terminal_state") or terminal_marker.get("terminal_grade") or ""
    ).strip()
    return bool(
        task_scope == "release_evidence_query"
        and blocker_state == "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH"
        and (
            terminal_state in {
                "MATCHED",
                "REVIEW_READY",
                "RELEASE_FIELD_QUERY_REVIEW_READY",
                "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
            }
            or terminal_state.startswith(("B_", "C_"))
        )
    )


def _is_original_readback_projection_only_terminal(closeout_precedence: Mapping[str, Any] | None) -> bool:
    if not isinstance(closeout_precedence, Mapping):
        return False
    task_scope = str(closeout_precedence.get("task_scope") or "")
    terminal_marker = (
        closeout_precedence.get("terminal_marker")
        if isinstance(closeout_precedence.get("terminal_marker"), Mapping)
        else {}
    )
    terminal_state = str(
        terminal_marker.get("terminal_state") or terminal_marker.get("marker_state") or ""
    ).strip()
    return bool(
        task_scope == "original_readback"
        and is_original_readback_projection_only_terminal_state(terminal_state)
    )


def _is_original_readback_projection_only_blocker(record: Mapping[str, Any]) -> bool:
    task_scope = str(record.get("task_scope") or "")
    blocker_state = str(record.get("blocker_state") or "")
    terminal_marker = record.get("terminal_marker") if isinstance(record.get("terminal_marker"), Mapping) else {}
    terminal_state = str(
        terminal_marker.get("terminal_state") or terminal_marker.get("marker_state") or ""
    ).strip()
    return bool(
        task_scope == "original_readback"
        and blocker_state == "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH"
        and is_original_readback_projection_only_terminal_state(terminal_state)
    )


def _dedupe_ledger_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for record in records:
        if not isinstance(record, Mapping) or not record:
            continue
        copied = dict(record)
        key = _ledger_semantic_key(copied)
        if key in seen:
            out[seen[key]] = _merge_ledger_duplicate(out[seen[key]], copied)
            continue
        seen[key] = len(out)
        copied = _with_ledger_sources(copied)
        out.append(copied)
    return out


def _ledger_semantic_key(record: Mapping[str, Any]) -> str:
    terminal_marker = record.get("terminal_marker") if isinstance(record.get("terminal_marker"), Mapping) else {}
    if str(record.get("blocker_state") or "") == "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH":
        marker_state = _first_text(
            terminal_marker.get("terminal_state") if isinstance(terminal_marker, Mapping) else "",
            terminal_marker.get("marker_state") if isinstance(terminal_marker, Mapping) else "",
            terminal_marker.get("terminal_grade") if isinstance(terminal_marker, Mapping) else "",
        )
        marker_artifact = str(terminal_marker.get("artifact_ref") or terminal_marker.get("source_json") or "")
        return "|".join(
            [
                "terminal_closeout",
                str(record.get("project_id") or ""),
                str(record.get("task_scope") or ""),
                marker_state,
                marker_artifact,
            ]
        )
    return str(record.get("blocker_ledger_id") or "").strip() or _fingerprint(record)


def _with_ledger_sources(record: Mapping[str, Any]) -> dict[str, Any]:
    copied = dict(record)
    scope = str(copied.get("ledger_scope") or "").strip()
    ledger_id = str(copied.get("blocker_ledger_id") or "").strip()
    runtime_layer = str(copied.get("runtime_layer") or "").strip()
    blocker_reason = str(copied.get("blocker_reason") or "").strip()
    copied["source_ledger_scopes"] = _dedupe([*_list(copied.get("source_ledger_scopes")), scope])
    copied["source_blocker_ledger_ids"] = _dedupe([*_list(copied.get("source_blocker_ledger_ids")), ledger_id])
    copied["source_runtime_layers"] = _dedupe([*_list(copied.get("source_runtime_layers")), runtime_layer])
    copied["source_blocker_reasons"] = _dedupe([*_list(copied.get("source_blocker_reasons")), blocker_reason])
    return copied


def _merge_ledger_duplicate(current: Mapping[str, Any], duplicate: Mapping[str, Any]) -> dict[str, Any]:
    merged = _with_ledger_sources(current)
    duplicate_sources = _with_ledger_sources(duplicate)
    merged["source_ledger_scopes"] = _dedupe(
        [*_list(merged.get("source_ledger_scopes")), *_list(duplicate_sources.get("source_ledger_scopes"))]
    )
    merged["source_blocker_ledger_ids"] = _dedupe(
        [*_list(merged.get("source_blocker_ledger_ids")), *_list(duplicate_sources.get("source_blocker_ledger_ids"))]
    )
    merged["source_runtime_layers"] = _dedupe(
        [*_list(merged.get("source_runtime_layers")), *_list(duplicate_sources.get("source_runtime_layers"))]
    )
    merged["source_blocker_reasons"] = _dedupe(
        [*_list(merged.get("source_blocker_reasons")), *_list(duplicate_sources.get("source_blocker_reasons"))]
    )
    merged["required_input"] = _dedupe([*_list(merged.get("required_input")), *_list(duplicate_sources.get("required_input"))])
    merged["reopen_conditions"] = _dedupe(
        [*_list(merged.get("reopen_conditions")), *_list(duplicate_sources.get("reopen_conditions"))]
    )
    merged["subqueue_routes"] = _dedupe(
        [*_list(merged.get("subqueue_routes")), *_list(duplicate_sources.get("subqueue_routes"))]
    )
    for key in ("artifact_ref", "retry_policy", "operator_next_action", "next_action"):
        if not str(merged.get(key) or "").strip() and str(duplicate_sources.get(key) or "").strip():
            merged[key] = duplicate_sources.get(key)
    return merged


def _ledger_scope_values(record: Mapping[str, Any]) -> list[str]:
    scopes = _list(record.get("source_ledger_scopes"))
    if scopes:
        return [str(scope) for scope in scopes if str(scope or "").strip()]
    return [str(record.get("ledger_scope") or "")] if str(record.get("ledger_scope") or "").strip() else []


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


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
    runtime_blocker_worker_followup_records: list[Mapping[str, Any]],
    release_field_query_result: Mapping[str, Any],
) -> str:
    if str(next_dispatch_record.get("dispatch_readiness_state") or "").strip():
        return "NEXT_CYCLE_DISPATCH_READY"
    if runtime_blocker_worker_followup_records:
        return "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY"
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
    if routing_state == "SUPPRESSED_BY_TERMINAL_CLOSEOUT_PRECEDENCE":
        return "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH"
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
    runtime_blocker_worker_followup_records: list[Mapping[str, Any]],
    release_field_query_result: Mapping[str, Any],
) -> str:
    if str(next_dispatch_record.get("dispatch_readiness_state") or "").strip():
        return "run_next_cycle_dispatch_or_keep_internal_review_dry_run"
    if runtime_blocker_worker_followup_records:
        return _first_text(
            *(record.get("next_action") for record in runtime_blocker_worker_followup_records if isinstance(record, Mapping)),
            "run_guangdong_local_field_query_probe_then_stage6_review_loop_backfill",
        )
    if str(next_manual_record.get("dispatch_block_reason") or "").strip():
        closeout_precedence = (
            next_manual_record.get("closeout_precedence")
            if isinstance(next_manual_record.get("closeout_precedence"), Mapping)
            else {}
        )
        return str(
            next_manual_record.get("operator_next_action")
            or closeout_precedence.get("operator_next_action")
            or closeout_precedence.get("next_action")
            or "manual_review_or_new_source_override_required_before_retry"
        )
    release_state = str(release_field_query_result.get("release_field_query_state") or "").strip()
    if release_state == "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY":
        return "manual_review_public_field_readback_before_stage7_preview"
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
        "release_field_query_authorized_session_input_state_counts": _merge_count_maps(
            record.get("release_field_query_authorized_session_input_state_counts")
            for record in project_status_records
        ),
        "release_field_query_authorization_state_counts": _merge_count_maps(
            record.get("release_field_query_authorization_state_counts") for record in project_status_records
        ),
        "release_field_query_operator_next_action_counts": _counts(
            action
            for record in project_status_records
            for action in _list(record.get("release_field_query_operator_next_actions"))
        ),
        "release_field_query_project_manager_change_ready_count": sum(
            1
            for record in project_status_records
            for summary in _list(record.get("release_field_query_source_hit_summaries"))
            if isinstance(summary, Mapping)
            and _list(summary.get("project_manager_change_interpretations"))
        ),
        "release_field_query_project_manager_change_interpretation_counts": _counts(
            interpretation
            for record in project_status_records
            for summary in _list(record.get("release_field_query_source_hit_summaries"))
            if isinstance(summary, Mapping)
            for interpretation in _list(summary.get("project_manager_change_interpretations"))
        ),
        "stage5_calibration_sample_count": sum(
            1 for record in project_status_records if str(record.get("stage5_calibration_review_bucket") or "").strip()
        ),
        "stage5_calibration_truth_label_required_count": sum(
            1 for record in project_status_records if bool(record.get("calibration_truth_label_required"))
        ),
        "stage5_calibration_review_bucket_counts": _counts(
            record.get("stage5_calibration_review_bucket") for record in project_status_records
        ),
        "stage5_abcd_calibration_counts": _counts(
            record.get("stage5_abcd_calibration_bucket") for record in project_status_records
        ),
        "stage5_calibration_evidence_strength_counts": _counts(
            record.get("stage5_calibration_evidence_strength") for record in project_status_records
        ),
        "stage5_calibration_review_family_counts": _counts(
            record.get("stage5_calibration_review_family") for record in project_status_records
        ),
        "stage5_calibration_suggested_action_counts": _counts(
            record.get("suggested_calibration_action") for record in project_status_records
        ),
        "limited_sellable_review_candidate_count": sum(
            1
            for record in project_status_records
            if record.get("limited_sellable_review_candidate_state") == "REVIEW_CANDIDATE"
        ),
        "limited_sellable_review_official_readback_task_count": sum(
            int(record.get("limited_sellable_review_official_readback_task_count") or 0)
            for record in project_status_records
        ),
        "limited_sellable_review_required_action_counts": _counts(
            action
            for record in project_status_records
            for action in _list(record.get("limited_sellable_review_required_actions"))
        ),
        "limited_sellable_review_evidence_grade_counts": _merge_count_maps(
            record.get("limited_sellable_review_evidence_grade_counts") for record in project_status_records
        ),
        "limited_sellable_review_gap_grade_counts": _merge_count_maps(
            record.get("limited_sellable_review_gap_grade_counts") for record in project_status_records
        ),
        "limited_sellable_review_public_source_chain_counts": _merge_count_maps(
            record.get("limited_sellable_review_public_source_chain_counts") for record in project_status_records
        ),
        "limited_sellable_review_stage4_bridge_backfill_state_counts": _merge_count_maps(
            record.get("limited_sellable_review_stage4_bridge_backfill_state_counts")
            for record in project_status_records
        ),
        "limited_sellable_review_gdcic_project_code_route_policy_counts": _merge_count_maps(
            record.get("limited_sellable_review_gdcic_project_code_route_policy_counts")
            for record in project_status_records
        ),
        "limited_sellable_review_candidate_state_counts": _counts(
            record.get("limited_sellable_review_candidate_state") for record in project_status_records
        ),
        "strong_lead_candidate_state_counts": _counts(
            record.get("strong_lead_candidate_state") for record in project_status_records
        ),
        "commercialization_boundary_state_counts": _counts(
            record.get("commercialization_boundary_state") for record in project_status_records
        ),
        "runtime_blocker_ledger_count": sum(
            len(_list(record.get("runtime_blocker_ledger_records"))) for record in project_status_records
        ),
        "runtime_blocker_ledger_state_counts": _counts(
            item.get("blocker_state")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_ledger_layer_counts": _counts(
            item.get("runtime_layer")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_ledger_scope_counts": _counts(
            scope
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
            for scope in _ledger_scope_values(item)
        ),
        "runtime_blocker_ledger_required_input_counts": _counts(
            required_input
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
            for required_input in _list(item.get("required_input"))
        ),
        "runtime_blocker_ledger_retry_policy_counts": _counts(
            item.get("retry_policy")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_ledger_operator_next_action_counts": _counts(
            item.get("operator_next_action") or item.get("next_action")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_ledger_reopen_condition_counts": _counts(
            condition
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_ledger_records"))
            if isinstance(item, Mapping)
            for condition in _list(item.get("reopen_conditions"))
        ),
        "runtime_blocker_subqueue_counts": _counts(
            route
            for record in project_status_records
            for route in _runtime_blocker_subqueue_routes(
                [
                    item
                    for item in _list(record.get("runtime_blocker_ledger_records"))
                    if isinstance(item, Mapping)
                ]
            )
        ),
        "runtime_blocker_worker_followup_count": sum(
            len(_list(record.get("runtime_blocker_worker_followup_records"))) for record in project_status_records
        ),
        "runtime_blocker_worker_followup_project_count": sum(
            1 for record in project_status_records if _list(record.get("runtime_blocker_worker_followup_records"))
        ),
        "runtime_blocker_worker_followup_entrypoint_counts": _counts(
            item.get("formal_entrypoint_id")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_worker_followup_task_type_counts": _counts(
            item.get("followup_task_type")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_worker_followup_readiness_state_counts": _counts(
            item.get("followup_readiness_state")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "runtime_blocker_worker_followup_next_action_counts": _counts(
            item.get("next_action")
            for record in project_status_records
            for item in _list(record.get("runtime_blocker_worker_followup_records"))
            if isinstance(item, Mapping)
        ),
        "owner_assignment_state_counts": _counts(
            _owner_assignment_state_from_status_record(record) for record in project_status_records
        ),
        "assigned_owner_counts": _counts(record.get("assigned_owner") for record in project_status_records),
        "owner_assignment_source_ref_counts": _counts(
            record.get("owner_assignment_source_ref") for record in project_status_records
        ),
        "unassigned_owner_count": sum(
            1
            for record in project_status_records
            if _owner_assignment_state_from_status_record(record) == "UNASSIGNED_OWNER_REVIEW_REQUIRED"
        ),
        "owner_assignment_next_action_counts": _counts(
            _owner_assignment_next_action_from_status_record(record) for record in project_status_records
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


def _owner_assignment_state_from_status_record(record: Mapping[str, Any]) -> str:
    return "ASSIGNED_OWNER_READY" if str(record.get("assigned_owner") or "").strip() else "UNASSIGNED_OWNER_REVIEW_REQUIRED"


def _owner_assignment_next_action_from_status_record(record: Mapping[str, Any]) -> str:
    if _owner_assignment_state_from_status_record(record) == "ASSIGNED_OWNER_READY":
        return "owner_reviews_project_status_and_records_decision"
    return "assign_project_owner_before_next_runtime_cycle"


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
            "continuation_input_refs": result["manifest"].get("continuation_input_refs", {}),
            "records": result["manifest"]["project_status_table"]["records"],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
    )
    _write_json(
        out_dir / "stage6-review-loop-runtime-blocker-next-subqueues.json",
        result["manifest"]["runtime_blocker_next_subqueue_table"],
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


def _stage5_abcd_calibration_bucket(record: Mapping[str, Any]) -> str:
    explicit = str(
        record.get("stage5_abcd_calibration_bucket")
        or record.get("calibration_bucket")
        or record.get("calibration_review_bucket")
        or ""
    ).strip()
    if explicit.startswith(("A_", "B_", "C_", "D_")):
        return explicit
    legacy_bucket = str(record.get("stage5_calibration_review_bucket") or "").strip()
    if legacy_bucket in {
        "POTENTIAL_FALSE_POSITIVE_REVIEW",
        "POTENTIAL_FALSE_NEGATIVE_REVIEW",
        "RULE_THRESHOLD_REVIEW",
    }:
        return "B_PUBLIC_READBACK_REVIEW_REQUIRED"
    if legacy_bucket in {"MISSING_RELEVANT_PUBLIC_READBACK", "INSUFFICIENT_PUBLIC_READBACK"}:
        return "C_MISSING_RELEVANT_PUBLIC_READBACK"
    if legacy_bucket in {"BLOCKED_OR_AUTHORIZATION_REQUIRED", "UNSUPPORTED_RULE_OR_RUNTIME_BLOCKED"}:
        return "D_BLOCKED_OR_AUTHORIZATION_REQUIRED"
    return ""


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
    parser.add_argument("--release-field-query-json", default="")
    parser.add_argument("--release-field-query-root", default="")
    parser.add_argument("--supplemental-release-field-query-json", default="")
    parser.add_argument("--supplemental-release-field-query-root", default="")
    parser.add_argument("--release-evidence-adapter-plan-json", default="")
    parser.add_argument("--release-evidence-adapter-plan-root", default="")
    parser.add_argument("--original-backtrace-continuation-json", default="")
    parser.add_argument("--original-backtrace-continuation-root", default="")
    parser.add_argument("--stage16-p13b-continuation-json", default="")
    parser.add_argument("--stage16-p13b-continuation-root", default="")
    parser.add_argument("--stage5-calibration-sample-json", default="")
    parser.add_argument("--stage5-calibration-sample-root", default="")
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
        release_field_query_json=args.release_field_query_json or None,
        release_field_query_root=args.release_field_query_root or None,
        supplemental_release_field_query_json=args.supplemental_release_field_query_json or None,
        supplemental_release_field_query_root=args.supplemental_release_field_query_root or None,
        release_evidence_adapter_plan_json=args.release_evidence_adapter_plan_json or None,
        release_evidence_adapter_plan_root=args.release_evidence_adapter_plan_root or None,
        original_backtrace_continuation_json=args.original_backtrace_continuation_json or None,
        original_backtrace_continuation_root=args.original_backtrace_continuation_root or None,
        stage16_p13b_continuation_json=args.stage16_p13b_continuation_json or None,
        stage16_p13b_continuation_root=args.stage16_p13b_continuation_root or None,
        stage5_calibration_sample_json=args.stage5_calibration_sample_json or None,
        stage5_calibration_sample_root=args.stage5_calibration_sample_root or None,
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
