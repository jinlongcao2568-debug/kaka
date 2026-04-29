from __future__ import annotations

from typing import Any, Mapping

from stage1_tasking.models import (
    Stage1PauseState,
    Stage1RetryState,
    Stage1SchedulerTask,
)
from storage.db import DatabaseSession, PersistedWorkerQueueItem
from storage.repositories.worker_queue_repo import WorkerQueueRepository


class Stage1SchedulerRepository:
    def __init__(
        self,
        *,
        session: DatabaseSession | None = None,
        worker_queue_repo: WorkerQueueRepository | None = None,
    ) -> None:
        self.session = session or DatabaseSession.default()
        self.worker_queue_repo = worker_queue_repo or WorkerQueueRepository(session=self.session)

    def enqueue_task(
        self,
        task: Stage1SchedulerTask,
        *,
        queue_name: str,
        queue_payload: Mapping[str, Any],
        priority: int,
        max_attempts: int,
        next_run_at: str,
        now: str,
    ) -> Stage1SchedulerTask:
        item = self.worker_queue_repo.enqueue(
            queue_item_id=task.queue_item_id,
            queue_name=queue_name,
            payload=queue_payload,
            priority=priority,
            max_attempts=max_attempts,
            next_run_at=next_run_at,
            trace_refs={
                "task_id": task.task_id,
                "project_id": task.project_id,
                "source_registry_id": task.source_registry_id,
                "route_policy_id": task.route_policy_id,
                "handoff_id": task.stage2_handoff_intent.handoff_id,
            },
            audit_refs=task.audit_refs,
            now=now,
        )
        return self._task_from_queue_item(item)

    def get_task(self, task_id: str) -> Stage1SchedulerTask | None:
        item = self._find_item_by_task_id(task_id)
        if item is None:
            return None
        return self._task_from_queue_item(item)

    def get_by_queue_item_id(self, queue_item_id: str) -> Stage1SchedulerTask | None:
        item = self.worker_queue_repo.get(queue_item_id)
        if item is None:
            return None
        return self._task_from_queue_item(item)

    def readback(self, queue_item_id: str) -> dict[str, Any]:
        item = self._require_item(queue_item_id)
        task = self._task_from_queue_item(item)
        return {
            "readback_state": "READBACK_READY",
            "repository_backed": True,
            "replayable": True,
            "scheduler_task": task.as_payload(),
            "queue_item": item.as_payload(),
            "stage2_handoff_intent": task.stage2_handoff_intent.as_payload(),
            "fetch_execution": {
                "stage2_fetch_enabled": False,
                "unregistered_capture_enabled": False,
                "real_external_fetch_enabled": False,
            },
            "audit_refs": dict(task.audit_refs),
        }

    def replay(self, queue_item_id: str) -> dict[str, Any]:
        replay = self.worker_queue_repo.replay(queue_item_id)
        replay.update(
            {
                "scheduler_readback": self.readback(queue_item_id),
                "stage2_fetch_executed": False,
                "unregistered_capture_executed": False,
                "real_external_fetch_executed": False,
            }
        )
        return replay

    def lease(
        self,
        queue_item_id: str,
        *,
        worker_id: str,
        lease_id: str,
        lease_seconds: int,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        item = self.worker_queue_repo.claim(
            queue_item_id=queue_item_id,
            worker_id=worker_id,
            lease_id=lease_id,
            lease_seconds=lease_seconds,
            now=now,
        )
        return self._task_from_queue_item(item)

    def retry(
        self,
        queue_item_id: str,
        *,
        worker_id: str,
        lease_id: str,
        error: str,
        retry_delay_seconds: int = 0,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        item = self.worker_queue_repo.mark_failed(
            queue_item_id=queue_item_id,
            worker_id=worker_id,
            lease_id=lease_id,
            error=error,
            retryable=True,
            retry_delay_seconds=retry_delay_seconds,
            now=now,
        )
        return self._task_from_queue_item(item)

    def pause(
        self,
        queue_item_id: str,
        *,
        paused_by: str,
        reason: str,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        item = self.worker_queue_repo.suspend(
            queue_item_id=queue_item_id,
            suspended_by=paused_by,
            reason=reason,
            now=now,
        )
        return self._task_from_queue_item(item)

    def resume(
        self,
        queue_item_id: str,
        *,
        next_run_at: str | None = None,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        item = self.worker_queue_repo.resume(
            queue_item_id=queue_item_id,
            next_run_at=next_run_at,
            now=now,
        )
        return self._task_from_queue_item(item)

    def dead_letter(
        self,
        queue_item_id: str,
        *,
        reason: str,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        item = self.worker_queue_repo.dead_letter(
            queue_item_id=queue_item_id,
            reason=reason,
            now=now,
        )
        return self._task_from_queue_item(item)

    def _require_item(self, queue_item_id: str) -> PersistedWorkerQueueItem:
        item = self.worker_queue_repo.get(queue_item_id)
        if item is None:
            raise ValueError(f"stage1 scheduler queue item {queue_item_id!r} not found")
        return item

    def _find_item_by_task_id(self, task_id: str) -> PersistedWorkerQueueItem | None:
        for item in self.worker_queue_repo.list():
            scheduler_payload = item.payload.get("scheduler_task", {})
            if scheduler_payload.get("task_id") == task_id:
                return item
        return None

    def _task_from_queue_item(self, item: PersistedWorkerQueueItem) -> Stage1SchedulerTask:
        scheduler_payload = dict(item.payload.get("scheduler_task", {}))
        if not scheduler_payload:
            raise ValueError(f"queue item {item.queue_item_id!r} does not carry a stage1 scheduler task")
        scheduler_payload.update(
            {
                "queue_item_id": item.queue_item_id,
                "status": item.status,
                "retry_state": Stage1RetryState(
                    attempt_count=item.attempt_count,
                    max_attempts=item.max_attempts,
                    next_retry_at=item.next_run_at if item.status == "retry" else None,
                    last_error=item.last_error,
                ).as_payload(),
                "pause_state": Stage1PauseState(
                    is_paused=item.status == "suspended",
                    paused_at=item.suspended_at,
                    paused_by=item.suspended_by,
                    reason=item.suspend_reason,
                    resumed_at=item.resumed_at,
                ).as_payload(),
                "audit_refs": {
                    **dict(scheduler_payload.get("audit_refs", {})),
                    **dict(item.audit_refs),
                },
                "updated_at": item.updated_at,
            }
        )
        return Stage1SchedulerTask.from_payload(scheduler_payload)


__all__ = ["Stage1SchedulerRepository"]
