from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
for search_path in (ROOT / "src", ROOT / "tests"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.main import create_app
from shared.agent_tool_planner import (
    build_agent_tool_plan,
    build_responses_tool_configuration,
    load_agent_tool_registry,
)
from storage.db import DatabaseSession, PersistedRecord
from storage.repositories.worker_queue_repo import WorkerQueueRepository
from storage_test_support import IsolatedStorageTestMixin


AUTH = {
    "authenticated": True,
    "principal_id": "operator-agent-planner-test",
    "role": "operator",
    "permissions": ["internal_api_access", "internal_agent_plan"],
}


class TestAgentToolPlanner(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="agent-tool-planner.json")
        load_agent_tool_registry.cache_clear()

    def tearDown(self) -> None:
        load_agent_tool_registry.cache_clear()
        self.tearDown_storage_test_env()

    def _payload(
        self,
        *,
        plan_id: str,
        tool_name: str,
        arguments: dict,
        execute_read_only: bool = True,
        permissions: list[str] | None = None,
    ) -> dict:
        auth = {**AUTH, "permissions": permissions if permissions is not None else AUTH["permissions"]}
        return {
            "plan_id": plan_id,
            "proposal_source": "MODEL_SHADOW_PROPOSAL",
            "execute_read_only": execute_read_only,
            "calls": [
                {
                    "call_id": f"CALL-{plan_id}",
                    "tool_name": tool_name,
                    "arguments": arguments,
                }
            ],
            "_internal_auth_context": auth,
        }

    def _persist_project_fact(self, project_id: str) -> None:
        DatabaseSession.default().upsert_record(
            PersistedRecord(
                object_type="project_fact",
                record_id=f"PF-{project_id}",
                stage_scope=6,
                project_id=project_id,
                object_refs={},
                decision_states={},
                trace_refs={},
                audit_refs={},
                governed_state={},
                writeback_state={},
                payload={
                    "project_id": project_id,
                    "sale_gate_status": "REVIEW_REQUIRED",
                    "rule_gate_status": "PASS",
                    "evidence_gate_status": "REVIEW_REQUIRED",
                    "source_url": "https://example.gov.cn/detail?id=1&token=remove-me",
                },
                persisted_at="2026-07-20T12:00:00+08:00",
            )
        )

    def test_registry_is_strict_sequential_bounded_and_never_live(self) -> None:
        registry = load_agent_tool_registry()

        self.assertTrue(registry["openai_responses_profile"]["strict"])
        self.assertFalse(registry["openai_responses_profile"]["parallel_tool_calls"])
        self.assertEqual(registry["execution_budget"]["max_plan_steps"], 4)
        self.assertEqual(registry["execution_budget"]["retry_count"], 0)
        self.assertFalse(registry["default_governance"]["live_execution_enabled"])
        for tool in registry["tools"]:
            with self.subTest(tool=tool["name"]):
                parameters = tool["parameters"]
                self.assertTrue(tool["strict"])
                self.assertFalse(parameters["additionalProperties"])
                self.assertEqual(set(parameters["properties"]), set(parameters["required"]))
                self.assertFalse(tool["mutation_allowed"])
                self.assertFalse(tool["live_execution_enabled"])
        handoff = next(
            tool for tool in registry["tools"] if tool["name"] == "internal_stage1_task_create_handoff"
        )
        self.assertTrue(handoff["requires_human_action"])
        self.assertEqual(handoff["execution_mode"], "HUMAN_HANDOFF_ONLY")
        self.assertFalse(handoff["human_handoff"]["planner_execution_after_approval_enabled"])

        provider_fragment = build_responses_tool_configuration(
            ["project_evidence_read", "internal_stage1_task_create_handoff"]
        )
        self.assertFalse(provider_fragment["parallel_tool_calls"])
        self.assertFalse(provider_fragment["provider_call_executed"])
        self.assertEqual(
            provider_fragment["tool_choice"],
            {
                "type": "allowed_tools",
                "mode": "auto",
                "tools": [
                    {"type": "function", "name": "project_evidence_read"},
                    {"type": "function", "name": "internal_stage1_task_create_handoff"},
                ],
            },
        )
        for tool in provider_fragment["tools"]:
            self.assertEqual(
                set(tool),
                {"type", "name", "description", "parameters", "strict"},
            )
            self.assertTrue(tool["strict"])
        with self.assertRaisesRegex(ValueError, "unregistered allowed tools"):
            build_responses_tool_configuration(["send_email"])

    def test_executes_grounded_read_only_tool_and_persists_call_id_hashes_and_output(self) -> None:
        project_id = "PROJ-TOOL-EVIDENCE-001"
        self._persist_project_fact(project_id)

        result = build_agent_tool_plan(
            self._payload(
                plan_id="PLAN-READ-001",
                tool_name="project_evidence_read",
                arguments={"project_id": project_id},
            )
        )

        self.assertEqual(result["plan_state"], "COMPLETED_READ_ONLY")
        self.assertTrue(result["execution_performed_this_request"])
        self.assertEqual(result["steps"][0]["call_id"], "CALL-PLAN-READ-001")
        self.assertEqual(result["steps"][0]["step_state"], "COMPLETED_READ_ONLY")
        self.assertTrue(result["steps"][0]["output"]["facts"])
        self.assertTrue(result["steps"][0]["output"]["citations"])
        self.assertNotIn("token=remove-me", json.dumps(result, ensure_ascii=False))
        self.assertFalse(result["governance"]["model_provider_call_executed"])
        self.assertFalse(result["governance"]["live_execution_enabled"])

        session = DatabaseSession.default()
        plan_record = session.get_record("agent_tool_plan", "PLAN-READ-001")
        step_record = session.get_record("agent_tool_step", result["steps"][0]["step_id"])
        self.assertIsNotNone(plan_record)
        self.assertIsNotNone(step_record)
        self.assertEqual(step_record.object_refs["call_id"], "CALL-PLAN-READ-001")
        self.assertEqual(len(step_record.trace_refs["arguments_sha256"]), 64)
        self.assertEqual(len(step_record.trace_refs["output_sha256"]), 64)
        self.assertEqual(step_record.payload["output"], result["steps"][0]["output"])

    def test_same_plan_is_idempotent_and_does_not_reexecute(self) -> None:
        payload = self._payload(
            plan_id="PLAN-IDEMPOTENT-001",
            tool_name="project_evidence_read",
            arguments={"project_id": "PROJ-MISSING-IDEMPOTENT"},
        )
        first = build_agent_tool_plan(payload)
        replay = build_agent_tool_plan(payload)

        self.assertEqual(first["plan_state"], "COMPLETED_READ_ONLY")
        self.assertEqual(replay["plan_state"], "REPLAYED_IDEMPOTENT")
        self.assertEqual(replay["original_plan_state"], "COMPLETED_READ_ONLY")
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(replay["execution_performed_this_request"])
        self.assertEqual(len(DatabaseSession.default().list_records("agent_tool_plan")), 1)
        self.assertEqual(len(DatabaseSession.default().list_records("agent_tool_step")), 1)

    def test_rejects_unregistered_tool_unknown_arguments_permission_gap_and_budget_before_execution(self) -> None:
        unregistered = build_agent_tool_plan(
            self._payload(
                plan_id="PLAN-UNREGISTERED-001",
                tool_name="send_email",
                arguments={"to": "victim@example.com"},
            )
        )
        unknown_argument = build_agent_tool_plan(
            self._payload(
                plan_id="PLAN-UNKNOWN-ARG-001",
                tool_name="project_evidence_read",
                arguments={"project_id": "PROJ-001", "url": "http://127.0.0.1"},
            )
        )
        permission_gap = build_agent_tool_plan(
            self._payload(
                plan_id="PLAN-PERMISSION-001",
                tool_name="project_evidence_read",
                arguments={"project_id": "PROJ-001"},
                permissions=[],
            )
        )
        too_many = {
            "plan_id": "PLAN-BUDGET-001",
            "proposal_source": "DETERMINISTIC_REQUEST",
            "execute_read_only": True,
            "calls": [
                {
                    "call_id": f"CALL-BUDGET-{index}",
                    "tool_name": "project_evidence_read",
                    "arguments": {"project_id": f"PROJ-{index}"},
                }
                for index in range(5)
            ],
            "_internal_auth_context": AUTH,
        }
        budget = build_agent_tool_plan(too_many)

        self.assertIn("TOOL_NOT_REGISTERED", {error["code"] for error in unregistered["errors"]})
        self.assertNotIn("victim@example.com", json.dumps(unregistered, ensure_ascii=False))
        self.assertEqual(unregistered["steps"][0]["arguments"], {})
        self.assertEqual(len(unregistered["steps"][0]["arguments_sha256"]), 64)
        self.assertIn("INVALID_TOOL_ARGUMENTS", {error["code"] for error in unknown_argument["errors"]})
        self.assertNotIn("127.0.0.1", json.dumps(unknown_argument, ensure_ascii=False))
        self.assertIn("TOOL_PERMISSION_DENIED", {error["code"] for error in permission_gap["errors"]})
        self.assertIn("PLAN_STEP_BUDGET_EXCEEDED", {error["code"] for error in budget["errors"]})
        for result in (unregistered, unknown_argument, permission_gap, budget):
            self.assertEqual(result["plan_state"], "REJECTED")
            self.assertFalse(result["execution_performed_this_request"])
            self.assertFalse(result["governance"]["live_execution_enabled"])

    def test_mutating_task_tool_always_pauses_for_human_and_never_creates_queue_item(self) -> None:
        repository = WorkerQueueRepository()
        self.assertEqual(repository.list(), [])

        result = build_agent_tool_plan(
            self._payload(
                plan_id="PLAN-HUMAN-HANDOFF-001",
                tool_name="internal_stage1_task_create_handoff",
                arguments={"project_id": "PROJ-HANDOFF-001", "region_code": "CN-GD"},
            )
        )

        self.assertEqual(result["plan_state"], "PAUSED_HUMAN_ACTION")
        self.assertEqual(result["steps"][0]["step_state"], "PAUSED_HUMAN_ACTION")
        self.assertFalse(result["steps"][0]["execution_performed"])
        self.assertFalse(result["steps"][0]["output"]["task_created"])
        self.assertEqual(
            result["steps"][0]["output"]["handoff_state"],
            "WAITING_AUTHENTICATED_OPERATOR_CONFIRMATION",
        )
        self.assertEqual(repository.list(), [])

    def test_api_mounts_separate_strict_plan_route_and_rejects_unknown_transport_fields(self) -> None:
        app = create_app()
        client = TestClient(app)
        headers = {
            "X-Kaka-Test-Operator-Auth": "approved",
            "X-Kaka-Test-Principal-Id": "operator-agent-plan-api",
            "X-Kaka-Test-Role": "operator",
        }
        payload = {
            "plan_id": "PLAN-API-001",
            "proposal_source": "DETERMINISTIC_REQUEST",
            "execute_read_only": False,
            "calls": [
                {
                    "call_id": "CALL-API-001",
                    "tool_name": "project_evidence_read",
                    "arguments": {"project_id": "PROJ-API-001"},
                }
            ],
        }

        response = client.post("/operator-console/agent/plans", headers=headers, json=payload)
        unknown = client.post(
            "/operator-console/agent/plans",
            headers=headers,
            json={**payload, "requested_by": "spoofed"},
        )
        reviewer = client.post(
            "/operator-console/agent/plans",
            headers={
                "X-Kaka-Test-Operator-Auth": "approved",
                "X-Kaka-Test-Principal-Id": "reviewer-agent-plan-api",
                "X-Kaka-Test-Role": "reviewer",
            },
            json={**payload, "plan_id": "PLAN-API-REVIEWER-001"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["plan_state"], "VALIDATED_NOT_EXECUTED")
        self.assertEqual(unknown.status_code, 400, unknown.text)
        self.assertEqual(reviewer.status_code, 403, reviewer.text)
        self.assertEqual(
            reviewer.json()["detail"]["required_permission"],
            "internal_agent_plan",
        )
        self.assertEqual(
            set(app.state.operator_agent_operations),
            {
                "createOperatorAgentTurn",
                "createOperatorAgentToolPlan",
                "listOperatorAgentMemories",
                "mutateOperatorAgentMemory",
            },
        )
        mounted = {
            row["operationId"]: row
            for row in app.state.transport_bootstrap["operator_agent_mounted_operations"]
        }
        self.assertTrue(mounted["createOperatorAgentToolPlan"]["strict_tool_registry"])
        self.assertFalse(mounted["createOperatorAgentToolPlan"]["parallel_tool_calls"])
        app.state.storage_session.close()


if __name__ == "__main__":
    unittest.main()
