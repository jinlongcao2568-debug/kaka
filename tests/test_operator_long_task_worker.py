from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.routes.operator_customer_access import (  # noqa: E402
    cancel_operator_long_task,
    run_operator_autonomous_opportunity_search,
    run_owner_real_public_source_capture,
)
from runtime.operator_long_task_worker import (  # noqa: E402
    AUTONOMOUS_SEARCH_JOB_KIND,
    OPERATOR_LONG_TASK_QUEUE_NAME,
    REAL_SOURCE_CAPTURE_JOB_KIND,
    enqueue_operator_long_task,
    operator_long_task_status,
    run_operator_long_task_worker_once,
)
from shared.settings import Settings  # noqa: E402
from storage.db import DatabaseSession  # noqa: E402
from storage.repositories.worker_queue_repo import WorkerQueueRepository  # noqa: E402


class TestOperatorLongTaskWorker(unittest.TestCase):
    def test_browser_capability_routes_and_executes_search_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            item = enqueue_operator_long_task(
                job_kind=AUTONOMOUS_SEARCH_JOB_KIND,
                task_payload={
                    "async_execution": False,
                    "region_code": "CN-NATIONAL",
                },
                repository=repo,
                queue_item_id="RUN003-BROWSER-SEARCH",
            )

            core = run_operator_long_task_worker_once(
                repository=repo,
                worker_capability="core",
            )
            with patch(
                "api.routes.operator_customer_access.run_operator_autonomous_opportunity_search",
                return_value={"search_state": "NO_CANDIDATES"},
            ) as run_search:
                browser = run_operator_long_task_worker_once(
                    repository=repo,
                    worker_capability="browser",
                    heartbeat_seconds=0.01,
                )

            terminal = repo.get(item.queue_item_id)
            self.assertEqual(core["worker_state"], "NO_DUE_QUEUE_ITEM")
            self.assertEqual(browser["worker_state"], "JOB_SUCCEEDED")
            self.assertFalse(browser["queue"]["recurring_schedule_enabled"])
            self.assertFalse(browser["queue"]["unattended_recurring_run_ready"])
            self.assertEqual(
                browser["queue"]["unattended_operator_long_task_scope"],
                "INTERNAL_ONLY",
            )
            self.assertIn(
                "runtime.operator_long_task_worker",
                browser["queue"]["dedicated_process_command"],
            )
            self.assertEqual(terminal.status, "succeeded")
            self.assertEqual(terminal.progress_percent, 100.0)
            run_search.assert_called_once()
            self.assertIsNotNone(
                run_search.call_args.args[0].get("_runtime_execution_control")
            )
            repo.session.close()

    def test_http_handlers_enqueue_without_running_browser_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")

            def enqueue(**kwargs):
                return enqueue_operator_long_task(repository=repo, **kwargs)

            def status(*, limit=20):
                return operator_long_task_status(repo, limit=limit)

            with patch(
                "api.routes.operator_customer_access.enqueue_operator_long_task",
                side_effect=enqueue,
            ), patch(
                "api.routes.operator_customer_access.operator_long_task_status",
                side_effect=status,
            ), patch(
                "api.routes.operator_customer_access.RealPublicCandidateDiscoveryService"
            ) as discovery, patch(
                "api.routes.operator_customer_access.Stage2Service"
            ) as stage2:
                search = run_operator_autonomous_opportunity_search(
                    {
                        "async_execution": True,
                        "region_code": "CN-NATIONAL",
                        "job_time_budget_seconds": 120,
                    }
                )
                capture = run_owner_real_public_source_capture(
                    {
                        "async_execution": True,
                        "capture_kind": "entry",
                        "profile_id": "allowlisted-profile",
                    }
                )

            self.assertTrue(search["async_execution"])
            self.assertTrue(capture["async_execution"])
            self.assertEqual(
                repo.get(search["job_id"]).payload["runtime_job_kind"],
                AUTONOMOUS_SEARCH_JOB_KIND,
            )
            self.assertEqual(
                repo.get(capture["job_id"]).payload["runtime_job_kind"],
                REAL_SOURCE_CAPTURE_JOB_KIND,
            )
            self.assertFalse(
                repo.get(search["job_id"]).payload["task_payload"]["async_execution"]
            )
            discovery.assert_not_called()
            stage2.assert_not_called()
            repo.session.close()

    def test_queued_long_task_can_be_cancelled_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(Path(tmp_dir) / "queue.json")
            item = enqueue_operator_long_task(
                job_kind=REAL_SOURCE_CAPTURE_JOB_KIND,
                task_payload={"capture_kind": "entry", "profile_id": "profile"},
                repository=repo,
                queue_item_id="RUN002-CANCEL-LONG-TASK",
            )

            with patch(
                "api.routes.operator_customer_access.WorkerQueueRepository",
                return_value=repo,
            ), patch(
                "api.routes.operator_customer_access.operator_long_task_status",
                side_effect=lambda limit=20: operator_long_task_status(repo, limit=limit),
            ):
                result = cancel_operator_long_task(
                    {
                        "queue_item_id": item.queue_item_id,
                        "reason": "operator test cancel",
                    }
                )

            self.assertTrue(result["cancel_request_accepted"])
            self.assertEqual(result["queue_item"]["status"], "cancelled")
            self.assertEqual(repo.get(item.queue_item_id).queue_name, OPERATOR_LONG_TASK_QUEUE_NAME)
            repo.session.close()


def _repo(storage_path: Path) -> WorkerQueueRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage_path),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
    )
    return WorkerQueueRepository(session=DatabaseSession(settings=settings))


if __name__ == "__main__":
    unittest.main()
