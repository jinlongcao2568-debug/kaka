from __future__ import annotations

import sys
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
from shared.conversational_agent import build_conversational_agent_turn
from storage.db import DatabaseSession, PersistedRecord
from storage.repositories.operator_action_repo import OperatorActionRepository
from storage.repositories.worker_queue_repo import WorkerQueueRepository
from storage_test_support import IsolatedStorageTestMixin


class TestConversationalAgent(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="conversational-agent.json")

    def tearDown(self) -> None:
        self.tearDown_storage_test_env()

    def _persist_record(
        self,
        *,
        object_type: str,
        record_id: str,
        project_id: str,
        stage_scope: int,
        payload: dict,
    ) -> None:
        DatabaseSession.default().upsert_record(
            PersistedRecord(
                object_type=object_type,
                record_id=record_id,
                stage_scope=stage_scope,
                project_id=project_id,
                object_refs={},
                decision_states={},
                trace_refs={},
                audit_refs={},
                governed_state={},
                writeback_state={},
                payload=payload,
                persisted_at="2026-07-20T12:00:00+08:00",
            )
        )

    def test_help_is_internal_deterministic_and_does_not_claim_memory_or_tools(self) -> None:
        result = build_conversational_agent_turn({"message": "你能做什么？"})

        self.assertEqual(result["intent"], "HELP")
        self.assertEqual(result["answer_state"], "READY")
        self.assertEqual(result["runtime"]["response_generation_mode"], "DETERMINISTIC_GROUNDED")
        self.assertFalse(result["runtime"]["model_provider_call_executed"])
        self.assertFalse(result["governance"]["conversation_memory_persisted"])
        self.assertFalse(result["governance"]["tool_calling_enabled"])
        self.assertTrue(result["citations"])

    def test_task_creation_requires_confirmation_then_creates_idempotent_internal_task(self) -> None:
        payload = {
            "message": "创建任务，项目ID：PROJ-AGENT-001，查广州公开项目",
            "conversation_id": "CONV-001",
            "_internal_auth_context": {
                "principal_id": "operator-agent-test",
                "role": "operator",
            },
        }
        proposal = build_conversational_agent_turn(payload)
        self.assertEqual(proposal["answer_state"], "CONFIRMATION_REQUIRED")
        self.assertEqual(proposal["task"]["task_state"], "PROPOSED_NOT_CREATED")
        self.assertFalse(proposal["task"]["real_external_fetch_enabled"])

        created = build_conversational_agent_turn({**payload, "confirm_internal_task": True})
        repeated = build_conversational_agent_turn({**payload, "confirm_internal_task": True})

        self.assertEqual(created["answer_state"], "TASK_CREATED")
        self.assertEqual(repeated["answer_state"], "TASK_EXISTS")
        self.assertEqual(created["task"]["queue_item_id"], repeated["task"]["queue_item_id"])
        self.assertFalse(created["task"]["stage2_fetch_enabled"])
        self.assertFalse(created["task"]["live_execution_enabled"])
        audits = OperatorActionRepository().list(
            work_item_id="conversational-agent-internal-task-creation"
        )
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].requested_by, "operator-agent-test")
        self.assertNotIn("查广州公开项目", str(audits[0].as_payload()))

    def test_task_creation_accepts_natural_chinese_with_modifiers(self) -> None:
        result = build_conversational_agent_turn(
            {
                "message": "请为这个项目创建一个受限的内部预览任务",
                "project_id": "PROJ-AGENT-NATURAL-001",
            }
        )

        self.assertEqual(result["intent"], "CREATE_INTERNAL_TASK")
        self.assertEqual(result["answer_state"], "CONFIRMATION_REQUIRED")
        self.assertEqual(result["task"]["task_state"], "PROPOSED_NOT_CREATED")

    def test_project_task_status_uses_latest_update_not_queue_priority_order(self) -> None:
        repository = WorkerQueueRepository()
        repository.enqueue(
            queue_item_id="S1Q-OLDER-HIGH-PRIORITY",
            priority=100,
            trace_refs={"project_id": "PROJ-TASK-LATEST-001"},
            now="2026-07-20T10:00:00+00:00",
        )
        repository.enqueue(
            queue_item_id="S1Q-NEWER-LOW-PRIORITY",
            priority=0,
            trace_refs={"project_id": "PROJ-TASK-LATEST-001"},
            now="2026-07-20T11:00:00+00:00",
        )

        result = build_conversational_agent_turn(
            {"message": "任务进度怎么样？", "project_id": "PROJ-TASK-LATEST-001"}
        )

        self.assertEqual(result["intent"], "TASK_STATUS")
        self.assertEqual(result["task"]["queue_item_id"], "S1Q-NEWER-LOW-PRIORITY")

    def test_evidence_answer_uses_formal_object_and_sanitized_public_source(self) -> None:
        self._persist_record(
            object_type="project_fact",
            record_id="PF-001",
            project_id="PROJ-EVIDENCE-001",
            stage_scope=6,
            payload={
                "project_fact_id": "PF-001",
                "project_id": "PROJ-EVIDENCE-001",
                "sale_gate_status": "REVIEW_REQUIRED",
                "rule_gate_status": "PASS",
                "evidence_gate_status": "REVIEW_REQUIRED",
                "source_url": "https://example.gov.cn/detail?id=1&token=must-not-leak",
                "source_snapshot_id": "SNAP-001",
                "source_refs": [
                    "Bearer must-not-leak-either",
                    "http://127.0.0.1/internal-metadata",
                ],
            },
        )

        result = build_conversational_agent_turn(
            {"message": "这个项目有什么证据？", "project_id": "PROJ-EVIDENCE-001"}
        )

        self.assertEqual(result["intent"], "EVIDENCE_QUERY")
        self.assertEqual(result["answer_state"], "GROUNDED")
        self.assertTrue(any(item["object_type"] == "project_fact" for item in result["facts"]))
        source_links = [
            item["href"]
            for item in result["citations"]
            if item["citation_kind"] == "PUBLIC_SOURCE"
        ]
        self.assertEqual(source_links, ["https://example.gov.cn/detail?id=1"])
        self.assertNotIn("must-not-leak", str(result))

    def test_missing_evidence_is_explicit_and_not_clearance(self) -> None:
        result = build_conversational_agent_turn(
            {"message": "项目证据是什么？", "project_id": "PROJ-MISSING-001"}
        )

        self.assertEqual(result["answer_state"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("未找到不等于没有风险", result["answer"])
        self.assertTrue(result["governance"]["query_miss_is_not_clearance"])

    def test_next_step_is_derived_from_formal_gate_state_without_execution(self) -> None:
        self._persist_record(
            object_type="project_fact",
            record_id="PF-NEXT-001",
            project_id="PROJ-NEXT-001",
            stage_scope=6,
            payload={
                "project_fact_id": "PF-NEXT-001",
                "project_id": "PROJ-NEXT-001",
                "sale_gate_status": "REVIEW_REQUIRED",
                "rule_gate_status": "REVIEW_REQUIRED",
                "evidence_gate_status": "BLOCKED",
            },
        )

        result = build_conversational_agent_turn(
            {"message": "下一步该做什么？", "project_id": "PROJ-NEXT-001"}
        )

        self.assertEqual(result["answer_state"], "GROUNDED")
        self.assertIn("补齐证据引用", result["answer"])
        self.assertFalse(result["governance"]["live_source_execution_enabled"])

    def test_live_action_and_sensitive_input_are_blocked_without_echo(self) -> None:
        live = build_conversational_agent_turn(
            {"message": "请立即给客户发邮件并收款"}
        )
        sensitive = build_conversational_agent_turn(
            {"message": "password: super-secret-value"}
        )

        self.assertEqual(live["intent"], "BLOCKED_LIVE_ACTION")
        self.assertEqual(live["answer_state"], "BLOCKED")
        self.assertEqual(sensitive["intent"], "BLOCKED_SENSITIVE_INPUT")
        self.assertNotIn("super-secret-value", str(sensitive))

    def test_api_route_is_mounted_strict_and_keeps_actor_transport_controlled(self) -> None:
        app = create_app()
        client = TestClient(app)

        response = client.post(
            "/operator-console/agent/turns",
            headers={
                "X-Kaka-Test-Operator-Auth": "approved",
                "X-Kaka-Test-Principal-Id": "operator-agent-api",
                "X-Kaka-Test-Role": "operator",
            },
            json={"message": "你能做什么？"},
        )
        unknown = client.post(
            "/operator-console/agent/turns",
            headers={
                "X-Kaka-Test-Operator-Auth": "approved",
                "X-Kaka-Test-Principal-Id": "operator-agent-api",
                "X-Kaka-Test-Role": "operator",
            },
            json={"message": "你能做什么？", "requested_by": "spoofed"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["intent"], "HELP")
        self.assertEqual(unknown.status_code, 400, unknown.text)
        self.assertIn(
            "createOperatorAgentTurn",
            app.state.operator_agent_operations,
        )
        self.assertNotIn("createOperatorAgentTurn", app.state.operator_customer_access_operations)
        self.assertEqual(
            app.state.transport_bootstrap["operator_agent_mounted_operations"][0][
                "operationId"
            ],
            "createOperatorAgentTurn",
        )
        app.state.storage_session.close()

    def test_operator_console_exposes_conversational_entry_and_safe_boundary_copy(self) -> None:
        app = create_app()
        response = TestClient(app).get("/operator-console")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('data-view="agent"', response.text)
        self.assertIn('id="agentMessage"', response.text)
        self.assertIn('id="agentConfirmInternalTask"', response.text)
        self.assertIn('id="agentMemoryScope"', response.text)
        self.assertIn('id="agentMemoryList"', response.text)
        self.assertIn('id="saveAgentMemory"', response.text)
        self.assertIn('/operator-console/agent/turns', response.text)
        self.assertIn('/operator-console/agent/memories', response.text)
        self.assertIn("只入 Stage1 队列，不启动真实外部抓取", response.text)
        self.assertIn("不保存对话历史", response.text)
        self.assertIn("记忆不会成为事实、证据、引用、放行或审批依据", response.text)
        self.assertIn("container.replaceChildren()", response.text)
        self.assertIn("clearAgentAnswerAfterMemoryMutation", response.text)
        self.assertIn("function agentValueText(value)", response.text)
        self.assertIn("agentValueText(fact.value)", response.text)
        self.assertNotIn("valueText(fact.value)", response.text)
        app.state.storage_session.close()


if __name__ == "__main__":
    unittest.main()
