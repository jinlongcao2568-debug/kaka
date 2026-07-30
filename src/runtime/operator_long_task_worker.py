from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path
from threading import Event
from typing import Any, Mapping
from uuid import uuid4

from runtime.controlled_gray_scheduler_worker import (
    JobExecutionControl,
    controlled_gray_scheduler_status,
    run_controlled_gray_scheduler_worker_once,
    serve_controlled_gray_scheduler_worker,
)
from shared.utils import utc_now_iso
from storage.db import PersistedWorkerQueueItem
from storage.repositories.worker_queue_repo import WorkerQueueRepository


OPERATOR_LONG_TASK_QUEUE_NAME = "operator_long_tasks"
OPERATOR_LONG_TASK_WORKER_ID = "operator-long-task-browser-worker-v1"
AUTONOMOUS_SEARCH_JOB_KIND = "operator_autonomous_opportunity_search_v1"
REAL_SOURCE_CAPTURE_JOB_KIND = "owner_real_public_source_capture_v1"
SUPPORTED_JOB_KINDS = (
    AUTONOMOUS_SEARCH_JOB_KIND,
    REAL_SOURCE_CAPTURE_JOB_KIND,
)
DEFAULT_STATUS_JSON = Path(
    "tmp/runtime/operator-long-task-browser-worker-status-v1.json"
)
_BLOCKED_FLAGS = (
    "live_execution_enabled",
    "external_release_enabled",
    "customer_visible_allowed",
    "payment_execution_enabled",
    "delivery_execution_enabled",
    "automatic_refund_enabled",
)


def enqueue_operator_long_task(
    *,
    job_kind: str,
    task_payload: Mapping[str, Any],
    repository: WorkerQueueRepository | None = None,
    queue_item_id: str | None = None,
    priority: int = 50,
    max_attempts: int = 3,
    time_budget_seconds: int = 1_800,
    now: str | None = None,
) -> PersistedWorkerQueueItem:
    normalized_kind = str(job_kind or "").strip()
    if normalized_kind not in SUPPORTED_JOB_KINDS:
        raise ValueError(f"unsupported operator long task job kind: {job_kind!r}")
    payload = dict(task_payload)
    opened = [key for key in _BLOCKED_FLAGS if _truthy(payload.get(key))]
    if opened:
        raise ValueError(
            "operator long task cannot enable customer/live execution flags: "
            + ", ".join(opened)
        )
    created_at = now or utc_now_iso()
    item_id = str(queue_item_id or f"OPERATOR-LONG-TASK-{uuid4().hex}")
    required_capability = "browser"
    runtime_payload = {
        "runtime_job_kind": normalized_kind,
        "required_worker_capability": required_capability,
        "task_payload": payload,
        "internal_only": True,
        "web_request_execution_enabled": False,
        "customer_visible_allowed": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
    }
    active_repo = repository or WorkerQueueRepository()
    return active_repo.enqueue(
        queue_item_id=item_id,
        queue_name=OPERATOR_LONG_TASK_QUEUE_NAME,
        payload=runtime_payload,
        priority=max(0, int(priority)),
        max_attempts=max(1, int(max_attempts)),
        next_run_at=created_at,
        time_budget_seconds=max(1, int(time_budget_seconds)),
        trace_refs={
            "trace_id": item_id,
            "runtime_job_kind": normalized_kind,
            "required_worker_capability": required_capability,
        },
        audit_refs={
            "run_audit_ref": item_id,
            "internal_only": "true",
            "web_request_execution_enabled": "false",
            "customer_visible_allowed": "false",
        },
        now=created_at,
    )


def execute_operator_long_task(
    payload: Mapping[str, Any],
    control: JobExecutionControl,
) -> Mapping[str, Any]:
    job_kind = str(payload.get("runtime_job_kind") or "")
    task_payload = dict(payload.get("task_payload") or {})
    control.report_progress("DISPATCH", 0, 3, "validating operator long task")
    control.raise_if_cancelled()
    task_payload["_runtime_execution_control"] = control

    # Lazy import avoids making the HTTP application depend on the worker module.
    from api.routes.operator_customer_access import (
        run_operator_autonomous_opportunity_search,
        run_owner_real_public_source_capture,
    )

    control.report_progress("EXECUTE", 1, 3, f"executing {job_kind}")
    if job_kind == AUTONOMOUS_SEARCH_JOB_KIND:
        result = run_operator_autonomous_opportunity_search(task_payload)
    elif job_kind == REAL_SOURCE_CAPTURE_JOB_KIND:
        result = run_owner_real_public_source_capture(task_payload)
    else:
        raise ValueError(f"unsupported operator long task job kind: {job_kind!r}")
    control.raise_if_cancelled()
    control.report_progress("PERSISTED_READBACK", 3, 3, "result persisted")
    return {
        "output_root": "",
        "summary": {
            "orchestration_state": str(
                result.get("search_state")
                or result.get("capture_status")
                or "COMPLETED"
            ),
            "aggregate_gray_review_state": "NOT_APPLICABLE",
        },
        "manifest": {},
        "operator_long_task_result": result,
    }


def run_operator_long_task_worker_once(
    *,
    repository: WorkerQueueRepository | None = None,
    worker_id: str = OPERATOR_LONG_TASK_WORKER_ID,
    worker_capability: str = "browser",
    lease_seconds: int = 900,
    heartbeat_seconds: float = 15.0,
    retry_delay_seconds: int = 60,
) -> dict[str, Any]:
    return run_controlled_gray_scheduler_worker_once(
        repository=repository,
        handler=execute_operator_long_task,
        worker_id=worker_id,
        worker_capability=worker_capability,
        queue_name=OPERATOR_LONG_TASK_QUEUE_NAME,
        lease_seconds=lease_seconds,
        heartbeat_seconds=heartbeat_seconds,
        retry_delay_seconds=retry_delay_seconds,
    )


def operator_long_task_status(
    repository: WorkerQueueRepository | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    status = controlled_gray_scheduler_status(
        repository,
        limit=limit,
        queue_name=OPERATOR_LONG_TASK_QUEUE_NAME,
    )
    status.update(
        {
            "supported_job_kinds": list(SUPPORTED_JOB_KINDS),
            "required_worker_capability": "browser",
            "dedicated_process_command": (
                "python -m runtime.operator_long_task_worker --serve "
                "--worker-capability browser"
            ),
            "recurring_schedule_enabled": False,
            "unattended_recurring_run_ready": False,
            "unattended_recurring_scope": "NOT_APPLICABLE",
            "unattended_operator_long_task_ready": True,
            "unattended_operator_long_task_scope": "INTERNAL_ONLY",
        }
    )
    return status


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run capability-routed operator long tasks outside the API process."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--serve", action="store_true")
    parser.add_argument("--worker-id", default=OPERATOR_LONG_TASK_WORKER_ID)
    parser.add_argument("--worker-capability", choices=("core", "browser"), default="browser")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--lease-seconds", type=int, default=900)
    parser.add_argument("--heartbeat-seconds", type=float, default=15.0)
    parser.add_argument("--retry-delay-seconds", type=int, default=60)
    parser.add_argument("--status-json", default=str(DEFAULT_STATUS_JSON))
    parser.add_argument("--max-idle-polls", type=int, default=0)
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.once:
        result = run_operator_long_task_worker_once(
            worker_id=args.worker_id,
            worker_capability=args.worker_capability,
            lease_seconds=args.lease_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            retry_delay_seconds=args.retry_delay_seconds,
        )
    else:
        stop = Event()

        def request_stop(signum: int, frame: Any) -> None:
            del signum, frame
            stop.set()

        signal.signal(signal.SIGINT, request_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_stop)
        result = serve_controlled_gray_scheduler_worker(
            handler=execute_operator_long_task,
            worker_id=args.worker_id,
            worker_capability=args.worker_capability,
            queue_name=OPERATOR_LONG_TASK_QUEUE_NAME,
            poll_seconds=args.poll_seconds,
            lease_seconds=args.lease_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            retry_delay_seconds=args.retry_delay_seconds,
            status_json=args.status_json,
            stop_event=stop,
            max_idle_polls=max(0, args.max_idle_polls),
        )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if str(result.get("worker_state") or "").endswith("DEAD_LETTERED") else 0


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "live"}
    return bool(value)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTONOMOUS_SEARCH_JOB_KIND",
    "OPERATOR_LONG_TASK_QUEUE_NAME",
    "REAL_SOURCE_CAPTURE_JOB_KIND",
    "enqueue_operator_long_task",
    "execute_operator_long_task",
    "operator_long_task_status",
    "run_operator_long_task_worker_once",
]
