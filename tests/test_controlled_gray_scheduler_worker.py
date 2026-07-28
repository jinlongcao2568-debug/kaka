from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime.controlled_gray_scheduler_worker import (  # noqa: E402
    CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME,
    controlled_gray_scheduler_status,
    enqueue_controlled_gray_orchestrator_job,
    run_controlled_gray_scheduler_worker_once,
    serve_controlled_gray_scheduler_worker,
)
from runtime.operational_observability import (  # noqa: E402
    load_operational_events,
    reset_operational_event_sinks,
)
from shared.settings import Settings  # noqa: E402
from storage.db import DatabaseSession  # noqa: E402
from storage.repositories.worker_queue_repo import WorkerQueueRepository  # noqa: E402


class TestControlledGraySchedulerWorker(unittest.TestCase):
    def test_actual_queue_started_and_success_events_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            event_path = root / "operational-events.jsonl"
            with patch.dict(
                os.environ,
                {
                    "KAKA_OBSERVABILITY_ENABLED": "true",
                    "KAKA_OBSERVABILITY_EVENT_PATH": str(event_path),
                    "KAKA_OBSERVABILITY_STDOUT_ENABLED": "false",
                    "KAKA_OBSERVABILITY_SERVICE_NAME": "core-worker",
                },
                clear=False,
            ):
                reset_operational_event_sinks()
                repo = _repo(root / "queue.json")
                item = _enqueue(repo, root, queue_item_id="OPS004-QUEUE-SUCCESS")
                result = run_controlled_gray_scheduler_worker_once(
                    repository=repo,
                    handler=_handler_result,
                )
                events = load_operational_events(event_path)
                repo.session.close()
                reset_operational_event_sinks()

        self.assertEqual(result["worker_state"], "JOB_SUCCEEDED")
        self.assertEqual(
            [event["outcome"] for event in events],
            ["started", "success"],
        )
        self.assertTrue(all(event["component"] == "queue" for event in events))
        self.assertTrue(all(event["trace_id"] == item.queue_item_id for event in events))

    def test_worker_capability_routing_prevents_browser_worker_from_claiming_core_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            item = _enqueue(repo, Path(tmp_dir), queue_item_id="RUN003-CORE-ROUTING")

            browser = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=_handler_result,
                worker_capability="browser",
            )
            core = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=_handler_result,
                worker_capability="core",
            )

            self.assertEqual(browser["worker_state"], "NO_DUE_QUEUE_ITEM")
            self.assertEqual(browser["worker_capability"], "browser")
            self.assertEqual(repo.get(item.queue_item_id).status, "succeeded")
            self.assertEqual(core["worker_capability"], "core")
            repo.session.close()

    def test_progress_is_persisted_and_terminal_success_reaches_100_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            item = _enqueue(repo, Path(tmp_dir), queue_item_id="RUN002-PROGRESS")

            def progress_handler(payload: dict, control: object) -> dict:
                control.report_progress("SEGMENT_PLAN", 2, 4, "two phases complete")
                return _handler_result(payload)

            result = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=progress_handler,
                heartbeat_seconds=0.01,
            )
            terminal = repo.get(item.queue_item_id)
            events = repo.list_events(item.queue_item_id)

            self.assertEqual(result["worker_state"], "JOB_SUCCEEDED")
            self.assertGreaterEqual(result["progress_update_count"], 1)
            self.assertEqual(terminal.progress_stage, "COMPLETED")
            self.assertEqual(terminal.progress_percent, 100.0)
            self.assertIn("progress_updated", [event.event_type for event in events])
            repo.session.close()

    def test_running_job_honors_cooperative_cancel_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "queue.json"
            worker_repo = _repo(storage_path)
            item = _enqueue(
                worker_repo,
                Path(tmp_dir),
                queue_item_id="RUN002-CANCEL",
            )
            started = Event()
            result_box: dict = {}

            def cancellable_handler(payload: dict, control: object) -> dict:
                del payload
                started.set()
                while not control.cancel_event.wait(0.01):
                    control.report_progress("WAITING", 1, 10, "waiting for cancel")
                control.raise_if_cancelled()
                return {}

            def run_worker() -> None:
                result_box.update(
                    run_controlled_gray_scheduler_worker_once(
                        repository=worker_repo,
                        handler=cancellable_handler,
                        heartbeat_seconds=0.02,
                        lease_seconds=2,
                    )
                )

            worker_thread = Thread(target=run_worker)
            worker_thread.start()
            self.assertTrue(started.wait(2))
            cancel_repo = _repo(storage_path)
            cancel_repo.request_cancel(
                queue_item_id=item.queue_item_id,
                requested_by="operator-test",
                reason="controlled cancel test",
            )
            worker_thread.join(3)

            self.assertFalse(worker_thread.is_alive())
            self.assertEqual(result_box["worker_state"], "JOB_CANCELLED")
            terminal = cancel_repo.get(item.queue_item_id)
            self.assertEqual(terminal.status, "cancelled")
            self.assertEqual(terminal.cancel_requested_by, "operator-test")
            self.assertIsNotNone(terminal.cancelled_at)
            cancel_repo.session.close()
            worker_repo.session.close()

    def test_execution_time_budget_fails_closed_with_error_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            item = _enqueue(
                repo,
                Path(tmp_dir),
                queue_item_id="RUN002-BUDGET",
                time_budget_seconds=1,
            )

            def budget_handler(payload: dict, control: object) -> dict:
                del payload
                while not control.cancel_event.wait(0.01):
                    control.report_progress("LONG_PHASE", 1, 10, "bounded work")
                control.raise_if_cancelled()
                return {}

            result = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=budget_handler,
                heartbeat_seconds=0.05,
                lease_seconds=2,
            )
            terminal = repo.get(item.queue_item_id)

            self.assertEqual(result["worker_state"], "JOB_TIME_BUDGET_EXCEEDED")
            self.assertEqual(terminal.status, "failed")
            self.assertEqual(terminal.last_error_category, "TIME_BUDGET_EXCEEDED")
            self.assertIsNotNone(terminal.budget_exhausted_at)
            repo.session.close()

    def test_dedicated_worker_heartbeats_and_releases_terminal_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            item = _enqueue(repo, Path(tmp_dir), queue_item_id="RUN001-HEARTBEAT")

            def slow_handler(payload: dict) -> dict:
                self.assertFalse(payload["web_request_execution_enabled"])
                time.sleep(0.08)
                return _handler_result(payload)

            result = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=slow_handler,
                lease_seconds=2,
                heartbeat_seconds=0.01,
            )
            replay = repo.replay(item.queue_item_id)

            self.assertEqual(result["worker_state"], "JOB_SUCCEEDED")
            self.assertGreaterEqual(result["heartbeat_count"], 1)
            self.assertEqual(replay["current_status"], "succeeded")
            self.assertIn("heartbeat", [event["event_type"] for event in replay["events"]])
            terminal = repo.get(item.queue_item_id)
            self.assertIsNone(terminal.worker_id)
            self.assertIsNone(terminal.lease_id)
            self.assertIsNone(terminal.heartbeat_at)
            self.assertIsNone(terminal.expires_at)
            repo.session.close()

    def test_retry_exhaustion_dead_letters_and_keeps_next_periodic_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            _enqueue(
                repo,
                Path(tmp_dir),
                queue_item_id="RUN001-RECUR-FAIL",
                max_attempts=2,
                recurring_interval_seconds=60,
                schedule_id="RUN001-RECUR-FAIL-SCHEDULE",
                now="2026-07-20T00:00:00+00:00",
            )

            def failing_handler(payload: dict) -> dict:
                del payload
                raise RuntimeError("controlled failure")

            first = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=failing_handler,
                retry_delay_seconds=0,
                now="2026-07-20T00:00:01+00:00",
            )
            second = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=failing_handler,
                retry_delay_seconds=0,
                now="2026-07-20T00:00:02+00:00",
            )

            self.assertEqual(first["worker_state"], "JOB_FAILED_RETRY_SCHEDULED")
            self.assertEqual(second["worker_state"], "JOB_FAILED_DEAD_LETTERED")
            self.assertEqual(second["queue_item"]["status"], "dead-letter")
            next_item = second["next_recurring_queue_item"]
            self.assertEqual(next_item["status"], "queued")
            self.assertEqual(next_item["occurrence"], 1)
            self.assertEqual(next_item["next_run_at"], "2026-07-20T00:01:00+00:00")
            status = controlled_gray_scheduler_status(
                repo,
                now="2026-07-20T00:00:03+00:00",
            )
            self.assertEqual(status["status_counts"], {"dead-letter": 1, "queued": 1})
            repo.session.close()

    def test_expired_lease_is_recovered_after_repository_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "queue.json"
            first_repo = _repo(storage_path)
            item = _enqueue(
                first_repo,
                Path(tmp_dir),
                queue_item_id="RUN001-RESTART",
                max_attempts=2,
                now="2026-07-20T01:00:00+00:00",
            )
            first_repo.claim(
                queue_item_id=item.queue_item_id,
                worker_id="crashed-worker",
                lease_id="crashed-lease",
                lease_seconds=1,
                now="2026-07-20T01:00:00+00:00",
            )
            with self.assertRaisesRegex(ValueError, "lease expired"):
                first_repo.heartbeat(
                    queue_item_id=item.queue_item_id,
                    worker_id="crashed-worker",
                    lease_id="crashed-lease",
                    lease_seconds=5,
                    now="2026-07-20T01:00:02+00:00",
                )
            first_repo.session.close()

            restarted_repo = _repo(storage_path)
            recovered = run_controlled_gray_scheduler_worker_once(
                repository=restarted_repo,
                handler=_handler_result,
                now="2026-07-20T01:00:03+00:00",
            )
            replay = restarted_repo.replay(item.queue_item_id)

            self.assertEqual(recovered["worker_state"], "JOB_SUCCEEDED")
            self.assertEqual(recovered["queue_item"]["attempt_count"], 2)
            self.assertEqual(
                [event["event_type"] for event in replay["events"]],
                [
                    "queued",
                    "claimed",
                    "lease_timeout_retry_scheduled",
                    "claimed",
                    "succeeded",
                ],
            )
            restarted_repo.session.close()

    def test_suspended_job_is_not_claimed_until_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            item = _enqueue(repo, Path(tmp_dir), queue_item_id="RUN001-PAUSE")
            repo.suspend(
                queue_item_id=item.queue_item_id,
                suspended_by="operator",
                reason="maintenance_window",
            )

            idle = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=_handler_result,
            )
            self.assertEqual(idle["worker_state"], "NO_DUE_QUEUE_ITEM")
            repo.resume(queue_item_id=item.queue_item_id)
            resumed = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=_handler_result,
            )
            self.assertEqual(resumed["worker_state"], "JOB_SUCCEEDED")
            repo.session.close()

    def test_successful_periodic_job_enqueues_one_deterministic_future_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            _enqueue(
                repo,
                Path(tmp_dir),
                queue_item_id="RUN001-RECUR-SUCCESS",
                recurring_interval_seconds=60,
                schedule_id="RUN001-SCHEDULE",
                now="2026-07-20T02:00:00+00:00",
            )

            result = run_controlled_gray_scheduler_worker_once(
                repository=repo,
                handler=_handler_result,
                now="2026-07-20T02:00:01+00:00",
            )

            self.assertEqual(result["worker_state"], "JOB_SUCCEEDED")
            next_item = result["next_recurring_queue_item"]
            self.assertEqual(
                next_item["queue_item_id"],
                "RUN001-SCHEDULE::occurrence::00000001",
            )
            self.assertEqual(next_item["next_run_at"], "2026-07-20T02:01:00+00:00")
            self.assertEqual(
                len(repo.list(queue_name=CONTROLLED_GRAY_ORCHESTRATOR_QUEUE_NAME)),
                2,
            )
            repo.session.close()

    def test_idle_serve_loop_writes_observable_process_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            status_path = Path(tmp_dir) / "worker-status.json"

            result = serve_controlled_gray_scheduler_worker(
                repository=repo,
                handler=_handler_result,
                poll_seconds=0.01,
                status_json=status_path,
                max_idle_polls=1,
            )
            persisted = json.loads(status_path.read_text(encoding="utf-8"))

            self.assertEqual(result["worker_process_state"], "STOPPED")
            self.assertEqual(persisted["worker_process_state"], "STOPPED")
            self.assertEqual(persisted["consecutive_idle_poll_count"], 1)
            self.assertTrue(persisted["queue"]["unattended_recurring_run_ready"])
            self.assertEqual(
                persisted["queue"]["unattended_recurring_scope"],
                "INTERNAL_PREPARE_ONLY",
            )
            self.assertFalse(persisted["queue"]["unattended_live_execution_ready"])
            self.assertFalse(persisted["web_request_execution_enabled"])
            repo.session.close()


def _repo(storage_path: Path) -> WorkerQueueRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage_path),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
    )
    return WorkerQueueRepository(session=DatabaseSession(settings=settings))


def _enqueue(
    repo: WorkerQueueRepository,
    root: Path,
    *,
    queue_item_id: str,
    max_attempts: int = 3,
    recurring_interval_seconds: int = 0,
    schedule_id: str | None = None,
    time_budget_seconds: int = 1_800,
    now: str | None = None,
):
    return enqueue_controlled_gray_orchestrator_job(
        {
            "output_root": str(root / "output" / queue_item_id),
            "source_targets_json": str(
                ROOT
                / "contracts"
                / "evaluation"
                / "evaluation_real_project_sample_targets.json"
            ),
            "per_target_sample_goal": 1,
            "per_target_candidate_limit": 1,
            "target_limit": 1,
            "group_by": "target",
            "segment_timeout_seconds": 60,
            "execute": False,
        },
        repository=repo,
        queue_item_id=queue_item_id,
        max_attempts=max_attempts,
        recurring_interval_seconds=recurring_interval_seconds,
        schedule_id=schedule_id,
        time_budget_seconds=time_budget_seconds,
        now=now,
    )


def _handler_result(payload: dict) -> dict:
    return {
        "output_root": payload["output_root"],
        "summary": {
            "orchestration_state": "CONTROLLED_GRAY_NOT_READY",
            "aggregate_gray_review_state": "NOT_READY_SEGMENTS_INCOMPLETE",
        },
        "manifest": {"manifest_sha256": "fixture-sha256"},
    }


if __name__ == "__main__":
    unittest.main()
