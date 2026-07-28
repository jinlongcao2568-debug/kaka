from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import signal
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Mapping
from uuid import uuid4

from runtime.controlled_gray_public_orchestrator import (
    build_controlled_gray_public_orchestrator_prepare_bundle,
)
from runtime.operational_observability import get_operational_event_sink
from shared.utils import utc_now_iso
from storage.db import PersistedWorkerQueueItem, StorageConcurrencyError
from storage.repositories.worker_queue_repo import WorkerQueueRepository
from storage.worker_queue import iso_after, iso_lte, parse_iso


CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME = "controlled_gray_public_orchestrator"
CONTROLLED_GRAY_ORCHESTRATOR_WORKER_ID = (
    "controlled-gray-public-orchestrator-dedicated-worker-v1"
)
CONTROLLED_GRAY_ORCHESTRATOR_JOB_KIND = (
    "controlled_gray_public_orchestrator_prepare_v1"
)
DEFAULT_STATUS_JSON = Path(
    "tmp/runtime/controlled-gray-scheduler-worker-status-v1.json"
)
MIN_RECURRING_INTERVAL_SECONDS = 60
MAX_RECURRING_INTERVAL_SECONDS = 31 * 24 * 60 * 60
DEFAULT_POLL_SECONDS = 5.0
DEFAULT_LEASE_SECONDS = 900
DEFAULT_HEARTBEAT_SECONDS = 30.0
DEFAULT_RETRY_DELAY_SECONDS = 60
DEFAULT_WORKER_CAPABILITY = "core"
SUPPORTED_WORKER_CAPABILITIES = ("core", "browser")
_SCHEDULE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BLOCKED_EXECUTION_FLAGS = (
    "execute",
    "live_execution_enabled",
    "external_release_enabled",
    "customer_visible_allowed",
    "payment_execution_enabled",
    "delivery_execution_enabled",
    "automatic_refund_enabled",
)

JobHandler = Callable[..., Mapping[str, Any]]


class JobCancellationRequested(RuntimeError):
    pass


class JobExecutionControl:
    def __init__(self) -> None:
        self.cancel_event = Event()
        self._lock = Lock()
        self._cancel_reason = ""
        self._pending_progress: dict[str, Any] | None = None

    @property
    def cancel_reason(self) -> str:
        with self._lock:
            return self._cancel_reason

    def request_cancel(self, reason: str) -> None:
        with self._lock:
            if not self._cancel_reason:
                self._cancel_reason = str(reason or "CANCEL_REQUESTED")
        self.cancel_event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancellationRequested(self.cancel_reason or "CANCEL_REQUESTED")

    def report_progress(
        self,
        stage: str,
        completed_units: int,
        total_units: int,
        message: str,
    ) -> None:
        self.raise_if_cancelled()
        with self._lock:
            self._pending_progress = {
                "stage": str(stage or "RUNNING"),
                "completed_units": max(0, int(completed_units)),
                "total_units": max(1, int(total_units)),
                "message": str(message or ""),
            }

    def take_progress(self) -> dict[str, Any] | None:
        with self._lock:
            progress = self._pending_progress
            self._pending_progress = None
        return progress


def enqueue_controlled_gray_orchestrator_job(
    payload: Mapping[str, Any],
    *,
    repository: WorkerQueueRepository | None = None,
    queue_item_id: str,
    priority: int = 50,
    max_attempts: int = 3,
    next_run_at: str | None = None,
    recurring_interval_seconds: int = 0,
    schedule_id: str | None = None,
    occurrence: int = 0,
    time_budget_seconds: int = 1_800,
    now: str | None = None,
) -> PersistedWorkerQueueItem:
    job_payload = dict(payload)
    _assert_safe_prepare_job(job_payload)
    created_at = now or utc_now_iso()
    scheduled_for = next_run_at or created_at
    interval = _validate_recurring_interval(recurring_interval_seconds)
    normalized_schedule_id = str(schedule_id or queue_item_id).strip()
    if not _SCHEDULE_ID_PATTERN.fullmatch(normalized_schedule_id):
        raise ValueError("schedule_id must be 1-128 safe identifier characters")
    job_payload.update(
        {
            "runtime_job_kind": CONTROLLED_GRAY_ORCHESTRATOR_JOB_KIND,
            "runtime_schedule": {
                "schedule_id": normalized_schedule_id,
                "recurring": interval > 0,
                "interval_seconds": interval,
                "occurrence": max(0, int(occurrence)),
                "scheduled_for": scheduled_for,
                "misfire_policy": "SKIP_TO_NEXT_FUTURE",
            },
            "dedicated_worker_required": True,
            "required_worker_capability": "core",
            "web_request_execution_enabled": False,
            "internal_only": True,
            "customer_visible_allowed": False,
        }
    )
    active_repo = repository or WorkerQueueRepository()
    return active_repo.enqueue(
        queue_item_id=queue_item_id,
        queue_name=CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME,
        payload=job_payload,
        priority=int(priority),
        max_attempts=max(1, int(max_attempts)),
        next_run_at=scheduled_for,
        trace_refs={
            "trace_id": queue_item_id,
            "runtime_job_kind": CONTROLLED_GRAY_ORCHESTRATOR_JOB_KIND,
            "schedule_id": normalized_schedule_id,
            "worker_entry": "python -m runtime.controlled_gray_scheduler_worker --serve",
            "output_root": str(job_payload.get("output_root") or ""),
        },
        audit_refs={
            "run_audit_ref": queue_item_id,
            "internal_only": "true",
            "dedicated_worker_required": "true",
            "web_request_execution_enabled": "false",
            "execute_enabled": "false",
            "customer_visible_allowed": "false",
            "payment_execution_enabled": "false",
            "delivery_execution_enabled": "false",
            "automatic_refund_enabled": "false",
        },
        time_budget_seconds=max(1, int(time_budget_seconds)),
        now=created_at,
    )


def execute_controlled_gray_prepare_job(
    payload: Mapping[str, Any],
    control: JobExecutionControl | None = None,
) -> Mapping[str, Any]:
    _assert_safe_prepare_job(payload)
    if str(payload.get("runtime_job_kind") or "") != CONTROLLED_GRAY_ORCHESTRATOR_JOB_KIND:
        raise ValueError("unsupported controlled gray orchestrator runtime_job_kind")
    return build_controlled_gray_public_orchestrator_prepare_bundle(
        output_root=str(payload.get("output_root") or ""),
        source_targets_json=str(payload.get("source_targets_json") or ""),
        per_target_sample_goal=max(1, int(payload.get("per_target_sample_goal") or 12)),
        per_target_candidate_limit=max(
            1, int(payload.get("per_target_candidate_limit") or 12)
        ),
        target_limit=max(0, int(payload.get("target_limit") or 0)),
        group_by=str(payload.get("group_by") or "target"),
        segment_timeout_seconds=max(
            1, int(payload.get("segment_timeout_seconds") or 900)
        ),
        professional_source_only=True,
        execute=False,
        auto_execute_source_remediation=True,
        progress_callback=control.report_progress if control is not None else None,
        cancellation_checkpoint=(
            control.raise_if_cancelled if control is not None else None
        ),
    )


def run_controlled_gray_scheduler_worker_once(
    *,
    repository: WorkerQueueRepository | None = None,
    handler: JobHandler | None = None,
    worker_id: str = CONTROLLED_GRAY_ORCHESTRATOR_WORKER_ID,
    worker_capability: str = DEFAULT_WORKER_CAPABILITY,
    queue_name: str = CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS,
    now: str | None = None,
    now_factory: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    observed_started = time.monotonic()
    active_repo = repository or WorkerQueueRepository()
    normalized_capability = _validate_worker_capability(worker_capability)
    claimed_at = now or now_factory()
    lease_id = _lease_id(worker_id)
    claimed = active_repo.claim_next(
        queue_name=queue_name,
        worker_id=worker_id,
        lease_id=lease_id,
        lease_seconds=max(1, int(lease_seconds)),
        payload_predicate=lambda payload: str(
            payload.get("required_worker_capability") or "core"
        )
        == normalized_capability,
        now=claimed_at,
    )
    if claimed is None:
        return {
            "worker_state": "NO_DUE_QUEUE_ITEM",
            "claimed": False,
            "heartbeat_count": 0,
            "worker_capability": normalized_capability,
            "queue": controlled_gray_scheduler_status(
                active_repo, now=claimed_at, queue_name=queue_name
            ),
            **_safety(),
        }

    _record_worker_event(
        queue_item_id=claimed.queue_item_id,
        queue_name=queue_name,
        worker_capability=normalized_capability,
        outcome="started",
        severity="INFO",
        duration_ms=0,
        error_category=None,
        queue_status=claimed.status,
    )

    active_handler = handler or execute_controlled_gray_prepare_job
    control = JobExecutionControl()
    heartbeat_count = 0
    progress_update_count = 0
    lease_lost_error = ""
    result: Mapping[str, Any] | None = None
    failure: Exception | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="kaka-controlled-gray-job") as pool:
        future: Future[Mapping[str, Any]] = pool.submit(
            _invoke_handler,
            active_handler,
            dict(claimed.payload),
            control,
        )
        heartbeat_wait = max(0.01, float(heartbeat_seconds))
        if claimed.time_budget_seconds is not None:
            heartbeat_wait = min(
                heartbeat_wait,
                max(0.01, min(1.0, claimed.time_budget_seconds / 10.0)),
            )
        while True:
            done, _ = wait((future,), timeout=heartbeat_wait)
            if done:
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - failures must enter durable retry state.
                    failure = exc
                break
            try:
                observed_at = now_factory()
                current = active_repo.get(claimed.queue_item_id)
                if current is None:
                    raise ValueError(
                        f"queue item {claimed.queue_item_id!r} disappeared while running"
                    )
                if current.cancel_requested_at:
                    control.request_cancel("OPERATOR_CANCEL_REQUESTED")
                if current.budget_deadline_at and iso_lte(
                    current.budget_deadline_at,
                    observed_at,
                ):
                    control.request_cancel("TIME_BUDGET_EXCEEDED")
                progress_update_count += _flush_progress(
                    control,
                    repository=active_repo,
                    queue_item_id=claimed.queue_item_id,
                    worker_id=worker_id,
                    lease_id=lease_id,
                    now=observed_at,
                )
                active_repo.heartbeat(
                    queue_item_id=claimed.queue_item_id,
                    worker_id=worker_id,
                    lease_id=lease_id,
                    lease_seconds=max(1, int(lease_seconds)),
                    now=observed_at,
                )
                heartbeat_count += 1
            except (StorageConcurrencyError, ValueError) as exc:
                lease_lost_error = str(exc)
                try:
                    result = future.result()
                except Exception as handler_exc:  # noqa: BLE001
                    failure = handler_exc
                break

    completed_at = now if now is not None else now_factory()
    if not lease_lost_error:
        try:
            progress_update_count += _flush_progress(
                control,
                repository=active_repo,
                queue_item_id=claimed.queue_item_id,
                worker_id=worker_id,
                lease_id=lease_id,
                now=completed_at,
            )
        except (StorageConcurrencyError, ValueError) as exc:
            lease_lost_error = str(exc)
    if lease_lost_error:
        _record_worker_event(
            queue_item_id=claimed.queue_item_id,
            queue_name=queue_name,
            worker_capability=normalized_capability,
            outcome="error",
            severity="ERROR",
            duration_ms=(time.monotonic() - observed_started) * 1000,
            error_category="LEASE_LOST",
            queue_status="lease-lost",
        )
        return {
            "worker_state": "LEASE_LOST_RESULT_DISCARDED",
            "claimed": True,
            "queue_item_id": claimed.queue_item_id,
            "lease_id": lease_id,
            "heartbeat_count": heartbeat_count,
            "progress_update_count": progress_update_count,
            "worker_capability": normalized_capability,
            "error": lease_lost_error,
            "handler_error": str(failure or ""),
            "queue": controlled_gray_scheduler_status(
                active_repo, now=completed_at, queue_name=queue_name
            ),
            **_safety(),
        }

    current = active_repo.get(claimed.queue_item_id)
    cancel_reason = control.cancel_reason
    if current is not None and current.cancel_requested_at and not cancel_reason:
        cancel_reason = "OPERATOR_CANCEL_REQUESTED"
    if cancel_reason == "TIME_BUDGET_EXCEEDED":
        failed = active_repo.mark_failed(
            queue_item_id=claimed.queue_item_id,
            worker_id=worker_id,
            lease_id=lease_id,
            error="task exceeded its configured execution time budget",
            error_category="TIME_BUDGET_EXCEEDED",
            retryable=False,
            now=completed_at,
        )
        _record_worker_event(
            queue_item_id=claimed.queue_item_id,
            queue_name=queue_name,
            worker_capability=normalized_capability,
            outcome="error",
            severity="ERROR",
            duration_ms=(time.monotonic() - observed_started) * 1000,
            error_category="TIME_BUDGET_EXCEEDED",
            queue_status=failed.status,
        )
        return {
            "worker_state": "JOB_TIME_BUDGET_EXCEEDED",
            "claimed": True,
            "queue_item": _item_summary(failed),
            "heartbeat_count": heartbeat_count,
            "progress_update_count": progress_update_count,
            "worker_capability": normalized_capability,
            "error_category": "TIME_BUDGET_EXCEEDED",
            "queue": controlled_gray_scheduler_status(
                active_repo, now=completed_at, queue_name=queue_name
            ),
            **_safety(),
        }
    if cancel_reason:
        cancelled = active_repo.mark_cancelled(
            queue_item_id=claimed.queue_item_id,
            worker_id=worker_id,
            lease_id=lease_id,
            reason=(current.cancel_reason if current is not None else "")
            or cancel_reason,
            now=completed_at,
        )
        _record_worker_event(
            queue_item_id=claimed.queue_item_id,
            queue_name=queue_name,
            worker_capability=normalized_capability,
            outcome="cancelled",
            severity="WARNING",
            duration_ms=(time.monotonic() - observed_started) * 1000,
            error_category="OPERATOR_CANCELLED",
            queue_status=cancelled.status,
        )
        return {
            "worker_state": "JOB_CANCELLED",
            "claimed": True,
            "queue_item": _item_summary(cancelled),
            "heartbeat_count": heartbeat_count,
            "progress_update_count": progress_update_count,
            "worker_capability": normalized_capability,
            "error_category": "OPERATOR_CANCELLED",
            "queue": controlled_gray_scheduler_status(
                active_repo, now=completed_at, queue_name=queue_name
            ),
            **_safety(),
        }

    if failure is not None:
        failed = active_repo.mark_failed(
            queue_item_id=claimed.queue_item_id,
            worker_id=worker_id,
            lease_id=lease_id,
            error=_bounded_error(failure),
            retryable=True,
            retry_delay_seconds=max(0, int(retry_delay_seconds)),
            error_category=(
                "COOPERATIVE_CANCELLATION_ERROR"
                if isinstance(failure, JobCancellationRequested)
                else "HANDLER_ERROR"
            ),
            now=completed_at,
        )
        next_item = None
        if (
            queue_name == CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME
            and failed.status == "dead-letter"
        ):
            next_item = _ensure_next_recurring_occurrence(
                failed,
                repository=active_repo,
                completed_at=completed_at,
            )
        retry_scheduled = failed.status == "retry"
        _record_worker_event(
            queue_item_id=claimed.queue_item_id,
            queue_name=queue_name,
            worker_capability=normalized_capability,
            outcome="retry" if retry_scheduled else "error",
            severity="WARNING" if retry_scheduled else "ERROR",
            duration_ms=(time.monotonic() - observed_started) * 1000,
            error_category=str(failed.last_error_category or "HANDLER_ERROR"),
            queue_status=failed.status,
        )
        return {
            "worker_state": (
                "JOB_FAILED_RETRY_SCHEDULED"
                if failed.status == "retry"
                else "JOB_FAILED_DEAD_LETTERED"
            ),
            "claimed": True,
            "queue_item": _item_summary(failed),
            "next_recurring_queue_item": _item_summary(next_item),
            "heartbeat_count": heartbeat_count,
            "progress_update_count": progress_update_count,
            "worker_capability": normalized_capability,
            "error": _bounded_error(failure),
            "error_category": failed.last_error_category,
            "queue": controlled_gray_scheduler_status(
                active_repo, now=completed_at, queue_name=queue_name
            ),
            **_safety(),
        }

    next_item = (
        _ensure_next_recurring_occurrence(
            claimed,
            repository=active_repo,
            completed_at=completed_at,
        )
        if queue_name == CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME
        else None
    )
    result_summary = _result_summary(result or {})
    succeeded = active_repo.mark_succeeded(
        queue_item_id=claimed.queue_item_id,
        worker_id=worker_id,
        lease_id=lease_id,
        result={
            **result_summary,
            "heartbeat_count": heartbeat_count,
            "next_recurring_queue_item_id": getattr(next_item, "queue_item_id", None),
        },
        now=completed_at,
    )
    _record_worker_event(
        queue_item_id=claimed.queue_item_id,
        queue_name=queue_name,
        worker_capability=normalized_capability,
        outcome="success",
        severity="INFO",
        duration_ms=(time.monotonic() - observed_started) * 1000,
        error_category=None,
        queue_status=succeeded.status,
    )
    return {
        "worker_state": "JOB_SUCCEEDED",
        "claimed": True,
        "queue_item": _item_summary(succeeded),
        "next_recurring_queue_item": _item_summary(next_item),
        "heartbeat_count": heartbeat_count,
        "progress_update_count": progress_update_count,
        "worker_capability": normalized_capability,
        "result_summary": result_summary,
        "queue": controlled_gray_scheduler_status(
            active_repo, now=completed_at, queue_name=queue_name
        ),
        **_safety(),
    }


def _record_worker_event(
    *,
    queue_item_id: str,
    queue_name: str,
    worker_capability: str,
    outcome: str,
    severity: str,
    duration_ms: float,
    error_category: str | None,
    queue_status: str,
) -> None:
    try:
        get_operational_event_sink("worker").record(
            component="queue",
            operation="worker_job",
            outcome=outcome,
            severity=severity,
            duration_ms=duration_ms,
            trace_id=queue_item_id,
            error_category=error_category,
            attributes={
                "queue_name": queue_name,
                "worker_capability": worker_capability,
                "queue_status": queue_status,
            },
        )
    except Exception as exc:  # observability must not corrupt the durable queue outcome.
        print(
            json.dumps(
                {
                    "event": "operational_observability_write_failed",
                    "component": "queue",
                    "queue_name": queue_name,
                    "error_category": type(exc).__name__,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )


def serve_controlled_gray_scheduler_worker(
    *,
    repository: WorkerQueueRepository | None = None,
    handler: JobHandler | None = None,
    worker_id: str = CONTROLLED_GRAY_ORCHESTRATOR_WORKER_ID,
    worker_capability: str = DEFAULT_WORKER_CAPABILITY,
    queue_name: str = CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS,
    status_json: str | Path = DEFAULT_STATUS_JSON,
    stop_event: Event | None = None,
    max_idle_polls: int = 0,
) -> dict[str, Any]:
    active_repo = repository or WorkerQueueRepository()
    stop = stop_event or Event()
    started_at = utc_now_iso()
    processed_count = 0
    idle_polls = 0
    last_result: dict[str, Any] = {}
    status_path = Path(status_json)
    while not stop.is_set():
        last_result = run_controlled_gray_scheduler_worker_once(
            repository=active_repo,
            handler=handler,
            worker_id=worker_id,
            worker_capability=worker_capability,
            queue_name=queue_name,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
            retry_delay_seconds=retry_delay_seconds,
        )
        if last_result.get("claimed"):
            processed_count += 1
            idle_polls = 0
        else:
            idle_polls += 1
        status = _process_status(
            state="RUNNING",
            worker_id=worker_id,
            worker_capability=worker_capability,
            queue_name=queue_name,
            started_at=started_at,
            processed_count=processed_count,
            idle_polls=idle_polls,
            last_result=last_result,
            repository=active_repo,
        )
        _write_status(status_path, status)
        if max_idle_polls and idle_polls >= max_idle_polls:
            break
        stop.wait(max(0.01, float(poll_seconds)))
    final = _process_status(
        state="STOPPED",
        worker_id=worker_id,
        worker_capability=worker_capability,
        queue_name=queue_name,
        started_at=started_at,
        processed_count=processed_count,
        idle_polls=idle_polls,
        last_result=last_result,
        repository=active_repo,
    )
    _write_status(status_path, final)
    return final


def controlled_gray_scheduler_status(
    repository: WorkerQueueRepository | None = None,
    *,
    now: str | None = None,
    limit: int = 20,
    queue_name: str = CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME,
) -> dict[str, Any]:
    active_repo = repository or WorkerQueueRepository()
    observed_at = now or utc_now_iso()
    items = active_repo.list(queue_name=queue_name)
    items.sort(key=lambda item: (item.updated_at, item.queue_item_id), reverse=True)
    status_counts: dict[str, int] = {}
    recurring_count = 0
    stale_lease_count = 0
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
        schedule = _mapping(item.payload.get("runtime_schedule"))
        recurring_count += bool(schedule.get("recurring"))
        stale_lease_count += bool(
            item.status == "running"
            and item.expires_at
            and iso_lte(item.expires_at, observed_at)
        )
    status = {
        "queue_name": queue_name,
        "observed_at": observed_at,
        "queue_item_count": len(items),
        "status_counts": dict(sorted(status_counts.items())),
        "recurring_queue_item_count": recurring_count,
        "active_running_count": status_counts.get("running", 0) - stale_lease_count,
        "stale_lease_count": stale_lease_count,
        "latest_items": [_item_summary(item) for item in items[: max(1, int(limit))]],
        "repository_backed": True,
        "leases_enabled": True,
        "heartbeats_enabled": True,
        "retry_enabled": True,
        "pause_resume_enabled": True,
        "dead_letter_enabled": True,
        "progress_reporting_enabled": True,
        "cooperative_cancellation_enabled": True,
        "execution_budget_enabled": True,
        "restart_recovery_enabled": True,
        "recurring_schedule_enabled": True,
        "unattended_recurring_run_ready": True,
        "unattended_recurring_scope": "INTERNAL_PREPARE_ONLY",
        "unattended_live_execution_ready": False,
        "dedicated_process_command": (
            "python -m runtime.controlled_gray_scheduler_worker --serve"
        ),
        "web_request_execution_enabled": False,
        **_safety(),
    }
    if queue_name == "operator_long_tasks":
        status.update(
            {
                "recurring_schedule_enabled": False,
                "unattended_recurring_run_ready": False,
                "unattended_recurring_scope": "NOT_APPLICABLE",
                "unattended_operator_long_task_ready": True,
                "unattended_operator_long_task_scope": "INTERNAL_ONLY",
                "dedicated_process_command": (
                    "python -m runtime.operator_long_task_worker --serve "
                    "--worker-capability browser"
                ),
            }
        )
    return status


def _ensure_next_recurring_occurrence(
    item: PersistedWorkerQueueItem,
    *,
    repository: WorkerQueueRepository,
    completed_at: str,
) -> PersistedWorkerQueueItem | None:
    schedule = _mapping(item.payload.get("runtime_schedule"))
    if not schedule.get("recurring"):
        return None
    interval = _validate_recurring_interval(schedule.get("interval_seconds"))
    if interval <= 0:
        return None
    schedule_id = str(schedule.get("schedule_id") or "").strip()
    if not _SCHEDULE_ID_PATTERN.fullmatch(schedule_id):
        raise ValueError("recurring queue item has invalid schedule_id")
    occurrence = max(0, int(schedule.get("occurrence") or 0)) + 1
    scheduled_for = _next_future_schedule(
        str(schedule.get("scheduled_for") or item.created_at),
        interval_seconds=interval,
        completed_at=completed_at,
    )
    queue_item_id = f"{schedule_id}::occurrence::{occurrence:08d}"
    existing = repository.get(queue_item_id)
    if existing is not None:
        return existing
    payload = {
        key: value
        for key, value in dict(item.payload).items()
        if key not in {"runtime_schedule"}
    }
    try:
        return enqueue_controlled_gray_orchestrator_job(
            payload,
            repository=repository,
            queue_item_id=queue_item_id,
            priority=item.priority,
            max_attempts=item.max_attempts,
            next_run_at=scheduled_for,
            recurring_interval_seconds=interval,
            schedule_id=schedule_id,
            occurrence=occurrence,
            time_budget_seconds=item.time_budget_seconds or 1_800,
            now=completed_at,
        )
    except StorageConcurrencyError:
        return repository.get(queue_item_id)


def _next_future_schedule(
    scheduled_for: str,
    *,
    interval_seconds: int,
    completed_at: str,
) -> str:
    scheduled = parse_iso(scheduled_for)
    completed = parse_iso(completed_at)
    elapsed = max(0.0, (completed - scheduled).total_seconds())
    steps = int(elapsed // interval_seconds) + 1
    return iso_after(steps * interval_seconds, now=scheduled_for)


def _assert_safe_prepare_job(payload: Mapping[str, Any]) -> None:
    opened = [key for key in _BLOCKED_EXECUTION_FLAGS if _truthy(payload.get(key))]
    if opened:
        raise ValueError(
            "dedicated controlled gray worker is internal prepare-only; blocked flags: "
            + ", ".join(opened)
        )
    missing = [
        key
        for key in ("output_root", "source_targets_json")
        if not str(payload.get(key) or "").strip()
    ]
    if missing:
        raise ValueError(
            "controlled gray prepare job missing required paths: " + ", ".join(missing)
        )


def _validate_recurring_interval(value: Any) -> int:
    interval = int(value or 0)
    if interval == 0:
        return 0
    if interval < MIN_RECURRING_INTERVAL_SECONDS:
        raise ValueError(
            f"recurring_interval_seconds must be 0 or at least {MIN_RECURRING_INTERVAL_SECONDS}"
        )
    if interval > MAX_RECURRING_INTERVAL_SECONDS:
        raise ValueError(
            f"recurring_interval_seconds must not exceed {MAX_RECURRING_INTERVAL_SECONDS}"
        )
    return interval


def _invoke_handler(
    handler: JobHandler,
    payload: Mapping[str, Any],
    control: JobExecutionControl,
) -> Mapping[str, Any]:
    try:
        parameters = tuple(inspect.signature(handler).parameters.values())
    except (TypeError, ValueError):
        parameters = ()
    accepts_control = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters
    ) or sum(
        parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in parameters
    ) >= 2
    if accepts_control:
        return handler(payload, control)
    return handler(payload)


def _flush_progress(
    control: JobExecutionControl,
    *,
    repository: WorkerQueueRepository,
    queue_item_id: str,
    worker_id: str,
    lease_id: str,
    now: str,
) -> int:
    progress = control.take_progress()
    if progress is None:
        return 0
    repository.update_progress(
        queue_item_id=queue_item_id,
        worker_id=worker_id,
        lease_id=lease_id,
        stage=str(progress["stage"]),
        completed_units=int(progress["completed_units"]),
        total_units=int(progress["total_units"]),
        message=str(progress["message"]),
        now=now,
    )
    return 1


def _result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(result.get("summary"))
    manifest = _mapping(result.get("manifest"))
    return {
        "output_root": str(result.get("output_root") or ""),
        "orchestration_state": str(summary.get("orchestration_state") or ""),
        "aggregate_gray_review_state": str(
            summary.get("aggregate_gray_review_state") or ""
        ),
        "manifest_sha256": str(manifest.get("manifest_sha256") or ""),
    }


def _process_status(
    *,
    state: str,
    worker_id: str,
    worker_capability: str,
    queue_name: str,
    started_at: str,
    processed_count: int,
    idle_polls: int,
    last_result: Mapping[str, Any],
    repository: WorkerQueueRepository,
) -> dict[str, Any]:
    observed_at = utc_now_iso()
    return {
        "manifest_kind": "controlled_gray_scheduler_worker_process_status_v1",
        "worker_process_state": state,
        "pid": os.getpid(),
        "worker_id": worker_id,
        "worker_capability": _validate_worker_capability(worker_capability),
        "started_at": started_at,
        "last_poll_at": observed_at,
        "processed_job_count": processed_count,
        "consecutive_idle_poll_count": idle_polls,
        "last_worker_state": str(last_result.get("worker_state") or ""),
        "queue": controlled_gray_scheduler_status(
            repository, now=observed_at, queue_name=queue_name
        ),
        "dedicated_process": True,
        "web_request_execution_enabled": False,
        **_safety(),
    }


def _write_status(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _item_summary(item: PersistedWorkerQueueItem | None) -> dict[str, Any]:
    if item is None:
        return {}
    schedule = _mapping(item.payload.get("runtime_schedule"))
    return {
        "queue_item_id": item.queue_item_id,
        "queue_name": item.queue_name,
        "runtime_job_kind": str(item.payload.get("runtime_job_kind") or ""),
        "required_worker_capability": str(
            item.payload.get("required_worker_capability") or "core"
        ),
        "status": item.status,
        "priority": item.priority,
        "attempt_count": item.attempt_count,
        "max_attempts": item.max_attempts,
        "next_run_at": item.next_run_at,
        "worker_id": item.worker_id,
        "lease_id": item.lease_id,
        "claimed_at": item.claimed_at,
        "heartbeat_at": item.heartbeat_at,
        "expires_at": item.expires_at,
        "last_error": item.last_error,
        "last_error_category": item.last_error_category,
        "completed_at": item.completed_at,
        "dead_letter_at": item.dead_letter_at,
        "suspended_at": item.suspended_at,
        "suspended_by": item.suspended_by,
        "suspend_reason": item.suspend_reason,
        "progress_stage": item.progress_stage,
        "progress_message": item.progress_message,
        "progress_completed_units": item.progress_completed_units,
        "progress_total_units": item.progress_total_units,
        "progress_percent": item.progress_percent,
        "time_budget_seconds": item.time_budget_seconds,
        "budget_started_at": item.budget_started_at,
        "budget_deadline_at": item.budget_deadline_at,
        "budget_exhausted_at": item.budget_exhausted_at,
        "cancel_requested_at": item.cancel_requested_at,
        "cancel_requested_by": item.cancel_requested_by,
        "cancel_reason": item.cancel_reason,
        "cancelled_at": item.cancelled_at,
        "schedule_id": str(schedule.get("schedule_id") or ""),
        "recurring": bool(schedule.get("recurring")),
        "recurring_interval_seconds": int(schedule.get("interval_seconds") or 0),
        "occurrence": int(schedule.get("occurrence") or 0),
        "scheduled_for": str(schedule.get("scheduled_for") or ""),
        "updated_at": item.updated_at,
    }


def _bounded_error(exc: Exception) -> str:
    return f"{type(exc).__name__}:{exc}"[:2048]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "live"}
    return bool(value)


def _lease_id(worker_id: str) -> str:
    return f"{worker_id}:{uuid4().hex}"


def _validate_worker_capability(value: str) -> str:
    normalized = str(value or DEFAULT_WORKER_CAPABILITY).strip().lower()
    if normalized not in SUPPORTED_WORKER_CAPABILITIES:
        raise ValueError(
            "worker_capability must be one of: "
            + ", ".join(SUPPORTED_WORKER_CAPABILITIES)
        )
    return normalized


def _safety() -> dict[str, Any]:
    return {
        "internal_only": True,
        "execute_enabled": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "customer_visible_allowed": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the dedicated durable controlled-gray scheduler worker."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--serve", action="store_true")
    parser.add_argument("--worker-id", default=CONTROLLED_GRAY_ORCHESTRATOR_WORKER_ID)
    parser.add_argument(
        "--worker-capability",
        choices=SUPPORTED_WORKER_CAPABILITIES,
        default=DEFAULT_WORKER_CAPABILITY,
    )
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    parser.add_argument("--heartbeat-seconds", type=float, default=DEFAULT_HEARTBEAT_SECONDS)
    parser.add_argument("--retry-delay-seconds", type=int, default=DEFAULT_RETRY_DELAY_SECONDS)
    parser.add_argument("--status-json", default=str(DEFAULT_STATUS_JSON))
    parser.add_argument("--max-idle-polls", type=int, default=0)
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.once:
        result = run_controlled_gray_scheduler_worker_once(
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
            worker_id=args.worker_id,
            worker_capability=args.worker_capability,
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


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTROLLED_GRAY_ORCHESTRATOR_JOB_KIND",
    "CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME",
    "CONTROLLED_GRAY_ORCHESTRATOR_WORKER_ID",
    "controlled_gray_scheduler_status",
    "enqueue_controlled_gray_orchestrator_job",
    "execute_controlled_gray_prepare_job",
    "run_controlled_gray_scheduler_worker_once",
    "serve_controlled_gray_scheduler_worker",
]
