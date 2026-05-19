from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_KIND = "stage6_review_action_dispatch_runner_v1_manifest"
STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_VERSION = 1
STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_ADAPTER_ID = "stage6-review-action-dispatch-runner-v1"

DEFAULT_DISPATCH_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-runner-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

TASK_TYPE_ORIGINAL = "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW"
TASK_TYPE_DESIGN_SURVEY = "RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW"
TASK_TYPE_RELEASE_PLAN = "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN"

EXPECTED_ARTIFACT_BY_TASK_TYPE = {
    TASK_TYPE_ORIGINAL: "evidence-orchestration-continuation-run-v1.json",
    TASK_TYPE_DESIGN_SURVEY: "design-survey-public-registry-readback-v1.json",
    TASK_TYPE_RELEASE_PLAN: "release-evidence-adapter-plan-v1.json",
}

CommandExecutor = Callable[[list[str], Path], Mapping[str, Any]]


def run_stage6_review_action_dispatch_runner(
    *,
    dispatch_json: str | Path | None = None,
    dispatch_root: str | Path = DEFAULT_DISPATCH_ROOT,
    baseline_evidence_state_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute_commands: bool = False,
    max_groups: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    cwd: str | Path | None = None,
    created_at: str | None = None,
    command_executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    dispatch_path = Path(dispatch_json) if dispatch_json else Path(dispatch_root) / "stage6-review-action-dispatch-v1.json"
    dispatch_payload = _load_json(dispatch_path, blocking_reasons, "stage6_review_action_dispatch_missing_or_invalid")
    dispatch_manifest = _source_manifest(dispatch_payload)
    dispatch_records = [
        dict(record)
        for record in _list(
            (dispatch_manifest.get("dispatch_task_table") or {}).get("records")
            if isinstance(dispatch_manifest.get("dispatch_task_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    if dispatch_payload and not dispatch_records:
        blocking_reasons.append("stage6_review_dispatch_task_records_missing")

    selected_project_ids = {str(project_id).strip() for project_id in project_ids if str(project_id).strip()}
    selected_records = _selected_dispatch_records(dispatch_records, selected_project_ids)
    group_specs = _group_specs(
        selected_records,
        explicit_baseline_evidence_state_json=baseline_evidence_state_json,
        output_root=out_dir,
        created_at=created,
    )

    repo_cwd = Path(cwd) if cwd else Path.cwd()
    executor = command_executor or _execute_subprocess
    group_limit = None if max_groups is None else max(0, int(max_groups))
    selected_group_count = 0
    group_records: list[dict[str, Any]] = []

    for spec in group_specs:
        execution_state = ""
        skip_reason = ""
        command_result: Mapping[str, Any] = {}
        if spec["group_readiness_state"] != "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_RUN":
            execution_state = "BLOCKED_MISSING_INPUTS"
            skip_reason = str(spec.get("group_blocking_reason") or "dispatch_group_not_ready")
        elif group_limit is not None and selected_group_count >= group_limit:
            execution_state = "SKIPPED_BY_MAX_GROUPS"
            skip_reason = "max_groups_reached"
        elif not execute_commands:
            selected_group_count += 1
            execution_state = "DRY_RUN_READY"
            skip_reason = "execute_commands_false"
        else:
            selected_group_count += 1
            command_result = executor(list(spec["recommended_command_argv"]), repo_cwd)
            execution_state = "EXECUTED_SUCCEEDED" if int(command_result.get("exit_code") or 0) == 0 else "EXECUTED_FAILED"
        group_records.append(
            _group_record_from_spec(
                spec,
                execution_state=execution_state,
                skip_reason=skip_reason,
                command_result=command_result,
                created_at=created,
            )
        )

    task_records = _task_records(selected_records, group_records, created_at=created)
    summary = _summary(
        source_dispatch_records=dispatch_records,
        selected_dispatch_records=selected_records,
        group_records=group_records,
        task_records=task_records,
        blocking_reasons=blocking_reasons,
        execute_commands=execute_commands,
    )
    manifest = {
        "manifest_version": STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_VERSION,
        "manifest_kind": STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_KIND,
        "adapter_id": STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewActionDispatchRunnerV1",
        "manifest_id": f"STAGE6-REVIEW-ACTION-DISPATCH-RUNNER-{_fingerprint({'summary': summary, 'groups': group_records, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_dispatch_json": str(dispatch_path),
        "source_dispatch_manifest_id": str(dispatch_manifest.get("manifest_id") or ""),
        "execute_commands": bool(execute_commands),
        "max_groups": group_limit,
        "project_ids": sorted(selected_project_ids),
        "result_roots_by_task_type": _result_roots_by_task_type(group_records),
        "dispatch_runner_group_table": {"records": group_records, "summary": summary},
        "dispatch_runner_task_table": {"records": task_records, "summary": summary},
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
            "executes_only_generated_structured_argv": True,
            "shell_execution_enabled": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage6_review_action_dispatch_runner_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": (
            not blocking_reasons
            and summary["executed_failed_group_count"] == 0
            and summary["blocked_missing_inputs_group_count"] == 0
        ),
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, group_records, task_records)
    return result


def _selected_dispatch_records(
    dispatch_records: list[Mapping[str, Any]],
    selected_project_ids: set[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in dispatch_records:
        project_id = str(record.get("project_id") or "").strip()
        if selected_project_ids and project_id not in selected_project_ids:
            continue
        if str(record.get("dispatch_readiness_state") or "") != "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_PLAN":
            continue
        records.append(dict(record))
    return records


def _group_specs(
    records: list[Mapping[str, Any]],
    *,
    explicit_baseline_evidence_state_json: str | Path | None,
    output_root: Path,
    created_at: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        task_type = str(record.get("dispatch_task_type") or "")
        grouped.setdefault(task_type, []).append(record)

    specs: list[dict[str, Any]] = []
    for order, (task_type, task_records) in enumerate(sorted(grouped.items()), start=1):
        project_ids = _dedupe(record.get("project_id") for record in task_records)
        source_evidence_state_jsons = _dedupe(
            _source_refs(record).get("evidence_state_json") for record in task_records
        )
        baseline_json = str(explicit_baseline_evidence_state_json or "")
        if not baseline_json and len(source_evidence_state_jsons) == 1:
            baseline_json = source_evidence_state_jsons[0]
        output_dir = output_root / "r" / f"{order:02d}-{_group_slug(task_type)}"
        argv, readiness_state, blocking_reason = _argv_for_task_type(
            task_type=task_type,
            task_records=task_records,
            project_ids=project_ids,
            baseline_evidence_state_json=baseline_json,
            multiple_baseline_sources=len(source_evidence_state_jsons) > 1 and not explicit_baseline_evidence_state_json,
            output_root=output_dir,
        )
        specs.append(
            {
                "dispatch_runner_group_id": _stable_id("S6-DISPATCH-RUN-GROUP", task_type, project_ids, baseline_json),
                "dispatch_task_type": task_type,
                "dispatch_task_ids": _dedupe(record.get("dispatch_task_id") for record in task_records),
                "project_ids": project_ids,
                "project_count": len(project_ids),
                "source_evidence_state_json": baseline_json,
                "source_evidence_state_json_candidates": source_evidence_state_jsons,
                "group_readiness_state": readiness_state,
                "group_blocking_reason": blocking_reason,
                "recommended_command_argv": argv,
                "recommended_command": _powershell_command(argv),
                "output_root": str(output_dir),
                "expected_output_artifact": EXPECTED_ARTIFACT_BY_TASK_TYPE.get(task_type, ""),
                "created_at": created_at,
            }
        )
    return specs


def _argv_for_task_type(
    *,
    task_type: str,
    task_records: list[Mapping[str, Any]],
    project_ids: list[str],
    baseline_evidence_state_json: str,
    multiple_baseline_sources: bool,
    output_root: Path,
) -> tuple[list[str], str, str]:
    if multiple_baseline_sources:
        return [], "BLOCKED_MULTIPLE_BASELINE_EVIDENCE_STATE_SOURCES", "multiple_evidence_state_sources_for_task_type"
    if task_type == TASK_TYPE_RELEASE_PLAN:
        args = _release_plan_args(task_records)
        args["OutputRoot"] = str(output_root)
        return _powershell_argv("scripts/build-release-evidence-adapter-plan-v1.ps1", args), "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_RUN", ""
    if task_type in {TASK_TYPE_ORIGINAL, TASK_TYPE_DESIGN_SURVEY} and not baseline_evidence_state_json:
        return [], "BLOCKED_BASELINE_EVIDENCE_STATE_MISSING", "baseline_evidence_state_json_missing"

    baseline_payload = _load_json_if_exists(Path(baseline_evidence_state_json))
    baseline_args = _baseline_evidence_state_args(_source_manifest(baseline_payload))
    if task_type == TASK_TYPE_ORIGINAL:
        if not baseline_args.get("Stage16StorageJson"):
            return [], "BLOCKED_BASELINE_INPUTS_MISSING", "stage16_storage_json_missing"
        args = dict(baseline_args)
        args["OutputRoot"] = str(output_root)
        if project_ids:
            args["ProjectIds"] = ",".join(project_ids)
        return _powershell_argv("scripts/run-evidence-orchestration-continuation-v1.ps1", args), "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_RUN", ""
    if task_type == TASK_TYPE_DESIGN_SURVEY:
        fallback_json = baseline_args.get("DesignSurveyPublicRegistryFallbackJson", "")
        if not fallback_json:
            return [], "BLOCKED_BASELINE_INPUTS_MISSING", "design_survey_public_registry_fallback_json_missing"
        args = {
            "PublicRegistryFallbackJson": fallback_json,
            "OutputRoot": str(output_root),
        }
        if project_ids:
            args["ProjectIds"] = ",".join(project_ids)
        return _powershell_argv("scripts/build-design-survey-public-registry-readback-v1.ps1", args), "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_RUN", ""
    return [], "BLOCKED_TASK_TYPE_NOT_SUPPORTED", "dispatch_task_type_not_supported_by_runner_v1"


def _release_plan_args(task_records: list[Mapping[str, Any]]) -> dict[str, str]:
    refs = _source_refs(task_records[0]) if task_records else {}
    mapping = {
        "BatchCloseoutJson": "evidence_batch_closeout_json",
        "BatchCloseoutRoot": "evidence_batch_closeout_root",
        "P13BOperationalCloseoutJson": "p13b_operational_closeout_json",
        "P13BOperationalCloseoutRoot": "p13b_operational_closeout_root",
    }
    args: dict[str, str] = {}
    for arg_name, ref_name in mapping.items():
        value = str(refs.get(ref_name) or "").strip()
        if value:
            args[arg_name] = value
    return args


def _group_record_from_spec(
    spec: Mapping[str, Any],
    *,
    execution_state: str,
    skip_reason: str,
    command_result: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        **dict(spec),
        "execution_state": execution_state,
        "skip_reason": skip_reason,
        "exit_code": int(command_result.get("exit_code") or 0) if command_result else None,
        "stdout_excerpt": _truncate(str(command_result.get("stdout") or "")) if command_result else "",
        "stderr_excerpt": _truncate(str(command_result.get("stderr") or "")) if command_result else "",
        "execution_mode": "CONTROLLED_INTERNAL_EXECUTED" if execution_state.startswith("EXECUTED_") else "PLAN_OR_SKIP_ONLY",
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _task_records(
    selected_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    group_by_task_type = {str(group.get("dispatch_task_type") or ""): group for group in group_records}
    out: list[dict[str, Any]] = []
    for task in selected_records:
        task_type = str(task.get("dispatch_task_type") or "")
        group = group_by_task_type.get(task_type, {})
        out.append(
            {
                "dispatch_runner_task_id": _stable_id(
                    "S6-DISPATCH-RUN-TASK",
                    task.get("dispatch_task_id"),
                    group.get("execution_state"),
                ),
                "dispatch_runner_group_id": str(group.get("dispatch_runner_group_id") or ""),
                "dispatch_task_id": str(task.get("dispatch_task_id") or ""),
                "project_id": str(task.get("project_id") or ""),
                "project_name": str(task.get("project_name") or ""),
                "dispatch_task_type": task_type,
                "execution_state": str(group.get("execution_state") or "SKIPPED_NO_GROUP"),
                "output_root": str(group.get("output_root") or ""),
                "expected_output_artifact": str(group.get("expected_output_artifact") or ""),
                "live_execution_enabled": False,
                "customer_visible_allowed": False,
                "external_send_enabled": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
                "created_at": created_at,
            }
        )
    return out


def _result_roots_by_task_type(group_records: list[Mapping[str, Any]]) -> dict[str, str]:
    roots: dict[str, str] = {}
    for group in group_records:
        task_type = str(group.get("dispatch_task_type") or "")
        output_root = str(group.get("output_root") or "")
        if task_type and output_root and task_type not in roots:
            roots[task_type] = output_root
    return roots


def _baseline_evidence_state_args(manifest: Mapping[str, Any]) -> dict[str, str]:
    source_fields = {
        "Stage16StorageJson": "source_stage16_storage_json",
        "CompanyFirstStage4InputsJson": "source_company_first_stage4_inputs_json",
        "P13BCompanyHistoryJson": "source_p13b_company_history_json",
        "OriginalNoticeBacktraceJson": "source_original_notice_backtrace_json",
        "OriginalBacktraceContinuationJson": "source_original_backtrace_continuation_json",
        "DesignSurveyAdapterPlanJson": "source_design_survey_adapter_plan_json",
        "DesignSurveyStage4ExecutionJson": "source_design_survey_stage4_execution_json",
        "DesignSurveyFlow08ReadbackJson": "source_design_survey_flow08_readback_json",
        "DesignSurveyFlow08AttachmentParseJson": "source_design_survey_flow08_attachment_parse_json",
        "DesignSurveyPublicRegistryFallbackJson": "source_design_survey_public_registry_fallback_json",
        "DesignSurveyPublicRegistryReadbackJson": "source_design_survey_public_registry_readback_json",
    }
    args: dict[str, str] = {}
    for arg_name, source_field in source_fields.items():
        value = str(manifest.get(source_field) or "").strip()
        if value:
            args[arg_name] = value
    return args


def _powershell_argv(script_path: str, args: Mapping[str, str]) -> list[str]:
    argv = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script_path,
    ]
    for key, value in args.items():
        text = str(value or "").strip()
        if not text:
            continue
        argv.append(f"-{key}")
        argv.append(text)
    return argv


def _powershell_command(argv: list[str]) -> str:
    return " ".join(_ps_quote_arg(part) for part in argv)


def _ps_quote_arg(value: str) -> str:
    if not value:
        return "''"
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-,")
    if all(char in safe_chars for char in value):
        return value
    return "'" + value.replace("'", "''") + "'"


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


def _summary(
    *,
    source_dispatch_records: list[Mapping[str, Any]],
    selected_dispatch_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
    task_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    execute_commands: bool,
) -> dict[str, Any]:
    return {
        "stage6_review_action_dispatch_runner_state": (
            "STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_READY"
            if not blocking_reasons
            else "STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_INPUT_BLOCKED"
        ),
        "execution_mode": "CONTROLLED_INTERNAL_EXECUTION" if execute_commands else "DRY_RUN_NOT_EXECUTED",
        "source_dispatch_task_count": len(source_dispatch_records),
        "selected_dispatch_task_count": len(selected_dispatch_records),
        "dispatch_runner_group_count": len(group_records),
        "dispatch_runner_task_count": len(task_records),
        "group_execution_state_counts": _counts(group.get("execution_state") for group in group_records),
        "task_execution_state_counts": _counts(task.get("execution_state") for task in task_records),
        "dry_run_ready_group_count": sum(1 for group in group_records if group.get("execution_state") == "DRY_RUN_READY"),
        "executed_success_group_count": sum(1 for group in group_records if group.get("execution_state") == "EXECUTED_SUCCEEDED"),
        "executed_failed_group_count": sum(1 for group in group_records if group.get("execution_state") == "EXECUTED_FAILED"),
        "blocked_missing_inputs_group_count": sum(
            1 for group in group_records if group.get("execution_state") == "BLOCKED_MISSING_INPUTS"
        ),
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "blocking_reasons": list(blocking_reasons),
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    group_records: list[Mapping[str, Any]],
    task_records: list[Mapping[str, Any]],
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
    _write_json(
        out_dir / "stage6-review-dispatch-runner-table.json",
        {"summary": result["summary"], "groups": group_records, "tasks": task_records},
    )
    _write_json(out_dir / "stage6-review-action-dispatch-runner-v1.json", result)


def _source_refs(record: Mapping[str, Any]) -> dict[str, Any]:
    refs = record.get("source_refs")
    return dict(refs) if isinstance(refs, Mapping) else {}


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


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload) if isinstance(payload, Mapping) else {}


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


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _group_slug(task_type: str) -> str:
    slugs = {
        TASK_TYPE_ORIGINAL: "o",
        TASK_TYPE_DESIGN_SURVEY: "d",
        TASK_TYPE_RELEASE_PLAN: "r",
    }
    if task_type in slugs:
        return slugs[task_type]
    return "".join(char.lower() if char.isalnum() else "-" for char in task_type).strip("-")[:40] or "task"


def _truncate(value: str, limit: int = 4000) -> str:
    return value if len(value) <= limit else value[:limit] + "...<truncated>"


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run grouped Stage6 review action dispatch tasks.")
    parser.add_argument("--dispatch-json", default="")
    parser.add_argument("--dispatch-root", default=str(DEFAULT_DISPATCH_ROOT))
    parser.add_argument("--baseline-evidence-state-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute", action="store_true", dest="execute_commands")
    parser.add_argument("--max-groups", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_stage6_review_action_dispatch_runner(
        dispatch_json=args.dispatch_json or None,
        dispatch_root=args.dispatch_root,
        baseline_evidence_state_json=args.baseline_evidence_state_json or None,
        output_root=args.output_root,
        execute_commands=bool(args.execute_commands),
        max_groups=args.max_groups,
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
    "STAGE6_REVIEW_ACTION_DISPATCH_RUNNER_KIND",
    "run_stage6_review_action_dispatch_runner",
]
