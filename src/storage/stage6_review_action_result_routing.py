from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


STAGE6_REVIEW_ACTION_RESULT_ROUTING_KIND = "stage6_review_action_result_routing_v1_manifest"
STAGE6_REVIEW_ACTION_RESULT_ROUTING_VERSION = 1
STAGE6_REVIEW_ACTION_RESULT_ROUTING_ADAPTER_ID = "stage6-review-action-result-routing-v1"

DEFAULT_DISPATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-result-routing-v1")
DEFAULT_BASELINE_EVIDENCE_STATE_ROOT = Path("tmp/evaluation-real-samples/evidence-orchestration-state-v1")
DEFAULT_EVIDENCE_STATE_REBUILD_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/evidence-state-rebuild-from-stage6-routing-v1"
)
DEFAULT_RELEASE_EVIDENCE_FIELD_QUERY_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/release-evidence-field-query-from-stage6-routing-v1"
)

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")


def build_stage6_review_action_result_routing(
    *,
    dispatch_closeout_json: str | Path | None = None,
    dispatch_closeout_root: str | Path = DEFAULT_DISPATCH_CLOSEOUT_ROOT,
    baseline_evidence_state_json: str | Path | None = None,
    baseline_evidence_state_root: str | Path | None = DEFAULT_BASELINE_EVIDENCE_STATE_ROOT,
    evidence_state_rebuild_output_root: str | Path = DEFAULT_EVIDENCE_STATE_REBUILD_OUTPUT_ROOT,
    release_evidence_field_query_output_root: str | Path = DEFAULT_RELEASE_EVIDENCE_FIELD_QUERY_OUTPUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    closeout_path = (
        Path(dispatch_closeout_json)
        if dispatch_closeout_json
        else Path(dispatch_closeout_root) / "stage6-review-action-dispatch-closeout-v1.json"
    )
    closeout_payload = _load_json(
        closeout_path,
        blocking_reasons,
        "stage6_review_action_dispatch_closeout_missing_or_invalid",
    )
    closeout_manifest = _source_manifest(closeout_payload)
    closeout_records = [
        dict(record)
        for record in _list(
            (closeout_manifest.get("dispatch_closeout_table") or {}).get("records")
            if isinstance(closeout_manifest.get("dispatch_closeout_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    if closeout_payload and not closeout_records:
        blocking_reasons.append("stage6_review_dispatch_closeout_records_missing")

    baseline_path = _optional_json_path(
        explicit_json=baseline_evidence_state_json,
        root=baseline_evidence_state_root,
        default_file_name="evidence-orchestration-state-v1.json",
    )
    baseline_payload = _load_json_if_exists(baseline_path)
    baseline_manifest = _source_manifest(baseline_payload)
    baseline_args = _baseline_evidence_state_args(baseline_manifest)

    routing_records = [
        _routing_record(
            record,
            baseline_args=baseline_args,
            evidence_state_rebuild_output_root=str(evidence_state_rebuild_output_root),
            release_evidence_field_query_output_root=str(release_evidence_field_query_output_root),
            created_at=created,
        )
        for record in closeout_records
    ]
    summary = _summary(routing_records=routing_records, blocking_reasons=blocking_reasons)
    manifest = {
        "manifest_version": STAGE6_REVIEW_ACTION_RESULT_ROUTING_VERSION,
        "manifest_kind": STAGE6_REVIEW_ACTION_RESULT_ROUTING_KIND,
        "adapter_id": STAGE6_REVIEW_ACTION_RESULT_ROUTING_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewActionResultRoutingV1",
        "manifest_id": f"STAGE6-REVIEW-ACTION-RESULT-ROUTING-{_fingerprint({'summary': summary, 'records': routing_records})[:16]}",
        "created_at": created,
        "source_dispatch_closeout_json": str(closeout_path),
        "source_dispatch_closeout_manifest_id": str(closeout_manifest.get("manifest_id") or ""),
        "source_baseline_evidence_state_json": str(baseline_path or ""),
        "source_baseline_evidence_state_manifest_id": str(baseline_manifest.get("manifest_id") or ""),
        "baseline_evidence_state_args": baseline_args,
        "result_routing_table": {"records": routing_records, "summary": summary},
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
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage6_review_action_result_routing_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, routing_records)
    return result


def _routing_record(
    record: Mapping[str, Any],
    *,
    baseline_args: Mapping[str, str],
    evidence_state_rebuild_output_root: str,
    release_evidence_field_query_output_root: str,
    created_at: str,
) -> dict[str, Any]:
    dispatch_task_type = str(record.get("dispatch_task_type") or "")
    result_json_path = str(record.get("result_json_path") or "")
    routing_state, next_task_type, script, command_template, input_arg_name = _routing_decision(
        closeout_state=str(record.get("dispatch_closeout_state") or ""),
        dispatch_task_type=dispatch_task_type,
    )
    command = _recommended_command(
        next_task_type=next_task_type,
        input_arg_name=input_arg_name,
        result_json_path=result_json_path,
        baseline_args=baseline_args,
        evidence_state_rebuild_output_root=evidence_state_rebuild_output_root,
        release_evidence_field_query_output_root=release_evidence_field_query_output_root,
    )
    return {
        "result_routing_id": _stable_id(
            "S6-RESULT-ROUTE",
            record.get("dispatch_closeout_id"),
            dispatch_task_type,
            routing_state,
        ),
        "dispatch_closeout_id": str(record.get("dispatch_closeout_id") or ""),
        "dispatch_task_id": str(record.get("dispatch_task_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "dispatch_task_type": dispatch_task_type,
        "dispatch_closeout_state": str(record.get("dispatch_closeout_state") or ""),
        "result_routing_state": routing_state,
        "next_task_type": next_task_type,
        "recommended_script": script,
        "recommended_command_template": command_template,
        "recommended_command": command,
        "recommended_command_ready": bool(command),
        "result_json_path": result_json_path,
        "result_json_exists": bool(record.get("result_json_exists")),
        "result_manifest_id": str(record.get("result_manifest_id") or ""),
        "input_arg_name_for_result_json": input_arg_name,
        "required_baseline_input_refs": _required_baseline_input_refs(next_task_type),
        "resolved_baseline_input_refs": _resolved_baseline_input_refs(next_task_type, baseline_args),
        "next_required_input_refs": _next_required_input_refs(record, routing_state, input_arg_name, next_task_type),
        "next_recommended_action": _next_recommended_action(routing_state, next_task_type),
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "live_execution_enabled": False,
        "requires_operator_action_before_live": True,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _recommended_command(
    *,
    next_task_type: str,
    input_arg_name: str,
    result_json_path: str,
    baseline_args: Mapping[str, str],
    evidence_state_rebuild_output_root: str,
    release_evidence_field_query_output_root: str,
) -> str:
    if next_task_type.startswith("REBUILD_EVIDENCE_STATE_WITH_") and result_json_path:
        args = dict(baseline_args)
        args[input_arg_name] = result_json_path
        args["OutputRoot"] = evidence_state_rebuild_output_root
        return _powershell_command("scripts/build-evidence-orchestration-state-v1.ps1", args)
    if next_task_type == "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE" and result_json_path:
        return _powershell_command(
            "scripts/run-guangdong-local-field-query-probe-v1.ps1",
            {
                input_arg_name: result_json_path,
                "OutputRoot": release_evidence_field_query_output_root,
            },
        )
    return ""


def _routing_decision(
    *,
    closeout_state: str,
    dispatch_task_type: str,
) -> tuple[str, str, str, str, str]:
    if closeout_state == "READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE":
        if dispatch_task_type == "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW":
            return (
                "READY_FOR_EVIDENCE_STATE_REBUILD",
                "REBUILD_EVIDENCE_STATE_WITH_ORIGINAL_BACKTRACE_CONTINUATION",
                "scripts/build-evidence-orchestration-state-v1.ps1",
                (
                    "pwsh -NoProfile -ExecutionPolicy Bypass -File "
                    "scripts/build-evidence-orchestration-state-v1.ps1 "
                    "-Stage16StorageJson <stage16_storage_json> "
                    "-OriginalBacktraceContinuationJson <result_json_path> "
                    "-OutputRoot <evidence_state_rebuild_output_root>"
                ),
                "OriginalBacktraceContinuationJson",
            )
        if dispatch_task_type == "RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW":
            return (
                "READY_FOR_EVIDENCE_STATE_REBUILD",
                "REBUILD_EVIDENCE_STATE_WITH_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
                "scripts/build-evidence-orchestration-state-v1.ps1",
                (
                    "pwsh -NoProfile -ExecutionPolicy Bypass -File "
                    "scripts/build-evidence-orchestration-state-v1.ps1 "
                    "-Stage16StorageJson <stage16_storage_json> "
                    "-DesignSurveyPublicRegistryReadbackJson <result_json_path> "
                    "-OutputRoot <evidence_state_rebuild_output_root>"
                ),
                "DesignSurveyPublicRegistryReadbackJson",
            )
        return (
            "MANUAL_ROUTING_REVIEW_REQUIRED",
            "MANUAL_EVIDENCE_STATE_REBUILD_REVIEW",
            "",
            "",
            "",
        )
    if closeout_state == "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY":
        return (
            "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY",
            "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE",
            "scripts/run-guangdong-local-field-query-probe-v1.ps1",
            (
                "pwsh -NoProfile -ExecutionPolicy Bypass -File "
                "scripts/run-guangdong-local-field-query-probe-v1.ps1 "
                "-ReleaseEvidenceAdapterPlanJson <result_json_path> "
                "-OutputRoot <release_evidence_field_query_output_root>"
            ),
            "ReleaseEvidenceAdapterPlanJson",
        )
    if closeout_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return (
            "WAITING_FOR_CONTROLLED_EXECUTION",
            "RUN_OR_SKIP_DISPATCH_TASK",
            "",
            "",
            "",
        )
    if closeout_state == "PARKED_OPERATOR_SKIPPED_THIS_ROUND":
        return (
            "PARKED_OPERATOR_SKIPPED_THIS_ROUND",
            "KEEP_INTERNAL_REVIEW_OR_REOPEN",
            "",
            "",
            "",
        )
    return (
        "BLOCKED_OR_MANUAL_REVIEW_REQUIRED",
        "RESOLVE_DISPATCH_OR_RESULT_BLOCKER",
        "",
        "",
        "",
    )


def _required_baseline_input_refs(next_task_type: str) -> list[str]:
    if next_task_type.startswith("REBUILD_EVIDENCE_STATE_WITH_"):
        return [
            "stage16_storage_json",
            "prior_evidence_state_inputs_to_preserve_existing_context",
        ]
    if next_task_type == "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE":
        return ["release_evidence_adapter_plan_json"]
    return []


def _resolved_baseline_input_refs(next_task_type: str, baseline_args: Mapping[str, str]) -> dict[str, str]:
    if not next_task_type.startswith("REBUILD_EVIDENCE_STATE_WITH_"):
        return {}
    return {key: value for key, value in baseline_args.items() if value}


def _next_required_input_refs(
    record: Mapping[str, Any],
    routing_state: str,
    input_arg_name: str,
    next_task_type: str,
) -> list[str]:
    if routing_state in {
        "READY_FOR_EVIDENCE_STATE_REBUILD",
        "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY",
    }:
        return _dedupe([input_arg_name, *_required_baseline_input_refs(next_task_type)])
    return _dedupe(_list(record.get("next_required_input_refs")))


def _next_recommended_action(routing_state: str, next_task_type: str) -> str:
    if routing_state == "READY_FOR_EVIDENCE_STATE_REBUILD":
        return "rebuild_evidence_orchestration_state_then_rebuild_batch_closeout_and_stage6"
    if routing_state == "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY":
        return "run_release_evidence_field_query_probe_then_dispatch_readback_again"
    if routing_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return "run_controlled_dispatch_task_or_record_operator_skip"
    if routing_state == "PARKED_OPERATOR_SKIPPED_THIS_ROUND":
        return "keep_internal_review_until_operator_reopens_or_closes_task"
    return "resolve_routing_or_result_blocker_before_retry"


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


def _powershell_command(script_path: str, args: Mapping[str, str]) -> str:
    parts = [
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
        parts.append(f"-{key}")
        parts.append(_ps_quote(text))
    return " ".join(parts)


def _ps_quote(value: str) -> str:
    return '"' + value.replace('"', '`"') + '"'


def _summary(
    *,
    routing_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "stage6_review_action_result_routing_state": (
            "STAGE6_REVIEW_ACTION_RESULT_ROUTING_READY"
            if not blocking_reasons
            else "STAGE6_REVIEW_ACTION_RESULT_ROUTING_INPUT_BLOCKED"
        ),
        "result_routing_count": len(routing_records),
        "result_routing_state_counts": _counts(record.get("result_routing_state") for record in routing_records),
        "next_task_type_counts": _counts(record.get("next_task_type") for record in routing_records),
        "evidence_state_rebuild_ready_count": sum(
            1 for record in routing_records if record.get("result_routing_state") == "READY_FOR_EVIDENCE_STATE_REBUILD"
        ),
        "release_evidence_field_query_ready_count": sum(
            1 for record in routing_records if record.get("result_routing_state") == "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY"
        ),
        "recommended_command_ready_count": sum(
            1 for record in routing_records if record.get("recommended_command_ready")
        ),
        "waiting_for_controlled_execution_count": sum(
            1 for record in routing_records if record.get("result_routing_state") == "WAITING_FOR_CONTROLLED_EXECUTION"
        ),
        "blocked_or_review_count": sum(
            1
            for record in routing_records
            if record.get("result_routing_state") == "BLOCKED_OR_MANUAL_REVIEW_REQUIRED"
            or record.get("result_routing_state") == "MANUAL_ROUTING_REVIEW_REQUIRED"
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
    routing_records: list[Mapping[str, Any]],
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
    _write_json(out_dir / "stage6-review-result-routing-table.json", {"summary": result["summary"], "records": routing_records})
    _write_json(out_dir / "stage6-review-action-result-routing-v1.json", result)


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


def _optional_json_path(*, explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> Path | None:
    if explicit_json:
        return Path(explicit_json)
    if root:
        return Path(root) / default_file_name
    return None


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route Stage6 dispatch closeout results to next controlled tasks.")
    parser.add_argument("--dispatch-closeout-json", default="")
    parser.add_argument("--dispatch-closeout-root", default=str(DEFAULT_DISPATCH_CLOSEOUT_ROOT))
    parser.add_argument("--baseline-evidence-state-json", default="")
    parser.add_argument("--baseline-evidence-state-root", default=str(DEFAULT_BASELINE_EVIDENCE_STATE_ROOT))
    parser.add_argument("--evidence-state-rebuild-output-root", default=str(DEFAULT_EVIDENCE_STATE_REBUILD_OUTPUT_ROOT))
    parser.add_argument(
        "--release-evidence-field-query-output-root",
        default=str(DEFAULT_RELEASE_EVIDENCE_FIELD_QUERY_OUTPUT_ROOT),
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_stage6_review_action_result_routing(
        dispatch_closeout_json=args.dispatch_closeout_json or None,
        dispatch_closeout_root=args.dispatch_closeout_root,
        baseline_evidence_state_json=args.baseline_evidence_state_json or None,
        baseline_evidence_state_root=args.baseline_evidence_state_root or None,
        evidence_state_rebuild_output_root=args.evidence_state_rebuild_output_root,
        release_evidence_field_query_output_root=args.release_evidence_field_query_output_root,
        output_root=args.output_root,
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
    "STAGE6_REVIEW_ACTION_RESULT_ROUTING_KIND",
    "build_stage6_review_action_result_routing",
]
