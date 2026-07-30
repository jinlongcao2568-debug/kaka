from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from shared.utils import utc_now_iso


CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENTS_KIND = "controlled_gray_public_batch_segments_v1"
CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENTS_VERSION = 1
CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENT_AGGREGATE_KIND = (
    "controlled_gray_public_batch_segment_aggregate_v1"
)
CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENT_AGGREGATE_VERSION = 1
DEFAULT_SEGMENTS_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/controlled-gray-public-batch-segments-v1")
DEFAULT_AGGREGATE_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/controlled-gray-public-batch-segment-aggregate-v1"
)


def build_controlled_gray_public_batch_segments(
    *,
    targets_json: str | Path,
    output_root: str | Path = DEFAULT_SEGMENTS_OUTPUT_ROOT,
    run_root_base: str | Path | None = None,
    group_by: str = "source_profile",
    per_target_candidate_limit: int = 12,
    target_limit: int = 0,
    professional_source_only: bool = True,
    execute: bool = True,
    auto_execute_source_remediation: bool = True,
    enable_alternate_public_source: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    targets_path = Path(targets_json)
    targets_payload = _load_json(targets_path)
    targets = _records(targets_payload.get("targets"))
    group_mode = _normalize_group_by(group_by)
    run_base = Path(run_root_base) if run_root_base else output_dir / "runs"
    segment_records: list[dict[str, Any]] = []

    for index, (key, group_targets) in enumerate(_group_targets(targets, group_mode).items(), start=1):
        target_ids = [str(target.get("target_id") or "") for target in group_targets if target.get("target_id")]
        safe_key = _safe_slug(key or f"segment-{index}")
        segment_id = f"CONTROLLED-GRAY-PUBLIC-SEGMENT-{index:02d}-{safe_key.upper()}"
        run_root = run_base / f"{index:02d}-{safe_key}"
        record = {
            "segment_id": segment_id,
            "segment_index": index,
            "segment_key": key,
            "group_by": group_mode,
            "run_root": str(run_root),
            "closeout_json": str(run_root / "controlled-live-public-batch-closeout.json"),
            "gray_launch_review_json": str(
                run_root / "gray-launch-review" / "controlled-live-public-batch-gray-launch-review-v1.json"
            ),
            "targets_json": str(targets_path),
            "target_ids": target_ids,
            "target_count": len(target_ids),
            "minimum_sample_goal": sum(_int(target.get("target_count")) for target in group_targets),
            "jurisdiction_counts": _counts(target.get("jurisdiction") for target in group_targets),
            "document_kind_counts": _counts(target.get("document_kind") for target in group_targets),
            "source_profile_counts": _counts(
                _source_profile_id(target) for target in group_targets
            ),
            "per_target_candidate_limit": max(1, int(per_target_candidate_limit)),
            "target_limit": max(0, int(target_limit)),
            "professional_source_only": bool(professional_source_only),
            "execute": bool(execute),
            "auto_execute_source_remediation": bool(auto_execute_source_remediation),
            "enable_alternate_public_source": bool(enable_alternate_public_source),
            "recommended_command": _segment_command(
                run_root=run_root,
                targets_json=targets_path,
                target_ids=target_ids,
                target_limit=target_limit,
                per_target_candidate_limit=per_target_candidate_limit,
                professional_source_only=professional_source_only,
                execute=execute,
                auto_execute_source_remediation=auto_execute_source_remediation,
                enable_alternate_public_source=enable_alternate_public_source,
            ),
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
        record["segment_sha256"] = _fingerprint(record)
        segment_records.append(record)

    summary = {
        "targets_json": str(targets_path),
        "target_set_id": str(targets_payload.get("target_set_id") or ""),
        "group_by": group_mode,
        "segment_count": len(segment_records),
        "target_count": sum(_int(record.get("target_count")) for record in segment_records),
        "minimum_total_sample_goal": sum(
            _int(record.get("minimum_sample_goal")) for record in segment_records
        ),
        "per_target_candidate_limit": max(1, int(per_target_candidate_limit)),
        "target_limit": max(0, int(target_limit)),
        "professional_source_only": bool(professional_source_only),
        "execute": bool(execute),
        "auto_execute_source_remediation": bool(auto_execute_source_remediation),
        "enable_alternate_public_source": bool(enable_alternate_public_source),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result = {
        "manifest_kind": CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENTS_KIND,
        "manifest_version": CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENTS_VERSION,
        "adapter_id": "controlled-gray-public-batch-segments-v1",
        "created_at": created,
        "summary": summary,
        "segment_table": {"records": segment_records, "summary": summary},
        "aggregate_command": _aggregate_command(output_dir=output_dir, segment_records=segment_records),
        "safety": _safety(),
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-gray-public-batch-segments-v1.json", result)
    (output_dir / "controlled-gray-public-batch-segments-v1.md").write_text(
        _segments_markdown(result),
        encoding="utf-8",
    )
    return result


def build_controlled_gray_public_batch_segment_aggregate(
    *,
    segment_roots: Sequence[str | Path] | None = None,
    segment_plan_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_AGGREGATE_OUTPUT_ROOT,
    gray_sample_goal_min: int = 100,
    gray_sample_goal_max: int = 200,
    operator_decision: str = "",
    operator_name: str = "",
    operator_decision_note: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = Path(segment_plan_json) if segment_plan_json else None
    plan = _load_json(plan_path)
    planned_records = _records(_mapping(plan.get("segment_table")).get("records"))
    roots = [Path(root) for root in _split_path_values(segment_roots or [])]
    if not roots and planned_records:
        roots = [Path(str(record.get("run_root") or "")) for record in planned_records if record.get("run_root")]
    planned_by_root = {str(Path(str(record.get("run_root") or ""))): record for record in planned_records}

    segment_records = []
    for index, root in enumerate(roots, start=1):
        planned = planned_by_root.get(str(root), {})
        segment_records.append(_aggregate_segment_record(root, planned=planned, segment_index=index))

    summary = _aggregate_summary(
        segment_records,
        gray_sample_goal_min=gray_sample_goal_min,
        gray_sample_goal_max=gray_sample_goal_max,
        operator_decision=operator_decision,
    )
    result = {
        "manifest_kind": CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENT_AGGREGATE_KIND,
        "manifest_version": CONTROLLED_GRAY_PUBLIC_BATCH_SEGMENT_AGGREGATE_VERSION,
        "adapter_id": "controlled-gray-public-batch-segment-aggregate-v1",
        "created_at": created,
        "segment_plan_json": str(plan_path or ""),
        "summary": summary,
        "segment_result_table": {"records": segment_records, "summary": summary},
        "operator_decision_record": _operator_decision_record(
            summary,
            operator_decision=operator_decision,
            operator_name=operator_name,
            operator_decision_note=operator_decision_note,
            created_at=created,
        ),
        "safety": _safety(),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-gray-public-batch-segment-aggregate-v1.json", result)
    (output_dir / "controlled-gray-public-batch-segment-aggregate-v1.md").write_text(
        _aggregate_markdown(result),
        encoding="utf-8",
    )
    return result


def _aggregate_segment_record(
    root: Path,
    *,
    planned: Mapping[str, Any],
    segment_index: int,
) -> dict[str, Any]:
    closeout_path = root / "controlled-live-public-batch-closeout.json"
    gray_review_path = root / "gray-launch-review" / "controlled-live-public-batch-gray-launch-review-v1.json"
    closeout = _load_json(closeout_path)
    gray_review = _load_json(gray_review_path)
    gray_summary = _mapping(gray_review.get("summary"))
    closeout_exists = bool(closeout)
    source_remediation_final_count = _final_source_remediation_count(closeout)
    record = {
        "segment_id": str(planned.get("segment_id") or f"CONTROLLED-GRAY-PUBLIC-SEGMENT-{segment_index:02d}"),
        "segment_index": _int(planned.get("segment_index")) or segment_index,
        "segment_key": str(planned.get("segment_key") or root.name),
        "run_root": str(root),
        "closeout_json": str(closeout_path),
        "gray_launch_review_json": str(gray_review_path),
        "closeout_exists": closeout_exists,
        "gray_launch_review_exists": bool(gray_review),
        "segment_review_state": str(
            gray_summary.get("gray_launch_review_state")
            or closeout.get("gray_launch_decision")
            or "MISSING_CLOSEOUT"
        ),
        "target_ids": list(planned.get("target_ids") or []),
        "target_count": _int(planned.get("target_count")),
        "execute": _truthy(closeout.get("execute")),
        "sample_count": _int(closeout.get("sample_count")),
        "fixed_snapshot_sha256_count": _int(closeout.get("fixed_snapshot_sha256_count")),
        "stage4_readback_required_sample_count": _int(
            closeout.get("stage4_evidence_readback_required_count")
        ),
        "stage4_readback_ready_sample_count": _int(closeout.get("stage4_readback_ready_sample_count")),
        "stage4_readback_missing_sample_count": _int(closeout.get("stage4_readback_missing_sample_count")),
        "stage4_public_evidence_readback_count": _int(
            closeout.get("stage4_public_evidence_readback_count")
        ),
        "stage4_all_required_readbacks_ready": _truthy(
            closeout.get("stage4_all_required_readbacks_ready")
        ),
        "source_remediation_initial_record_count": _int(closeout.get("source_remediation_record_count")),
        "source_remediation_final_record_count": source_remediation_final_count,
        "quarantined_source_remediation_record_count": _int(
            closeout.get("quarantined_source_remediation_record_count")
        ),
        "source_remediation_execution_state": str(closeout.get("source_remediation_execution_state") or ""),
        "partial_or_blocked_count": _int(closeout.get("partial_or_blocked_count")),
        "no_match_count": _int(closeout.get("no_match_count")),
        "customer_visible_allowed": _truthy(closeout.get("customer_visible_allowed")),
        "external_send_enabled": _truthy(closeout.get("external_send_enabled")),
        "payment_execution_enabled": _truthy(closeout.get("payment_execution_enabled")),
        "delivery_execution_enabled": _truthy(closeout.get("delivery_execution_enabled")),
        "automatic_refund_enabled": _truthy(closeout.get("automatic_refund_enabled")),
        "query_miss_is_not_clearance": _truthy(closeout.get("query_miss_is_not_clearance")),
        "no_legal_conclusion": _truthy(closeout.get("no_legal_conclusion")),
    }
    record["segment_result_sha256"] = _fingerprint(record)
    return record


def _aggregate_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    gray_sample_goal_min: int,
    gray_sample_goal_max: int,
    operator_decision: str,
) -> dict[str, Any]:
    segment_count = len(records)
    completed_count = sum(1 for record in records if bool(record.get("closeout_exists")))
    sample_count = sum(_int(record.get("sample_count")) for record in records)
    fixed_count = sum(_int(record.get("fixed_snapshot_sha256_count")) for record in records)
    stage4_required = sum(_int(record.get("stage4_readback_required_sample_count")) for record in records)
    stage4_ready = sum(_int(record.get("stage4_readback_ready_sample_count")) for record in records)
    stage4_missing = sum(_int(record.get("stage4_readback_missing_sample_count")) for record in records)
    source_remediation_final = sum(
        _int(record.get("source_remediation_final_record_count")) for record in records
    )
    safety_boundary_closed = all(
        not _truthy(record.get(key))
        for record in records
        for key in (
            "customer_visible_allowed",
            "external_send_enabled",
            "payment_execution_enabled",
            "delivery_execution_enabled",
            "automatic_refund_enabled",
        )
    )
    semantics_ready = all(
        _truthy(record.get("query_miss_is_not_clearance")) and _truthy(record.get("no_legal_conclusion"))
        for record in records
        if bool(record.get("closeout_exists"))
    )
    all_stage4_ready = (
        completed_count == segment_count
        and stage4_missing == 0
        and all(
            _truthy(record.get("stage4_all_required_readbacks_ready"))
            for record in records
            if bool(record.get("closeout_exists"))
        )
    )
    execute_all_completed = (
        completed_count == segment_count
        and segment_count > 0
        and all(_truthy(record.get("execute")) for record in records)
    )
    aggregate_state = _aggregate_review_state(
        segment_count=segment_count,
        completed_count=completed_count,
        execute_all_completed=execute_all_completed,
        sample_count=sample_count,
        fixed_count=fixed_count,
        all_stage4_ready=all_stage4_ready,
        source_remediation_final=source_remediation_final,
        safety_boundary_closed=safety_boundary_closed,
        semantics_ready=semantics_ready,
    )
    ready = aggregate_state == "READY_FOR_HUMAN_GRAY_LAUNCH_REVIEW"
    decision = _normalize_operator_decision(operator_decision)
    approved = ready and decision == "APPROVED"
    if not ready:
        approval_state = "NOT_REQUESTABLE"
    elif approved:
        approval_state = "APPROVED"
    elif decision in {"HOLD", "REJECTED"}:
        approval_state = decision
    else:
        approval_state = "WAITING_OPERATOR_APPROVAL"
    return {
        "aggregate_gray_review_state": aggregate_state,
        "eligible_for_human_gray_launch_review": ready,
        "human_gray_launch_approval_state": approval_state,
        "approved_for_controlled_gray_execution": approved,
        "next_required_step": (
            "controlled_gray_batch_review_complete"
            if approved
            else "record_operator_gray_launch_decision"
            if ready and approval_state == "WAITING_OPERATOR_APPROVAL"
            else _aggregate_next_step(aggregate_state)
        ),
        "segment_count": segment_count,
        "completed_segment_count": completed_count,
        "missing_segment_count": max(segment_count - completed_count, 0),
        "source_execute_all_completed": execute_all_completed,
        "project_sample_count": sample_count,
        "gray_sample_goal_min": max(1, int(gray_sample_goal_min)),
        "gray_sample_goal_max": max(max(1, int(gray_sample_goal_min)), int(gray_sample_goal_max)),
        "gray_sample_goal_state": _gray_sample_goal_state(
            sample_count,
            gray_sample_goal_min=max(1, int(gray_sample_goal_min)),
            gray_sample_goal_max=max(max(1, int(gray_sample_goal_min)), int(gray_sample_goal_max)),
        ),
        "gray_sample_goal_met": sample_count >= max(1, int(gray_sample_goal_min)),
        "fixed_snapshot_sha256_count": fixed_count,
        "stage4_readback_required_sample_count": stage4_required,
        "stage4_readback_ready_sample_count": stage4_ready,
        "stage4_readback_missing_sample_count": stage4_missing,
        "stage4_public_evidence_readback_count": sum(
            _int(record.get("stage4_public_evidence_readback_count")) for record in records
        ),
        "stage4_all_required_readbacks_ready": all_stage4_ready,
        "source_remediation_initial_record_count": sum(
            _int(record.get("source_remediation_initial_record_count")) for record in records
        ),
        "source_remediation_final_record_count": source_remediation_final,
        "quarantined_source_remediation_record_count": sum(
            _int(record.get("quarantined_source_remediation_record_count")) for record in records
        ),
        "partial_or_blocked_count": sum(_int(record.get("partial_or_blocked_count")) for record in records),
        "no_match_count": sum(_int(record.get("no_match_count")) for record in records),
        "safety_boundary_closed": safety_boundary_closed,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": semantics_ready,
        "no_legal_conclusion": semantics_ready,
        "public_release_allowed": False,
    }


def _aggregate_review_state(
    *,
    segment_count: int,
    completed_count: int,
    execute_all_completed: bool,
    sample_count: int,
    fixed_count: int,
    all_stage4_ready: bool,
    source_remediation_final: int,
    safety_boundary_closed: bool,
    semantics_ready: bool,
) -> str:
    if segment_count <= 0:
        return "NOT_READY_NO_SEGMENTS"
    if completed_count < segment_count:
        return "NOT_READY_SEGMENTS_INCOMPLETE"
    if not execute_all_completed:
        return "NOT_READY_REAL_PUBLIC_EXECUTION_REQUIRED"
    if sample_count <= 0:
        return "NOT_READY_NO_REAL_PUBLIC_SAMPLES"
    if fixed_count <= 0:
        return "NOT_READY_NO_FIXED_SNAPSHOT_HASHES"
    if not all_stage4_ready:
        return "NOT_READY_STAGE4_EVIDENCE_READBACK_REQUIRED"
    if source_remediation_final > 0:
        return "NOT_READY_SOURCE_REMEDIATION_REQUIRED"
    if not safety_boundary_closed:
        return "NOT_READY_SAFETY_BOUNDARY_OPEN"
    if not semantics_ready:
        return "NOT_READY_BOUNDARY_SEMANTICS_REVIEW_REQUIRED"
    return "READY_FOR_HUMAN_GRAY_LAUNCH_REVIEW"


def _aggregate_next_step(state: str) -> str:
    return {
        "NOT_READY_NO_SEGMENTS": "build_controlled_gray_public_batch_segments",
        "NOT_READY_SEGMENTS_INCOMPLETE": "run_missing_controlled_gray_public_segments",
        "NOT_READY_REAL_PUBLIC_EXECUTION_REQUIRED": "rerun_segments_with_execute",
        "NOT_READY_NO_REAL_PUBLIC_SAMPLES": "expand_or_fix_public_source_targets",
        "NOT_READY_NO_FIXED_SNAPSHOT_HASHES": "fix_evidence_snapshot_hashing",
        "NOT_READY_STAGE4_EVIDENCE_READBACK_REQUIRED": "run_stage4_evidence_readback_for_hashed_public_snapshots",
        "NOT_READY_SOURCE_REMEDIATION_REQUIRED": "execute_or_review_source_remediation_queue",
        "NOT_READY_SAFETY_BOUNDARY_OPEN": "close_customer_payment_delivery_release_flags_before_review",
        "NOT_READY_BOUNDARY_SEMANTICS_REVIEW_REQUIRED": "restore_no_clearance_and_no_legal_conclusion_boundaries",
    }.get(state, "review_segment_aggregate")


def _group_targets(targets: Sequence[Mapping[str, Any]], group_by: str) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for target in targets:
        key = _segment_key(target, group_by)
        grouped.setdefault(key, []).append(target)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def _segment_key(target: Mapping[str, Any], group_by: str) -> str:
    if group_by == "target":
        return str(target.get("target_id") or "UNKNOWN")
    if group_by == "jurisdiction":
        return str(target.get("jurisdiction") or "UNKNOWN")
    if group_by == "platform":
        return str(target.get("platform_name") or target.get("jurisdiction") or "UNKNOWN")
    return _source_profile_id(target) or str(target.get("jurisdiction") or "UNKNOWN")


def _source_profile_id(target: Mapping[str, Any]) -> str:
    return str(
        target.get("required_fetch_profile_id_optional")
        or target.get("fetch_profile_id_optional")
        or target.get("source_profile_id")
        or ""
    )


def _normalize_group_by(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"target", "target_id", "targetid"}:
        return "target"
    if text in {"jurisdiction", "province", "region"}:
        return "jurisdiction"
    if text in {"platform", "platform_name"}:
        return "platform"
    return "source_profile"


def _segment_command(
    *,
    run_root: Path,
    targets_json: Path,
    target_ids: Sequence[str],
    target_limit: int,
    per_target_candidate_limit: int,
    professional_source_only: bool,
    execute: bool,
    auto_execute_source_remediation: bool,
    enable_alternate_public_source: bool,
) -> str:
    parts = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts\\run-controlled-live-public-batch-v1.ps1",
        "-RunRoot",
        _quote(str(run_root)),
        "-TargetsJson",
        _quote(str(targets_json)),
        "-TargetIds",
        _quote(",".join(target_ids)),
        "-TargetLimit",
        str(max(0, int(target_limit))),
        "-PerTargetCandidateLimit",
        str(max(1, int(per_target_candidate_limit))),
    ]
    if professional_source_only:
        parts.append("-ProfessionalSourceOnly")
    if execute:
        parts.append("-Execute")
    if auto_execute_source_remediation:
        parts.append("-AutoExecuteSourceRemediation")
    if enable_alternate_public_source:
        parts.append("-EnableAlternatePublicSource")
    return " ".join(parts)


def _aggregate_command(*, output_dir: Path, segment_records: Sequence[Mapping[str, Any]]) -> str:
    roots = ",".join(str(record.get("run_root") or "") for record in segment_records)
    return (
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "scripts\\build-controlled-gray-public-batch-segment-aggregate-v1.ps1 "
        f"-SegmentRoots {_quote(roots)} -OutputRoot {_quote(str(output_dir / 'aggregate'))}"
    )


def _segments_markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Gray Public Batch Segments",
        "",
        f"- segment_count: {summary.get('segment_count')}",
        f"- target_count: {summary.get('target_count')}",
        f"- minimum_total_sample_goal: {summary.get('minimum_total_sample_goal')}",
        f"- per_target_candidate_limit: {summary.get('per_target_candidate_limit')}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- payment_execution_enabled: {str(bool(summary.get('payment_execution_enabled'))).lower()}",
        "",
        "## Segments",
    ]
    for record in _records(_mapping(result.get("segment_table")).get("records")):
        lines.append(
            f"- {record.get('segment_id')}: targets={record.get('target_count')} "
            f"goal={record.get('minimum_sample_goal')} run_root={record.get('run_root')}"
        )
    lines.extend(["", f"aggregate_command: `{result.get('aggregate_command')}`"])
    return "\n".join(lines) + "\n"


def _aggregate_markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Gray Public Batch Segment Aggregate",
        "",
        f"- aggregate_gray_review_state: {summary.get('aggregate_gray_review_state')}",
        f"- eligible_for_human_gray_launch_review: {str(bool(summary.get('eligible_for_human_gray_launch_review'))).lower()}",
        f"- human_gray_launch_approval_state: {summary.get('human_gray_launch_approval_state')}",
        f"- next_required_step: {summary.get('next_required_step')}",
        f"- completed_segment_count: {summary.get('completed_segment_count')}/{summary.get('segment_count')}",
        f"- project_sample_count: {summary.get('project_sample_count')}",
        f"- gray_sample_goal_state: {summary.get('gray_sample_goal_state')}",
        f"- fixed_snapshot_sha256_count: {summary.get('fixed_snapshot_sha256_count')}",
        f"- stage4_all_required_readbacks_ready: {str(bool(summary.get('stage4_all_required_readbacks_ready'))).lower()}",
        f"- source_remediation_final_record_count: {summary.get('source_remediation_final_record_count')}",
        f"- safety_boundary_closed: {str(bool(summary.get('safety_boundary_closed'))).lower()}",
        "",
        "## Segments",
    ]
    for record in _records(_mapping(result.get("segment_result_table")).get("records")):
        lines.append(
            f"- {record.get('segment_review_state')}: {record.get('segment_id')} "
            f"samples={record.get('sample_count')} hashes={record.get('fixed_snapshot_sha256_count')} "
            f"stage4_missing={record.get('stage4_readback_missing_sample_count')} "
            f"source_remediation_final={record.get('source_remediation_final_record_count')}"
        )
    return "\n".join(lines) + "\n"


def _operator_decision_record(
    summary: Mapping[str, Any],
    *,
    operator_decision: str,
    operator_name: str,
    operator_decision_note: str,
    created_at: str,
) -> dict[str, Any]:
    decision = _normalize_operator_decision(operator_decision)
    record = {
        "created_at": created_at,
        "operator_name": str(operator_name or ""),
        "operator_decision": decision,
        "operator_decision_note": str(operator_decision_note or ""),
        "approval_state": str(summary.get("human_gray_launch_approval_state") or ""),
        "approved_for_controlled_gray_execution": bool(
            summary.get("approved_for_controlled_gray_execution")
        ),
        "scope": "controlled_gray_public_source_segment_aggregate",
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "public_release_allowed": False,
    }
    record["decision_record_sha256"] = _fingerprint(record)
    return record


def _normalize_operator_decision(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"APPROVED", "APPROVE", "ALLOW", "YES"}:
        return "APPROVED"
    if text in {"HOLD", "HELD", "PAUSE"}:
        return "HOLD"
    if text in {"REJECTED", "REJECT", "DENY", "DENIED", "NO"}:
        return "REJECTED"
    return "UNSPECIFIED"


def _gray_sample_goal_state(
    sample_count: int,
    *,
    gray_sample_goal_min: int,
    gray_sample_goal_max: int,
) -> str:
    if sample_count <= 0:
        return "NO_GRAY_SAMPLE_COVERAGE"
    if sample_count >= gray_sample_goal_max:
        return "MEETS_GRAY_SAMPLE_TARGET_RANGE"
    if sample_count >= gray_sample_goal_min:
        return "MEETS_GRAY_SAMPLE_MINIMUM_GOAL"
    return "CATALOG_LIMITED_BELOW_GRAY_SAMPLE_GOAL"


def _final_source_remediation_count(closeout: Mapping[str, Any]) -> int:
    execution_state = str(closeout.get("source_remediation_execution_state") or "")
    if execution_state:
        return _int(closeout.get("post_run_source_remediation_record_count"))
    return _int(closeout.get("source_remediation_record_count"))


def _safety() -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "public_release_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) and isinstance(value.get("records"), list):
        value = value.get("records")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _split_path_values(values: Sequence[str | Path]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        result.extend(part.strip() for part in text.split(",") if part.strip())
    return result


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "enabled", "allow", "allowed"}


def _safe_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    text = re.sub(r"-+", "-", text).strip("-._")
    return (text or "segment").lower()[:80]


def _quote(value: str) -> str:
    text = str(value or "")
    if not text:
        return '""'
    if re.search(r"\s", text):
        return f'"{text}"'
    return text


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--targets-json", required=True)
    plan_parser.add_argument("--output-root", default=str(DEFAULT_SEGMENTS_OUTPUT_ROOT))
    plan_parser.add_argument("--run-root-base", default="")
    plan_parser.add_argument("--group-by", default="source_profile")
    plan_parser.add_argument("--per-target-candidate-limit", type=int, default=12)
    plan_parser.add_argument("--target-limit", type=int, default=0)
    plan_parser.add_argument("--professional-source-only", action="store_true")
    plan_parser.add_argument("--execute", action="store_true")
    plan_parser.add_argument("--auto-execute-source-remediation", action="store_true")
    plan_parser.add_argument("--enable-alternate-public-source", action="store_true")
    plan_parser.add_argument("--json", action="store_true")

    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("--segment-roots", nargs="*", default=[])
    aggregate_parser.add_argument("--segment-plan-json", default="")
    aggregate_parser.add_argument("--output-root", default=str(DEFAULT_AGGREGATE_OUTPUT_ROOT))
    aggregate_parser.add_argument("--gray-sample-goal-min", type=int, default=100)
    aggregate_parser.add_argument("--gray-sample-goal-max", type=int, default=200)
    aggregate_parser.add_argument("--operator-decision", default="")
    aggregate_parser.add_argument("--operator-name", default="")
    aggregate_parser.add_argument("--operator-decision-note", default="")
    aggregate_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "plan":
        result = build_controlled_gray_public_batch_segments(
            targets_json=args.targets_json,
            output_root=args.output_root,
            run_root_base=args.run_root_base or None,
            group_by=args.group_by,
            per_target_candidate_limit=args.per_target_candidate_limit,
            target_limit=args.target_limit,
            professional_source_only=args.professional_source_only,
            execute=args.execute,
            auto_execute_source_remediation=args.auto_execute_source_remediation,
            enable_alternate_public_source=args.enable_alternate_public_source,
        )
    else:
        result = build_controlled_gray_public_batch_segment_aggregate(
            segment_roots=args.segment_roots,
            segment_plan_json=args.segment_plan_json or None,
            output_root=args.output_root,
            gray_sample_goal_min=args.gray_sample_goal_min,
            gray_sample_goal_max=args.gray_sample_goal_max,
            operator_decision=args.operator_decision,
            operator_name=args.operator_name,
            operator_decision_note=args.operator_decision_note,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
