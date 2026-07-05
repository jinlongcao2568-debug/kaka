from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from shared.utils import utc_now_iso
from runtime.controlled_gray_public_batch_segments import (
    build_controlled_gray_public_batch_segment_aggregate,
    build_controlled_gray_public_batch_segments,
)
from runtime.controlled_gray_public_source_targets import (
    build_controlled_gray_public_source_targets,
)


CONTROLLED_GRAY_PUBLIC_ORCHESTRATOR_KIND = "controlled_gray_public_orchestrator_v1"
CONTROLLED_GRAY_PUBLIC_ORCHESTRATOR_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/controlled-gray-public-orchestrator-v1"
)


def build_controlled_gray_public_orchestrator_prepare_bundle(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    source_targets_json: str | Path,
    per_target_sample_goal: int = 12,
    per_target_candidate_limit: int = 12,
    target_limit: int = 0,
    group_by: str = "target",
    segment_timeout_seconds: int = 900,
    professional_source_only: bool = True,
    execute: bool = False,
    auto_execute_source_remediation: bool = True,
    created_at: str | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_root)
    source_targets_root = output_dir / "source-targets"
    segments_root = output_dir / "segments"
    aggregate_root = segments_root / "aggregate"

    source_targets = build_controlled_gray_public_source_targets(
        source_targets_json=source_targets_json,
        output_root=source_targets_root,
        per_target_sample_goal=per_target_sample_goal,
        created_at=created_at,
    )
    derived_targets_json = Path(str(source_targets.get("targets_json") or ""))
    segment_plan = build_controlled_gray_public_batch_segments(
        targets_json=derived_targets_json,
        output_root=segments_root,
        run_root_base=segments_root / "runs",
        group_by=group_by,
        per_target_candidate_limit=per_target_candidate_limit,
        target_limit=target_limit,
        professional_source_only=professional_source_only,
        execute=execute,
        auto_execute_source_remediation=auto_execute_source_remediation,
        created_at=created_at,
    )
    segments_json = segments_root / "controlled-gray-public-batch-segments-v1.json"
    aggregate = build_controlled_gray_public_batch_segment_aggregate(
        segment_plan_json=segments_json,
        output_root=aggregate_root,
        created_at=created_at,
    )
    aggregate_json = aggregate_root / "controlled-gray-public-batch-segment-aggregate-v1.json"
    manifest = build_controlled_gray_public_orchestrator_manifest(
        output_root=output_dir,
        source_targets_json=source_targets_json,
        derived_targets_json=derived_targets_json,
        source_targets_summary_json=source_targets_root
        / "controlled-gray-public-source-targets-summary-v1.json",
        segments_json=segments_json,
        aggregate_json=aggregate_json,
        execute=execute,
        group_by=group_by,
        per_target_sample_goal=per_target_sample_goal,
        per_target_candidate_limit=per_target_candidate_limit,
        target_limit=target_limit,
        segment_timeout_seconds=segment_timeout_seconds,
        professional_source_only=professional_source_only,
        auto_execute_source_remediation=auto_execute_source_remediation,
        created_at=created_at,
    )
    return {
        "output_root": str(output_dir),
        "source_targets_summary": source_targets.get("summary", {}),
        "source_targets": source_targets,
        "segment_summary": segment_plan.get("summary", {}),
        "segment_plan": segment_plan,
        "aggregate_summary": aggregate.get("summary", {}),
        "aggregate": aggregate,
        "manifest": manifest,
        "summary": manifest.get("summary", {}),
    }


def build_controlled_gray_public_orchestrator_manifest(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    source_targets_json: str | Path = "",
    derived_targets_json: str | Path = "",
    source_targets_summary_json: str | Path = "",
    segments_json: str | Path = "",
    aggregate_json: str | Path = "",
    execute: bool = False,
    group_by: str = "target",
    per_target_sample_goal: int = 12,
    per_target_candidate_limit: int = 12,
    target_limit: int = 0,
    segment_timeout_seconds: int = 900,
    professional_source_only: bool = False,
    auto_execute_source_remediation: bool = False,
    force_rerun: bool = False,
    operator_decision: str = "",
    operator_name: str = "",
    operator_decision_note: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_targets_summary = _load_json(_path_or_none(source_targets_summary_json))
    segment_plan = _load_json(_path_or_none(segments_json))
    aggregate = _load_json(_path_or_none(aggregate_json))

    source_summary = _mapping(source_targets_summary.get("summary"))
    segment_summary = _mapping(segment_plan.get("summary"))
    aggregate_summary = _mapping(aggregate.get("summary"))
    command_config = {
        "execute": bool(execute),
        "group_by": str(group_by or ""),
        "per_target_sample_goal": max(1, int(per_target_sample_goal)),
        "per_target_candidate_limit": max(1, int(per_target_candidate_limit)),
        "target_limit": max(0, int(target_limit)),
        "segment_timeout_seconds": max(0, int(segment_timeout_seconds)),
        "professional_source_only": bool(professional_source_only),
        "auto_execute_source_remediation": bool(auto_execute_source_remediation),
        "force_rerun": bool(force_rerun),
        "operator_decision": str(operator_decision or ""),
        "operator_name": str(operator_name or ""),
        "operator_decision_note": str(operator_decision_note or ""),
    }
    summary = _orchestrator_summary(
        source_summary=source_summary,
        segment_summary=segment_summary,
        aggregate_summary=aggregate_summary,
        aggregate_json=aggregate_json,
    )
    capabilities = _automation_capabilities(
        source_targets_summary_json=source_targets_summary_json,
        segments_json=segments_json,
        aggregate_json=aggregate_json,
        command_config=command_config,
        summary=summary,
    )
    result = {
        "manifest_kind": CONTROLLED_GRAY_PUBLIC_ORCHESTRATOR_KIND,
        "manifest_version": CONTROLLED_GRAY_PUBLIC_ORCHESTRATOR_VERSION,
        "adapter_id": "controlled-gray-public-orchestrator-v1",
        "created_at": created,
        "summary": summary,
        "inputs": {
            "output_root": str(output_dir),
            "source_targets_json": str(source_targets_json or ""),
            "derived_targets_json": str(derived_targets_json or ""),
            "source_targets_summary_json": str(source_targets_summary_json or ""),
            "segments_json": str(segments_json or ""),
            "aggregate_json": str(aggregate_json or ""),
            "command_config": command_config,
        },
        "source_targets_summary": source_summary,
        "segment_summary": segment_summary,
        "aggregate_summary": aggregate_summary,
        "automation_capability_matrix": {
            "records": capabilities,
            "summary": _capability_summary(capabilities),
        },
        "safety": _safety(),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "public_release_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-gray-public-orchestrator-v1.json", result)
    (output_dir / "controlled-gray-public-orchestrator-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _orchestrator_summary(
    *,
    source_summary: Mapping[str, Any],
    segment_summary: Mapping[str, Any],
    aggregate_summary: Mapping[str, Any],
    aggregate_json: str | Path,
) -> dict[str, Any]:
    aggregate_state = str(aggregate_summary.get("aggregate_gray_review_state") or "")
    approval_state = str(
        aggregate_summary.get("human_gray_launch_approval_state") or ""
    )
    approved = _truthy(aggregate_summary.get("approved_for_controlled_gray_execution"))
    eligible = _truthy(aggregate_summary.get("eligible_for_human_gray_launch_review"))
    if not aggregate_summary:
        orchestration_state = "ORCHESTRATOR_BLOCKED_MISSING_AGGREGATE"
        next_step = "run_controlled_gray_public_batch_segments"
    elif approved:
        orchestration_state = "CONTROLLED_GRAY_REVIEW_APPROVED"
        next_step = str(
            aggregate_summary.get("next_required_step")
            or "controlled_gray_batch_review_complete"
        )
    elif eligible and approval_state == "WAITING_OPERATOR_APPROVAL":
        orchestration_state = "CONTROLLED_GRAY_WAITING_OPERATOR_DECISION"
        next_step = "record_operator_gray_launch_decision"
    elif approval_state in {"HOLD", "REJECTED"}:
        orchestration_state = "CONTROLLED_GRAY_OPERATOR_HOLD"
        next_step = "resolve_operator_hold_before_gray_execution"
    elif aggregate_state.startswith("NOT_READY"):
        orchestration_state = "CONTROLLED_GRAY_NOT_READY"
        next_step = str(aggregate_summary.get("next_required_step") or "review_aggregate")
    else:
        orchestration_state = "CONTROLLED_GRAY_REVIEW_REQUIRED"
        next_step = str(aggregate_summary.get("next_required_step") or "review_aggregate")

    stage4_missing = _int(aggregate_summary.get("stage4_readback_missing_sample_count"))
    source_remediation_final = _int(
        aggregate_summary.get("source_remediation_final_record_count")
    )
    safety_closed = (
        bool(aggregate_summary)
        and _truthy(aggregate_summary.get("safety_boundary_closed"))
        and not any(_truthy(aggregate_summary.get(key)) for key in _OPEN_SAFETY_KEYS)
    )
    can_enter_controlled_gray_execution = approved and safety_closed
    return {
        "orchestration_state": orchestration_state,
        "aggregate_gray_review_state": aggregate_state,
        "eligible_for_human_gray_launch_review": eligible,
        "human_gray_launch_approval_state": approval_state,
        "approved_for_controlled_gray_execution": approved,
        "can_enter_controlled_gray_execution": can_enter_controlled_gray_execution,
        "next_required_step": next_step,
        "source_targets_summary_available": bool(source_summary),
        "segment_plan_available": bool(segment_summary),
        "aggregate_available": bool(aggregate_summary) and bool(str(aggregate_json or "")),
        "source_target_count": _int(source_summary.get("source_target_count")),
        "derived_target_count": _int(source_summary.get("derived_target_count")),
        "minimum_total_sample_goal": _int(source_summary.get("minimum_total_sample_goal")),
        "planned_segment_count": _int(segment_summary.get("segment_count")),
        "planned_target_count": _int(segment_summary.get("target_count")),
        "segment_count": _int(aggregate_summary.get("segment_count")),
        "completed_segment_count": _int(aggregate_summary.get("completed_segment_count")),
        "missing_segment_count": _int(aggregate_summary.get("missing_segment_count")),
        "source_execute_all_completed": _truthy(
            aggregate_summary.get("source_execute_all_completed")
        ),
        "project_sample_count": _int(aggregate_summary.get("project_sample_count")),
        "gray_sample_goal_min": _int(aggregate_summary.get("gray_sample_goal_min")),
        "gray_sample_goal_max": _int(aggregate_summary.get("gray_sample_goal_max")),
        "gray_sample_goal_state": str(
            aggregate_summary.get("gray_sample_goal_state") or ""
        ),
        "gray_sample_goal_met": _truthy(aggregate_summary.get("gray_sample_goal_met")),
        "fixed_snapshot_sha256_count": _int(
            aggregate_summary.get("fixed_snapshot_sha256_count")
        ),
        "stage4_readback_required_sample_count": _int(
            aggregate_summary.get("stage4_readback_required_sample_count")
        ),
        "stage4_readback_ready_sample_count": _int(
            aggregate_summary.get("stage4_readback_ready_sample_count")
        ),
        "stage4_readback_missing_sample_count": stage4_missing,
        "stage4_public_evidence_readback_count": _int(
            aggregate_summary.get("stage4_public_evidence_readback_count")
        ),
        "stage4_all_required_readbacks_ready": _truthy(
            aggregate_summary.get("stage4_all_required_readbacks_ready")
        ),
        "source_remediation_initial_record_count": _int(
            aggregate_summary.get("source_remediation_initial_record_count")
        ),
        "source_remediation_final_record_count": source_remediation_final,
        "partial_or_blocked_count": _int(aggregate_summary.get("partial_or_blocked_count")),
        "no_match_count": _int(aggregate_summary.get("no_match_count")),
        "remaining_evidence_blocker_count": stage4_missing + source_remediation_final,
        "safety_boundary_closed": safety_closed,
        "runtime_orchestration_manifest_ready": True,
        "pipeline_steps_automated_for_current_batch": bool(aggregate_summary),
        "unattended_recurring_run_ready": False,
        "workbench_trigger_ready": True,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "public_release_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _automation_capabilities(
    *,
    source_targets_summary_json: str | Path,
    segments_json: str | Path,
    aggregate_json: str | Path,
    command_config: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    operator_decision = str(command_config.get("operator_decision") or "").strip()
    return [
        _capability(
            "source_target_generation",
            "public-source target filtering and gray sample expansion",
            "AUTOMATED_BY_ORCHESTRATOR",
            True,
            str(source_targets_summary_json or ""),
        ),
        _capability(
            "segment_planning",
            "controlled batch segment plan generation",
            "AUTOMATED_BY_ORCHESTRATOR",
            True,
            str(segments_json or ""),
        ),
        _capability(
            "segment_execution",
            "controlled public-source segment execution",
            "AUTOMATED_BY_ORCHESTRATOR" if command_config.get("execute") else "DRY_RUN_ONLY",
            bool(command_config.get("execute")),
            str(segments_json or ""),
            next_required_step=(
                ""
                if command_config.get("execute")
                else "rerun_orchestrator_with_execute_for_real_public_source_batch"
            ),
        ),
        _capability(
            "segment_timeout_cleanup",
            "timeout cleanup and resume-safe segment rerun",
            "AUTOMATED_BY_ORCHESTRATOR",
            True,
            f"segment_timeout_seconds={command_config.get('segment_timeout_seconds')}",
        ),
        _capability(
            "evidence_hash_fixation",
            "fixed public snapshot hash capture",
            "AUTOMATED_IN_BATCH_CLOSEOUT",
            True,
            str(aggregate_json or ""),
        ),
        _capability(
            "stage4_evidence_readback",
            "Stage4 evidence readback after snapshot hashing",
            "AUTOMATED_IN_BATCH_CLOSEOUT",
            True,
            str(aggregate_json or ""),
        ),
        _capability(
            "source_remediation",
            "same-source retry and alternate public source remediation",
            (
                "AUTOMATED_WHEN_ENABLED"
                if command_config.get("auto_execute_source_remediation")
                else "OPERATOR_OPTIONAL"
            ),
            bool(command_config.get("auto_execute_source_remediation")),
            str(aggregate_json or ""),
        ),
        _capability(
            "aggregate_review",
            "cross-segment closeout aggregation and readiness decision",
            "AUTOMATED_BY_ORCHESTRATOR",
            True,
            str(aggregate_json or ""),
        ),
        _capability(
            "operator_gray_launch_decision",
            "human approval gate for controlled gray execution",
            "HUMAN_DECISION_RECORDED" if operator_decision else "HUMAN_GATE_REQUIRED",
            False,
            operator_decision,
            next_required_step=(
                ""
                if operator_decision
                else "record_operator_gray_launch_decision"
                if summary.get("orchestration_state")
                == "CONTROLLED_GRAY_WAITING_OPERATOR_DECISION"
                else ""
            ),
        ),
        _capability(
            "customer_visibility",
            "customer-visible output",
            "DISABLED_BY_SAFETY_BOUNDARY",
            False,
            "customer_visible_allowed=false",
        ),
        _capability(
            "payment_delivery_refund",
            "payment, delivery, and automatic refund execution",
            "DISABLED_BY_SAFETY_BOUNDARY",
            False,
            "payment/delivery/refund=false",
        ),
        _capability(
            "workbench_trigger",
            "operator workbench trigger button",
            "WORKBENCH_PREPARE_READY",
            False,
            "/operator-console/controlled-gray-orchestrator/prepare",
            next_required_step="operator_can_prepare_manifest_from_workbench",
        ),
        _capability(
            "background_scheduler",
            "internal storage-backed controlled-batch worker queue",
            "INTERNAL_WORKER_QUEUE_READY",
            True,
            "/operator-console/controlled-gray-orchestrator/worker/run-once",
            next_required_step="start_worker_loop_or_os_scheduler_for_recurring_batches",
        ),
    ]


def _capability(
    capability_id: str,
    title: str,
    state: str,
    automated: bool,
    evidence: str,
    *,
    next_required_step: str = "",
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "title": title,
        "state": state,
        "automated": bool(automated),
        "evidence": evidence,
        "next_required_step": next_required_step,
    }


def _capability_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    for record in records:
        state = str(record.get("state") or "")
        state_counts[state] = state_counts.get(state, 0) + 1
    return {
        "capability_count": len(records),
        "automated_capability_count": sum(1 for record in records if record.get("automated")),
        "not_implemented_count": sum(
            1 for record in records if record.get("state") == "NOT_IMPLEMENTED"
        ),
        "human_gate_count": sum(
            1 for record in records if str(record.get("state") or "").startswith("HUMAN_")
        ),
        "state_counts": dict(sorted(state_counts.items())),
    }


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Gray Public Orchestrator",
        "",
        f"- orchestration_state: {summary.get('orchestration_state')}",
        f"- aggregate_gray_review_state: {summary.get('aggregate_gray_review_state')}",
        f"- human_gray_launch_approval_state: {summary.get('human_gray_launch_approval_state')}",
        f"- next_required_step: {summary.get('next_required_step')}",
        f"- completed_segment_count: {summary.get('completed_segment_count')}/{summary.get('segment_count')}",
        f"- project_sample_count: {summary.get('project_sample_count')}",
        f"- fixed_snapshot_sha256_count: {summary.get('fixed_snapshot_sha256_count')}",
        f"- stage4_readback_missing_sample_count: {summary.get('stage4_readback_missing_sample_count')}",
        f"- source_remediation_final_record_count: {summary.get('source_remediation_final_record_count')}",
        f"- can_enter_controlled_gray_execution: {str(bool(summary.get('can_enter_controlled_gray_execution'))).lower()}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- payment_execution_enabled: {str(bool(summary.get('payment_execution_enabled'))).lower()}",
        "",
        "## Automation Capabilities",
    ]
    for record in _records(_mapping(result.get("automation_capability_matrix")).get("records")):
        lines.append(
            f"- {record.get('capability_id')}: {record.get('state')} "
            f"automated={str(bool(record.get('automated'))).lower()}"
        )
    return "\n".join(lines) + "\n"


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


def _path_or_none(value: str | Path) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) and isinstance(value.get("records"), list):
        value = value.get("records")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


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


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


_OPEN_SAFETY_KEYS = (
    "customer_visible_allowed",
    "external_send_enabled",
    "payment_execution_enabled",
    "delivery_execution_enabled",
    "automatic_refund_enabled",
    "public_release_allowed",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--source-targets-json", default="")
    parser.add_argument("--derived-targets-json", default="")
    parser.add_argument("--source-targets-summary-json", default="")
    parser.add_argument("--segments-json", default="")
    parser.add_argument("--aggregate-json", default="")
    parser.add_argument("--group-by", default="target")
    parser.add_argument("--per-target-sample-goal", type=int, default=12)
    parser.add_argument("--per-target-candidate-limit", type=int, default=12)
    parser.add_argument("--target-limit", type=int, default=0)
    parser.add_argument("--segment-timeout-seconds", type=int, default=900)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--professional-source-only", action="store_true")
    parser.add_argument("--auto-execute-source-remediation", action="store_true")
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--operator-decision", default="")
    parser.add_argument("--operator-name", default="")
    parser.add_argument("--operator-decision-note", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = build_controlled_gray_public_orchestrator_manifest(
        output_root=args.output_root,
        source_targets_json=args.source_targets_json,
        derived_targets_json=args.derived_targets_json,
        source_targets_summary_json=args.source_targets_summary_json,
        segments_json=args.segments_json,
        aggregate_json=args.aggregate_json,
        execute=args.execute,
        group_by=args.group_by,
        per_target_sample_goal=args.per_target_sample_goal,
        per_target_candidate_limit=args.per_target_candidate_limit,
        target_limit=args.target_limit,
        segment_timeout_seconds=args.segment_timeout_seconds,
        professional_source_only=args.professional_source_only,
        auto_execute_source_remediation=args.auto_execute_source_remediation,
        force_rerun=args.force_rerun,
        operator_decision=args.operator_decision,
        operator_name=args.operator_name,
        operator_decision_note=args.operator_decision_note,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
