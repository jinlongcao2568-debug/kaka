from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


STAGE6_REVIEW_ACTION_RESULT_RUNNER_KIND = "stage6_review_action_result_runner_v1_manifest"
STAGE6_REVIEW_ACTION_RESULT_RUNNER_VERSION = 1
STAGE6_REVIEW_ACTION_RESULT_RUNNER_ADAPTER_ID = "stage6-review-action-result-runner-v1"

DEFAULT_RESULT_ROUTING_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-result-routing-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-result-runner-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

ALLOWED_SCRIPT_BY_NEXT_TASK = {
    "REBUILD_EVIDENCE_STATE_WITH_ORIGINAL_BACKTRACE_CONTINUATION": "scripts/build-evidence-orchestration-state-v1.ps1",
    "REBUILD_EVIDENCE_STATE_WITH_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK": "scripts/build-evidence-orchestration-state-v1.ps1",
    "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE": "scripts/run-guangdong-local-field-query-probe-v1.ps1",
    "REBUILD_BATCH_CLOSEOUT_WITH_CONTINUATION_RUN": "scripts/build-evidence-batch-closeout-v1.ps1",
}

EXPECTED_ARTIFACT_BY_NEXT_TASK = {
    "REBUILD_EVIDENCE_STATE_WITH_ORIGINAL_BACKTRACE_CONTINUATION": "evidence-orchestration-state-v1.json",
    "REBUILD_EVIDENCE_STATE_WITH_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK": "evidence-orchestration-state-v1.json",
    "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE": "guangdong-local-field-query-probe-v1.json",
    "REBUILD_BATCH_CLOSEOUT_WITH_CONTINUATION_RUN": "evidence-batch-closeout-v1.json",
}

LIVE_OR_EXTERNAL_FLAGS = {
    "-enablelivepublicquery",
    "-enableliveoriginalnoticebacktrace",
    "-enablelivetargetedpersonreadback",
    "-downloadtargetedpersonattachments",
    "-executelivepublicregistryentryreadback",
    "--enable-live-public-query",
    "--enable-live-original-notice-backtrace",
    "--enable-live-targeted-person-readback",
    "--download-targeted-person-attachments",
    "--execute-live-public-registry-entry-readback",
}

CommandExecutor = Callable[[list[str], Path], Mapping[str, Any]]


def run_stage6_review_action_result_runner(
    *,
    result_routing_json: str | Path | None = None,
    result_routing_root: str | Path = DEFAULT_RESULT_ROUTING_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute_commands: bool = False,
    max_commands: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    cwd: str | Path | None = None,
    created_at: str | None = None,
    command_executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    routing_path = (
        Path(result_routing_json)
        if result_routing_json
        else Path(result_routing_root) / "stage6-review-action-result-routing-v1.json"
    )
    routing_payload = _load_json(
        routing_path,
        blocking_reasons,
        "stage6_review_action_result_routing_missing_or_invalid",
    )
    routing_manifest = _source_manifest(routing_payload)
    routing_records = [
        dict(record)
        for record in _list(
            (routing_manifest.get("result_routing_table") or {}).get("records")
            if isinstance(routing_manifest.get("result_routing_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    if routing_payload and not routing_records:
        blocking_reasons.append("stage6_review_action_result_routing_records_missing")

    selected_project_ids = {str(project_id).strip() for project_id in project_ids if str(project_id).strip()}
    repo_cwd = Path(cwd) if cwd else Path.cwd()
    executor = command_executor or _execute_subprocess
    command_limit = None if max_commands is None else max(0, int(max_commands))
    selected_command_count = 0
    seen_command_keys: set[str] = set()
    runner_records: list[dict[str, Any]] = []

    for record in routing_records:
        project_id = str(record.get("project_id") or "").strip()
        argv = _recommended_argv(record)
        command_key = _command_key(argv)
        execution_state = ""
        skip_reason = ""
        allowlist_state = "NOT_APPLICABLE"
        allowlist_reason = ""
        command_result: Mapping[str, Any] = {}

        if selected_project_ids and project_id not in selected_project_ids:
            execution_state = "SKIPPED_BY_PROJECT_FILTER"
            skip_reason = "project_id_not_selected"
        elif not bool(record.get("recommended_command_ready")):
            execution_state = "SKIPPED_NOT_READY"
            skip_reason = "recommended_command_not_ready"
        elif command_key in seen_command_keys:
            execution_state = "SKIPPED_DUPLICATE_COMMAND"
            skip_reason = "same_recommended_command_already_selected"
        elif command_limit is not None and selected_command_count >= command_limit:
            execution_state = "SKIPPED_BY_MAX_COMMANDS"
            skip_reason = "max_commands_reached"
        else:
            seen_command_keys.add(command_key)
            allowlist_state, allowlist_reason = _allowlist_state(record, argv)
            if allowlist_state != "ALLOWLIST_PASS":
                selected_command_count += 1
                execution_state = "BLOCKED_BY_ALLOWLIST"
                skip_reason = allowlist_reason
            elif not execute_commands:
                selected_command_count += 1
                execution_state = "DRY_RUN_READY"
                skip_reason = "execute_commands_false"
            else:
                selected_command_count += 1
                command_result = executor(argv, repo_cwd)
                execution_state = (
                    "EXECUTED_SUCCEEDED" if int(command_result.get("exit_code") or 0) == 0 else "EXECUTED_FAILED"
                )

        runner_records.append(
            _runner_record(
                record,
                argv=argv,
                execution_state=execution_state,
                skip_reason=skip_reason,
                allowlist_state=allowlist_state,
                allowlist_reason=allowlist_reason,
                command_result=command_result,
                created_at=created,
            )
        )

    summary = _summary(
        runner_records=runner_records,
        blocking_reasons=blocking_reasons,
        execute_commands=execute_commands,
    )
    manifest = {
        "manifest_version": STAGE6_REVIEW_ACTION_RESULT_RUNNER_VERSION,
        "manifest_kind": STAGE6_REVIEW_ACTION_RESULT_RUNNER_KIND,
        "adapter_id": STAGE6_REVIEW_ACTION_RESULT_RUNNER_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewActionResultRunnerV1",
        "manifest_id": f"STAGE6-REVIEW-ACTION-RESULT-RUNNER-{_fingerprint({'summary': summary, 'records': runner_records})[:16]}",
        "created_at": created,
        "source_result_routing_json": str(routing_path),
        "source_result_routing_manifest_id": str(routing_manifest.get("manifest_id") or ""),
        "execute_commands": bool(execute_commands),
        "max_commands": command_limit,
        "project_ids": sorted(selected_project_ids),
        "result_runner_table": {"records": runner_records, "summary": summary},
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
            "executes_only_allowlisted_structured_argv": True,
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
        "stage6_review_action_result_runner_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons and summary["executed_failed_count"] == 0 and summary["allowlist_blocked_count"] == 0,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, runner_records)
    return result


def _runner_record(
    record: Mapping[str, Any],
    *,
    argv: list[str],
    execution_state: str,
    skip_reason: str,
    allowlist_state: str,
    allowlist_reason: str,
    command_result: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    next_task_type = str(record.get("next_task_type") or "")
    output_root = _arg_value(argv, "-OutputRoot")
    expected_artifact = EXPECTED_ARTIFACT_BY_NEXT_TASK.get(next_task_type, "")
    expected_artifact_path = str(Path(output_root) / expected_artifact) if output_root and expected_artifact else ""
    return {
        "result_runner_id": _stable_id(
            "S6-RESULT-RUNNER",
            record.get("result_routing_id"),
            execution_state,
        ),
        "result_routing_id": str(record.get("result_routing_id") or ""),
        "dispatch_closeout_id": str(record.get("dispatch_closeout_id") or ""),
        "dispatch_task_id": str(record.get("dispatch_task_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "dispatch_task_type": str(record.get("dispatch_task_type") or ""),
        "result_routing_state": str(record.get("result_routing_state") or ""),
        "next_task_type": next_task_type,
        "execution_state": execution_state,
        "skip_reason": skip_reason,
        "allowlist_state": allowlist_state,
        "allowlist_reason": allowlist_reason,
        "recommended_script": str(record.get("recommended_script") or ""),
        "recommended_command": str(record.get("recommended_command") or ""),
        "recommended_command_argv": argv,
        "expected_output_root": output_root,
        "expected_output_artifact": expected_artifact,
        "expected_output_artifact_path": expected_artifact_path,
        "exit_code": int(command_result.get("exit_code") or 0) if command_result else None,
        "stdout_excerpt": _truncate(str(command_result.get("stdout") or "")) if command_result else "",
        "stderr_excerpt": _truncate(str(command_result.get("stderr") or "")) if command_result else "",
        "execution_mode": "CONTROLLED_INTERNAL_EXECUTED" if execution_state.startswith("EXECUTED_") else "PLAN_OR_SKIP_ONLY",
        "live_execution_enabled": False,
        "requires_operator_action_before_live": True,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _recommended_argv(record: Mapping[str, Any]) -> list[str]:
    value = record.get("recommended_command_argv")
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _allowlist_state(record: Mapping[str, Any], argv: list[str]) -> tuple[str, str]:
    if not argv:
        return "ALLOWLIST_BLOCKED", "structured_recommended_command_argv_missing"
    if _normalize_exe(argv[0]) not in {"pwsh", "pwsh.exe"}:
        return "ALLOWLIST_BLOCKED", "command_must_start_with_pwsh"
    script = _script_from_argv(argv)
    if not script:
        return "ALLOWLIST_BLOCKED", "powershell_file_script_missing"
    next_task_type = str(record.get("next_task_type") or "")
    expected_script = ALLOWED_SCRIPT_BY_NEXT_TASK.get(next_task_type)
    if not expected_script:
        return "ALLOWLIST_BLOCKED", "next_task_type_not_allowlisted"
    if _normalize_path(script) != _normalize_path(expected_script):
        return "ALLOWLIST_BLOCKED", "recommended_script_does_not_match_next_task_type"
    if any(_is_live_or_external_flag(token) for token in argv):
        return "ALLOWLIST_BLOCKED", "live_or_external_execution_flag_present"
    return "ALLOWLIST_PASS", ""


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


def _script_from_argv(argv: list[str]) -> str:
    for index, token in enumerate(argv[:-1]):
        if token.lower() == "-file":
            return argv[index + 1]
    return ""


def _arg_value(argv: list[str], name: str) -> str:
    expected = name.lower()
    for index, token in enumerate(argv[:-1]):
        if token.lower() == expected:
            return argv[index + 1]
    return ""


def _is_live_or_external_flag(token: str) -> bool:
    lowered = token.lower()
    return lowered in LIVE_OR_EXTERNAL_FLAGS


def _normalize_exe(value: str) -> str:
    return Path(str(value or "")).name.lower()


def _normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip("/").lower()


def _summary(
    *,
    runner_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    execute_commands: bool,
) -> dict[str, Any]:
    return {
        "stage6_review_action_result_runner_state": (
            "STAGE6_REVIEW_ACTION_RESULT_RUNNER_READY"
            if not blocking_reasons
            else "STAGE6_REVIEW_ACTION_RESULT_RUNNER_INPUT_BLOCKED"
        ),
        "execution_mode": "CONTROLLED_INTERNAL_EXECUTION" if execute_commands else "DRY_RUN_NOT_EXECUTED",
        "result_runner_record_count": len(runner_records),
        "execution_state_counts": _counts(record.get("execution_state") for record in runner_records),
        "ready_command_count": sum(
            1
            for record in runner_records
            if record.get("execution_state") in {"DRY_RUN_READY", "EXECUTED_SUCCEEDED", "EXECUTED_FAILED", "BLOCKED_BY_ALLOWLIST"}
        ),
        "dry_run_ready_count": sum(1 for record in runner_records if record.get("execution_state") == "DRY_RUN_READY"),
        "executed_success_count": sum(1 for record in runner_records if record.get("execution_state") == "EXECUTED_SUCCEEDED"),
        "executed_failed_count": sum(1 for record in runner_records if record.get("execution_state") == "EXECUTED_FAILED"),
        "allowlist_blocked_count": sum(1 for record in runner_records if record.get("execution_state") == "BLOCKED_BY_ALLOWLIST"),
        "skipped_not_ready_count": sum(1 for record in runner_records if record.get("execution_state") == "SKIPPED_NOT_READY"),
        "skipped_duplicate_command_count": sum(
            1 for record in runner_records if record.get("execution_state") == "SKIPPED_DUPLICATE_COMMAND"
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
    runner_records: list[Mapping[str, Any]],
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
    _write_json(out_dir / "stage6-review-result-runner-table.json", {"summary": result["summary"], "records": runner_records})
    _write_json(out_dir / "stage6-review-action-result-runner-v1.json", result)


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


def _command_key(argv: list[str]) -> str:
    return _fingerprint(argv)


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _truncate(value: str, limit: int = 4000) -> str:
    return value if len(value) <= limit else value[:limit] + "...<truncated>"


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run allowlisted Stage6 result-routing commands.")
    parser.add_argument("--result-routing-json", default="")
    parser.add_argument("--result-routing-root", default=str(DEFAULT_RESULT_ROUTING_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute", action="store_true", dest="execute_commands")
    parser.add_argument("--max-commands", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_stage6_review_action_result_runner(
        result_routing_json=args.result_routing_json or None,
        result_routing_root=args.result_routing_root,
        output_root=args.output_root,
        execute_commands=bool(args.execute_commands),
        max_commands=args.max_commands,
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
    "STAGE6_REVIEW_ACTION_RESULT_RUNNER_KIND",
    "run_stage6_review_action_result_runner",
]
