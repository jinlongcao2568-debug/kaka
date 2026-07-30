from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


DIAGNOSTIC_KIND = "runtime_blocker_controller_diagnostic_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/runtime-blocker-controller-diagnostic-v1")


def build_runtime_blocker_controller_diagnostic(
    *,
    stage6_review_cycle_json: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    cycle_path = Path(stage6_review_cycle_json)
    cycle = _read_json(cycle_path)
    summary = _mapping(cycle.get("summary"))
    manifest = _mapping(cycle.get("manifest"))
    controller_table = _mapping(manifest.get("runtime_blocker_subqueue_controller_table"))
    dispatch_table = _mapping(manifest.get("runtime_blocker_controller_dispatch_table"))
    dispatch_runner = _mapping(manifest.get("runtime_blocker_controller_dispatch_runner"))
    worker_followup_queue = _mapping(manifest.get("runtime_blocker_worker_followup_queue"))
    projection_table = _mapping(manifest.get("operator_projection_status_table"))

    result = {
        "diagnostic_kind": DIAGNOSTIC_KIND,
        "diagnostic_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "stage6_review_cycle_json": str(cycle_path),
            "source_stage6_review_loop_status_json": str(
                manifest.get("source_stage6_review_loop_status_json") or ""
            ),
            "source_release_field_query_json": str(manifest.get("source_release_field_query_json") or ""),
        },
        "controller_state": _controller_state(summary),
        "route_diagnosis": _route_diagnosis(summary),
        "dispatch_diagnosis": _dispatch_diagnosis(summary),
        "followup_diagnosis": _followup_diagnosis(summary, dispatch_runner, worker_followup_queue),
        "operator_projection_diagnosis": _operator_projection_diagnosis(projection_table),
        "priority_work_queues": _priority_work_queues(controller_table, dispatch_table, projection_table),
        "p0_gap_summary": _p0_gap_summary(summary),
        "recommended_next_actions": _recommended_next_actions(summary),
        "safety": _safety(summary, manifest),
    }

    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "runtime-blocker-controller-diagnostic-v1.json", result)
    _write_markdown(out_dir / "runtime-blocker-controller-diagnostic-v1.md", result)
    return result


def _controller_state(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stage6_review_cycle_runner_state": str(summary.get("stage6_review_cycle_runner_state") or ""),
        "stage6_review_cycle_input_mode": str(summary.get("stage6_review_cycle_input_mode") or ""),
        "execution_mode": str(summary.get("execution_mode") or ""),
        "runtime_blocker_next_subqueue_input_state": str(
            summary.get("runtime_blocker_next_subqueue_input_state") or ""
        ),
        "runtime_blocker_next_subqueue_record_count": _int(
            summary.get("runtime_blocker_next_subqueue_record_count")
        ),
        "runtime_blocker_controller_queue_record_count": _int(
            summary.get("runtime_blocker_controller_queue_record_count")
        ),
        "runtime_blocker_controller_dispatch_task_count": _int(
            summary.get("runtime_blocker_controller_dispatch_task_count")
        ),
        "runtime_blocker_controller_dispatch_ready_count": _int(
            summary.get("runtime_blocker_controller_dispatch_ready_count")
        ),
        "runtime_blocker_controller_automated_worker_dispatch_allowed_count": _int(
            summary.get("runtime_blocker_controller_automated_worker_dispatch_allowed_count")
        ),
    }


def _route_diagnosis(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "subqueue_route_counts": _dict(summary.get("runtime_blocker_next_subqueue_route_counts")),
        "controller_route_state_counts": _dict(summary.get("runtime_blocker_controller_route_state_counts")),
        "controller_next_action_counts": _dict(summary.get("runtime_blocker_controller_next_action_counts")),
        "dispatch_worker_family_counts": _dict(
            summary.get("runtime_blocker_controller_dispatch_worker_family_counts")
        ),
    }


def _dispatch_diagnosis(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dispatch_readiness_state_counts": _dict(
            summary.get("runtime_blocker_controller_dispatch_readiness_state_counts")
        ),
        "dispatch_route_counts": _dict(summary.get("runtime_blocker_controller_dispatch_route_counts")),
        "dispatch_blocking_reason_counts": _dict(
            summary.get("runtime_blocker_controller_dispatch_blocking_reason_counts")
        ),
        "dispatch_runner_execution_state_counts": _dict(
            summary.get("runtime_blocker_dispatch_runner_execution_state_counts")
        ),
        "dispatch_runner_readback_state_counts": _dict(
            summary.get("runtime_blocker_dispatch_runner_readback_state_counts")
        ),
        "dispatch_runner_closeout_state_counts": _dict(
            summary.get("runtime_blocker_dispatch_runner_closeout_state_counts")
        ),
        "ready_for_field_query_backfill_count": _int(
            summary.get("runtime_blocker_dispatch_runner_ready_for_field_query_backfill_count")
        ),
    }


def _followup_diagnosis(
    summary: Mapping[str, Any],
    dispatch_runner: Mapping[str, Any],
    worker_followup_queue: Mapping[str, Any],
) -> dict[str, Any]:
    queue_records = _records(worker_followup_queue)
    runner_manifest = _mapping(dispatch_runner.get("manifest"))
    runner_records = _records(runner_manifest.get("records"))
    return {
        "summary_followup_task_count": _int(summary.get("runtime_blocker_dispatch_runner_followup_task_count")),
        "summary_followup_task_type_counts": _dict(
            summary.get("runtime_blocker_dispatch_runner_followup_task_type_counts")
        ),
        "worker_followup_queue_record_count": len(queue_records),
        "worker_followup_queue_task_type_counts": _counts(
            str(record.get("followup_task_type") or "") for record in queue_records
        ),
        "dispatch_runner_record_count": len(runner_records),
        "existing_output_consumed_count": _int(
            summary.get("runtime_blocker_dispatch_runner_existing_output_consumed_count")
        ),
        "executed_success_count": _int(summary.get("runtime_blocker_dispatch_runner_executed_success_count")),
        "executed_failed_count": _int(summary.get("runtime_blocker_dispatch_runner_executed_failed_count")),
    }


def _operator_projection_diagnosis(projection_table: Mapping[str, Any]) -> dict[str, Any]:
    projection_summary = _mapping(projection_table.get("summary"))
    records = _records(projection_table.get("records"))
    return {
        "project_status_record_count": _int(projection_summary.get("project_status_record_count")) or len(records),
        "limited_sellable_review_candidate_count": _int(
            projection_summary.get("limited_sellable_review_candidate_count")
        ),
        "limited_sellable_review_candidate_state_counts": _dict(
            projection_summary.get("limited_sellable_review_candidate_state_counts")
        ),
        "commercialization_boundary_state_counts": _dict(
            projection_summary.get("commercialization_boundary_state_counts")
        ),
        "customer_visible_allowed_count": sum(1 for record in records if bool(record.get("customer_visible_allowed"))),
        "gdcic_authorization_readiness_state_counts": _counts(
            str(record.get("gdcic_authorization_readiness_state") or "") for record in records
        ),
        "alternative_public_source_route_total": sum(
            _int(record.get("gdcic_alternative_public_source_route_count")) for record in records
        ),
    }


def _priority_work_queues(
    controller_table: Mapping[str, Any],
    dispatch_table: Mapping[str, Any],
    projection_table: Mapping[str, Any],
) -> dict[str, Any]:
    controller_records = _records(controller_table.get("records"))
    dispatch_records = _records(dispatch_table.get("records"))
    projection_records = _records(projection_table.get("records"))
    return {
        "fallback_source_plan_required": _sample_records(
            controller_records,
            lambda record: str(record.get("subqueue_route") or "") == "fallback_source",
            ("project_id", "task_id", "task_type", "controller_route_state", "blocker_state", "operator_next_action"),
        ),
        "authorized_browser_input_required": _sample_records(
            controller_records,
            lambda record: str(record.get("subqueue_route") or "") == "browser_worker",
            ("project_id", "task_id", "task_type", "controller_route_state", "blocker_state", "required_input"),
        ),
        "retry_reopen_input_required": _sample_records(
            dispatch_records,
            lambda record: str(record.get("dispatch_route") or "") == "retry",
            ("project_id", "task_id", "task_type", "dispatch_readiness_state", "blocking_reason"),
        ),
        "operator_action_required": _sample_records(
            controller_records,
            lambda record: str(record.get("subqueue_route") or "") == "operator_action",
            ("project_id", "task_id", "task_type", "controller_route_state", "blocker_state", "operator_next_action"),
        ),
        "limited_review_internal_candidates": _sample_records(
            projection_records,
            lambda record: str(record.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE",
            (
                "project_id",
                "project_name",
                "strong_lead_candidate_state",
                "commercialization_boundary_state",
                "limited_sellable_review_evidence_grade_counts",
            ),
        ),
    }


def _p0_gap_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    readiness = _dict(summary.get("runtime_blocker_controller_dispatch_readiness_state_counts"))
    route_counts = _dict(summary.get("runtime_blocker_controller_dispatch_route_counts"))
    followup_types = _dict(summary.get("runtime_blocker_dispatch_runner_followup_task_type_counts"))
    return {
        "stage4_followup_queue_entered_controller": _int(
            summary.get("runtime_blocker_controller_queue_record_count")
        )
        > 0,
        "dispatch_ready_count": _int(summary.get("runtime_blocker_controller_dispatch_ready_count")),
        "fallback_source_plan_required_count": _int(readiness.get("FALLBACK_SOURCE_PLAN_REQUIRED")),
        "authorized_browser_or_same_session_input_required_count": _int(
            readiness.get("BLOCKED_REQUIRED_INPUT_OR_WORKER_SPEC_MISSING")
        ),
        "operator_action_recorded_count": _int(readiness.get("OPERATOR_ACTION_RECORDED_NO_WORKER_DISPATCH")),
        "retry_reopen_input_required_count": _int(readiness.get("RETRY_REOPEN_INPUT_REQUIRED")),
        "fallback_source_route_count": _int(route_counts.get("fallback_source")),
        "runtime_blocker_followup_task_count": _int(
            summary.get("runtime_blocker_dispatch_runner_followup_task_count")
        ),
        "fallback_source_followup_task_count": _int(followup_types.get("BUILD_FALLBACK_SOURCE_ADAPTER_PLAN")),
        "retry_followup_task_count": _int(followup_types.get("RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT")),
    }


def _recommended_next_actions(summary: Mapping[str, Any]) -> list[str]:
    actions: list[str] = []
    readiness = _dict(summary.get("runtime_blocker_controller_dispatch_readiness_state_counts"))
    if _int(readiness.get("FALLBACK_SOURCE_PLAN_REQUIRED")):
        actions.append("build_fallback_source_adapter_plan_for_local_authority_or_bid_show_routes")
    if _int(readiness.get("BLOCKED_REQUIRED_INPUT_OR_WORKER_SPEC_MISSING")):
        actions.append("keep_login_or_sso_required_unless_authorized_session_input_exists")
    if _int(readiness.get("RETRY_REOPEN_INPUT_REQUIRED")):
        actions.append("retry_only_after_reopen_inputs_or_more_precise_public_identifiers_exist")
    if _int(readiness.get("OPERATOR_ACTION_RECORDED_NO_WORKER_DISPATCH")):
        actions.append("surface_operator_actions_without_customer_delivery")
    actions.append("keep_customer_delivery_payment_refund_disabled")
    actions.append("keep_not_found_blocked_needs_browser_as_non_clearance")
    return actions


def _safety(summary: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    manifest_safety = _mapping(manifest.get("safety"))
    return {
        "live_execution_enabled": bool(summary.get("live_execution_enabled")),
        "customer_visible_allowed": bool(summary.get("customer_visible_allowed")),
        "dispatch_execution_enabled": bool(manifest_safety.get("dispatch_execution_enabled")),
        "runtime_blocker_dispatch_execution_enabled": bool(
            manifest_safety.get("runtime_blocker_dispatch_execution_enabled")
        ),
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": bool(summary.get("query_miss_is_not_clearance", True)),
        "no_legal_conclusion": bool(summary.get("no_legal_conclusion", True)),
        "not_found_blocked_needs_browser_are_not_clearance": True,
        "forbidden_term_scan_state": str(summary.get("forbidden_term_scan_state") or ""),
    }


def _sample_records(
    records: list[Mapping[str, Any]],
    predicate: Any,
    fields: Iterable[str],
    *,
    limit: int = 10,
) -> dict[str, Any]:
    matched = [record for record in records if predicate(record)]
    return {
        "record_count": len(matched),
        "sample_records": [
            {field: record.get(field) for field in fields if field in record}
            for record in matched[:limit]
        ],
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        value = value.get("records")
    return [record for record in value if isinstance(record, Mapping)] if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _int(count) for key, count in value.items()}


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    lines = [
        "# Runtime Blocker Controller Diagnostic v1",
        "",
        f"- controller_state: {json.dumps(payload.get('controller_state', {}), ensure_ascii=False, sort_keys=True)}",
        f"- route_diagnosis: {json.dumps(payload.get('route_diagnosis', {}), ensure_ascii=False, sort_keys=True)}",
        f"- dispatch_diagnosis: {json.dumps(payload.get('dispatch_diagnosis', {}), ensure_ascii=False, sort_keys=True)}",
        f"- followup_diagnosis: {json.dumps(payload.get('followup_diagnosis', {}), ensure_ascii=False, sort_keys=True)}",
        f"- operator_projection_diagnosis: {json.dumps(payload.get('operator_projection_diagnosis', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p0_gap_summary: {json.dumps(payload.get('p0_gap_summary', {}), ensure_ascii=False, sort_keys=True)}",
        f"- recommended_next_actions: {json.dumps(payload.get('recommended_next_actions', []), ensure_ascii=False)}",
        "",
        "customer_visible_allowed=false; query_miss_is_not_clearance=true; no_legal_conclusion=true",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage6-review-cycle-json", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_runtime_blocker_controller_diagnostic(
        stage6_review_cycle_json=args.stage6_review_cycle_json,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result.get("p0_gap_summary") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
