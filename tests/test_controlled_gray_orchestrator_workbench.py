from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.main import create_app  # noqa: E402
from api.routes.operator_customer_access import (  # noqa: E402
    enqueue_controlled_gray_public_orchestrator_worker,
    prepare_controlled_gray_public_orchestrator,
    preview_controlled_gray_public_orchestrator,
    run_controlled_gray_public_orchestrator_worker_once,
)
from storage_test_support import IsolatedStorageTestMixin  # noqa: E402


class ControlledGrayOrchestratorWorkbenchTests(
    unittest.TestCase,
    IsolatedStorageTestMixin,
):
    def setUp(self) -> None:
        self.setUp_storage_test_env(
            storage_filename="controlled-gray-orchestrator-workbench.json"
        )

    def tearDown(self) -> None:
        self.tearDown_storage_test_env()

    def test_prepare_orchestrator_generates_manifest_and_repository_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_root = Path(tmp_dir) / "controlled-gray-orchestrator"

            result = prepare_controlled_gray_public_orchestrator(
                {
                    "output_root": str(output_root),
                    "per_target_sample_goal": 1,
                    "per_target_candidate_limit": 1,
                    "target_limit": 1,
                }
            )
            preview = preview_controlled_gray_public_orchestrator({})

        summary = result["summary"]
        self.assertEqual(result["surface_id"], "operator_controlled_gray_public_orchestrator_prepare")
        self.assertEqual(summary["orchestration_state"], "CONTROLLED_GRAY_NOT_READY")
        self.assertEqual(summary["aggregate_gray_review_state"], "NOT_READY_SEGMENTS_INCOMPLETE")
        self.assertFalse(result["execute_from_workbench_enabled"])
        self.assertFalse(result["customer_visible_allowed"])
        self.assertIn("manifest_sha256", result["manifest"])
        self.assertTrue(summary["workbench_trigger_ready"])
        capabilities = {
            record["capability_id"]: record
            for record in result["manifest"]["automation_capability_matrix"]["records"]
        }
        self.assertEqual(capabilities["workbench_trigger"]["state"], "WORKBENCH_PREPARE_READY")
        self.assertEqual(capabilities["background_scheduler"]["state"], "INTERNAL_WORKER_QUEUE_READY")
        self.assertEqual(preview["run_count"], 1)
        self.assertTrue(preview["latest_manifest_available"])
        self.assertEqual(
            preview["summary"]["aggregate_gray_review_state"],
            "NOT_READY_SEGMENTS_INCOMPLETE",
        )
        self.assertIn("-Execute", preview["recommended_execute_command"])
        self.assertFalse(preview["execute_from_workbench_enabled"])
        self.assertTrue(preview["background_worker_ready"])
        self.assertEqual(preview["background_scheduler_state"], "INTERNAL_WORKER_QUEUE_READY")

    def test_worker_queue_runs_controlled_gray_prepare_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_root = Path(tmp_dir) / "controlled-gray-orchestrator-worker"

            queued = enqueue_controlled_gray_public_orchestrator_worker(
                {
                    "output_root": str(output_root),
                    "per_target_sample_goal": 1,
                    "per_target_candidate_limit": 1,
                    "target_limit": 1,
                    "now": "2026-07-05T00:00:00+00:00",
                }
            )
            worker = run_controlled_gray_public_orchestrator_worker_once(
                {"now": "2026-07-05T00:00:01+00:00"}
            )
            preview = preview_controlled_gray_public_orchestrator({})

        self.assertEqual(queued["queue_item"]["status"], "queued")
        self.assertEqual(worker["worker_state"], "CONTROLLED_GRAY_ORCHESTRATOR_WORKER_SUCCEEDED")
        self.assertEqual(worker["queue_item"]["status"], "succeeded")
        self.assertEqual(worker["summary"]["orchestration_state"], "CONTROLLED_GRAY_NOT_READY")
        self.assertEqual(preview["run_count"], 1)
        self.assertEqual(preview["background_worker_queue"]["status_counts"]["succeeded"], 1)
        self.assertFalse(worker["execute_from_workbench_enabled"])

    def test_operator_console_exposes_controlled_gray_orchestrator_routes_and_view(self) -> None:
        app = create_app()
        mounted = {
            operation["operationId"]: operation
            for operation in app.state.transport_bootstrap[
                "operator_customer_access_mounted_operations"
            ]
        }

        self.assertTrue(mounted["previewControlledGrayPublicOrchestrator"]["internal_only"])
        self.assertTrue(
            mounted["previewControlledGrayPublicOrchestrator"][
                "controlled_gray_orchestrator_readback"
            ]
        )
        self.assertTrue(
            mounted["prepareControlledGrayPublicOrchestrator"][
                "controlled_gray_orchestrator_prepare"
            ]
        )
        self.assertFalse(mounted["prepareControlledGrayPublicOrchestrator"]["live_execution_enabled"])

        with tempfile.TemporaryDirectory() as tmp_dir:
            client = TestClient(app)
            response = client.post(
                "/operator-console/controlled-gray-orchestrator/prepare",
                json={
                    "output_root": str(Path(tmp_dir) / "controlled-gray-orchestrator"),
                    "per_target_sample_goal": 1,
                    "per_target_candidate_limit": 1,
                    "target_limit": 1,
                },
            )
            readback = client.get("/operator-console/controlled-gray-orchestrator")
            enqueue = client.post(
                "/operator-console/controlled-gray-orchestrator/worker/enqueue",
                json={
                    "output_root": str(Path(tmp_dir) / "controlled-gray-worker"),
                    "per_target_sample_goal": 1,
                    "per_target_candidate_limit": 1,
                    "target_limit": 1,
                },
            )
            worker = client.post(
                "/operator-console/controlled-gray-orchestrator/worker/run-once",
                json={},
            )
            blocked_execute = client.post(
                "/operator-console/controlled-gray-orchestrator/prepare",
                json={"execute": True},
            )
            blocked_worker_execute = client.post(
                "/operator-console/controlled-gray-orchestrator/worker/enqueue",
                json={"execute": True},
            )
            page = client.get("/operator-console")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(enqueue.status_code, 200)
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker.json()["worker_state"], "CONTROLLED_GRAY_ORCHESTRATOR_WORKER_SUCCEEDED")
        self.assertEqual(readback.status_code, 200)
        self.assertEqual(blocked_execute.status_code, 409)
        self.assertIn("execute is not allowed", blocked_execute.text)
        self.assertEqual(blocked_worker_execute.status_code, 409)
        self.assertIn("execute is not allowed", blocked_worker_execute.text)
        self.assertGreaterEqual(readback.json()["run_count"], 1)
        self.assertIn("灰度总控", page.text)
        self.assertIn("prepareGrayOrchestrator", page.text)
        self.assertIn("enqueueGrayOrchestrator", page.text)
        self.assertIn("runGrayOrchestratorWorker", page.text)
        self.assertIn("/operator-console/controlled-gray-orchestrator/prepare", page.text)
        self.assertIn("/operator-console/controlled-gray-orchestrator/worker/enqueue", page.text)


if __name__ == "__main__":
    unittest.main()
