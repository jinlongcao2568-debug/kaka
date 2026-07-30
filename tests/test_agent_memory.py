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
from shared.agent_memory import (
    AGENT_MEMORY_AUDIT_OBJECT_TYPE,
    AGENT_MEMORY_OBJECT_TYPE,
    AgentMemoryInputError,
    build_model_safe_agent_memory_context,
    list_agent_memories,
    mutate_agent_memory,
)
from shared.agent_tool_planner import build_agent_tool_plan, load_agent_tool_registry
from shared.conversational_agent import build_conversational_agent_turn
from storage.db import DatabaseSession
from storage_test_support import IsolatedStorageTestMixin


def _auth(
    *,
    tenant_id: str = "customer-a",
    principal_id: str = "operator-a",
    role: str = "operator",
) -> dict:
    return {
        "authenticated": True,
        "deployment_tenant_id": tenant_id,
        "principal_id": principal_id,
        "role": role,
        "permissions": [
            "internal_api_access",
            "internal_agent_memory",
            "internal_agent_plan",
            "internal_draft_write",
        ],
    }


def _mutation(
    *,
    auth: dict,
    action: str = "UPSERT",
    scope: str = "PRINCIPAL",
    project_id: str | None = None,
    memory_key: str = "response_detail",
    value: str | None = "concise",
    ttl_days: int | None = None,
    expected_version: int | None = None,
) -> dict:
    return {
        "action": action,
        "scope": scope,
        "project_id": project_id,
        "memory_key": memory_key,
        "value": value,
        "ttl_days": ttl_days,
        "expected_version": expected_version,
        "_internal_auth_context": auth,
    }


class TestAgentMemoryGovernance(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="agent-memory.json")
        load_agent_tool_registry.cache_clear()

    def tearDown(self) -> None:
        load_agent_tool_registry.cache_clear()
        self.tearDown_storage_test_env()

    def test_principal_tenant_and_project_scopes_are_isolated(self) -> None:
        auth_a = _auth()
        mutate_agent_memory(_mutation(auth=auth_a))
        mutate_agent_memory(
            _mutation(
                auth=auth_a,
                scope="PROJECT",
                project_id="PROJ-A",
                memory_key="project_workflow_note",
                value="优先补齐附件解析，再进入人工复核。",
            )
        )

        principal_a = list_agent_memories(
            {"scope": "PRINCIPAL", "_internal_auth_context": auth_a}
        )
        other_tenant = list_agent_memories(
            {
                "scope": "PRINCIPAL",
                "_internal_auth_context": _auth(tenant_id="customer-b"),
            }
        )
        other_principal = list_agent_memories(
            {
                "scope": "PRINCIPAL",
                "_internal_auth_context": _auth(principal_id="operator-b"),
            }
        )
        shared_project = list_agent_memories(
            {
                "scope": "PROJECT",
                "project_id": "PROJ-A",
                "_internal_auth_context": _auth(principal_id="operator-b"),
            }
        )
        other_project = list_agent_memories(
            {
                "scope": "PROJECT",
                "project_id": "PROJ-B",
                "_internal_auth_context": auth_a,
            }
        )

        self.assertEqual(principal_a["count"], 1)
        self.assertEqual(other_tenant["count"], 0)
        self.assertEqual(other_principal["count"], 0)
        self.assertEqual(shared_project["count"], 1)
        self.assertEqual(other_project["count"], 0)
        self.assertNotEqual(
            principal_a["context_scope"]["tenant_scope_sha256"],
            other_tenant["context_scope"]["tenant_scope_sha256"],
        )

    def test_correction_delete_and_audit_never_keep_raw_history(self) -> None:
        auth = _auth()
        created = mutate_agent_memory(_mutation(auth=auth, value="concise"))
        corrected = mutate_agent_memory(
            _mutation(
                auth=auth,
                action="CORRECT",
                value="detailed",
                expected_version=1,
            )
        )
        deleted = mutate_agent_memory(
            _mutation(
                auth=auth,
                action="DELETE",
                value=None,
                expected_version=2,
            )
        )

        self.assertEqual(created["operation_state"], "UPSERTED")
        self.assertEqual(corrected["operation_state"], "CORRECTED")
        self.assertEqual(corrected["memory"]["version"], 2)
        self.assertEqual(deleted["operation_state"], "DELETED")
        self.assertIsNone(deleted["memory"]["value"])
        record = DatabaseSession.default().get_record(
            AGENT_MEMORY_OBJECT_TYPE,
            str(deleted["memory"]["memory_id"]),
        )
        self.assertEqual(record.payload["state"], "DELETED")
        self.assertIsNone(record.payload["value"])
        audits = DatabaseSession.default().list_records(AGENT_MEMORY_AUDIT_OBJECT_TYPE)
        self.assertEqual(len(audits), 3)
        serialized = json.dumps([row.payload for row in audits], ensure_ascii=False)
        self.assertNotIn("concise", serialized)
        self.assertNotIn("detailed", serialized)
        self.assertTrue(all(row.payload["raw_value_persisted"] is False for row in audits))

    def test_sensitive_values_are_rejected_without_persistence(self) -> None:
        for index, sensitive in enumerate(
            (
                "api_key=sk-do-not-store",
                "联系邮箱 bad@example.com",
                "手机号 13800138000",
                "身份证 440101199001011234",
                "https://example.gov.cn/?token=secret",
            )
        ):
            with self.subTest(index=index), self.assertRaisesRegex(
                AgentMemoryInputError,
                "sensitive data",
            ):
                mutate_agent_memory(
                    _mutation(
                        auth=_auth(),
                        scope="PROJECT",
                        project_id=f"PROJ-SENSITIVE-{index}",
                        memory_key="project_workflow_note",
                        value=sensitive,
                    )
                )
        self.assertEqual(DatabaseSession.default().list_records(AGENT_MEMORY_OBJECT_TYPE), [])
        self.assertEqual(DatabaseSession.default().list_records(AGENT_MEMORY_AUDIT_OBJECT_TYPE), [])

    def test_expiry_clears_value_and_is_hidden_by_default(self) -> None:
        auth = _auth()
        mutate_agent_memory(
            _mutation(auth=auth, ttl_days=1),
            now_factory=lambda: "2026-07-20T00:00:00+00:00",
        )
        context = build_model_safe_agent_memory_context(
            auth,
            session=DatabaseSession.default(),
            now_factory=lambda: "2026-07-22T00:00:00+00:00",
        )
        default_list = list_agent_memories(
            {"scope": "PRINCIPAL", "_internal_auth_context": auth},
            now_factory=lambda: "2026-07-22T00:00:00+00:00",
        )
        expired_list = list_agent_memories(
            {
                "scope": "PRINCIPAL",
                "include_expired": True,
                "_internal_auth_context": auth,
            },
            now_factory=lambda: "2026-07-22T00:00:00+00:00",
        )

        self.assertEqual(context["context_state"], "EMPTY")
        self.assertEqual(default_list["count"], 0)
        self.assertEqual(expired_list["count"], 1)
        self.assertEqual(expired_list["memories"][0]["state"], "EXPIRED")
        self.assertIsNone(expired_list["memories"][0]["value"])
        stored = DatabaseSession.default().list_records(AGENT_MEMORY_OBJECT_TYPE)[0]
        self.assertIsNone(stored.payload["value"])

    def test_memory_context_is_visible_but_never_fact_evidence_or_citation(self) -> None:
        auth = _auth()
        mutate_agent_memory(
            _mutation(
                auth=auth,
                scope="PROJECT",
                project_id="PROJ-MEMORY-EVIDENCE",
                memory_key="project_workflow_note",
                value="工作假设：需要复核项目经理变更。",
            )
        )

        result = build_conversational_agent_turn(
            {
                "message": "这个项目有什么证据？",
                "project_id": "PROJ-MEMORY-EVIDENCE",
                "_internal_auth_context": auth,
            }
        )

        self.assertEqual(result["answer_state"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["facts"], [])
        self.assertTrue(result["memory_context"]["items"])
        self.assertFalse(result["memory_context"]["fact_evidence_eligible"])
        self.assertFalse(result["memory_context"]["citation_eligible"])
        self.assertTrue(result["governance"]["memory_is_not_fact_or_evidence"])
        self.assertFalse(
            any(citation.get("citation_kind") == "MEMORY" for citation in result["citations"])
        )

    def test_planner_can_only_read_model_safe_memory_context(self) -> None:
        auth = _auth()
        mutate_agent_memory(
            _mutation(auth=auth, memory_key="response_language", value="zh-CN")
        )
        result = build_agent_tool_plan(
            {
                "plan_id": "PLAN-MEMORY-READ-001",
                "proposal_source": "DETERMINISTIC_REQUEST",
                "execute_read_only": True,
                "calls": [
                    {
                        "call_id": "CALL-MEMORY-READ-001",
                        "tool_name": "agent_memory_context_read",
                        "arguments": {"project_id": None},
                    }
                ],
                "_internal_auth_context": auth,
            }
        )

        self.assertEqual(result["plan_state"], "COMPLETED_READ_ONLY")
        output = result["steps"][0]["output"]
        self.assertEqual(output["memory_context"]["items"][0]["value"], "zh-CN")
        self.assertFalse(output["memory_context"]["fact_evidence_eligible"])
        tool = next(
            item
            for item in load_agent_tool_registry()["tools"]
            if item["name"] == "agent_memory_context_read"
        )
        self.assertFalse(tool["mutation_allowed"])
        self.assertEqual(tool["required_permission"], "internal_agent_memory")

    def test_api_is_strict_transport_scoped_and_reviewer_denied(self) -> None:
        app = create_app()
        client = TestClient(app)
        headers = {
            "X-Kaka-Test-Operator-Auth": "approved",
            "X-Kaka-Test-Principal-Id": "memory-api-operator",
            "X-Kaka-Test-Role": "operator",
        }
        payload = {
            "action": "UPSERT",
            "scope": "PRINCIPAL",
            "project_id": None,
            "memory_key": "response_detail",
            "value": "standard",
            "ttl_days": 30,
            "expected_version": None,
        }

        created = client.post("/operator-console/agent/memories", headers=headers, json=payload)
        listed = client.get("/operator-console/agent/memories?scope=PRINCIPAL", headers=headers)
        spoofed = client.post(
            "/operator-console/agent/memories",
            headers=headers,
            json={**payload, "deployment_tenant_id": "customer-b"},
        )
        reviewer_headers = {
            "X-Kaka-Test-Operator-Auth": "approved",
            "X-Kaka-Test-Principal-Id": "memory-api-reviewer",
            "X-Kaka-Test-Role": "reviewer",
        }
        reviewer_write = client.post(
            "/operator-console/agent/memories",
            headers=reviewer_headers,
            json=payload,
        )
        reviewer_read = client.get(
            "/operator-console/agent/memories",
            headers=reviewer_headers,
        )

        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["count"], 1)
        self.assertEqual(spoofed.status_code, 400, spoofed.text)
        self.assertEqual(reviewer_write.status_code, 403, reviewer_write.text)
        self.assertEqual(reviewer_read.status_code, 403, reviewer_read.text)
        self.assertEqual(
            set(app.state.operator_agent_operations),
            {
                "createOperatorAgentTurn",
                "createOperatorAgentToolPlan",
                "listOperatorAgentMemories",
                "mutateOperatorAgentMemory",
            },
        )
        app.state.storage_session.close()


if __name__ == "__main__":
    unittest.main()
