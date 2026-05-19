from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


EVIDENCE_BATCH_CLOSEOUT_KIND = "evidence_batch_closeout_v1_manifest"
EVIDENCE_BATCH_CLOSEOUT_VERSION = 1
EVIDENCE_BATCH_CLOSEOUT_ADAPTER_ID = "evidence-batch-closeout-v1"

DEFAULT_EVIDENCE_STATE_ROOT = Path("tmp/evaluation-real-samples/evidence-orchestration-state-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW = "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW"
CONTINUE_EVIDENCE_RUN = "CONTINUE_EVIDENCE_RUN"
PARK_D_INSUFFICIENT_OR_BLOCKED = "PARK_D_INSUFFICIENT_OR_BLOCKED"
PARK_NO_CLEARANCE_CLAIM = "PARK_NO_CLEARANCE_CLAIM"
DEFER_NON_MAINLINE_OR_SCOPE = "DEFER_NON_MAINLINE_OR_SCOPE"
FIX_UPSTREAM_EXTRACTION_OR_CAPTURE = "FIX_UPSTREAM_EXTRACTION_OR_CAPTURE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"


def build_evidence_batch_closeout(
    *,
    evidence_state_json: str | Path | None = None,
    evidence_state_root: str | Path = DEFAULT_EVIDENCE_STATE_ROOT,
    continuation_run_json: str | Path | None = None,
    continuation_run_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    state_path = _resolve_input_json(
        explicit_json=evidence_state_json,
        root=evidence_state_root,
        default_file_name="evidence-orchestration-state-v1.json",
    )
    state_payload = _load_json(state_path, blocking_reasons, "evidence_orchestration_state_missing_or_invalid")
    state_manifest = _source_manifest(state_payload)
    if state_payload and not state_manifest:
        blocking_reasons.append("evidence_orchestration_state_manifest_missing")

    continuation_path = _resolve_input_json(
        explicit_json=continuation_run_json,
        root=continuation_run_root,
        default_file_name="evidence-orchestration-continuation-run-v1.json",
    )
    continuation_payload = (
        _load_json(continuation_path, [], "continuation_run_missing_or_invalid")
        if continuation_path
        else {}
    )
    continuation_manifest = _source_manifest(continuation_payload)

    evidence_records = _records_from_table(state_manifest, "evidence_state_table")
    batch_records = _records_by_project(_records_from_table(state_manifest, "batch_triage_table"))
    stage6_records = _records_by_project(_records_from_table(state_manifest, "stage6_fact_package_readiness_table"))
    adapter_jobs_by_project = _adapter_jobs_by_project(_records_from_table(state_manifest, "adapter_job_table"))

    closeout_records = [
        _closeout_record(
            evidence=record,
            batch=batch_records.get(str(record.get("project_id") or ""), {}),
            stage6=stage6_records.get(str(record.get("project_id") or ""), {}),
            adapter_jobs=adapter_jobs_by_project.get(str(record.get("project_id") or ""), []),
            state_manifest=state_manifest,
            continuation_manifest=continuation_manifest,
            state_path=state_path,
            continuation_path=continuation_path,
            created_at=created,
        )
        for record in evidence_records
        if isinstance(record, Mapping)
    ]
    next_action_queue = _next_action_queue(closeout_records)
    summary = _summary(
        closeout_records=closeout_records,
        next_action_queue=next_action_queue,
        adapter_job_count=sum(len(jobs) for jobs in adapter_jobs_by_project.values()),
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": EVIDENCE_BATCH_CLOSEOUT_VERSION,
        "manifest_kind": EVIDENCE_BATCH_CLOSEOUT_KIND,
        "adapter_id": EVIDENCE_BATCH_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "EvidenceBatchCloseoutV1",
        "manifest_id": f"EVIDENCE-BATCH-CLOSEOUT-{_fingerprint({'summary': summary, 'records': closeout_records})[:16]}",
        "created_at": created,
        "source_evidence_state_json": str(state_path or ""),
        "source_continuation_run_json": str(continuation_path or ""),
        "source_evidence_orchestration_manifest_id": str(state_manifest.get("manifest_id") or ""),
        "source_continuation_manifest_id": str(continuation_manifest.get("manifest_id") or ""),
        "closeout_records": closeout_records,
        "next_action_queue": next_action_queue,
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
        "evidence_batch_closeout_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, closeout_records, next_action_queue)
    return result


def _closeout_record(
    *,
    evidence: Mapping[str, Any],
    batch: Mapping[str, Any],
    stage6: Mapping[str, Any],
    adapter_jobs: list[Mapping[str, Any]],
    state_manifest: Mapping[str, Any],
    continuation_manifest: Mapping[str, Any],
    state_path: Path | None,
    continuation_path: Path | None,
    created_at: str,
) -> dict[str, Any]:
    project_id = str(evidence.get("project_id") or "")
    closeout_state = _closeout_state(evidence=evidence, batch=batch, adapter_jobs=adapter_jobs)
    next_action_type = _next_action_type(closeout_state=closeout_state, adapter_jobs=adapter_jobs, batch=batch)
    return {
        "closeout_id": _stable_id("EVIDENCE-BATCH-CLOSEOUT", project_id, evidence.get("evidence_state"), batch.get("batch_triage_bucket")),
        "project_id": project_id,
        "project_name": str(evidence.get("project_name") or batch.get("project_name") or stage6.get("project_name") or ""),
        "engineering_work_lane": str(evidence.get("engineering_work_lane") or ""),
        "opportunity_priority_class": str(evidence.get("opportunity_priority_class") or ""),
        "candidate_group_members": _list(evidence.get("candidate_group_members")),
        "responsible_person_name": str(evidence.get("responsible_person_name") or ""),
        "evidence_state": str(evidence.get("evidence_state") or ""),
        "evidence_grade": str(evidence.get("evidence_grade") or ""),
        "evidence_signal_source": str(evidence.get("evidence_signal_source") or ""),
        "evidence_recommended_next_action": str(evidence.get("recommended_next_action") or ""),
        "batch_triage_bucket": str(batch.get("batch_triage_bucket") or ""),
        "commercial_decision_state": str(batch.get("commercial_decision_state") or ""),
        "batch_recommended_next_action": str(batch.get("recommended_next_action") or ""),
        "batch_stop_reason": str(batch.get("stop_reason") or ""),
        "stage6_fact_package_state": str(
            stage6.get("stage6_fact_package_state") or evidence.get("stage6_fact_package_state") or ""
        ),
        "stage6_ready": bool(batch.get("stage6_ready")) or _stage6_ready(stage6, evidence),
        "stage7_commercial_input_allowed": bool(batch.get("stage7_commercial_input_allowed")),
        "continue_allowed": _continue_allowed(batch),
        "closeout_state": closeout_state,
        "next_action_type": next_action_type,
        "next_action_label": _next_action_label(closeout_state=closeout_state, batch=batch, evidence=evidence),
        "pending_adapter_job_count": len(adapter_jobs),
        "pending_adapter_jobs": [_adapter_job_summary(job) for job in adapter_jobs],
        "review_reasons": _dedupe(
            [
                *_list(evidence.get("review_reasons")),
                batch.get("stop_reason"),
                *[
                    reason
                    for job in adapter_jobs
                    for reason in _list(job.get("review_reasons"))
                ],
            ]
        ),
        "signal_counts": dict(evidence.get("signal_counts") or {}),
        "design_survey_adapter_counts": dict(evidence.get("design_survey_adapter_counts") or {}),
        "source_refs": {
            "evidence_state_json": str(state_path or ""),
            "continuation_run_json": str(continuation_path or ""),
            "evidence_orchestration_manifest_id": str(state_manifest.get("manifest_id") or ""),
            "continuation_manifest_id": str(continuation_manifest.get("manifest_id") or ""),
            "state_after_root": str(continuation_manifest.get("state_after_root") or ""),
        },
        "continuation_lineage": _continuation_lineage(continuation_manifest),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _closeout_state(
    *,
    evidence: Mapping[str, Any],
    batch: Mapping[str, Any],
    adapter_jobs: list[Mapping[str, Any]],
) -> str:
    evidence_state = str(evidence.get("evidence_state") or "")
    evidence_grade = str(evidence.get("evidence_grade") or "")
    bucket = str(batch.get("batch_triage_bucket") or "")
    commercial = str(batch.get("commercial_decision_state") or "")
    if (
        evidence_state == "A_STRONG_TIME_OVERLAP_SIGNAL_READY"
        or evidence_grade.startswith("A_")
        or bucket == "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE"
        or commercial == "PROMOTE_TO_STAGE6_FACT_PACKAGE_AND_STAGE7_GOVERNED_PREVIEW"
    ):
        return PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW
    if evidence_state.startswith("D_") or bucket == "D_BLOCKED_OR_INSUFFICIENT_REVIEW":
        return PARK_D_INSUFFICIENT_OR_BLOCKED
    if bucket == "LOW_VALUE_REVIEW_NO_CLEARANCE_CLAIM" or commercial == "STOP_OR_PARK_WITHOUT_CLEARANCE_CLAIM":
        return PARK_NO_CLEARANCE_CLAIM
    if bucket == "DEFER_NON_MAINLINE_ADAPTER" or commercial == "PARK_NON_MAINLINE_ADAPTER":
        return DEFER_NON_MAINLINE_OR_SCOPE
    if commercial == "FIX_UPSTREAM_EXTRACTION_OR_CAPTURE" or bucket.startswith("FIX_"):
        return FIX_UPSTREAM_EXTRACTION_OR_CAPTURE
    if adapter_jobs or commercial in {
        "CONTINUE_INTERNAL_EVIDENCE_RUN",
        "CONTINUE_INTERNAL_REVIEW_OR_STAGE6_FACT_PACKAGE",
    }:
        return CONTINUE_EVIDENCE_RUN
    return REVIEW_REQUIRED


def _next_action_type(
    *,
    closeout_state: str,
    adapter_jobs: list[Mapping[str, Any]],
    batch: Mapping[str, Any],
) -> str:
    if closeout_state == PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW:
        return "BUILD_STAGE6_FACT_PACKAGE_OR_STAGE7_GOVERNED_PREVIEW"
    if closeout_state == CONTINUE_EVIDENCE_RUN and adapter_jobs:
        return "RUN_ADAPTER_JOB"
    if closeout_state == CONTINUE_EVIDENCE_RUN:
        return "CONTINUE_INTERNAL_EVIDENCE_RUN"
    if closeout_state == PARK_D_INSUFFICIENT_OR_BLOCKED:
        return "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM"
    if closeout_state == PARK_NO_CLEARANCE_CLAIM:
        return "PARK_WITHOUT_CLEARANCE_CLAIM"
    if closeout_state == DEFER_NON_MAINLINE_OR_SCOPE:
        return "DEFER_UNTIL_ADAPTER_AVAILABLE"
    if closeout_state == FIX_UPSTREAM_EXTRACTION_OR_CAPTURE:
        return "FIX_UPSTREAM_CAPTURE_OR_EXTRACTION"
    return str(batch.get("recommended_next_action") or "MANUAL_REVIEW")


def _next_action_label(
    *,
    closeout_state: str,
    batch: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> str:
    batch_action = str(batch.get("recommended_next_action") or "")
    evidence_action = str(evidence.get("recommended_next_action") or "")
    if batch_action:
        return batch_action
    if evidence_action:
        return evidence_action
    if closeout_state == PARK_D_INSUFFICIENT_OR_BLOCKED:
        return "park_or_manual_review_without_clearance_claim"
    if closeout_state == PARK_NO_CLEARANCE_CLAIM:
        return "park_without_clearance_claim"
    return "manual_review"


def _next_action_queue(closeout_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    queue_states = {
        PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW,
        CONTINUE_EVIDENCE_RUN,
        FIX_UPSTREAM_EXTRACTION_OR_CAPTURE,
        REVIEW_REQUIRED,
    }
    rows = [
        {
            "queue_id": _stable_id("EVIDENCE-BATCH-NEXT-ACTION", record.get("project_id"), record.get("next_action_type")),
            "project_id": str(record.get("project_id") or ""),
            "project_name": str(record.get("project_name") or ""),
            "closeout_state": str(record.get("closeout_state") or ""),
            "next_action_type": str(record.get("next_action_type") or ""),
            "next_action_label": str(record.get("next_action_label") or ""),
            "pending_adapter_job_count": int(record.get("pending_adapter_job_count") or 0),
            "priority_score": _priority_score(record),
            "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
        for record in closeout_records
        if str(record.get("closeout_state") or "") in queue_states
    ]
    return sorted(rows, key=lambda row: (-int(row["priority_score"]), row["project_id"]))


def _priority_score(record: Mapping[str, Any]) -> int:
    state = str(record.get("closeout_state") or "")
    base = {
        PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW: 1000,
        CONTINUE_EVIDENCE_RUN: 760,
        FIX_UPSTREAM_EXTRACTION_OR_CAPTURE: 420,
        REVIEW_REQUIRED: 300,
    }.get(state, 0)
    base += min(int(record.get("pending_adapter_job_count") or 0), 5) * 10
    signal_counts = record.get("signal_counts") if isinstance(record.get("signal_counts"), Mapping) else {}
    base += min(int(signal_counts.get("p13b_a_strong_direct_signal_count") or 0), 5) * 30
    base += min(int(signal_counts.get("original_notice_a_strong_signal_count") or 0), 5) * 30
    return base


def _summary(
    *,
    closeout_records: list[Mapping[str, Any]],
    next_action_queue: list[Mapping[str, Any]],
    adapter_job_count: int,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    closeout_state_counts = _counts(record.get("closeout_state") for record in closeout_records)
    return {
        "closeout_state": "EVIDENCE_BATCH_CLOSEOUT_READY" if not blocking_reasons else "EVIDENCE_BATCH_CLOSEOUT_INPUT_BLOCKED",
        "project_count": len(closeout_records),
        "closeout_state_counts": closeout_state_counts,
        "continue_project_count": closeout_state_counts.get(CONTINUE_EVIDENCE_RUN, 0),
        "stage6_candidate_count": sum(1 for record in closeout_records if bool(record.get("stage6_ready"))),
        "stage7_preview_candidate_count": sum(
            1 for record in closeout_records if bool(record.get("stage7_commercial_input_allowed"))
        ),
        "parked_or_d_count": closeout_state_counts.get(PARK_D_INSUFFICIENT_OR_BLOCKED, 0)
        + closeout_state_counts.get(PARK_NO_CLEARANCE_CLAIM, 0),
        "deferred_project_count": closeout_state_counts.get(DEFER_NON_MAINLINE_OR_SCOPE, 0),
        "fix_upstream_project_count": closeout_state_counts.get(FIX_UPSTREAM_EXTRACTION_OR_CAPTURE, 0),
        "review_required_project_count": closeout_state_counts.get(REVIEW_REQUIRED, 0),
        "adapter_job_count": adapter_job_count,
        "next_action_queue_count": len(next_action_queue),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    closeout_records: list[Mapping[str, Any]],
    next_action_queue: list[Mapping[str, Any]],
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
    _write_json(out_dir / "project-closeout-records.json", {"summary": result["summary"], "records": closeout_records})
    _write_json(out_dir / "next-action-queue.json", {"summary": result["summary"], "records": next_action_queue})
    _write_json(out_dir / "evidence-batch-closeout-v1.json", result)


def _resolve_input_json(
    *,
    explicit_json: str | Path | None,
    root: str | Path | None,
    default_file_name: str,
) -> Path | None:
    if explicit_json:
        return Path(explicit_json)
    if root:
        return Path(root) / default_file_name
    return None


def _load_json(path: Path | None, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if path is None or not path.exists():
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


def _records_from_table(manifest: Mapping[str, Any], table_name: str) -> list[Mapping[str, Any]]:
    table = manifest.get(table_name) if isinstance(manifest.get(table_name), Mapping) else {}
    records = table.get("records") if isinstance(table, Mapping) else []
    return [record for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out[project_id] = record
    return out


def _adapter_jobs_by_project(records: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        out.setdefault(project_id, []).append(record)
    return out


def _adapter_job_summary(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "adapter_job_id": str(job.get("adapter_job_id") or job.get("job_id") or ""),
        "job_type": str(job.get("job_type") or ""),
        "recommended_script": str(job.get("recommended_script") or ""),
        "recommended_next_action": str(job.get("recommended_next_action") or ""),
        "execution_mode": str(job.get("execution_mode") or "PLAN_ONLY_NOT_EXECUTED"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _continue_allowed(batch: Mapping[str, Any]) -> bool:
    commercial = str(batch.get("commercial_decision_state") or "")
    return commercial in {
        "CONTINUE_INTERNAL_EVIDENCE_RUN",
        "CONTINUE_INTERNAL_REVIEW_OR_STAGE6_FACT_PACKAGE",
        "PROMOTE_TO_STAGE6_FACT_PACKAGE_AND_STAGE7_GOVERNED_PREVIEW",
    }


def _stage6_ready(stage6: Mapping[str, Any], evidence: Mapping[str, Any]) -> bool:
    state = str(stage6.get("stage6_fact_package_state") or evidence.get("stage6_fact_package_state") or "")
    return state in {"REVIEW_FACT_PACKAGE_READY", "A_SIGNAL_FACT_PACKAGE_READY"}


def _continuation_lineage(continuation_manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "original_action_state": str((continuation_manifest.get("summary") or {}).get("original_action_state") or ""),
        "targeted_person_action_state": str((continuation_manifest.get("summary") or {}).get("targeted_person_action_state") or ""),
        "state_after_evidence_state_counts": dict(
            (continuation_manifest.get("summary") or {}).get("state_after_evidence_state_counts") or {}
        ),
        "state_after_adapter_job_count": int(
            (continuation_manifest.get("summary") or {}).get("state_after_adapter_job_count") or 0
        ),
        "final_original_backtrace_continuation_recommended_next_action": str(
            (continuation_manifest.get("summary") or {}).get("final_original_backtrace_continuation_recommended_next_action")
            or ""
        ),
    }


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
    parser = argparse.ArgumentParser(description="Build Evidence Batch Closeout v1 from orchestration state tables.")
    parser.add_argument("--evidence-state-json", default="")
    parser.add_argument("--evidence-state-root", default=str(DEFAULT_EVIDENCE_STATE_ROOT))
    parser.add_argument("--continuation-run-json", default="")
    parser.add_argument("--continuation-run-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evidence_batch_closeout(
        evidence_state_json=args.evidence_state_json or None,
        evidence_state_root=args.evidence_state_root,
        continuation_run_json=args.continuation_run_json or None,
        continuation_run_root=args.continuation_run_root or None,
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
    "EVIDENCE_BATCH_CLOSEOUT_KIND",
    "build_evidence_batch_closeout",
]
