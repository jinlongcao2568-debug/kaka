from __future__ import annotations

from typing import Any, Mapping


WORKER_ID = "stage1_3_repair_worker"


def build_stage1_3_repair_worker_plan(
    payload: Mapping[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    records = _dispatch_records(payload)
    repair_records = [
        dict(record)
        for record in records
        if str(record.get("review_family") or "").startswith("stage1_3_")
    ]
    tasks = [_repair_task(record, created_at=created_at) for record in repair_records]
    return {
        "worker_id": WORKER_ID,
        "worker_mode": "INTERNAL_REPAIR_PLAN_ONLY",
        "repair_worker_state": "REPAIR_PLAN_READY" if tasks else "NO_STAGE1_3_REPAIR_TASKS",
        "created_at": created_at,
        "repair_task_count": len(tasks),
        "repair_metric_counts": _sum_by_key(tasks, key_field="source_metric", value_field="metric_count"),
        "repair_worker_family_counts": _counts(task.get("worker_family") for task in tasks),
        "repair_review_family_counts": _counts(task.get("review_family") for task in tasks),
        "repair_tasks": tasks,
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "external_customer_action_enabled": False,
        "real_payment_enabled": False,
        "real_delivery_enabled": False,
        "automatic_refund_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _dispatch_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    direct_records = payload.get("dispatch_queue_records")
    if isinstance(direct_records, list):
        return [dict(record) for record in direct_records if isinstance(record, Mapping)]
    queue = payload.get("controller_dispatch_queue") or payload.get("dispatch_queue")
    if isinstance(queue, Mapping) and isinstance(queue.get("records"), list):
        return [dict(record) for record in queue.get("records", []) if isinstance(record, Mapping)]
    latest_projection = payload.get("latest_projection")
    if isinstance(latest_projection, Mapping):
        projection_queue = latest_projection.get("controller_dispatch_queue")
        if isinstance(projection_queue, Mapping) and isinstance(projection_queue.get("records"), list):
            return [dict(record) for record in projection_queue.get("records", []) if isinstance(record, Mapping)]
    return []


def _repair_task(record: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    review_family = str(record.get("review_family") or "")
    source_metric = str(record.get("source_metric") or record.get("reason") or "")
    metric_count = int(record.get("metric_count") or 0)
    dispatch_task_id = str(record.get("dispatch_task_id") or "")
    worker_family = _worker_family(review_family)
    return {
        "repair_task_id": f"REPAIR-{dispatch_task_id}" if dispatch_task_id else f"REPAIR-{review_family}",
        "source_dispatch_task_id": dispatch_task_id,
        "run_id": str(record.get("run_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "current_stage_id": str(record.get("current_stage_id") or ""),
        "review_family": review_family,
        "review_state": str(record.get("review_state") or ""),
        "source_metric": source_metric,
        "metric_count": metric_count,
        "worker_family": worker_family,
        "worker_next_action": _worker_next_action(worker_family),
        "operator_next_action": str(record.get("operator_next_action") or ""),
        "input_refs": [str(ref) for ref in record.get("input_refs", []) if str(ref or "").strip()]
        if isinstance(record.get("input_refs"), list)
        else [],
        "execution_state": "PLAN_READY_INTERNAL_REPAIR_NOT_EXECUTED",
        "requires_operator_review": True,
        "live_execution_enabled": False,
        "external_customer_action_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _worker_family(review_family: str) -> str:
    mapping = {
        "stage1_3_attachment_snapshot_repair": "stage2_attachment_snapshot_repair_worker",
        "stage1_3_attachment_snapshot_readback_repair": "stage2_attachment_readback_repair_worker",
        "stage1_3_attachment_ocr_repair": "stage3_attachment_ocr_repair_worker",
        "stage1_3_responsible_role_review": "stage3_responsible_role_review_worker",
        "stage1_3_parse_blocker_review": "stage3_parse_blocker_review_worker",
    }
    return mapping.get(review_family, "stage1_3_manual_repair_worker")


def _worker_next_action(worker_family: str) -> str:
    mapping = {
        "stage2_attachment_snapshot_repair_worker": "prepare_attachment_snapshot_repair_inputs_before_fetch",
        "stage2_attachment_readback_repair_worker": "prepare_attachment_readback_repair_inputs_before_parse",
        "stage3_attachment_ocr_repair_worker": "prepare_attachment_ocr_repair_inputs_before_ocr",
        "stage3_responsible_role_review_worker": "prepare_responsible_role_review_inputs_before_writeback",
        "stage3_parse_blocker_review_worker": "prepare_parse_blocker_diagnostics_before_retry",
    }
    return mapping.get(worker_family, "prepare_stage1_3_manual_repair_inputs")


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        out[text] = out.get(text, 0) + 1
    return out


def _sum_by_key(records: list[Mapping[str, Any]], *, key_field: str, value_field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in records:
        key = str(record.get(key_field) or "").strip()
        if not key:
            continue
        out[key] = out.get(key, 0) + int(record.get(value_field) or 0)
    return out


__all__ = ["WORKER_ID", "build_stage1_3_repair_worker_plan"]
