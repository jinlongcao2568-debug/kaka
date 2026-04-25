from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from storage.db import DatabaseSession, PersistedWorkerQueueEvent, PersistedWorkerQueueItem
from storage.worker_queue import (
    CLAIMABLE_QUEUE_STATUSES,
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_QUEUE_NAME,
    QUEUE_STATUS_DEAD_LETTER,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_QUEUED,
    QUEUE_STATUS_RETRY,
    QUEUE_STATUS_RUNNING,
    QUEUE_STATUS_SUCCEEDED,
    QUEUE_STATUS_SUSPENDED,
    append_audit_trace,
    build_queue_event,
    iso_after,
    iso_lte,
    new_queue_item,
    utc_now,
)


class WorkerQueueRepository:
    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def enqueue(
        self,
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
        item = new_queue_item(
            queue_item_id=queue_item_id,
            queue_name=queue_name,
            payload=payload,
            priority=priority,
            max_attempts=max(1, int(max_attempts)),
            next_run_at=next_run_at,
            trace_refs=trace_refs,
            audit_refs=audit_refs,
            now=now,
        )
        return self._commit_transition(
            previous_status=None,
            item=item,
            event_type="queued",
            detail={"queue_backend": "storage", "durable": True},
            now=now,
        )

    def get(self, queue_item_id: str) -> PersistedWorkerQueueItem | None:
        return self.session.get_worker_queue_item(queue_item_id)

    def list(
        self,
        *,
        queue_name: str | None = None,
        status: str | None = None,
    ) -> list[PersistedWorkerQueueItem]:
        return self._sort_items(self.session.list_worker_queue_items(queue_name=queue_name, status=status))

    def claim_next(
        self,
        *,
        queue_name: str = DEFAULT_QUEUE_NAME,
        worker_id: str,
        lease_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem | None:
        effective_now = now or utc_now()
        self.mark_timeouts(now=effective_now)
        for item in self.list(queue_name=queue_name):
            if item.status not in CLAIMABLE_QUEUE_STATUSES:
                continue
            if not iso_lte(item.next_run_at, effective_now):
                continue
            return self.claim(
                queue_item_id=item.queue_item_id,
                worker_id=worker_id,
                lease_id=lease_id,
                lease_seconds=lease_seconds,
                now=effective_now,
            )
        return None

    def claim(
        self,
        *,
        queue_item_id: str,
        worker_id: str,
        lease_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        item = self._require_item(queue_item_id)
        effective_now = now or utc_now()
        if item.status not in CLAIMABLE_QUEUE_STATUSES:
            raise ValueError(f"queue item {queue_item_id!r} cannot be claimed from status {item.status!r}")
        if not iso_lte(item.next_run_at, effective_now):
            raise ValueError(f"queue item {queue_item_id!r} is not due for claim")

        previous_status = item.status
        updated = replace(
            item,
            status=QUEUE_STATUS_RUNNING,
            worker_id=worker_id,
            lease_id=lease_id,
            claimed_at=effective_now,
            heartbeat_at=effective_now,
            expires_at=iso_after(lease_seconds, now=effective_now),
            attempt_count=item.attempt_count + 1,
            next_run_at=None,
            completed_at=None,
            updated_at=effective_now,
        )
        return self._commit_transition(
            previous_status=previous_status,
            item=updated,
            event_type="claimed",
            detail={"lease_seconds": lease_seconds},
            now=effective_now,
        )

    def heartbeat(
        self,
        *,
        queue_item_id: str,
        worker_id: str,
        lease_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        item = self._require_active_lease(queue_item_id, worker_id=worker_id, lease_id=lease_id)
        effective_now = now or utc_now()
        updated = replace(
            item,
            heartbeat_at=effective_now,
            expires_at=iso_after(lease_seconds, now=effective_now),
            updated_at=effective_now,
        )
        return self._commit_transition(
            previous_status=item.status,
            item=updated,
            event_type="heartbeat",
            detail={"lease_seconds": lease_seconds},
            now=effective_now,
        )

    def mark_succeeded(
        self,
        *,
        queue_item_id: str,
        worker_id: str,
        lease_id: str,
        result: Mapping[str, Any] | None = None,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        item = self._require_active_lease(queue_item_id, worker_id=worker_id, lease_id=lease_id)
        effective_now = now or utc_now()
        updated = replace(
            item,
            status=QUEUE_STATUS_SUCCEEDED,
            next_run_at=None,
            completed_at=effective_now,
            updated_at=effective_now,
        )
        return self._commit_transition(
            previous_status=item.status,
            item=updated,
            event_type="succeeded",
            detail={"result": dict(result or {})},
            now=effective_now,
        )

    def mark_failed(
        self,
        *,
        queue_item_id: str,
        worker_id: str,
        lease_id: str,
        error: str,
        retryable: bool = True,
        retry_delay_seconds: int = 0,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        item = self._require_active_lease(queue_item_id, worker_id=worker_id, lease_id=lease_id)
        effective_now = now or utc_now()
        if retryable and item.attempt_count < item.max_attempts:
            next_status = QUEUE_STATUS_RETRY
            next_run_at = iso_after(retry_delay_seconds, now=effective_now)
            dead_letter_at = None
            event_type = "retry_scheduled"
        elif retryable:
            next_status = QUEUE_STATUS_DEAD_LETTER
            next_run_at = None
            dead_letter_at = effective_now
            event_type = "dead_lettered"
        else:
            next_status = QUEUE_STATUS_FAILED
            next_run_at = None
            dead_letter_at = None
            event_type = "failed"

        updated = replace(
            item,
            status=next_status,
            worker_id=None,
            lease_id=None,
            claimed_at=None,
            heartbeat_at=None,
            expires_at=None,
            next_run_at=next_run_at,
            last_error=error,
            completed_at=effective_now if next_status == QUEUE_STATUS_FAILED else item.completed_at,
            dead_letter_at=dead_letter_at,
            updated_at=effective_now,
        )
        return self._commit_transition(
            previous_status=item.status,
            item=updated,
            event_type=event_type,
            detail={"error": error, "retryable": retryable, "retry_delay_seconds": retry_delay_seconds},
            now=effective_now,
        )

    def mark_timeouts(self, *, now: str | None = None) -> list[PersistedWorkerQueueItem]:
        effective_now = now or utc_now()
        timed_out: list[PersistedWorkerQueueItem] = []
        for item in self.list(status=QUEUE_STATUS_RUNNING):
            if not item.expires_at or not iso_lte(item.expires_at, effective_now):
                continue
            if item.attempt_count >= item.max_attempts:
                next_status = QUEUE_STATUS_DEAD_LETTER
                next_run_at = None
                dead_letter_at = effective_now
                event_type = "lease_timeout_dead_lettered"
            else:
                next_status = QUEUE_STATUS_RETRY
                next_run_at = effective_now
                dead_letter_at = None
                event_type = "lease_timeout_retry_scheduled"

            updated = replace(
                item,
                status=next_status,
                worker_id=None,
                lease_id=None,
                claimed_at=None,
                heartbeat_at=None,
                expires_at=None,
                next_run_at=next_run_at,
                last_error="lease_timeout",
                dead_letter_at=dead_letter_at,
                updated_at=effective_now,
            )
            timed_out.append(
                self._commit_transition(
                    previous_status=item.status,
                    item=updated,
                    event_type=event_type,
                    detail={"expired_at": item.expires_at, "previous_worker_id": item.worker_id},
                    now=effective_now,
                )
            )
        return timed_out

    def suspend(
        self,
        *,
        queue_item_id: str,
        suspended_by: str,
        reason: str,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        item = self._require_item(queue_item_id)
        effective_now = now or utc_now()
        updated = replace(
            item,
            status=QUEUE_STATUS_SUSPENDED,
            worker_id=None,
            lease_id=None,
            claimed_at=None,
            heartbeat_at=None,
            expires_at=None,
            suspended_at=effective_now,
            suspended_by=suspended_by,
            suspend_reason=reason,
            updated_at=effective_now,
        )
        return self._commit_transition(
            previous_status=item.status,
            item=updated,
            event_type="suspended",
            detail={"reason": reason, "suspended_by": suspended_by},
            now=effective_now,
        )

    def resume(
        self,
        *,
        queue_item_id: str,
        next_run_at: str | None = None,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        item = self._require_item(queue_item_id)
        if item.status != QUEUE_STATUS_SUSPENDED:
            raise ValueError(f"queue item {queue_item_id!r} cannot be resumed from status {item.status!r}")
        effective_now = now or utc_now()
        updated = replace(
            item,
            status=QUEUE_STATUS_QUEUED,
            next_run_at=next_run_at or effective_now,
            resumed_at=effective_now,
            updated_at=effective_now,
        )
        return self._commit_transition(
            previous_status=item.status,
            item=updated,
            event_type="resumed",
            detail={"next_run_at": updated.next_run_at},
            now=effective_now,
        )

    def dead_letter(
        self,
        *,
        queue_item_id: str,
        reason: str,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        item = self._require_item(queue_item_id)
        effective_now = now or utc_now()
        updated = replace(
            item,
            status=QUEUE_STATUS_DEAD_LETTER,
            worker_id=None,
            lease_id=None,
            claimed_at=None,
            heartbeat_at=None,
            expires_at=None,
            next_run_at=None,
            last_error=reason,
            dead_letter_at=effective_now,
            updated_at=effective_now,
        )
        return self._commit_transition(
            previous_status=item.status,
            item=updated,
            event_type="dead_lettered",
            detail={"reason": reason, "manual_dead_letter": True},
            now=effective_now,
        )

    def list_events(self, queue_item_id: str) -> list[PersistedWorkerQueueEvent]:
        return self.session.list_worker_queue_events(queue_item_id)

    def replay(self, queue_item_id: str) -> dict[str, Any]:
        item = self._require_item(queue_item_id)
        events = self.list_events(queue_item_id)
        return {
            "queue_item": item.as_payload(),
            "events": [event.as_payload() for event in events],
            "replayable": True,
            "audit_event_count": len(events),
            "current_status": item.status,
            "current_attempt_count": item.attempt_count,
        }

    def _require_item(self, queue_item_id: str) -> PersistedWorkerQueueItem:
        item = self.get(queue_item_id)
        if item is None:
            raise ValueError(f"queue item {queue_item_id!r} not found")
        return item

    def _require_active_lease(
        self,
        queue_item_id: str,
        *,
        worker_id: str,
        lease_id: str,
    ) -> PersistedWorkerQueueItem:
        item = self._require_item(queue_item_id)
        if item.status != QUEUE_STATUS_RUNNING:
            raise ValueError(f"queue item {queue_item_id!r} is not running")
        if item.worker_id != worker_id or item.lease_id != lease_id:
            raise ValueError(f"queue item {queue_item_id!r} lease mismatch")
        return item

    def _commit_transition(
        self,
        *,
        previous_status: str | None,
        item: PersistedWorkerQueueItem,
        event_type: str,
        detail: Mapping[str, Any] | None = None,
        now: str | None = None,
    ) -> PersistedWorkerQueueItem:
        existing_events = self.session.list_worker_queue_events(item.queue_item_id)
        event = build_queue_event(
            item=item,
            event_type=event_type,
            previous_status=previous_status,
            detail=detail,
            now=now,
            event_index=len(existing_events) + 1,
        )
        item_with_trace = append_audit_trace(item, event)
        self.session.upsert_worker_queue_item(item_with_trace)
        self.session.append_worker_queue_event(event)
        return item_with_trace

    def _sort_items(self, items: list[PersistedWorkerQueueItem]) -> list[PersistedWorkerQueueItem]:
        return sorted(
            items,
            key=lambda item: (
                -item.priority,
                item.next_run_at or "",
                item.created_at,
                item.queue_item_id,
            ),
        )


__all__ = ["WorkerQueueRepository"]
