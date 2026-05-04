# Stage: stage4_verification
# Lightweight local job queue for repeatable provider execution without Redis.

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED_RETRYABLE = "FAILED_RETRYABLE"
EXHAUSTED = "EXHAUSTED"


@dataclass
class Stage4QueuedJob:
    job_id: str
    provider_id: str
    payload: dict[str, Any]
    status: str = QUEUED
    max_attempts: int = 3
    attempt_count: int = 0
    next_run_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    lease_owner: str = ""
    last_error: str = ""
    error_history: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


ProviderHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class Stage4LocalJobQueue:
    """Small JSON-backed queue for local/offline Stage4 provider jobs.

    This is intentionally simple: it gives the product a repeatable retry boundary
    before introducing Redis/RQ/Celery. It is not a distributed lock manager.
    """

    def __init__(self, queue_path: str | os.PathLike[str] | None = None) -> None:
        self.queue_path = Path(
            queue_path
            or os.environ.get("KAKA_STAGE4_JOB_QUEUE_PATH")
            or Path(tempfile.gettempdir()) / "kaka-stage4-provider-jobs.json"
        )

    def enqueue(
        self,
        *,
        provider_id: str,
        payload: Mapping[str, Any],
        job_id: str | None = None,
        max_attempts: int = 3,
        run_after_seconds: float = 0.0,
    ) -> dict[str, Any]:
        data = self._read()
        resolved_job_id = job_id or _stable_job_id(provider_id, payload)
        existing = data["jobs"].get(resolved_job_id)
        if existing and str(existing.get("status")) not in {SUCCEEDED, EXHAUSTED}:
            return dict(existing)
        job = Stage4QueuedJob(
            job_id=resolved_job_id,
            provider_id=str(provider_id),
            payload=dict(payload),
            max_attempts=max(1, int(max_attempts or 1)),
            next_run_at=time.time() + max(0.0, float(run_after_seconds or 0.0)),
        )
        data["jobs"][resolved_job_id] = job.as_payload()
        self._write(data)
        return job.as_payload()

    def list_jobs(self, *, status: str | None = None) -> list[dict[str, Any]]:
        jobs = list(self._read()["jobs"].values())
        if status:
            jobs = [job for job in jobs if job.get("status") == status]
        return sorted(jobs, key=lambda job: (float(job.get("next_run_at") or 0), str(job.get("job_id") or "")))

    def lease_due_job(self, *, lease_owner: str = "stage4-local-worker") -> dict[str, Any] | None:
        data = self._read()
        now = time.time()
        due = [
            job
            for job in data["jobs"].values()
            if job.get("status") in {QUEUED, FAILED_RETRYABLE}
            and float(job.get("next_run_at") or 0) <= now
            and int(job.get("attempt_count") or 0) < int(job.get("max_attempts") or 1)
        ]
        if not due:
            return None
        due.sort(key=lambda job: (float(job.get("next_run_at") or 0), str(job.get("job_id") or "")))
        job = dict(due[0])
        job["status"] = RUNNING
        job["lease_owner"] = lease_owner
        job["attempt_count"] = int(job.get("attempt_count") or 0) + 1
        job["updated_at"] = now
        data["jobs"][job["job_id"]] = job
        self._write(data)
        return job

    def complete(self, job_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
        data = self._read()
        job = dict(data["jobs"][job_id])
        job["status"] = SUCCEEDED
        job["result"] = dict(result)
        job["last_error"] = ""
        job["updated_at"] = time.time()
        data["jobs"][job_id] = job
        self._write(data)
        return job

    def fail(
        self,
        job_id: str,
        error: str,
        *,
        retry_delay_seconds: float = 30.0,
        retryable: bool = True,
    ) -> dict[str, Any]:
        data = self._read()
        job = dict(data["jobs"][job_id])
        now = time.time()
        max_attempts = int(job.get("max_attempts") or 1)
        attempt_count = int(job.get("attempt_count") or 0)
        retry_allowed = retryable and attempt_count < max_attempts
        job["status"] = FAILED_RETRYABLE if retry_allowed else EXHAUSTED
        job["last_error"] = str(error)
        job["next_run_at"] = now + max(0.0, float(retry_delay_seconds or 0.0)) if retry_allowed else 0.0
        job["updated_at"] = now
        history = list(job.get("error_history") or [])
        history.append(
            {
                "attempt_no": attempt_count,
                "error": str(error),
                "retryable": retry_allowed,
                "recorded_at": now,
            }
        )
        job["error_history"] = history
        data["jobs"][job_id] = job
        self._write(data)
        return job

    def run_due_jobs(
        self,
        handlers: Mapping[str, ProviderHandler],
        *,
        limit: int = 10,
        lease_owner: str = "stage4-local-worker",
        retry_delay_seconds: float = 30.0,
    ) -> dict[str, Any]:
        processed: list[dict[str, Any]] = []
        for _ in range(max(0, int(limit or 0))):
            job = self.lease_due_job(lease_owner=lease_owner)
            if job is None:
                break
            handler = handlers.get(str(job.get("provider_id") or ""))
            if handler is None:
                processed.append(
                    self.fail(
                        str(job["job_id"]),
                        f"stage4_provider_handler_missing:{job.get('provider_id')}",
                        retry_delay_seconds=retry_delay_seconds,
                        retryable=False,
                    )
                )
                continue
            try:
                result = dict(handler(dict(job.get("payload") or {})))
            except Exception as exc:  # pragma: no cover - defensive runtime boundary
                processed.append(
                    self.fail(
                        str(job["job_id"]),
                        f"{type(exc).__name__}:{exc}",
                        retry_delay_seconds=retry_delay_seconds,
                        retryable=True,
                    )
                )
                continue
            processed.append(self.complete(str(job["job_id"]), result))
        return {
            "queue_path": str(self.queue_path),
            "processed_count": len(processed),
            "processed_jobs": processed,
            "remaining_due_count": len(
                [
                    job
                    for job in self.list_jobs()
                    if job.get("status") in {QUEUED, FAILED_RETRYABLE}
                    and float(job.get("next_run_at") or 0) <= time.time()
                ]
            ),
        }

    def _read(self) -> dict[str, Any]:
        if not self.queue_path.exists():
            return {"version": 1, "jobs": {}}
        try:
            data = json.loads(self.queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "jobs": {}}
        if not isinstance(data, dict):
            return {"version": 1, "jobs": {}}
        jobs = data.get("jobs")
        if not isinstance(jobs, dict):
            data["jobs"] = {}
        return data

    def _write(self, data: Mapping[str, Any]) -> None:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.queue_path.with_suffix(self.queue_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.queue_path)


def enqueue_provider_plan_tasks(
    queue: Stage4LocalJobQueue,
    provider_plan: Mapping[str, Any],
    *,
    max_attempts: int = 3,
) -> list[dict[str, Any]]:
    jobs = []
    for task in list(provider_plan.get("tasks") or []):
        if not isinstance(task, Mapping):
            continue
        provider_id = str(task.get("provider_id") or "").strip()
        if not provider_id:
            continue
        jobs.append(
            queue.enqueue(
                provider_id=provider_id,
                payload=dict(task),
                job_id=str(task.get("task_id") or "") or None,
                max_attempts=max_attempts,
            )
        )
    return jobs


def _stable_job_id(provider_id: str, payload: Mapping[str, Any]) -> str:
    import hashlib

    raw = json.dumps([provider_id, payload], ensure_ascii=False, sort_keys=True, default=str)
    return "ST4JOB-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
