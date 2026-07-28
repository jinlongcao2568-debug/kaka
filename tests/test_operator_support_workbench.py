from __future__ import annotations

import copy
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

from api.main import create_app
from shared.operator_support_workbench import (
    OperatorSupportAccessError,
    OperatorSupportConflictError,
    OperatorSupportInputError,
    build_operator_support_overview,
    retry_operator_support_task,
)
from shared.settings import Settings
from storage.db import DatabaseSession
from storage.repositories.worker_queue_repo import WorkerQueueRepository
from storage_test_support import IsolatedStorageTestMixin


NOW = "2026-07-20T10:00:00+00:00"


def _actor(role: str = "owner") -> dict:
    return {
        "authenticated": True,
        "principal_id": f"{role}-support-principal",
        "role": role,
        "permissions": ["internal_support_admin"] if role in {"owner", "admin"} else [],
        "deployment_tenant_id": "customer-a",
    }


class OperatorSupportWorkbenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.session = DatabaseSession(
            settings=Settings(
                storage_path_optional=str(Path(self.tmp.name) / "support.json"),
                storage_scope="process",
                storage_runtime_mode="explicit-path",
            )
        )
        self.repository = WorkerQueueRepository(session=self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.tmp.cleanup()

    def _failed_item(self, *, external: bool = False):
        queued = self.repository.enqueue(
            queue_item_id="SUPPORT-FAILED-001" if not external else "SUPPORT-EXTERNAL-001",
            queue_name="operator_long_tasks",
            payload={
                "runtime_job_kind": "operator_autonomous_opportunity_search_v1",
                "required_worker_capability": "browser",
                "internal_only": True,
                "live_execution_enabled": external,
                "customer_visible_allowed": False,
                "task_payload": {"task_id": "TASK-001", "project_id": "PROJ-001"},
            },
            max_attempts=1,
            now=NOW,
        )
        claimed = self.repository.claim(
            queue_item_id=queued.queue_item_id,
            worker_id="test-worker",
            lease_id="test-lease",
            now=NOW,
        )
        return self.repository.mark_failed(
            queue_item_id=claimed.queue_item_id,
            worker_id="test-worker",
            lease_id="test-lease",
            error="controlled test failure with internal diagnostic",
            retryable=False,
            error_category="HANDLER_ERROR",
            now="2026-07-20T10:00:30+00:00",
        )

    def test_overview_redacts_payload_error_and_reports_tenant_blockers_versions(self) -> None:
        failed = self._failed_item()
        result = build_operator_support_overview(
            {"_internal_auth_context": _actor(), "limit": 20},
            session=self.session,
        )
        self.assertEqual(result["context"]["deployment_tenant_id"], "customer-a")
        self.assertEqual(result["context"]["visible_tenant_count"], 1)
        self.assertFalse(result["context"]["cross_tenant_query_enabled"])
        self.assertEqual(result["metrics"]["blocker_count"], 1)
        task = result["tasks"][0]
        self.assertEqual(task["queue_item_id"], failed.queue_item_id)
        self.assertEqual(task["task_id"], "TASK-001")
        self.assertEqual(task["project_id"], "PROJ-001")
        self.assertTrue(task["support_retry_available"])
        self.assertFalse(task["raw_payload_exposed"])
        self.assertFalse(task["raw_error_exposed"])
        self.assertNotIn("controlled test failure", str(result))
        self.assertEqual(result["versions"]["support_contract_version"], "1.0.0")
        self.assertFalse(result["capabilities"]["direct_fact_edit"])
        self.assertTrue(result["audit_events"])
        self.assertTrue(all(not item["raw_detail_exposed"] for item in result["audit_events"]))

    def test_governed_retry_preserves_payload_and_writes_audit(self) -> None:
        failed = self._failed_item()
        original_payload = copy.deepcopy(failed.payload)
        result = retry_operator_support_task(
            {
                "action": "RETRY",
                "queue_item_id": failed.queue_item_id,
                "expected_status": "failed",
                "expected_updated_at": failed.updated_at,
                "confirmation": "RETRY_FAILED_INTERNAL_TASK",
                "reason": "负责人确认内部失败任务可以安全重试",
                "_internal_auth_context": _actor(),
            },
            session=self.session,
        )
        self.assertEqual(result["operation_state"], "GOVERNED_MANUAL_RETRY_QUEUED")
        self.assertEqual(result["task"]["status"], "retry")
        self.assertEqual(result["audit_event"]["event_type"], "manual_retry_queued")
        current = self.repository.get(failed.queue_item_id)
        self.assertEqual(current.payload, original_payload)
        self.assertEqual(current.progress_stage, "MANUAL_RETRY_QUEUED")
        self.assertFalse(result["governance"]["fact_layer_edit_enabled"])

    def test_retry_rejects_missing_confirmation_stale_state_sensitive_reason_and_external_boundary(self) -> None:
        failed = self._failed_item()
        base = {
            "action": "RETRY",
            "queue_item_id": failed.queue_item_id,
            "expected_status": "failed",
            "expected_updated_at": failed.updated_at,
            "confirmation": "RETRY_FAILED_INTERNAL_TASK",
            "reason": "负责人确认内部失败任务可以安全重试",
            "_internal_auth_context": _actor(),
        }
        invalid_cases = [
            ({**base, "confirmation": "yes"}, OperatorSupportInputError),
            ({**base, "expected_updated_at": NOW}, OperatorSupportConflictError),
            ({**base, "reason": "password=should-not-persist"}, OperatorSupportInputError),
        ]
        for payload, error in invalid_cases:
            with self.subTest(payload=payload):
                with self.assertRaises(error):
                    retry_operator_support_task(payload, session=self.session)
        external = self._failed_item(external=True)
        with self.assertRaises(OperatorSupportConflictError):
            retry_operator_support_task(
                {
                    **base,
                    "queue_item_id": external.queue_item_id,
                    "expected_updated_at": external.updated_at,
                },
                session=self.session,
            )
        with self.assertRaises(OperatorSupportAccessError):
            build_operator_support_overview(
                {"_internal_auth_context": _actor("operator")},
                session=self.session,
            )


class OperatorSupportWorkbenchApiTests(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="operator-support-api.json")
        self.client = TestClient(create_app())
        self.owner_headers = {
            "X-Kaka-Test-Operator-Auth": "approved",
            "X-Kaka-Test-Principal-Id": "support-owner",
            "X-Kaka-Test-Role": "owner",
        }

    def tearDown(self) -> None:
        self.client.close()
        self.tearDown_storage_test_env()

    def test_support_api_is_owner_only_and_rejects_unknown_write_fields(self) -> None:
        owner = self.client.get(
            "/operator-console/support/overview?limit=10",
            headers=self.owner_headers,
        )
        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertEqual(owner.json()["context"]["visible_tenant_count"], 1)
        operator = self.client.get(
            "/operator-console/support/overview",
            headers={
                "X-Kaka-Test-Operator-Auth": "approved",
                "X-Kaka-Test-Principal-Id": "support-operator",
                "X-Kaka-Test-Role": "operator",
            },
        )
        self.assertEqual(operator.status_code, 403, operator.text)
        invalid = self.client.post(
            "/operator-console/support/task-actions",
            headers=self.owner_headers,
            json={
                "action": "RETRY",
                "queue_item_id": "SUPPORT-MISSING",
                "expected_status": "failed",
                "expected_updated_at": NOW,
                "confirmation": "RETRY_FAILED_INTERNAL_TASK",
                "reason": "负责人确认内部失败任务可以安全重试",
                "unexpected": "rejected",
            },
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertTrue(
            any(error["type"] == "extra_forbidden" for error in invalid.json()["detail"]["errors"])
        )

    def test_support_api_retries_failed_item_with_exact_confirmation(self) -> None:
        repository = WorkerQueueRepository()
        queued = repository.enqueue(
            queue_item_id="SUPPORT-API-FAILED-001",
            queue_name="operator_long_tasks",
            payload={
                "internal_only": True,
                "live_execution_enabled": False,
                "customer_visible_allowed": False,
            },
            max_attempts=1,
            now=NOW,
        )
        repository.claim(
            queue_item_id=queued.queue_item_id,
            worker_id="api-test-worker",
            lease_id="api-test-lease",
            now=NOW,
        )
        failed = repository.mark_failed(
            queue_item_id=queued.queue_item_id,
            worker_id="api-test-worker",
            lease_id="api-test-lease",
            error="controlled API test failure",
            retryable=False,
            now="2026-07-20T10:00:30+00:00",
        )
        response = self.client.post(
            "/operator-console/support/task-actions",
            headers=self.owner_headers,
            json={
                "action": "RETRY",
                "queue_item_id": failed.queue_item_id,
                "expected_status": "failed",
                "expected_updated_at": failed.updated_at,
                "confirmation": "RETRY_FAILED_INTERNAL_TASK",
                "reason": "负责人确认内部失败任务可以安全重试",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["task"]["status"], "retry")
        self.assertEqual(response.json()["audit_event"]["event_type"], "manual_retry_queued")


if __name__ == "__main__":
    unittest.main()
