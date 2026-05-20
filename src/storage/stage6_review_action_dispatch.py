from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


STAGE6_REVIEW_ACTION_DISPATCH_KIND = "stage6_review_action_dispatch_v1_manifest"
STAGE6_REVIEW_ACTION_DISPATCH_VERSION = 1
STAGE6_REVIEW_ACTION_DISPATCH_ADAPTER_ID = "stage6-review-action-dispatch-v1"

DEFAULT_STAGE6_FACT_PACKAGE_ROOT = Path("tmp/evaluation-real-samples/evidence-stage6-fact-package-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

DISPATCH_SPECS = {
    "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW": {
        "dispatch_task_type": "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
        "recommended_script": "scripts/build-release-evidence-adapter-plan-v1.ps1",
        "recommended_command_template": (
            "pwsh -NoProfile -ExecutionPolicy Bypass -File "
            "scripts/build-release-evidence-adapter-plan-v1.ps1 "
            "-BatchCloseoutRoot <evidence_batch_closeout_root> "
            "-P13bOperationalCloseoutRoot <p13b_operational_closeout_root> "
            "-OutputRoot <release_evidence_adapter_plan_output_root>"
        ),
        "required_input_refs": [
            "evidence_batch_closeout_root",
            "p13b_operational_closeout_root_or_release_source_plan",
        ],
        "expected_output_artifact": "release-evidence-adapter-plan-v1.json",
    },
    "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW": {
        "dispatch_task_type": "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
        "recommended_script": "scripts/run-evidence-orchestration-continuation-v1.ps1",
        "recommended_command_template": (
            "pwsh -NoProfile -ExecutionPolicy Bypass -File "
            "scripts/run-evidence-orchestration-continuation-v1.ps1 "
            "-EvidenceStateRoot <evidence_orchestration_state_root> "
            "-OutputRoot <original_backtrace_continuation_output_root>"
        ),
        "required_input_refs": [
            "evidence_orchestration_state_root_or_json",
            "original_notice_backtrace_root_when_available",
        ],
        "expected_output_artifact": "evidence-orchestration-continuation-run-v1.json",
    },
    "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW": {
        "dispatch_task_type": "RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW",
        "recommended_script": "scripts/build-design-survey-public-registry-readback-v1.ps1",
        "recommended_command_template": (
            "pwsh -NoProfile -ExecutionPolicy Bypass -File "
            "scripts/build-design-survey-public-registry-readback-v1.ps1 "
            "-PublicRegistryFallbackRoot <design_survey_public_registry_fallback_root> "
            "-OutputRoot <design_survey_public_registry_readback_output_root>"
        ),
        "required_input_refs": [
            "design_survey_public_registry_fallback_root_or_provider_jobs_json",
            "public_registry_snapshot_json_or_snapshot_html",
        ],
        "expected_output_artifact": "design-survey-public-registry-readback-v1.json",
    },
}


def build_stage6_review_action_dispatch(
    *,
    stage6_fact_package_json: str | Path | None = None,
    stage6_fact_package_root: str | Path = DEFAULT_STAGE6_FACT_PACKAGE_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    stage6_path = (
        Path(stage6_fact_package_json)
        if stage6_fact_package_json
        else Path(stage6_fact_package_root) / "stage6-fact-package-v1.json"
    )
    stage6_payload = _load_json(stage6_path, blocking_reasons, "stage6_fact_package_missing_or_invalid")
    stage6_manifest = _source_manifest(stage6_payload)
    action_plan_records = [
        dict(record)
        for record in _list(
            (stage6_manifest.get("stage6_review_action_plan_table") or {}).get("records")
            if isinstance(stage6_manifest.get("stage6_review_action_plan_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    if stage6_payload and not action_plan_records:
        blocking_reasons.append("stage6_review_action_plan_records_missing")

    dispatchable_action_plan_records = [
        record for record in action_plan_records if _automated_dispatch_allowed(record)
    ]
    manual_only_action_plan_records = [
        record for record in action_plan_records if not _automated_dispatch_allowed(record)
    ]
    dispatch_task_records = [
        _dispatch_task_record(record, created_at=created)
        for record in dispatchable_action_plan_records
    ]
    summary = _summary(
        action_plan_records=action_plan_records,
        manual_only_action_plan_records=manual_only_action_plan_records,
        dispatch_task_records=dispatch_task_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": STAGE6_REVIEW_ACTION_DISPATCH_VERSION,
        "manifest_kind": STAGE6_REVIEW_ACTION_DISPATCH_KIND,
        "adapter_id": STAGE6_REVIEW_ACTION_DISPATCH_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewActionDispatchV1",
        "manifest_id": f"STAGE6-REVIEW-ACTION-DISPATCH-{_fingerprint({'summary': summary, 'tasks': dispatch_task_records})[:16]}",
        "created_at": created,
        "source_stage6_fact_package_json": str(stage6_path),
        "source_stage6_fact_package_manifest_id": str(stage6_manifest.get("manifest_id") or ""),
        "dispatch_task_table": {"records": dispatch_task_records, "summary": summary},
        "manual_only_action_plan_table": {"records": manual_only_action_plan_records, "summary": summary},
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
        "stage6_review_action_dispatch_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, dispatch_task_records, manual_only_action_plan_records)
    return result


def _automated_dispatch_allowed(record: Mapping[str, Any]) -> bool:
    return bool(record.get("automated_dispatch_allowed", True))


def _dispatch_task_record(record: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    action_family = str(record.get("action_family") or "")
    spec = DISPATCH_SPECS.get(action_family, {})
    action_items = [item for item in _list(record.get("action_items")) if isinstance(item, Mapping)]
    source_refs = dict(record.get("source_refs") or {})
    input_blockers = _dispatch_input_blocking_reasons(action_family=action_family, source_refs=source_refs)
    if not spec or not action_items:
        readiness_state = "BLOCKED_DISPATCH_SPEC_OR_ACTION_ITEMS_MISSING"
    elif input_blockers:
        readiness_state = "BLOCKED_REQUIRED_SOURCE_REFS_MISSING"
    else:
        readiness_state = "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_PLAN"
    return {
        "dispatch_task_id": _stable_id(
            "S6-DISPATCH",
            record.get("review_action_plan_id"),
            record.get("project_id"),
            action_family,
        ),
        "source_review_action_plan_id": str(record.get("review_action_plan_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "review_lane": str(record.get("review_lane") or ""),
        "review_queue_bucket": str(record.get("review_queue_bucket") or ""),
        "review_priority_score": int(record.get("review_priority_score") or 0),
        "primary_evidence_topic_code": str(record.get("primary_evidence_topic_code") or ""),
        "action_family": action_family,
        "dispatch_task_type": str(spec.get("dispatch_task_type") or "MANUAL_STAGE6_REVIEW"),
        "dispatch_readiness_state": readiness_state,
        "recommended_script": str(spec.get("recommended_script") or ""),
        "recommended_command_template": str(spec.get("recommended_command_template") or ""),
        "required_input_refs": list(spec.get("required_input_refs") or []),
        "expected_output_artifact": str(spec.get("expected_output_artifact") or ""),
        "target_adapter_scope": str(record.get("target_adapter_scope") or ""),
        "target_source_scope": _list(record.get("target_source_scope")),
        "regional_routing_policy": str(record.get("regional_routing_policy") or ""),
        "source_refs": source_refs,
        "dispatch_input_blocking_reasons": input_blockers,
        "continuation_lineage": dict(record.get("continuation_lineage") or {}),
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "live_execution_enabled": False,
        "requires_operator_action_before_live": True,
        "dispatch_status": "OPEN",
        "blocked_or_not_found_policy": "record_as_evidence_gap_or_source_blocker_not_clearance",
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _dispatch_input_blocking_reasons(*, action_family: str, source_refs: Mapping[str, Any]) -> list[str]:
    if action_family != "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW":
        return []
    blockers: list[str] = []
    if not _has_any_source_ref(source_refs, ("evidence_batch_closeout_json", "evidence_batch_closeout_root")):
        blockers.append("release_evidence_batch_closeout_ref_missing")
    if not _has_any_source_ref(
        source_refs,
        (
            "p13b_operational_closeout_json",
            "p13b_operational_closeout_root",
        ),
    ):
        blockers.append("p13b_operational_closeout_ref_missing")
    return blockers


def _has_any_source_ref(source_refs: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    return any(str(source_refs.get(key) or "").strip() for key in keys)


def _summary(
    *,
    action_plan_records: list[Mapping[str, Any]],
    manual_only_action_plan_records: list[Mapping[str, Any]],
    dispatch_task_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "stage6_review_action_dispatch_state": "STAGE6_REVIEW_ACTION_DISPATCH_READY"
        if not blocking_reasons
        else "STAGE6_REVIEW_ACTION_DISPATCH_INPUT_BLOCKED",
        "source_review_action_plan_count": len(action_plan_records),
        "dispatchable_action_plan_count": len(dispatch_task_records),
        "manual_only_action_plan_count": len(manual_only_action_plan_records),
        "manual_only_action_family_counts": _counts(record.get("action_family") for record in manual_only_action_plan_records),
        "dispatch_task_count": len(dispatch_task_records),
        "dispatch_task_type_counts": _counts(record.get("dispatch_task_type") for record in dispatch_task_records),
        "dispatch_readiness_state_counts": _counts(record.get("dispatch_readiness_state") for record in dispatch_task_records),
        "action_family_counts": _counts(record.get("action_family") for record in dispatch_task_records),
        "open_dispatch_task_count": sum(1 for record in dispatch_task_records if record.get("dispatch_status") == "OPEN"),
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
    dispatch_task_records: list[Mapping[str, Any]],
    manual_only_action_plan_records: list[Mapping[str, Any]],
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
    _write_json(out_dir / "stage6-review-dispatch-task-table.json", {"summary": result["summary"], "records": dispatch_task_records})
    _write_json(
        out_dir / "stage6-review-manual-only-action-plan-table.json",
        {"summary": result["summary"], "records": manual_only_action_plan_records},
    )
    _write_json(out_dir / "stage6-review-action-dispatch-v1.json", result)


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


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage6 review action dispatch tasks.")
    parser.add_argument("--stage6-fact-package-json", default="")
    parser.add_argument("--stage6-fact-package-root", default=str(DEFAULT_STAGE6_FACT_PACKAGE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_stage6_review_action_dispatch(
        stage6_fact_package_json=args.stage6_fact_package_json or None,
        stage6_fact_package_root=args.stage6_fact_package_root,
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
    "STAGE6_REVIEW_ACTION_DISPATCH_KIND",
    "build_stage6_review_action_dispatch",
]
