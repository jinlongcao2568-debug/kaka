from __future__ import annotations

import copy
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

from api.deps import get_settings
from api.main import create_app
from api.routes.operator_frontend import OPERATOR_FRONTEND_ROUTES
from helpers import load_fixture
from shared.pipeline import run_internal_chain
from storage import persist_stage_bundle, reset_default_storage


class TestOperatorFrontendPortal(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        reset_default_storage()

    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_owner_console_frontend_is_mounted_and_exposes_operator_workflow(self) -> None:
        app = create_app()
        client = TestClient(app)

        self.assertEqual(
            set(app.state.operator_frontend_operations),
            {
                "renderOwnerOperatorConsole",
                "renderCustomerArtifactPortal",
                "renderCustomerArtifactPortalReadback",
            },
        )
        route_metadata = {
            route["operationId"]: route
            for route in OPERATOR_FRONTEND_ROUTES
        }
        self.assertTrue(route_metadata["renderOwnerOperatorConsole"]["productized_owner_workbench"])
        self.assertTrue(route_metadata["renderOwnerOperatorConsole"]["stage1_to_stage9_operations_board"])
        self.assertTrue(route_metadata["renderOwnerOperatorConsole"]["business_closure_dashboard"])
        self.assertTrue(route_metadata["renderCustomerArtifactPortal"]["customer_artifact_empty_state"])
        self.assertTrue(
            route_metadata["renderCustomerArtifactPortalReadback"][
                "customer_artifact_portal_frontend_readback"
            ]
        )
        bootstrap = app.state.transport_bootstrap
        frontend_ops = {
            operation["operationId"]: operation
            for operation in bootstrap["operator_frontend_mounted_operations"]
        }
        self.assertEqual(set(frontend_ops), set(app.state.operator_frontend_operations))
        self.assertTrue(frontend_ops["renderOwnerOperatorConsole"]["internal_only"])
        self.assertFalse(frontend_ops["renderOwnerOperatorConsole"]["external_release_enabled"])
        self.assertFalse(frontend_ops["renderOwnerOperatorConsole"]["live_execution_enabled"])
        self.assertFalse(frontend_ops["renderOwnerOperatorConsole"]["real_provider_call_enabled"])

        access_bootstrap = bootstrap["operator_customer_access_bootstrap"]
        self.assertEqual(access_bootstrap["owner_operator_frontend_path"], "/operator-console")
        self.assertEqual(
            access_bootstrap["customer_artifact_portal_path"],
            "/customer-artifact-portal/{opportunity_id}",
        )
        self.assertEqual(set(access_bootstrap["frontend_operations"]), set(frontend_ops))
        owner_entry = bootstrap["entry_strategy"]["operator_customer_access"]["owner_operator_frontend"]
        self.assertTrue(owner_entry["task_creation_visible"])
        self.assertTrue(owner_entry["project_import_visible"])
        self.assertTrue(owner_entry["stage6_to_stage9_workbench_visible"])
        self.assertTrue(owner_entry["approval_audit_visible"])
        self.assertFalse(owner_entry["live_execution_enabled"])

        response = client.request("GET", "/operator-console")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        html = response.text
        for expected in (
            "AX9S Owner Console",
            "证据包运营操作台",
            "Stage1-9 运营总览",
            "Stage1 调度",
            "Stage2 公开源",
            "Stage3 解析",
            "Stage4 核验",
            "Stage5 规则",
            "Stage6 产品包",
            "Stage7 销售",
            "Stage8 触达",
            "Stage9 支付交付",
            "业务闭环",
            "证据链",
            "销售闭环",
            "客户交付",
            "支付交付",
            "任务创建",
            "全链路运行入口",
            "Stage6-9 工作台",
            "Provider 与调度状态",
            "审批审计",
            "客户 Artifact 门户",
            "/operator-console/tasks",
            "/operator-console/project-imports",
            "/operator-console/readiness",
            "/go-live/readiness",
            "external release blocked",
            "auto refund excluded",
            "real customer download blocked by default",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("public software release enabled", html)

    def test_owner_console_visible_controls_call_existing_internal_readback_apis(self) -> None:
        client = TestClient(create_app())
        task_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        task_payload.update(
            {
                "task_id": "TASK-FRONTEND-127-001",
                "project_id": "PROJ-FRONTEND-127-001",
                "now": "2026-04-27T00:00:00+00:00",
            }
        )

        created_response = client.request("POST", "/operator-console/tasks", json=task_payload)
        self.assertEqual(created_response.status_code, 200)
        created = created_response.json()
        self.assertEqual(created["surface_id"], "operator_task_creation")
        self.assertTrue(created["task_creation_visible"])
        self.assertFalse(created["stage2_fetch_enabled"])
        self.assertFalse(created["real_external_fetch_enabled"])
        self.assertFalse(created["live_execution_enabled"])

        scheduler_response = client.request("GET", "/operator-console/scheduler-status")
        self.assertEqual(scheduler_response.status_code, 200)
        scheduler = scheduler_response.json()
        self.assertEqual(scheduler["queue_status_counts"]["queued"], 1)
        self.assertFalse(scheduler["real_external_fetch_enabled"])
        self.assertFalse(scheduler["real_provider_execution_enabled"])

    def test_customer_artifact_portal_is_gated_and_uses_candidate_readback(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(create_app())
        page_response = client.request("GET", f"/customer-artifact-portal/{opportunity_id}")

        self.assertEqual(page_response.status_code, 200)
        self.assertIn("text/html", page_response.headers["content-type"])
        html = page_response.text
        for expected in (
            "AX9S Artifact Portal",
            "客户 Artifact 门户",
            "访问控制",
            "字段策略",
            "下载审计",
            "allowlist enforced",
            "masking required",
            "real download not executed",
            "/customer-artifact-portal-readback/",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("signed download url enabled", html.lower())
        self.assertIn("暂无 artifact readback", html)
        self.assertIn("暂无客户 artifact", html)
        self.assertIn("renderMissingArtifact", html)

        candidate_response = client.request(
            "GET",
            f"/customer-artifact-access-candidates/{opportunity_id}",
        )
        self.assertEqual(candidate_response.status_code, 200)
        candidate = candidate_response.json()
        self.assertTrue(candidate["release_blocked"])
        self.assertTrue(candidate["download_auth"]["auth_required"])
        self.assertFalse(candidate["download_auth"]["customer_download_enabled"])
        self.assertTrue(candidate["field_allowlist_masking"]["allowlist_enforced"])
        self.assertFalse(candidate["field_allowlist_masking"]["internal_blackbox_fields_exposed"])
        self.assertFalse(candidate["external_release_enabled"])
        self.assertFalse(candidate["public_software_release"])

    def test_customer_artifact_portal_exposes_empty_state_for_missing_readback(self) -> None:
        client = TestClient(create_app())
        page_response = client.request("GET", "/customer-artifact-portal/OPP-MISSING-UI-001")

        self.assertEqual(page_response.status_code, 200)
        html = page_response.text
        for expected in (
            "暂无 artifact readback",
            "暂无客户 artifact",
            "请先在 Owner Console 完成项目导入",
            "real download not executed",
            "customer-visible release blocked",
            "internal blackbox hidden",
        ):
            self.assertIn(expected, html)

        candidate_response = client.request(
            "GET",
            "/customer-artifact-access-candidates/OPP-MISSING-UI-001",
        )
        self.assertEqual(candidate_response.status_code, 400)

        portal_readback_response = client.request(
            "GET",
            "/customer-artifact-portal-readback/OPP-MISSING-UI-001",
        )
        self.assertEqual(portal_readback_response.status_code, 200)
        portal_readback = portal_readback_response.json()
        self.assertTrue(portal_readback["empty_state"])
        self.assertFalse(portal_readback["external_release_enabled"])
        self.assertFalse(portal_readback["download_auth"]["customer_download_enabled"])


if __name__ == "__main__":
    unittest.main()
