from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from stage1_tasking.scheduler import H01_CONSUMER_MUST_NOT_RECOMPUTE, Stage1Scheduler
from storage import reset_default_storage
from storage.db import DatabaseSession


class TestStage1Scheduler(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()
        self.payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        self.payload.update(
            {
                "task_id": "TASK-SCHED-001",
                "project_id": "PROJ-SCHED-001",
                "now": "2026-04-25T00:00:00+00:00",
                "current_action_start_at_optional": "2026-04-25T01:00:00+00:00",
                "current_action_deadline_at_optional": "2026-04-26T01:00:00+00:00",
            }
        )

    def test_next_window_uses_stage1_source_route_clock_authority(self) -> None:
        window = Stage1Scheduler().next_window(self.payload)

        self.assertEqual(window.window_id, "S1WIN-TASK-SCHED-001")
        self.assertEqual(window.window_start_at, "2026-04-25T01:00:00+00:00")
        self.assertEqual(window.window_due_at, "2026-04-26T01:00:00+00:00")
        self.assertEqual(window.clock_resolution_rule_id, "CLOCK-DEFAULT")
        self.assertEqual(window.clock_precedence_rule_id, "CLOCK-PROC-NOTICE-001")
        self.assertEqual(window.authority_refs["source_registry_id"], "SRC-REG-PROC-NATIONAL-HTML")
        self.assertEqual(window.authority_refs["route_policy_id"], "ROUTE-PROC-NOTICE-001")
        self.assertEqual(window.authority_refs["default_route"], "LIST_TO_DETAIL")
        self.assertEqual(window.authority_refs["fallback_route"], "DETAIL_DIRECT")

    def test_create_task_persists_queue_payload_and_stage2_handoff_intent_without_fetch(self) -> None:
        scheduler = Stage1Scheduler()
        task = scheduler.create_task(self.payload)
        readback = scheduler.readback(task.queue_item_id)

        self.assertEqual(task.task_id, "TASK-SCHED-001")
        self.assertEqual(task.project_id, "PROJ-SCHED-001")
        self.assertEqual(task.source_family, "PROCUREMENT_NOTICE")
        self.assertEqual(task.route_policy_id, "ROUTE-PROC-NOTICE-001")
        self.assertEqual(task.queue_item_id, "S1Q-TASK-SCHED-001")
        self.assertEqual(task.status, "queued")
        self.assertEqual(task.retry_state.attempt_count, 0)
        self.assertEqual(task.retry_state.max_attempts, 3)
        self.assertFalse(task.pause_state.is_paused)
        self.assertEqual(task.audit_refs["scheduling_audit_id"], "S1AUD-TASK-SCHED-001")

        intent = task.stage2_handoff_intent
        self.assertEqual(intent.handoff_id, "H-01-STAGE1-TO-STAGE2")
        self.assertEqual(intent.consumer_stage, "stage2_ingestion")
        self.assertFalse(intent.fetch_enabled)
        self.assertFalse(intent.crawler_enabled)
        self.assertFalse(intent.real_external_fetch_enabled)
        self.assertEqual(intent.consumer_must_not_recompute_fields, H01_CONSUMER_MUST_NOT_RECOMPUTE)
        self.assertEqual(intent.handoff_payload["source_registry_id"], "SRC-REG-PROC-NATIONAL-HTML")
        self.assertEqual(intent.handoff_payload["route_policy_id"], "ROUTE-PROC-NOTICE-001")
        self.assertEqual(intent.handoff_payload["clock_precedence_rule_id"], "CLOCK-PROC-NOTICE-001")

        self.assertTrue(readback["repository_backed"])
        self.assertTrue(readback["replayable"])
        self.assertFalse(readback["fetch_execution"]["stage2_fetch_enabled"])
        self.assertFalse(readback["fetch_execution"]["crawler_enabled"])
        self.assertFalse(readback["fetch_execution"]["real_external_fetch_enabled"])
        self.assertEqual(readback["queue_item"]["payload"]["scheduler_task"]["task_id"], task.task_id)
        self.assertEqual(
            readback["queue_item"]["payload"]["stage2_handoff_intent"]["handoff_payload"]["default_route"],
            "LIST_TO_DETAIL",
        )

    def test_pause_resume_retry_lease_dead_letter_are_replayable(self) -> None:
        payload = dict(self.payload)
        payload.update({"task_id": "TASK-SCHED-LIFECYCLE", "max_attempts": 2})
        scheduler = Stage1Scheduler()
        task = scheduler.create_task(payload)

        paused = scheduler.pause(
            task.queue_item_id,
            paused_by="single_operator",
            reason="manual_review_window",
            now="2026-04-25T02:00:00+00:00",
        )
        self.assertEqual(paused.status, "suspended")
        self.assertTrue(paused.pause_state.is_paused)
        self.assertEqual(paused.pause_state.reason, "manual_review_window")

        resumed = scheduler.resume(
            task.queue_item_id,
            next_run_at="2026-04-25T03:00:00+00:00",
            now="2026-04-25T02:30:00+00:00",
        )
        self.assertEqual(resumed.status, "queued")
        self.assertFalse(resumed.pause_state.is_paused)
        self.assertEqual(resumed.pause_state.resumed_at, "2026-04-25T02:30:00+00:00")

        leased = scheduler.lease(
            task.queue_item_id,
            worker_id="worker-1",
            lease_id="lease-1",
            now="2026-04-25T03:00:00+00:00",
        )
        self.assertEqual(leased.status, "running")
        self.assertEqual(leased.retry_state.attempt_count, 1)

        retry = scheduler.retry(
            task.queue_item_id,
            worker_id="worker-1",
            lease_id="lease-1",
            error="stage2_handoff_not_ready",
            retry_delay_seconds=0,
            now="2026-04-25T03:01:00+00:00",
        )
        self.assertEqual(retry.status, "retry")
        self.assertEqual(retry.retry_state.last_error, "stage2_handoff_not_ready")

        leased_again = scheduler.lease(
            task.queue_item_id,
            worker_id="worker-1",
            lease_id="lease-2",
            now="2026-04-25T03:02:00+00:00",
        )
        self.assertEqual(leased_again.retry_state.attempt_count, 2)

        dead = scheduler.retry(
            task.queue_item_id,
            worker_id="worker-1",
            lease_id="lease-2",
            error="stage2_handoff_still_not_ready",
            retry_delay_seconds=0,
            now="2026-04-25T03:03:00+00:00",
        )
        self.assertEqual(dead.status, "dead-letter")
        self.assertEqual(dead.retry_state.last_error, "stage2_handoff_still_not_ready")

        replay = scheduler.replay(task.queue_item_id)
        event_types = [event["event_type"] for event in replay["events"]]
        self.assertEqual(
            event_types,
            [
                "queued",
                "suspended",
                "resumed",
                "claimed",
                "retry_scheduled",
                "claimed",
                "dead_lettered",
            ],
        )
        self.assertFalse(replay["stage2_fetch_executed"])
        self.assertFalse(replay["crawler_executed"])
        self.assertFalse(replay["real_external_fetch_executed"])

    def test_manual_dead_letter_is_persisted_and_readable(self) -> None:
        payload = dict(self.payload)
        payload["task_id"] = "TASK-SCHED-MANUAL-DL"
        scheduler = Stage1Scheduler()
        task = scheduler.create_task(payload)

        dead = scheduler.dead_letter(
            task.queue_item_id,
            reason="operator_dead_lettered_before_stage2_fetch",
            now="2026-04-25T04:00:00+00:00",
        )
        readback = scheduler.readback(task.queue_item_id)

        self.assertEqual(dead.status, "dead-letter")
        self.assertEqual(dead.retry_state.last_error, "operator_dead_lettered_before_stage2_fetch")
        self.assertEqual(readback["queue_item"]["dead_letter_at"], "2026-04-25T04:00:00+00:00")
        self.assertEqual(readback["scheduler_task"]["status"], "dead-letter")

    def test_json_file_persistence_reopens_scheduler_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "stage1-scheduler.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "json-file",
                    "KAKA_STORAGE_PATH": str(storage_path),
                    "KAKA_STORAGE_SCOPE": "shared",
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                DatabaseSession.default().close()
                reset_default_storage()
                payload = dict(self.payload)
                payload["task_id"] = "TASK-SCHED-PERSIST"
                task = Stage1Scheduler().create_task(payload)
                DatabaseSession.default(reload_from_disk=True)
                readback = Stage1Scheduler().readback(task.queue_item_id)

        self.assertEqual(readback["scheduler_task"]["task_id"], "TASK-SCHED-PERSIST")
        self.assertEqual(readback["queue_item"]["status"], "queued")
        self.assertTrue(readback["replayable"])

    def test_scheduler_rejects_real_fetch_and_private_or_gray_source_requests(self) -> None:
        live_payload = dict(self.payload)
        live_payload["task_id"] = "TASK-SCHED-LIVE-BLOCK"
        live_payload["real_external_fetch_enabled"] = True
        with self.assertRaisesRegex(ValueError, "real_external_fetch_enabled"):
            Stage1Scheduler().create_task(live_payload)

        private_payload = dict(self.payload)
        private_payload["task_id"] = "TASK-SCHED-PRIVATE-BLOCK"
        private_payload["source_mode"] = "PRIVATE_SOURCE"
        with self.assertRaisesRegex(ValueError, "PRIVATE"):
            Stage1Scheduler().create_task(private_payload)


if __name__ == "__main__":
    unittest.main()
