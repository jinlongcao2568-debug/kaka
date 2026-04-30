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
            "AX9S 运营操作台",
            "证据包运营操作台",
            "阶段1-9 运营总览",
            "阶段1 调度",
            "阶段2 公开源",
            "阶段3 解析",
            "阶段4 核验",
            "阶段5 规则",
            "阶段6 产品包",
            "阶段7 销售",
            "阶段8 触达",
            "阶段9 支付交付",
            "系统方向：市场扫描",
            "阶段运行日志",
            "业务闭环摘要",
            "证据链",
            "证据风险",
            "销售闭环",
            "客户交付",
            "支付交付",
            "实战搜索",
            "实战项目搜索",
            "地区适配器",
            "房建工程",
            "市政工程",
            "金额区间（万元）",
            "搜索并生成机会闭环",
            "搜索运行记录",
            "待读取最新搜索记录",
            "刷新搜索记录",
            "买家排序",
            "交付状态",
            "下一步动作",
            "/operator-console/region-adapters",
            "/operator-console/autonomous-opportunity-search",
            "/operator-console/autonomous-search-runs",
            "/customer-artifact-portal/",
            "customerPortalLink",
            "data-workbench-opportunity",
            "updateCustomerPortalLink",
            "搜索运行中",
            "机会工作台",
            "采集运行",
            "系统与放行",
            "任务与项目",
            "公开源采集",
            "入口页配置",
            "附件配置",
            "执行入口页抓取",
            "执行附件抓取",
            "刷新真实源任务列表",
            "暂无真实源任务运行记录",
            "内部链路运行",
            "运行内部样本链路",
            "/internal/stage1-6/orchestrations",
            "/operator-console/real-source-profiles",
            "/operator-console/real-source-runs",
            "TASK-OWNER-SAMPLE-001",
            "SANITIZED_OFFLINE_INTERNAL",
            "真实执行已关闭",
            "阶段6-9读回",
            "服务商与调度状态",
            "审批审计",
            "证据包预览",
            "/operator-console/tasks",
            "/operator-console/project-imports",
            "/operator-console/readiness",
            "/go-live/readiness",
            "内部测试放行状态",
            "内部测试发布模拟已打开",
            "客户账号不作为内部测试前置",
            "真实邮件/电话未接入",
            "真实退款未接入，仅可模拟",
        ):
            self.assertIn(expected, html)
        for expected in (
            'class="layout operator-shell"',
            'data-view="systemRelease"',
            'data-view-panel="systemRelease"',
            'class="resultPane"',
            "function formatOperatorSummary(value)",
            "function renderStageOverviewTelemetry(telemetry)",
            "function showView(view)",
            "id=\"searchRegionChoices\"",
            "id=\"searchProjectTypeChoices\"",
            "id=\"opportunityDetail\"",
        ):
            self.assertIn(expected, html)
        for removed_duplicate in (
            "流程观察",
            "系统流程图与数据流",
            'data-view="flow"',
            'data-view-panel="flow"',
            "function renderFlowTelemetry(flow)",
            'data-view="business"',
            'data-view-panel="business"',
            'data-view="workbench"',
            'data-view-panel="workbench"',
            'data-view="providers"',
            'data-view-panel="providers"',
            'data-view="audit"',
            'data-view-panel="audit"',
            "自主机会工作台",
            "阶段6-9 工作台",
            "全链路运行",
            "运行受控样本到阶段6",
        ):
            self.assertNotIn(removed_duplicate, html)
        self.assertNotIn(
            'const out = (value) => { $("output").textContent = JSON.stringify(value, null, 2); };',
            html,
        )
        self.assertIn(r'join("\n")', html)
        self.assertNotIn('join("\n")', html)
        self.assertNotIn('href="#audit"', html)
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

        run_payload = load_fixture("internal_chain_happy.json")
        run_payload.update(
            {
                "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
                "source_mode": "OFFLINE_FIXTURE",
                "run_mode": "DRY_RUN",
                "live_execution_enabled": False,
            }
        )
        run_response = client.request(
            "POST",
            "/internal/stage1-6/orchestrations",
            json=run_payload,
        )
        self.assertEqual(run_response.status_code, 200)
        run_result = run_response.json()
        self.assertTrue(run_result["stage6_persisted"])
        self.assertEqual(run_result["orchestration_scope"], "stage1_to_stage6")
        self.assertFalse(run_result["live_execution_enabled"])
        self.assertFalse(run_result["external_live_transport_enabled"])
        self.assertEqual(
            run_result["stage6_readback"]["operational_context_status"],
            "persisted",
        )

    def test_owner_console_real_source_runner_uses_internal_only_routes(self) -> None:
        client = TestClient(create_app())
        html = client.request("GET", "/operator-console").text
        self.assertIn(
            'Promise.all([loadReadiness(false), loadAutonomousWorkbench(), loadRegionAdapters(), loadAutonomousSearchRuns(), loadRealSourceProfiles(), loadRealSourceRuns()])',
            html,
        )
        self.assertIn('"/operator-console/region-adapters"', html)
        self.assertIn('"/operator-console/autonomous-opportunity-search"', html)
        self.assertIn('"/operator-console/autonomous-search-runs"', html)
        self.assertIn('href="#autonomousWorkbench"', html)
        self.assertIn('data-workbench-opportunity', html)
        self.assertIn('id="selectAllRegions"', html)
        self.assertIn('id="selectAllProjectTypes"', html)
        self.assertIn('renderCandidateCards', html)
        self.assertIn('renderSearchResultFromRun', html)
        self.assertIn('"/customer-artifact-portal/', html)
        self.assertIn('"/operator-console/real-source-profiles"', html)
        self.assertIn('"/operator-console/real-source-runs"', html)
        self.assertIn('"/operator-console/real-source-task-runs"', html)
        self.assertIn("请先执行入口页或附件抓取。", html)

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
            "AX9S 内部证据包预览",
            "内部证据包预览 / 交付材料验收",
            "测试访问状态",
            "字段策略",
            "下载审计",
            "证据包内容",
            "拟邮件发送包",
            "内部预览验收",
            "字段白名单已执行",
            "脱敏必需",
            "真实下载未执行",
            "读回摘要",
            "renderReadbackSummary",
            "blockedReasonLabel",
            "/customer-artifact-portal-readback/",
            "内部验收可用",
            "renderEvidencePackage",
            "邮件发送包预览",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("signed download url enabled", html.lower())
        self.assertNotIn("JSON.stringify(value, null, 2)", html)
        self.assertIn("暂无证据包读回", html)
        self.assertIn("暂无证据包", html)
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
            "暂无证据包读回",
            "暂无证据包",
            "请先在运营操作台完成实战搜索",
            "真实下载未执行",
            "客户自助发布不是当前路径",
            "内部黑箱已隐藏",
            "内部预览未形成",
            "还没有可预览的拟邮件证据包",
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
