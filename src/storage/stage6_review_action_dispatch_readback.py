from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


STAGE6_REVIEW_ACTION_DISPATCH_READBACK_KIND = "stage6_review_action_dispatch_readback_v1_manifest"
STAGE6_REVIEW_ACTION_DISPATCH_READBACK_VERSION = 1
STAGE6_REVIEW_ACTION_DISPATCH_READBACK_ADAPTER_ID = "stage6-review-action-dispatch-readback-v1"

DEFAULT_DISPATCH_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-readback-v1")

DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_ROOT = Path("tmp/evaluation-real-samples/release-evidence-adapter-plan-v1")
DEFAULT_EVIDENCE_ORCHESTRATION_CONTINUATION_ROOT = Path(
    "tmp/evaluation-real-samples/evidence-orchestration-continuation-run-v1"
)
DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT = Path(
    "tmp/evaluation-real-samples/design-survey-public-registry-readback-v1"
)

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

RESULT_ARTIFACT_BY_TASK_TYPE = {
    "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN": "release-evidence-adapter-plan-v1.json",
    "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW": "evidence-orchestration-continuation-run-v1.json",
    "RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW": "design-survey-public-registry-readback-v1.json",
}


def build_stage6_review_action_dispatch_readback(
    *,
    dispatch_json: str | Path | None = None,
    dispatch_root: str | Path = DEFAULT_DISPATCH_ROOT,
    release_evidence_adapter_plan_json: str | Path | None = None,
    release_evidence_adapter_plan_root: str | Path | None = DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_ROOT,
    evidence_orchestration_continuation_json: str | Path | None = None,
    evidence_orchestration_continuation_root: str | Path | None = DEFAULT_EVIDENCE_ORCHESTRATION_CONTINUATION_ROOT,
    design_survey_public_registry_readback_json: str | Path | None = None,
    design_survey_public_registry_readback_root: str | Path | None = DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT,
    dispatch_decision_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
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

    decisions = _decision_index(dispatch_decision_json)
    result_sources = _result_sources(
        release_evidence_adapter_plan_json=release_evidence_adapter_plan_json,
        release_evidence_adapter_plan_root=release_evidence_adapter_plan_root,
        evidence_orchestration_continuation_json=evidence_orchestration_continuation_json,
        evidence_orchestration_continuation_root=evidence_orchestration_continuation_root,
        design_survey_public_registry_readback_json=design_survey_public_registry_readback_json,
        design_survey_public_registry_readback_root=design_survey_public_registry_readback_root,
    )
    readback_records = [
        _readback_record(
            task,
            decision=decisions.get(str(task.get("dispatch_task_id") or ""))
            or decisions.get(str(task.get("project_id") or "")),
            result_sources=result_sources,
            created_at=created,
        )
        for task in dispatch_records
    ]
    summary = _summary(
        dispatch_records=dispatch_records,
        readback_records=readback_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": STAGE6_REVIEW_ACTION_DISPATCH_READBACK_VERSION,
        "manifest_kind": STAGE6_REVIEW_ACTION_DISPATCH_READBACK_KIND,
        "adapter_id": STAGE6_REVIEW_ACTION_DISPATCH_READBACK_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewActionDispatchReadbackV1",
        "manifest_id": f"STAGE6-REVIEW-ACTION-DISPATCH-READBACK-{_fingerprint({'summary': summary, 'records': readback_records})[:16]}",
        "created_at": created,
        "source_dispatch_json": str(dispatch_path),
        "source_dispatch_manifest_id": str(dispatch_manifest.get("manifest_id") or ""),
        "source_dispatch_decision_json": str(dispatch_decision_json or ""),
        "result_source_paths": {key: str(value.get("path") or "") for key, value in result_sources.items()},
        "dispatch_readback_table": {"records": readback_records, "summary": summary},
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
        "stage6_review_action_dispatch_readback_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, readback_records)
    return result


def _readback_record(
    task: Mapping[str, Any],
    *,
    decision: Mapping[str, Any] | None,
    result_sources: Mapping[str, Mapping[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    dispatch_task_type = str(task.get("dispatch_task_type") or "")
    source = result_sources.get(dispatch_task_type, {})
    output_payload = source.get("payload") if isinstance(source.get("payload"), Mapping) else {}
    output_manifest = _source_manifest(output_payload)
    decision_state = str((decision or {}).get("dispatch_decision") or "").upper()
    output_path = Path(str(source.get("path") or "")) if source.get("path") else None
    output_exists = bool(output_path and output_path.exists())
    readback_state = _readback_state(
        task=task,
        decision_state=decision_state,
        output_exists=output_exists,
        output_payload=output_payload,
    )
    output_blocking_reasons = _dedupe(
        [
            *_list(output_payload.get("blocking_reasons")),
            *_list((output_payload.get("summary") or {}).get("blocking_reasons") if isinstance(output_payload.get("summary"), Mapping) else []),
            *_list((output_manifest.get("summary") or {}).get("blocking_reasons") if isinstance(output_manifest.get("summary"), Mapping) else []),
        ]
    )
    return {
        "dispatch_readback_id": _stable_id(
            "S6-DISPATCH-READBACK",
            task.get("dispatch_task_id"),
            dispatch_task_type,
            readback_state,
        ),
        "dispatch_task_id": str(task.get("dispatch_task_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "project_name": str(task.get("project_name") or ""),
        "dispatch_task_type": dispatch_task_type,
        "action_family": str(task.get("action_family") or ""),
        "dispatch_readiness_state": str(task.get("dispatch_readiness_state") or ""),
        "dispatch_status": str(task.get("dispatch_status") or ""),
        "dispatch_readback_state": readback_state,
        "dispatch_decision": decision_state,
        "dispatch_decision_reason": str((decision or {}).get("reason") or ""),
        "recommended_script": str(task.get("recommended_script") or ""),
        "expected_output_artifact": str(
            task.get("expected_output_artifact")
            or RESULT_ARTIFACT_BY_TASK_TYPE.get(dispatch_task_type)
            or ""
        ),
        "result_json_path": str(output_path or ""),
        "result_json_exists": output_exists,
        "result_manifest_id": str(output_manifest.get("manifest_id") or ""),
        "result_safe_to_execute": bool(output_payload.get("safe_to_execute")) if output_payload else False,
        "result_blocking_reasons": output_blocking_reasons,
        "next_required_input_refs": _next_required_input_refs(task, readback_state),
        "next_recommended_action": _next_recommended_action(task, readback_state),
        "execution_mode": "READBACK_ONLY_NOT_EXECUTED",
        "live_execution_enabled": False,
        "requires_operator_action_before_live": True,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _readback_state(
    *,
    task: Mapping[str, Any],
    decision_state: str,
    output_exists: bool,
    output_payload: Mapping[str, Any],
) -> str:
    if str(task.get("dispatch_readiness_state") or "") != "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_PLAN":
        return "BLOCKED_DISPATCH_NOT_READY"
    if decision_state == "SKIPPED":
        return "SKIPPED_BY_OPERATOR"
    if decision_state == "BLOCKED":
        return "BLOCKED_BY_OPERATOR_DECISION"
    if not output_exists:
        return "WAITING_FOR_CONTROLLED_EXECUTION"
    if not output_payload:
        return "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED"
    if output_payload and not bool(output_payload.get("safe_to_execute", True)):
        return "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED"
    blocking_reasons = _dedupe(
        [
            *_list(output_payload.get("blocking_reasons")),
            *_list((output_payload.get("summary") or {}).get("blocking_reasons") if isinstance(output_payload.get("summary"), Mapping) else []),
        ]
    )
    if blocking_reasons:
        return "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED"
    return "EXECUTION_OUTPUT_READY"


def _next_required_input_refs(task: Mapping[str, Any], readback_state: str) -> list[str]:
    if readback_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return _dedupe(_list(task.get("required_input_refs")))
    if readback_state in {"BLOCKED_DISPATCH_NOT_READY", "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED"}:
        return _dedupe(
            [
                *(_list(task.get("required_input_refs"))),
                "operator_review_or_missing_result_artifact",
            ]
        )
    return []


def _next_recommended_action(task: Mapping[str, Any], readback_state: str) -> str:
    if readback_state == "EXECUTION_OUTPUT_READY":
        return "feed_result_artifact_back_into_evidence_state_or_stage6_closeout"
    if readback_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return "run_recommended_script_in_controlled_internal_mode_or_record_skip_decision"
    if readback_state == "SKIPPED_BY_OPERATOR":
        return "keep_task_open_or_close_with_operator_skip_reason"
    if readback_state == "BLOCKED_BY_OPERATOR_DECISION":
        return "resolve_operator_blocker_before_retry"
    return "review_dispatch_inputs_and_result_blockers_before_retry"


def _result_sources(
    *,
    release_evidence_adapter_plan_json: str | Path | None,
    release_evidence_adapter_plan_root: str | Path | None,
    evidence_orchestration_continuation_json: str | Path | None,
    evidence_orchestration_continuation_root: str | Path | None,
    design_survey_public_registry_readback_json: str | Path | None,
    design_survey_public_registry_readback_root: str | Path | None,
) -> dict[str, dict[str, Any]]:
    return {
        "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN": _optional_result_source(
            explicit_json=release_evidence_adapter_plan_json,
            root=release_evidence_adapter_plan_root,
            default_file_name="release-evidence-adapter-plan-v1.json",
        ),
        "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW": _optional_result_source(
            explicit_json=evidence_orchestration_continuation_json,
            root=evidence_orchestration_continuation_root,
            default_file_name="evidence-orchestration-continuation-run-v1.json",
        ),
        "RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW": _optional_result_source(
            explicit_json=design_survey_public_registry_readback_json,
            root=design_survey_public_registry_readback_root,
            default_file_name="design-survey-public-registry-readback-v1.json",
        ),
    }


def _optional_result_source(
    *,
    explicit_json: str | Path | None,
    root: str | Path | None,
    default_file_name: str,
) -> dict[str, Any]:
    path: Path | None = None
    if explicit_json:
        path = Path(explicit_json)
    elif root:
        path = Path(root) / default_file_name
    payload = _load_json_if_exists(path)
    return {"path": path, "payload": payload}


def _decision_index(dispatch_decision_json: str | Path | None) -> dict[str, Mapping[str, Any]]:
    if not dispatch_decision_json:
        return {}
    payload = _load_json_if_exists(Path(dispatch_decision_json))
    manifest = _source_manifest(payload)
    records = [
        record
        for record in _list(manifest.get("dispatch_decision_records") or payload.get("dispatch_decision_records"))
        if isinstance(record, Mapping)
    ]
    out: dict[str, Mapping[str, Any]] = {}
    for record in records:
        dispatch_task_id = str(record.get("dispatch_task_id") or "").strip()
        project_id = str(record.get("project_id") or "").strip()
        if dispatch_task_id:
            out[dispatch_task_id] = record
        if project_id:
            out[project_id] = record
    return out


def _summary(
    *,
    dispatch_records: list[Mapping[str, Any]],
    readback_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "stage6_review_action_dispatch_readback_state": (
            "STAGE6_REVIEW_ACTION_DISPATCH_READBACK_READY"
            if not blocking_reasons
            else "STAGE6_REVIEW_ACTION_DISPATCH_READBACK_INPUT_BLOCKED"
        ),
        "source_dispatch_task_count": len(dispatch_records),
        "dispatch_readback_count": len(readback_records),
        "dispatch_readback_state_counts": _counts(record.get("dispatch_readback_state") for record in readback_records),
        "dispatch_task_type_counts": _counts(record.get("dispatch_task_type") for record in readback_records),
        "execution_output_ready_count": sum(
            1 for record in readback_records if record.get("dispatch_readback_state") == "EXECUTION_OUTPUT_READY"
        ),
        "waiting_for_controlled_execution_count": sum(
            1
            for record in readback_records
            if record.get("dispatch_readback_state") == "WAITING_FOR_CONTROLLED_EXECUTION"
        ),
        "operator_skipped_count": sum(
            1 for record in readback_records if record.get("dispatch_readback_state") == "SKIPPED_BY_OPERATOR"
        ),
        "blocked_or_review_count": sum(
            1
            for record in readback_records
            if str(record.get("dispatch_readback_state") or "").startswith("BLOCKED")
            or record.get("dispatch_readback_state") == "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED"
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
    readback_records: list[Mapping[str, Any]],
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
    _write_json(out_dir / "stage6-review-dispatch-readback-table.json", {"summary": result["summary"], "records": readback_records})
    _write_json(out_dir / "stage6-review-action-dispatch-readback-v1.json", result)


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read back Stage6 review action dispatch execution artifacts.")
    parser.add_argument("--dispatch-json", default="")
    parser.add_argument("--dispatch-root", default=str(DEFAULT_DISPATCH_ROOT))
    parser.add_argument("--release-evidence-adapter-plan-json", default="")
    parser.add_argument("--release-evidence-adapter-plan-root", default=str(DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_ROOT))
    parser.add_argument("--evidence-orchestration-continuation-json", default="")
    parser.add_argument(
        "--evidence-orchestration-continuation-root",
        default=str(DEFAULT_EVIDENCE_ORCHESTRATION_CONTINUATION_ROOT),
    )
    parser.add_argument("--design-survey-public-registry-readback-json", default="")
    parser.add_argument(
        "--design-survey-public-registry-readback-root",
        default=str(DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT),
    )
    parser.add_argument("--dispatch-decision-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_stage6_review_action_dispatch_readback(
        dispatch_json=args.dispatch_json or None,
        dispatch_root=args.dispatch_root,
        release_evidence_adapter_plan_json=args.release_evidence_adapter_plan_json or None,
        release_evidence_adapter_plan_root=args.release_evidence_adapter_plan_root or None,
        evidence_orchestration_continuation_json=args.evidence_orchestration_continuation_json or None,
        evidence_orchestration_continuation_root=args.evidence_orchestration_continuation_root or None,
        design_survey_public_registry_readback_json=args.design_survey_public_registry_readback_json or None,
        design_survey_public_registry_readback_root=args.design_survey_public_registry_readback_root or None,
        dispatch_decision_json=args.dispatch_decision_json or None,
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
    "STAGE6_REVIEW_ACTION_DISPATCH_READBACK_KIND",
    "build_stage6_review_action_dispatch_readback",
]
