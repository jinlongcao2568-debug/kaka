from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_KIND = "runtime_blocker_controller_dispatch_runner_v1_manifest"
RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_VERSION = 1
RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_ADAPTER_ID = "runtime-blocker-controller-dispatch-runner-v1"

DEFAULT_CONTROLLER_DISPATCH_ROOT = Path("tmp/evaluation-real-samples/stage6-review-cycle-runner-v1")
DEFAULT_CONTROLLER_DISPATCH_FILENAME = "stage6-review-cycle-runtime-blocker-controller-dispatch-tasks.json"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/runtime-blocker-controller-dispatch-runner-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

READY_FOR_WORKER = "READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH"
GDCIC_BROWSER_READBACK_ARTIFACT = "gdcic-browser-authorized-readback-v1.json"
RELEASE_PLAN_ARTIFACT = "release-evidence-adapter-plan-v1.json"

ALLOWED_SCRIPT_BY_EXPECTED_ARTIFACT = {
    GDCIC_BROWSER_READBACK_ARTIFACT: "scripts/build-gdcic-browser-authorized-readback-v1.ps1",
}

LIVE_OR_EXTERNAL_FLAG_TOKENS = {
    "-enablelivebrowserexecution",
    "-enablelivepublicquery",
    "-enableliveprovider",
    "-enableliveoriginalnoticebacktrace",
    "-enablelivetargetedpersonreadback",
    "-executelivepublicregistryentryreadback",
    "--enable-live-browser-execution",
    "--enable-live-public-query",
    "--enable-live-provider",
    "--enable-live-original-notice-backtrace",
    "--enable-live-targeted-person-readback",
    "--execute-live-public-registry-entry-readback",
    "-external",
    "--external",
    "-enableexternal",
    "--enable-external",
    "-enabledelivery",
    "--enable-delivery",
    "-enablepayment",
    "--enable-payment",
    "-enablerefund",
    "--enable-refund",
    "-executeexternaldelivery",
    "--execute-external-delivery",
    "-executepayment",
    "--execute-payment",
    "-executerefund",
    "--execute-refund",
}

CommandExecutor = Callable[[list[str], Path], Mapping[str, Any]]


def run_runtime_blocker_controller_dispatch_runner(
    *,
    controller_dispatch_json: str | Path | None = None,
    controller_dispatch_root: str | Path = DEFAULT_CONTROLLER_DISPATCH_ROOT,
    controller_dispatch_table: Mapping[str, Any] | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute_commands: bool = False,
    max_tasks: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    cwd: str | Path | None = None,
    created_at: str | None = None,
    command_executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    source_path = (
        Path(controller_dispatch_json)
        if controller_dispatch_json
        else Path(controller_dispatch_root) / DEFAULT_CONTROLLER_DISPATCH_FILENAME
    )
    if controller_dispatch_table is None:
        payload = _load_json(source_path, blocking_reasons, "runtime_blocker_controller_dispatch_json_missing_or_invalid")
    else:
        payload = dict(controller_dispatch_table)
    records = [dict(record) for record in _list(payload.get("records")) if isinstance(record, Mapping)]

    selected_project_ids = {str(project_id).strip() for project_id in project_ids if str(project_id).strip()}
    selected = _selected_records(records, selected_project_ids)
    repo_cwd = Path(cwd) if cwd else Path.cwd()
    executor = command_executor or _execute_subprocess
    task_limit = None if max_tasks is None else max(0, int(max_tasks))

    runner_records: list[dict[str, Any]] = []
    executed_count = 0
    for record in selected:
        runner_record, executed = _runner_record(
            record,
            output_root=out_dir,
            execute_commands=execute_commands,
            task_limit=task_limit,
            executed_count=executed_count,
            cwd=repo_cwd,
            command_executor=executor,
            created_at=created,
        )
        if executed:
            executed_count += 1
        runner_records.append(runner_record)

    followup_records = [
        followup
        for record in runner_records
        for followup in _followup_records(record, output_root=out_dir, created_at=created)
    ]
    summary = _summary(
        source_records=records,
        selected_records=selected,
        runner_records=runner_records,
        followup_records=followup_records,
        blocking_reasons=blocking_reasons,
        execute_commands=execute_commands,
    )
    manifest = {
        "manifest_version": RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_VERSION,
        "manifest_kind": RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_KIND,
        "adapter_id": RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_ADAPTER_ID,
        "pipeline_stage": "RuntimeBlockerControllerDispatchRunnerV1",
        "manifest_id": f"RUNTIME-BLOCKER-CONTROLLER-DISPATCH-RUNNER-{_fingerprint({'summary': summary, 'records': runner_records, 'followups': followup_records})[:16]}",
        "created_at": created,
        "source_controller_dispatch_json": str(source_path),
        "execute_commands": bool(execute_commands),
        "max_tasks": task_limit,
        "project_ids": sorted(selected_project_ids),
        "runtime_blocker_dispatch_runner_table": {"records": runner_records, "summary": summary},
        "runtime_blocker_worker_followup_queue": {"records": followup_records, "summary": summary},
        "summary": summary,
        "safety": {
            "worker_command_execution_enabled": bool(execute_commands),
            "live_browser_execution_enabled": bool(summary.get("live_execution_enabled")),
            "network_enabled": False,
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "stage7_to_stage9_live_execution_enabled": False,
            "executes_only_generated_structured_argv": True,
            "shell_execution_enabled": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "runtime_blocker_controller_dispatch_runner_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": (
            not blocking_reasons
            and summary["executed_failed_count"] == 0
            and summary["executed_missing_output_count"] == 0
            and summary["allowlist_blocked_count"] == 0
        ),
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, runner_records, followup_records)
    return result


def _selected_records(records: list[Mapping[str, Any]], selected_project_ids: set[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if selected_project_ids and project_id not in selected_project_ids:
            continue
        selected.append(dict(record))
    return selected


def _runner_record(
    record: Mapping[str, Any],
    *,
    output_root: Path,
    execute_commands: bool,
    task_limit: int | None,
    executed_count: int,
    cwd: Path,
    command_executor: CommandExecutor,
    created_at: str,
) -> tuple[dict[str, Any], bool]:
    expected_output = str(record.get("expected_output_artifact_path") or "")
    expected_path = Path(expected_output) if expected_output else None
    initial_payload = _load_json_if_exists(expected_path)
    if initial_payload and _can_reuse_existing_output(record, initial_payload):
        execution_state = "EXISTING_OUTPUT_CONSUMED_SUPPRESS_DUPLICATE_WORKER_DISPATCH"
        skip_reason = "expected_output_artifact_already_present"
        command_result: Mapping[str, Any] = {}
        executed = False
        allowlist_state, allowlist_reason = "NOT_APPLICABLE_EXISTING_OUTPUT", ""
    else:
        execution_state, skip_reason, command_result, executed, allowlist_state, allowlist_reason = _execution_result(
            record,
            execute_commands=execute_commands,
            task_limit=task_limit,
            executed_count=executed_count,
            cwd=cwd,
            command_executor=command_executor,
        )
    output_payload = _load_json_if_exists(expected_path)
    output_exists = bool(expected_path and expected_path.exists())
    worker_readback_state = _worker_readback_state(
        record,
        execution_state=execution_state,
        output_exists=output_exists,
        output_payload=output_payload,
    )
    closeout_state = _worker_closeout_state(worker_readback_state)
    return (
        {
            "runtime_blocker_dispatch_runner_task_id": _stable_id(
                "RUNTIME-BLOCKER-DISPATCH-RUNNER",
                record.get("controller_dispatch_task_id"),
                execution_state,
                worker_readback_state,
            ),
            "controller_dispatch_task_id": str(record.get("controller_dispatch_task_id") or ""),
            "source_controller_queue_record_id": str(record.get("source_controller_queue_record_id") or ""),
            "source_next_subqueue_record_id": str(record.get("source_next_subqueue_record_id") or ""),
            "project_id": str(record.get("project_id") or ""),
            "project_name": str(record.get("project_name") or ""),
            "assigned_owner": str(record.get("assigned_owner") or ""),
            "assigned_owner_role": str(record.get("assigned_owner_role") or ""),
            "dispatch_route": str(record.get("dispatch_route") or ""),
            "dispatch_worker_family": str(record.get("dispatch_worker_family") or ""),
            "dispatch_readiness_state": str(record.get("dispatch_readiness_state") or ""),
            "dispatch_blocking_reasons": _dedupe(_list(record.get("dispatch_blocking_reasons"))),
            "execution_state": execution_state,
            "skip_reason": skip_reason,
            "allowlist_state": allowlist_state,
            "allowlist_reason": allowlist_reason,
            "exit_code": int(command_result.get("exit_code") or 0) if command_result else None,
            "stdout_excerpt": _truncate(str(command_result.get("stdout") or "")) if command_result else "",
            "stderr_excerpt": _truncate(str(command_result.get("stderr") or "")) if command_result else "",
            "worker_readback_state": worker_readback_state,
            "worker_closeout_state": closeout_state,
            "ready_for_field_query_backfill": closeout_state == "READY_FOR_GUANGDONG_FIELD_QUERY_BACKFILL",
            "expected_output_artifact": str(record.get("expected_output_artifact") or ""),
            "expected_output_artifact_path": expected_output,
            "expected_output_artifact_exists": output_exists,
            "result_manifest_id": _result_manifest_id(output_payload),
            "result_safe_to_execute": bool(output_payload.get("safe_to_execute")) if output_payload else False,
            "result_blocking_reasons": _result_blocking_reasons(output_payload),
            "recommended_script": str(record.get("recommended_script") or ""),
            "recommended_command_argv": _dedupe_argv(_list(record.get("recommended_command_argv"))),
            "recommended_command": str(record.get("recommended_command") or ""),
            "input_artifact_refs": _dedupe(_list(record.get("input_artifact_refs"))),
            "required_input": _dedupe(_list(record.get("required_input"))),
            "retry_policy": str(record.get("retry_policy") or ""),
            "reopen_conditions": _dedupe(_list(record.get("reopen_conditions"))),
            "operator_next_action": _operator_next_action(record, worker_readback_state),
            "next_action": _next_action(worker_readback_state),
            "execution_mode": (
                "CONTROLLED_INTERNAL_EXECUTED" if execution_state.startswith("EXECUTED_") else "READBACK_OR_PLAN_ONLY"
            ),
            "live_execution_enabled": _argv_has_live_or_external_flag(_list(record.get("recommended_command_argv"))),
            "requires_operator_approval_before_execution": _requires_operator_approval_before_execution(record),
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "created_at": created_at,
        },
        executed,
    )


def _execution_result(
    record: Mapping[str, Any],
    *,
    execute_commands: bool,
    task_limit: int | None,
    executed_count: int,
    cwd: Path,
    command_executor: CommandExecutor,
) -> tuple[str, str, Mapping[str, Any], bool, str, str]:
    readiness = str(record.get("dispatch_readiness_state") or "")
    argv = _dedupe_argv(_list(record.get("recommended_command_argv")))
    allowlist_state, allowlist_reason = _allowlist_state(record, argv)
    if readiness != READY_FOR_WORKER:
        return "WORKER_DISPATCH_NOT_READY_RECORDED", "dispatch_readiness_state_not_ready", {}, False, allowlist_state, allowlist_reason
    if not argv:
        return "BLOCKED_COMMAND_ARGV_MISSING", "recommended_command_argv_missing", {}, False, allowlist_state, allowlist_reason
    if allowlist_state != "ALLOWLIST_PASS":
        return "BLOCKED_BY_ALLOWLIST", allowlist_reason, {}, False, allowlist_state, allowlist_reason
    if task_limit is not None and executed_count >= task_limit:
        return "SKIPPED_BY_MAX_TASKS", "max_tasks_reached", {}, False, allowlist_state, allowlist_reason
    if not execute_commands:
        return "DRY_RUN_READY", "execute_commands_false", {}, False, allowlist_state, allowlist_reason
    command_result = command_executor(argv, cwd)
    exit_code = int(command_result.get("exit_code") or 0)
    return ("EXECUTED_SUCCEEDED" if exit_code == 0 else "EXECUTED_FAILED"), "", command_result, True, allowlist_state, allowlist_reason


def _worker_readback_state(
    record: Mapping[str, Any],
    *,
    execution_state: str,
    output_exists: bool,
    output_payload: Mapping[str, Any],
) -> str:
    if not output_exists:
        if execution_state == "DRY_RUN_READY":
            return "WAITING_FOR_CONTROLLED_WORKER_EXECUTION"
        if execution_state == "EXECUTED_SUCCEEDED":
            return "EXECUTED_BUT_OUTPUT_ARTIFACT_MISSING"
        if execution_state == "EXECUTED_FAILED":
            return "WORKER_EXECUTION_FAILED"
        if execution_state in {"SKIPPED_BY_MAX_TASKS", "BLOCKED_COMMAND_ARGV_MISSING"}:
            return "WORKER_DISPATCH_BLOCKED_OR_SKIPPED"
        return "WORKER_DISPATCH_NOT_READY_OPERATOR_OR_INPUT_REQUIRED"
    if not output_payload:
        return "WORKER_OUTPUT_INVALID_REVIEW_REQUIRED"
    if _gdcic_plan_only_output(output_payload):
        return "WORKER_PLAN_OUTPUT_WAITING_FOR_LIVE_OR_AUTHORIZED_SESSION"
    if not bool(output_payload.get("safe_to_execute", True)) or _result_blocking_reasons(output_payload):
        return "WORKER_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED"
    if _gdcic_browser_readback_output_ready(output_payload):
        return "WORKER_OUTPUT_READY_FOR_BACKFILL"
    if str(record.get("expected_output_artifact") or "") == GDCIC_BROWSER_READBACK_ARTIFACT:
        return "WORKER_OUTPUT_REVIEW_REQUIRED"
    return "WORKER_OUTPUT_READY_FOR_BACKFILL"


def _worker_closeout_state(worker_readback_state: str) -> str:
    if worker_readback_state == "WORKER_OUTPUT_READY_FOR_BACKFILL":
        return "READY_FOR_GUANGDONG_FIELD_QUERY_BACKFILL"
    if worker_readback_state == "WORKER_PLAN_OUTPUT_WAITING_FOR_LIVE_OR_AUTHORIZED_SESSION":
        return "WAITING_FOR_AUTHORIZED_BROWSER_EXECUTION_OR_OPERATOR_ACTION"
    if worker_readback_state == "WAITING_FOR_CONTROLLED_WORKER_EXECUTION":
        return "WAITING_FOR_CONTROLLED_WORKER_EXECUTION"
    if worker_readback_state in {
        "WORKER_DISPATCH_NOT_READY_OPERATOR_OR_INPUT_REQUIRED",
        "WORKER_DISPATCH_BLOCKED_OR_SKIPPED",
    }:
        return "KEPT_IN_RUNTIME_BLOCKER_SUBQUEUE"
    if worker_readback_state == "EXECUTED_BUT_OUTPUT_ARTIFACT_MISSING":
        return "BLOCKED_WORKER_OUTPUT_ARTIFACT_MISSING"
    if worker_readback_state == "WORKER_EXECUTION_FAILED":
        return "BLOCKED_WORKER_EXECUTION_FAILED"
    if worker_readback_state in {"WORKER_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED", "WORKER_OUTPUT_INVALID_REVIEW_REQUIRED"}:
        return "RUNTIME_BLOCKER_WORKER_OUTPUT_BLOCKED_LEDGER_RECORDED"
    return "MANUAL_REVIEW_REQUIRED"


def _followup_records(
    runner_record: Mapping[str, Any],
    *,
    output_root: Path,
    created_at: str,
) -> list[dict[str, Any]]:
    route_followup = _route_followup_record(runner_record, output_root=output_root, created_at=created_at)
    if route_followup:
        return [route_followup]
    if runner_record.get("worker_closeout_state") != "READY_FOR_GUANGDONG_FIELD_QUERY_BACKFILL":
        return []
    release_plan = _first_input_artifact(runner_record, RELEASE_PLAN_ARTIFACT)
    readback_json = str(runner_record.get("expected_output_artifact_path") or "")
    if not release_plan or not readback_json:
        return []
    project_id = str(runner_record.get("project_id") or "project").strip() or "project"
    followup_output = output_root / "followup-field-query" / _safe_path_segment(project_id)
    argv = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/run-guangdong-local-field-query-probe-v1.ps1",
        "-ReleaseEvidenceAdapterPlanJson",
        release_plan,
        "-GdcicBrowserReadbackJson",
        readback_json,
        "-OutputRoot",
        str(followup_output),
        "-SourceProfileIds",
        "GUANGDONG-GDCIC-HOME",
        "-EnableLivePublicQuery",
        "-MaxLiveTasks",
        "1",
    ]
    return [
        {
            "runtime_blocker_followup_task_id": _stable_id(
                "RUNTIME-BLOCKER-FOLLOWUP",
                runner_record.get("runtime_blocker_dispatch_runner_task_id"),
                release_plan,
                readback_json,
            ),
            "source_runtime_blocker_dispatch_runner_task_id": str(
                runner_record.get("runtime_blocker_dispatch_runner_task_id") or ""
            ),
            "project_id": project_id,
            "project_name": str(runner_record.get("project_name") or ""),
            "assigned_owner": str(runner_record.get("assigned_owner") or ""),
            "assigned_owner_role": str(runner_record.get("assigned_owner_role") or ""),
            "formal_entrypoint_id": "guangdong_local_field_query_probe",
            "followup_task_type": "RUN_GUANGDONG_LOCAL_FIELD_QUERY_WITH_GDCIC_BROWSER_READBACK",
            "followup_readiness_state": "READY_FOR_CONTROLLED_FIELD_QUERY_BACKFILL",
            "recommended_script": "scripts/run-guangdong-local-field-query-probe-v1.ps1",
            "recommended_command_argv": argv,
            "recommended_command": _powershell_command(argv),
            "release_evidence_adapter_plan_json": release_plan,
            "gdcic_browser_readback_json": readback_json,
            "expected_output_artifact": "guangdong-local-field-query-probe-v1.json",
            "output_root": str(followup_output),
            "next_action": "run_guangdong_local_field_query_probe_then_stage6_review_loop_backfill",
            "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
            "live_execution_enabled": False,
            "recommended_command_live_or_external_flag_present": _argv_has_live_or_external_flag(argv),
            "requires_operator_action_before_live": True,
            "requires_operator_approval_before_execution": True,
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "created_at": created_at,
        }
    ]


def _route_followup_record(
    runner_record: Mapping[str, Any],
    *,
    output_root: Path,
    created_at: str,
) -> dict[str, Any]:
    route = str(runner_record.get("dispatch_route") or "")
    if route not in {"fallback_source", "retry", "manual_hold", "suspend_dead_letter"}:
        return {}
    spec = {
        "fallback_source": {
            "formal_entrypoint_id": "stage4_release_evidence_bridge_builder",
            "followup_task_type": "BUILD_FALLBACK_SOURCE_ADAPTER_PLAN",
            "followup_readiness_state": "WAITING_FOR_FALLBACK_SOURCE_OR_MORE_PRECISE_QUERY_TERMS",
            "next_action": "build_fallback_source_adapter_plan_then_rerun_stage6_cycle",
            "operator_next_action": "choose_fallback_official_source_or_record_no_retry_scope_without_clearance_claim",
        },
        "retry": {
            "formal_entrypoint_id": "stage6_review_cycle_runner",
            "followup_task_type": "RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT",
            "followup_readiness_state": "WAITING_FOR_RETRY_REOPEN_INPUT_OR_BUDGET",
            "next_action": "rerun_stage6_review_cycle_after_reopen_input_is_recorded",
            "operator_next_action": "record_retry_budget_or_new_machine_readable_input_before_rerun",
        },
        "manual_hold": {
            "formal_entrypoint_id": "stage6_review_cycle_runner",
            "followup_task_type": "MANUAL_HOLD_OPERATOR_REVIEW",
            "followup_readiness_state": "MANUAL_HOLD_RECORDED_NO_WORKER_DISPATCH",
            "next_action": "operator_reviews_manual_hold_then_records_reopen_or_closeout",
            "operator_next_action": "operator_reviews_manual_hold_without_clearance_claim",
        },
        "suspend_dead_letter": {
            "formal_entrypoint_id": "stage6_review_cycle_runner",
            "followup_task_type": "SUSPEND_DEAD_LETTER_REOPEN_CHECK",
            "followup_readiness_state": "SUSPEND_DEAD_LETTER_RECORDED_UNTIL_REOPEN_CONDITION",
            "next_action": "keep_suspended_until_reopen_condition_or_dead_letter_review",
            "operator_next_action": "operator_records_reopen_condition_or_keeps_dead_letter_hold",
        },
    }[route]
    project_id = str(runner_record.get("project_id") or "project").strip() or "project"
    followup_output = output_root / "followup-runtime-blocker" / route / _safe_path_segment(project_id)
    return {
        "runtime_blocker_followup_task_id": _stable_id(
            "RUNTIME-BLOCKER-FOLLOWUP",
            runner_record.get("runtime_blocker_dispatch_runner_task_id"),
            route,
            runner_record.get("worker_closeout_state"),
        ),
        "source_runtime_blocker_dispatch_runner_task_id": str(
            runner_record.get("runtime_blocker_dispatch_runner_task_id") or ""
        ),
        "source_controller_dispatch_task_id": str(runner_record.get("controller_dispatch_task_id") or ""),
        "project_id": project_id,
        "project_name": str(runner_record.get("project_name") or ""),
        "assigned_owner": str(runner_record.get("assigned_owner") or ""),
        "assigned_owner_role": str(runner_record.get("assigned_owner_role") or ""),
        "formal_entrypoint_id": spec["formal_entrypoint_id"],
        "followup_task_type": spec["followup_task_type"],
        "followup_readiness_state": spec["followup_readiness_state"],
        "recommended_script": "",
        "recommended_command_argv": [],
        "recommended_command": "",
        "dispatch_route": route,
        "dispatch_worker_family": str(runner_record.get("dispatch_worker_family") or ""),
        "dispatch_readiness_state": str(runner_record.get("dispatch_readiness_state") or ""),
        "worker_readback_state": str(runner_record.get("worker_readback_state") or ""),
        "worker_closeout_state": str(runner_record.get("worker_closeout_state") or ""),
        "input_artifact_refs": _dedupe(_list(runner_record.get("input_artifact_refs"))),
        "required_input": _dedupe(_list(runner_record.get("required_input"))),
        "retry_policy": str(runner_record.get("retry_policy") or ""),
        "reopen_conditions": _dedupe(_list(runner_record.get("reopen_conditions"))),
        "operator_next_action": str(runner_record.get("operator_next_action") or spec["operator_next_action"]),
        "expected_output_artifact": "",
        "output_root": str(followup_output),
        "next_action": spec["next_action"],
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "live_execution_enabled": False,
        "requires_operator_action_before_live": True,
        "requires_operator_approval_before_execution": True,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _summary(
    *,
    source_records: list[Mapping[str, Any]],
    selected_records: list[Mapping[str, Any]],
    runner_records: list[Mapping[str, Any]],
    followup_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    execute_commands: bool,
) -> dict[str, Any]:
    return {
        "runtime_blocker_controller_dispatch_runner_state": (
            "RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_READY"
            if not blocking_reasons
            else "RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_INPUT_BLOCKED"
        ),
        "execution_mode": "CONTROLLED_INTERNAL_EXECUTION" if execute_commands else "DRY_RUN_OR_EXISTING_OUTPUT_READBACK",
        "source_controller_dispatch_task_count": len(source_records),
        "selected_controller_dispatch_task_count": len(selected_records),
        "runtime_blocker_dispatch_runner_task_count": len(runner_records),
        "execution_state_counts": _counts(record.get("execution_state") for record in runner_records),
        "worker_readback_state_counts": _counts(record.get("worker_readback_state") for record in runner_records),
        "worker_closeout_state_counts": _counts(record.get("worker_closeout_state") for record in runner_records),
        "dry_run_ready_count": sum(1 for record in runner_records if record.get("execution_state") == "DRY_RUN_READY"),
        "existing_output_consumed_count": sum(
            1
            for record in runner_records
            if record.get("execution_state") == "EXISTING_OUTPUT_CONSUMED_SUPPRESS_DUPLICATE_WORKER_DISPATCH"
        ),
        "executed_success_count": sum(1 for record in runner_records if record.get("execution_state") == "EXECUTED_SUCCEEDED"),
        "executed_failed_count": sum(1 for record in runner_records if record.get("execution_state") == "EXECUTED_FAILED"),
        "allowlist_blocked_count": sum(
            1 for record in runner_records if record.get("execution_state") == "BLOCKED_BY_ALLOWLIST"
        ),
        "executed_missing_output_count": sum(
            1 for record in runner_records if record.get("worker_readback_state") == "EXECUTED_BUT_OUTPUT_ARTIFACT_MISSING"
        ),
        "not_ready_recorded_count": sum(
            1 for record in runner_records if record.get("execution_state") == "WORKER_DISPATCH_NOT_READY_RECORDED"
        ),
        "ready_for_field_query_backfill_count": sum(
            1 for record in runner_records if record.get("ready_for_field_query_backfill")
        ),
        "followup_task_count": len(followup_records),
        "followup_task_type_counts": _counts(record.get("followup_task_type") for record in followup_records),
        "operator_next_action_counts": _counts(record.get("operator_next_action") for record in runner_records),
        "live_execution_enabled": any(
            bool(record.get("live_execution_enabled")) for record in list(runner_records) + list(followup_records)
        ),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "blocking_reasons": list(blocking_reasons),
        "forbidden_term_scan_state": "PENDING",
    }


def _operator_next_action(record: Mapping[str, Any], worker_readback_state: str) -> str:
    if worker_readback_state == "WORKER_OUTPUT_READY_FOR_BACKFILL":
        return "run_guangdong_local_field_query_probe_with_gdcic_browser_readback"
    if worker_readback_state == "WORKER_PLAN_OUTPUT_WAITING_FOR_LIVE_OR_AUTHORIZED_SESSION":
        return "provide_authorized_session_and_enable_controlled_browser_execution_or_keep_operator_hold"
    if worker_readback_state == "WAITING_FOR_CONTROLLED_WORKER_EXECUTION":
        return "execute_allowlisted_runtime_blocker_worker_or_record_operator_skip"
    if worker_readback_state == "WORKER_DISPATCH_NOT_READY_OPERATOR_OR_INPUT_REQUIRED":
        return str(record.get("operator_next_action") or "resolve_required_input_before_worker_dispatch")
    if worker_readback_state in {"WORKER_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED", "WORKER_OUTPUT_INVALID_REVIEW_REQUIRED"}:
        return "review_worker_output_blocker_then_retry_suspend_or_dead_letter"
    if worker_readback_state == "EXECUTED_BUT_OUTPUT_ARTIFACT_MISSING":
        return "inspect_worker_execution_and_missing_output_artifact_before_retry"
    if worker_readback_state == "WORKER_EXECUTION_FAILED":
        return "inspect_worker_execution_failure_then_retry_or_suspend"
    return str(record.get("operator_next_action") or "operator_review_runtime_blocker_dispatch_state")


def _requires_operator_approval_before_execution(record: Mapping[str, Any]) -> bool:
    if bool(record.get("requires_operator_approval_before_execution")):
        return True
    if str(record.get("dispatch_route") or "") == "browser_worker":
        return True
    return _argv_has_live_or_external_flag(_list(record.get("recommended_command_argv")))


def _allowlist_state(record: Mapping[str, Any], argv: list[str]) -> tuple[str, str]:
    if not argv:
        return "ALLOWLIST_BLOCKED", "structured_recommended_command_argv_missing"
    if _normalize_exe(argv[0]) not in {"pwsh", "pwsh.exe"}:
        return "ALLOWLIST_BLOCKED", "command_must_start_with_pwsh"
    script = _script_from_argv(argv)
    if not script:
        return "ALLOWLIST_BLOCKED", "powershell_file_script_missing"
    expected_artifact = str(record.get("expected_output_artifact") or "")
    expected_script = ALLOWED_SCRIPT_BY_EXPECTED_ARTIFACT.get(expected_artifact)
    if not expected_script:
        return "ALLOWLIST_BLOCKED", "expected_output_artifact_not_allowlisted"
    if _normalize_path(script) != _normalize_path(expected_script):
        return "ALLOWLIST_BLOCKED", "recommended_script_does_not_match_expected_artifact"
    if any(_is_live_or_external_flag(token) for token in argv):
        return "ALLOWLIST_BLOCKED", "live_or_external_execution_flag_present"
    return "ALLOWLIST_PASS", ""


def _next_action(worker_readback_state: str) -> str:
    if worker_readback_state == "WORKER_OUTPUT_READY_FOR_BACKFILL":
        return "enqueue_guangdong_local_field_query_backfill"
    if worker_readback_state == "WORKER_PLAN_OUTPUT_WAITING_FOR_LIVE_OR_AUTHORIZED_SESSION":
        return "wait_for_authorized_browser_execution_or_operator_action"
    if worker_readback_state == "WAITING_FOR_CONTROLLED_WORKER_EXECUTION":
        return "wait_for_controlled_worker_execution"
    if worker_readback_state == "WORKER_DISPATCH_NOT_READY_OPERATOR_OR_INPUT_REQUIRED":
        return "keep_in_runtime_blocker_subqueue"
    if worker_readback_state in {"WORKER_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED", "WORKER_OUTPUT_INVALID_REVIEW_REQUIRED"}:
        return "route_worker_output_blocker_to_retry_suspend_or_operator_action"
    return "operator_review_runtime_blocker_dispatch_state"


def _gdcic_plan_only_output(payload: Mapping[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    execution_mode = str(payload.get("manifest", {}).get("execution_mode") if isinstance(payload.get("manifest"), Mapping) else "")
    return (
        str(summary.get("execution_mode") or execution_mode) == "PLAN_ONLY_NOT_EXECUTED"
        and int(summary.get("gdcic_browser_readback_record_count") or 0) == 0
    )


def _gdcic_browser_readback_output_ready(payload: Mapping[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    if int(summary.get("gdcic_browser_readback_ready_count") or 0) > 0:
        return True
    if int(summary.get("gdcic_browser_no_field_match_count") or 0) > 0:
        return True
    if int(summary.get("gdcic_browser_readback_record_count") or 0) > 0:
        return True
    return bool(_list(manifest.get("browser_readback_records")))


def _result_manifest_id(payload: Mapping[str, Any]) -> str:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    return str(manifest.get("manifest_id") or "") if isinstance(manifest, Mapping) else ""


def _result_blocking_reasons(payload: Mapping[str, Any]) -> list[str]:
    if not payload:
        return []
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    manifest_summary = manifest.get("summary") if isinstance(manifest.get("summary"), Mapping) else {}
    return _dedupe(
        [
            *_list(payload.get("blocking_reasons")),
            *_list(summary.get("blocking_reasons")),
            *_list(manifest_summary.get("blocking_reasons")),
        ]
    )


def _can_reuse_existing_output(record: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    expected_artifact = str(record.get("expected_output_artifact") or "").strip()
    if expected_artifact != GDCIC_BROWSER_READBACK_ARTIFACT:
        return True
    if not _gdcic_output_matches_dispatch_identity(record, payload):
        return False
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    source_release_plan = str(manifest.get("source_release_evidence_adapter_plan_json") or "").strip()
    source_release_plan_manifest_id = str(
        manifest.get("source_release_evidence_adapter_plan_manifest_id") or ""
    ).strip()
    source_release_plan_manifest_sha256 = str(
        manifest.get("source_release_evidence_adapter_plan_manifest_sha256") or ""
    ).strip()
    current_release_plan = _first_input_artifact(record, RELEASE_PLAN_ARTIFACT)
    if not current_release_plan:
        return True
    current_release_plan_payload = _load_json_if_exists(Path(current_release_plan))
    current_release_plan_manifest = (
        current_release_plan_payload.get("manifest")
        if isinstance(current_release_plan_payload.get("manifest"), Mapping)
        else {}
    )
    current_release_plan_manifest_id = str(
        current_release_plan_manifest.get("manifest_id") or ""
    ).strip()
    current_release_plan_manifest_sha256 = str(
        current_release_plan_manifest.get("manifest_sha256") or ""
    ).strip()
    if (
        current_release_plan_manifest_id
        and source_release_plan_manifest_id
        and current_release_plan_manifest_id != source_release_plan_manifest_id
    ):
        return False
    if (
        current_release_plan_manifest_sha256
        and source_release_plan_manifest_sha256
        and current_release_plan_manifest_sha256 != source_release_plan_manifest_sha256
    ):
        return False
    if (
        (current_release_plan_manifest_id and source_release_plan_manifest_id)
        or (current_release_plan_manifest_sha256 and source_release_plan_manifest_sha256)
    ):
        return True
    return bool(source_release_plan) and _same_path_text(source_release_plan, current_release_plan)


def _gdcic_output_matches_dispatch_identity(record: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    identity_rows = [
        dict(item)
        for item in [
            *_list(manifest.get("browser_readback_records")),
            *_list(manifest.get("browser_readback_task_records")),
        ]
        if isinstance(item, Mapping)
    ]
    dispatch_project_id = str(record.get("project_id") or "").strip()
    dispatch_task_id = str(record.get("task_id") or "").strip()
    payload_project_ids = {
        str(item.get("project_id") or "").strip()
        for item in identity_rows
        if str(item.get("project_id") or "").strip()
    }
    payload_task_ids = {
        str(item.get("release_evidence_adapter_task_id") or "").strip()
        for item in identity_rows
        if str(item.get("release_evidence_adapter_task_id") or "").strip()
    }
    if dispatch_project_id and payload_project_ids and dispatch_project_id not in payload_project_ids:
        return False
    if dispatch_task_id and payload_task_ids and dispatch_task_id not in payload_task_ids:
        return False
    return True


def _same_path_text(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    try:
        return Path(left_text).resolve() == Path(right_text).resolve()
    except OSError:
        return left_text.replace("\\", "/").rstrip("/").lower() == right_text.replace("\\", "/").rstrip("/").lower()


def _first_input_artifact(record: Mapping[str, Any], suffix: str) -> str:
    expected = str(suffix or "").replace("\\", "/")
    for value in _list(record.get("input_artifact_refs")):
        text = str(value or "").strip()
        if text and text.replace("\\", "/").endswith(expected):
            return text
    return ""


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blocking_reasons.append(missing_reason)
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_if_exists(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _execute_subprocess(argv: list[str], cwd: Path) -> Mapping[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    runner_records: list[Mapping[str, Any]],
    followup_records: list[Mapping[str, Any]],
) -> None:
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
    _write_json(out_dir / "runtime-blocker-controller-dispatch-runner-table.json", {"summary": result["summary"], "records": runner_records})
    _write_json(out_dir / "runtime-blocker-worker-followup-queue.json", {"summary": result["summary"], "records": followup_records})
    _write_json(out_dir / "runtime-blocker-controller-dispatch-runner-v1.json", result)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _dedupe_argv(values: Iterable[Any]) -> list[str]:
    return [str(value) for value in values if str(value or "").strip()]


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _powershell_command(argv: Iterable[Any]) -> str:
    return " ".join(_ps_quote_arg(str(part)) for part in argv)


def _ps_quote_arg(value: str) -> str:
    if not value:
        return "''"
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-,")
    if all(char in safe_chars for char in value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _script_from_argv(argv: list[str]) -> str:
    for index, token in enumerate(argv[:-1]):
        if token.lower() == "-file":
            return argv[index + 1]
    return ""


def _normalize_exe(value: str) -> str:
    return Path(str(value or "")).name.lower()


def _normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _is_live_or_external_flag(token: Any) -> bool:
    text = str(token or "").strip().lower()
    if text in LIVE_OR_EXTERNAL_FLAG_TOKENS:
        return True
    if not text.startswith("-"):
        return False
    return any(keyword in text for keyword in ("live", "external", "delivery", "payment", "refund"))


def _argv_has_live_or_external_flag(argv: Iterable[Any]) -> bool:
    return any(_is_live_or_external_flag(part) for part in argv)


def _any_live_or_external_argv(argv_values: Iterable[Any]) -> bool:
    return any(_argv_has_live_or_external_flag(_list(argv)) for argv in argv_values)


def _safe_path_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value) or "project"


def _truncate(value: str, limit: int = 4000) -> str:
    return value if len(value) <= limit else value[:limit] + "...<truncated>"


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or read back runtime blocker controller dispatch tasks.")
    parser.add_argument("--controller-dispatch-json", default="")
    parser.add_argument("--controller-dispatch-root", default=str(DEFAULT_CONTROLLER_DISPATCH_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute", action="store_true", dest="execute_commands")
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_runtime_blocker_controller_dispatch_runner(
        controller_dispatch_json=args.controller_dispatch_json or None,
        controller_dispatch_root=args.controller_dispatch_root,
        output_root=args.output_root,
        execute_commands=bool(args.execute_commands),
        max_tasks=args.max_tasks,
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
    "RUNTIME_BLOCKER_CONTROLLER_DISPATCH_RUNNER_KIND",
    "run_runtime_blocker_controller_dispatch_runner",
]
