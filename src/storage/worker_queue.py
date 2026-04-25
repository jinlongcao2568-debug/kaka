from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.db import PersistedWorkerQueueEvent, PersistedWorkerQueueItem


QUEUE_STATUS_QUEUED = "queued"
QUEUE_STATUS_RUNNING = "running"
QUEUE_STATUS_SUCCEEDED = "succeeded"
QUEUE_STATUS_FAILED = "failed"
QUEUE_STATUS_SUSPENDED = "suspended"
QUEUE_STATUS_RETRY = "retry"
QUEUE_STATUS_DEAD_LETTER = "dead-letter"
INTERNAL_QUEUE_STATUSES = (
    QUEUE_STATUS_QUEUED,
    QUEUE_STATUS_RUNNING,
    QUEUE_STATUS_SUCCEEDED,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_SUSPENDED,
    QUEUE_STATUS_RETRY,
    QUEUE_STATUS_DEAD_LETTER,
)
CLAIMABLE_QUEUE_STATUSES = (QUEUE_STATUS_QUEUED, QUEUE_STATUS_RETRY)
TERMINAL_QUEUE_STATUSES = (
    QUEUE_STATUS_SUCCEEDED,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_DEAD_LETTER,
)
DEFAULT_QUEUE_NAME = "internal_worker_queue"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 60


def utc_now() -> str:
    return utc_now_iso()


def iso_after(seconds: int, *, now: str | None = None) -> str:
    base = parse_iso(now) if now else datetime.now(tz=timezone.utc)
    return (base + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_lte(value: str | None, boundary: str) -> bool:
    if not value:
        return True
    return parse_iso(value) <= parse_iso(boundary)


def validate_internal_queue_status(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized not in INTERNAL_QUEUE_STATUSES:
        raise ValueError(f"unsupported internal worker queue status: {status!r}")
    return normalized


def new_queue_item(
    *,
    queue_item_id: str,
    queue_name: str = DEFAULT_QUEUE_NAME,
    payload: Mapping[str, Any] | None = None,
    priority: int = 0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    next_run_at: str | None = None,
    trace_refs: Mapping[str, str] | None = None,
    audit_refs: Mapping[str, str] | None = None,
    now: str | None = None,
) -> PersistedWorkerQueueItem:
    created_at = now or utc_now()
    return PersistedWorkerQueueItem(
        queue_item_id=queue_item_id,
        queue_name=queue_name,
        status=QUEUE_STATUS_QUEUED,
        payload=dict(payload or {}),
        priority=int(priority),
        worker_id=None,
        lease_id=None,
        claimed_at=None,
        heartbeat_at=None,
        expires_at=None,
        attempt_count=0,
        max_attempts=int(max_attempts),
        next_run_at=next_run_at or created_at,
        last_error=None,
        suspended_at=None,
        suspended_by=None,
        suspend_reason=None,
        resumed_at=None,
        completed_at=None,
        dead_letter_at=None,
        trace_refs={key: str(value) for key, value in dict(trace_refs or {}).items()},
        audit_refs={key: str(value) for key, value in dict(audit_refs or {}).items()},
        audit_trace=[],
        created_at=created_at,
        updated_at=created_at,
    )


def build_queue_event(
    *,
    item: PersistedWorkerQueueItem,
    event_type: str,
    previous_status: str | None,
    detail: Mapping[str, Any] | None = None,
    now: str | None = None,
    event_index: int = 1,
) -> PersistedWorkerQueueEvent:
    occurred_at = now or utc_now()
    return PersistedWorkerQueueEvent(
        queue_item_id=item.queue_item_id,
        event_id=f"WQ-{item.queue_item_id}-{event_index:04d}",
        event_type=event_type,
        queue_name=item.queue_name,
        worker_id=item.worker_id,
        lease_id=item.lease_id,
        previous_status=previous_status,
        next_status=item.status,
        attempt_count=item.attempt_count,
        next_run_at=item.next_run_at,
        last_error=item.last_error,
        trace_refs=dict(item.trace_refs),
        audit_refs=dict(item.audit_refs),
        detail=dict(detail or {}),
        occurred_at=occurred_at,
    )


def append_audit_trace(
    item: PersistedWorkerQueueItem,
    event: PersistedWorkerQueueEvent,
) -> PersistedWorkerQueueItem:
    audit_trace = [
        *[dict(entry) for entry in item.audit_trace],
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "previous_status": event.previous_status,
            "next_status": event.next_status,
            "worker_id": event.worker_id,
            "lease_id": event.lease_id,
            "attempt_count": event.attempt_count,
            "occurred_at": event.occurred_at,
            "detail": dict(event.detail),
        },
    ]
    return replace(item, audit_trace=audit_trace, updated_at=event.occurred_at)


def worker_queue_bootstrap_summary(
    *,
    queue_backend: str,
    worker_runtime: str,
    active_storage_backend: str,
) -> dict[str, Any]:
    configured_backend = str(queue_backend or "storage").strip().lower()
    external_backend_configured = configured_backend in {"redis", "dramatiq", "external"}
    return {
        "queue_backend": configured_backend,
        "effective_queue_backend": "storage",
        "active_storage_backend": active_storage_backend,
        "worker_runtime": str(worker_runtime or "internal-storage-worker").strip(),
        "readiness_state": "EXECUTABLE",
        "repository_backed": True,
        "durable_queue_enabled": True,
        "worker_lease_enabled": True,
        "heartbeat_enabled": True,
        "retry_enabled": True,
        "timeout_recovery_enabled": True,
        "suspend_resume_enabled": True,
        "audit_replay_enabled": True,
        "status_values": list(INTERNAL_QUEUE_STATUSES),
        "external_queue_backend_configured": external_backend_configured,
        "external_queue_connection_enabled": False,
        "redis_connection_enabled": False,
        "dramatiq_worker_enabled": False,
        "stage1_scheduler_enabled": False,
        "real_provider_execution_enabled": False,
        "why_not_live": "Redis/external queue and Stage1 scheduler remain reserved; current worker queue runs through existing storage only.",
    }


__all__ = [
    "CLAIMABLE_QUEUE_STATUSES",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_QUEUE_NAME",
    "INTERNAL_QUEUE_STATUSES",
    "QUEUE_STATUS_DEAD_LETTER",
    "QUEUE_STATUS_FAILED",
    "QUEUE_STATUS_QUEUED",
    "QUEUE_STATUS_RETRY",
    "QUEUE_STATUS_RUNNING",
    "QUEUE_STATUS_SUCCEEDED",
    "QUEUE_STATUS_SUSPENDED",
    "TERMINAL_QUEUE_STATUSES",
    "append_audit_trace",
    "build_queue_event",
    "iso_after",
    "iso_lte",
    "new_queue_item",
    "utc_now",
    "validate_internal_queue_status",
    "worker_queue_bootstrap_summary",
]
