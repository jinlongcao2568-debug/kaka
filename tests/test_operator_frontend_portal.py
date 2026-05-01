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
                "renderCustomerArtifactPortalDownload",
                "renderOperatorUserAcceptanceContract",
                "renderOperatorUserAcceptanceGapMatrix",
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
        self.assertTrue(
            route_metadata["renderCustomerArtifactPortalDownload"][
                "internal_evidence_package_download"
            ]
        )
        self.assertTrue(
            route_metadata["renderOperatorUserAcceptanceContract"][
                "operator_user_acceptance_contract"
            ]
        )
        self.assertTrue(
            route_metadata["renderOperatorUserAcceptanceGapMatrix"][
                "operator_user_acceptance_gap_matrix"
            ]
        )
        self.assertTrue(route_metadata["renderOperatorUserAcceptanceGapMatrix"]["ui_acceptance_status"])
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
            "阶段对象流与失败分类",
            "最新运行的阶段对象",
            "阶段运行日志",
            "业务闭环摘要",
            "证据链",
            "证据风险",
            "销售闭环",
            "证据包交付候选",
            "支付交付",
            "真实公开市场机会发现 + 证据包商业化运营系统",
            "内部/样本只作为回归模式",
            "客户不使用工作台",
            "真实可卖性判断",
            "当前能卖到哪一步",
            "实战搜索",
            "实战项目搜索",
            "地区适配器",
            "地区覆盖缺口",
            "房建工程",
            "市政工程",
            "金额区间（万元）",
            "使用离线样本验证后续链路（不代表真实市场发现）",
            "搜索并生成机会闭环",
            "搜索运行记录",
            "待读取最新搜索记录",
            "数据来源待读取",
            "清空测试搜索记录",
            "刷新搜索记录",
            "批量候选复盘与失败分类",
            "买家排序",
            "卖前/交付后边界",
            "卖前价值摘要",
            "卖前不可讲",
            "交付状态",
            "下一步动作",
            "/operator-console/region-adapters",
            "/operator-console/autonomous-opportunity-search",
            "/operator-console/autonomous-search-runs",
            "/operator-console/autonomous-search-runs/clear",
            "/operator-console/real-candidates",
            "/operator-console/real-candidate-stage2-captures",
            "真实候选入库 / 去重读回",
            "刷新真实候选库",
            "候选详情快照 / Stage2 读回",
            "无候选诊断 / 来源解析",
            "refreshRealCandidateDiscoveryDiagnostics",
            "/operator-console/real-candidate-discovery-runs",
            "疑似 JS 列表壳，需要接列表数据源",
            "function reasonLabel(value)",
            "金额低于搜索下限",
            "刷新详情快照",
            "/customer-artifact-portal/",
            "customerPortalLink",
            "data-workbench-opportunity",
            "updateCustomerPortalLink",
            "搜索运行中",
            "机会工作台",
            "采集运行",
            "系统与放行",
            "验收契约",
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
            "服务商沙箱 + 审批 + 审计 + 操作确认",
            "沙箱试运行读回",
            "真实服务商放行矩阵",
            "真实外部动作门禁矩阵",
            "审批审计",
            "证据包预览",
            "/operator-console/tasks",
            "/operator-console/project-imports",
            "/operator-console/readiness",
            "/go-live/readiness",
            "/operator-console/real-world-sellability",
            "回归与受控放行状态",
            "默认实战搜索已接真实公开列表页候选发现",
            "内部测试发布模拟已打开",
            "客户账号不作为内部测试前置",
            "真实邮件/电话未接入",
            "真实退款未接入，仅可模拟",
            "后台能力暴露清单",
            "真实候选发现器",
            "默认实战搜索会调用真实公开列表页候选发现器",
            "详情页快照读回",
            "用户验收契约",
            "当前验收状态",
            "验收差距矩阵",
            "验收标准",
            "当前优化优先级",
            "/operator-console/user-acceptance-contract",
            "/operator-console/user-acceptance-gap-matrix",
            "先验收契约，再改 UI/系统",
            "脚本绿灯",
            "系统已有能力是不是已经在 UI 可见",
            "证据包清单/下载预览",
            "公开来源网址校验",
            "文字识别/验证码/校验页处理入口",
            "批量商机运营",
        ):
            self.assertIn(expected, html)
        for expected in (
            'class="layout operator-shell"',
            'data-view="systemRelease"',
            'data-view-panel="systemRelease"',
            'class="resultPane"',
            "function formatOperatorSummary(value)",
            "function renderStageOverviewTelemetry(telemetry)",
            "function renderStageObjectFlow(stages)",
            "function clearAutonomousSearchRuns()",
            "function renderCapabilityExposure(readiness, scheduler, goLive)",
            "function renderUserAcceptanceContract(contract)",
            "async function loadUserAcceptanceContract()",
            "function renderAcceptanceGapMatrix(matrix)",
            "async function loadAcceptanceGapMatrix()",
            "function renderRealWorldSellability(surface)",
            "async function loadRealWorldSellability()",
            "function showView(view)",
            "id=\"sellabilityDecision\"",
            "id=\"sellabilityMetrics\"",
            "id=\"sellabilityBoundary\"",
            "id=\"sellabilityLaneList\"",
            "id=\"stageObjectFlow\"",
            "id=\"stageRunBoundary\"",
            "id=\"autonomousSearchPersistence\"",
            "id=\"clearAutonomousSearchRuns\"",
            "id=\"searchRegionChoices\"",
            "id=\"regionCoverageSummary\"",
            "id=\"regionCoverageNarrative\"",
            "id=\"searchProjectTypeChoices\"",
            "id=\"opportunityDetail\"",
            "id=\"providerExecutionMatrix\"",
            "id=\"liveActionGateMatrix\"",
            "id=\"capabilityExposure\"",
            "id=\"acceptanceContractSummary\"",
            "id=\"acceptanceGapSummary\"",
            "id=\"acceptanceGapMatrix\"",
            "id=\"acceptanceDimensionList\"",
            "id=\"realCandidateStage2Captures\"",
            "async function loadRealCandidateStage2Captures()",
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

    def test_owner_console_minimal_task_creation_is_visible_in_run_overview(self) -> None:
        client = TestClient(create_app())

        created_response = client.request(
            "POST",
            "/operator-console/tasks",
            json={
                "task_id": "TASK-FRONTEND-MIN-001",
                "project_id": "PROJ-FRONTEND-MIN-001",
                "now": "2026-05-01T00:00:00+00:00",
            },
        )

        self.assertEqual(created_response.status_code, 200)
        created = created_response.json()
        self.assertEqual(created["surface_id"], "operator_task_creation")
        self.assertEqual(created["scheduler_task"]["task_id"], "TASK-FRONTEND-MIN-001")
        self.assertEqual(created["scheduler_task"]["project_id"], "PROJ-FRONTEND-MIN-001")
        self.assertEqual(created["scheduler_task"]["region_code"], "CN-GD")
        self.assertEqual(created["operator_task_overview"]["task_id"], "TASK-FRONTEND-MIN-001")
        self.assertEqual(created["operator_task_overview"]["status"], "queued")
        self.assertFalse(created["real_external_fetch_enabled"])
        self.assertFalse(created["live_execution_enabled"])

        scheduler_response = client.request("GET", "/operator-console/scheduler-status")
        self.assertEqual(scheduler_response.status_code, 200)
        scheduler = scheduler_response.json()
        self.assertEqual(scheduler["queue_status_counts"]["queued"], 1)
        self.assertEqual(scheduler["latest_queue_item"]["task_id"], "TASK-FRONTEND-MIN-001")
        self.assertEqual(scheduler["latest_queue_items"][0]["project_id"], "PROJ-FRONTEND-MIN-001")
        self.assertFalse(scheduler["real_external_fetch_enabled"])

    def test_owner_console_real_source_runner_uses_internal_only_routes(self) -> None:
        client = TestClient(create_app())
        html = client.request("GET", "/operator-console").text
        self.assertIn(
            'Promise.all([loadReadiness(false), loadAutonomousWorkbench(), loadRegionAdapters(), loadAutonomousSearchRuns(), loadRealCandidateDiscoveryDiagnostics(), loadRealCandidateCatalog(), loadRealCandidateStage2Captures(), loadRealSourceProfiles(), loadRealSourceRuns(), loadUserAcceptanceContract(), loadAcceptanceGapMatrix(), loadRealWorldSellability()])',
            html,
        )
        self.assertIn('"/operator-console/region-adapters"', html)
        self.assertIn('"/operator-console/autonomous-opportunity-search"', html)
        self.assertIn('"/operator-console/autonomous-search-runs"', html)
        self.assertIn('"/operator-console/autonomous-search-runs/clear"', html)
        self.assertIn('"/operator-console/real-candidates"', html)
        self.assertIn('"/operator-console/real-candidate-stage2-captures"', html)
        self.assertIn('"/operator-console/user-acceptance-contract"', html)
        self.assertIn('"/operator-console/user-acceptance-gap-matrix"', html)
        self.assertIn('"/operator-console/real-world-sellability"', html)
        self.assertIn('href="#autonomousWorkbench"', html)
        self.assertIn('data-workbench-opportunity', html)
        self.assertIn('id="selectAllRegions"', html)
        self.assertIn('id="selectAllProjectTypes"', html)
        self.assertIn('id="clearAutonomousSearchRuns"', html)
        self.assertIn("持久保存，直到 owner 显式清空", html)
        self.assertIn("renderCandidateBatchReview", html)
        self.assertIn("renderProviderExecutionMatrix", html)
        self.assertIn("renderCommercialBoundary", html)
        self.assertIn("当前任务运行总览", html)
        self.assertIn("taskRunOverviewList", html)
        self.assertIn("renderTaskRunOverview", html)
        self.assertIn("taskOverviewTelemetryFromQueueItem", html)
        self.assertIn("renderStageRunBoundary", html)
        self.assertIn("客户可售证据未就绪", html)
        self.assertIn("真实候选缺失", html)
        self.assertIn("upstream_stage_not_reached", html)
        self.assertIn("<strong>9</strong><span>阶段数</span>", html)
        self.assertIn('window.scrollTo({ top: 0, left: 0, behavior: "auto" })', html)
        self.assertLess(
            html.index("<h3>阶段1-9 运营总览</h3>"),
            html.index("<h3>当前任务运行总览</h3>"),
        )
        self.assertLess(
            html.index("<h3>阶段1-9 运营总览</h3>"),
            html.index("<h3>真实可卖性判断</h3>"),
        )
        self.assertIn("showView(\"overview\")", html)
        self.assertIn("真实邮件/电话触达", html)
        self.assertIn('renderCandidateCards', html)
        self.assertIn('renderSearchResultFromRun', html)
        self.assertIn('"/customer-artifact-portal/', html)
        self.assertIn('"/customer-artifact-portal-download/', html)
        self.assertIn('"/operator-console/real-source-profiles"', html)
        self.assertIn('"/operator-console/real-source-runs"', html)
        self.assertIn('"/operator-console/real-source-task-runs"', html)
        self.assertIn("请先执行入口页或附件抓取。", html)

    def test_operator_user_acceptance_contract_defines_owner_real_world_standard(self) -> None:
        client = TestClient(create_app())

        response = client.request("GET", "/operator-console/user-acceptance-contract")

        self.assertEqual(response.status_code, 200)
        contract = response.json()
        self.assertEqual(contract["contractId"], "AX9S-OPERATOR-USER-ACCEPTANCE-CONTRACT")
        self.assertEqual(contract["status"], "ACTIVE")
        self.assertTrue(contract["acceptanceAuthority"]["userAcceptancePrecedesUiRewrite"])
        self.assertTrue(contract["acceptanceAuthority"]["scriptsPassingIsNotEnough"])
        self.assertTrue(contract["acceptanceAuthority"]["ownerMustObserveWithoutRawApi"])
        self.assertEqual(
            contract["productDefinition"]["soldProduct"],
            "证据包 / 线索包 / 机会包 / 情报包 / 销售推进结果",
        )
        self.assertIn("manual_url_picker_as_primary_flow", contract["productDefinition"]["mustNotBe"])
        self.assertIn("raw_json_dashboard_for_owner", contract["productDefinition"]["mustNotBe"])
        self.assertIn("offline_sample_chain_as_product_completion", contract["productDefinition"]["mustNotBe"])
        self.assertIn("真实公开来源候选自动进料", contract["productDefinition"]["completionStandard"])
        dimensions = {
            item["dimensionId"]: item
            for item in contract["acceptanceDimensions"]
        }
        for dimension_id in (
            "UA-01-product-definition-alignment",
            "UA-02-autonomous-market-to-opportunity-loop",
            "UA-03-stage-observability",
            "UA-04-opportunity-operability",
            "UA-05-evidence-package-verifiability",
            "UA-06-commercial-hook-boundary",
            "UA-07-governed-outreach-and-delivery",
            "UA-08-system-capability-exposure",
            "UA-09-data-persistence-and-operator-control",
            "UA-10-chinese-information-architecture",
            "UA-11-real-world-sellability",
        ):
            self.assertIn(dimension_id, dimensions)
            self.assertTrue(dimensions[dimension_id]["userQuestion"])
            self.assertTrue(dimensions[dimension_id]["passCriteria"])
            self.assertTrue(dimensions[dimension_id]["uiObligations"])
            self.assertTrue(dimensions[dimension_id]["failSignals"])
            self.assertTrue(dimensions[dimension_id]["sourceRefs"])
        self.assertIn(
            "证据包无法查看、无法下载或无法回到公开来源验证。",
            contract["nonNegotiableFailSignals"],
        )

    def test_operator_user_acceptance_gap_matrix_exposes_current_product_gaps(self) -> None:
        client = TestClient(create_app())

        response = client.request("GET", "/operator-console/user-acceptance-gap-matrix")

        self.assertEqual(response.status_code, 200)
        matrix = response.json()
        self.assertEqual(matrix["matrixId"], "AX9S-OPERATOR-USER-ACCEPTANCE-GAP-MATRIX")
        self.assertEqual(matrix["contractRef"], "contracts/ui/operator_user_acceptance_contract.json")
        self.assertEqual(matrix["status"], "ACTIVE")
        self.assertEqual(matrix["summary"]["totalDimensions"], 11)
        self.assertEqual(matrix["summary"]["passCount"], 8)
        self.assertEqual(matrix["summary"]["partialCount"], 3)
        self.assertEqual(matrix["summary"]["notExposedCount"], 0)
        self.assertEqual(matrix["summary"]["failCount"], 0)
        self.assertIn("真实公开列表页候选发现", matrix["summary"]["operatorConclusion"])
        dimensions = {
            item["dimensionId"]: item
            for item in matrix["dimensions"]
        }
        self.assertEqual(
            set(dimensions),
            {
                "UA-01-product-definition-alignment",
                "UA-02-autonomous-market-to-opportunity-loop",
                "UA-03-stage-observability",
                "UA-04-opportunity-operability",
                "UA-05-evidence-package-verifiability",
                "UA-06-commercial-hook-boundary",
                "UA-07-governed-outreach-and-delivery",
                "UA-08-system-capability-exposure",
                "UA-09-data-persistence-and-operator-control",
                "UA-10-chinese-information-architecture",
                "UA-11-real-world-sellability",
            },
        )
        for item in dimensions.values():
            self.assertIn(item["status"], {"PASS", "PARTIAL", "NOT_EXPOSED", "FAIL"})
            self.assertTrue(item["currentUiState"])
            self.assertTrue(item["evidenceRefs"])
            self.assertTrue(item["gaps"])
            self.assertTrue(item["nextActions"])
        self.assertEqual(
            dimensions["UA-05-evidence-package-verifiability"]["status"],
            "PASS",
        )
        self.assertIn(
            "来源网址",
            dimensions["UA-05-evidence-package-verifiability"]["currentUiState"],
        )
        self.assertEqual(
            dimensions["UA-11-real-world-sellability"]["status"],
            "PARTIAL",
        )
        self.assertEqual(
            dimensions["UA-01-product-definition-alignment"]["status"],
            "PASS",
        )
        self.assertEqual(
            dimensions["UA-03-stage-observability"]["status"],
            "PASS",
        )
        self.assertEqual(
            dimensions["UA-09-data-persistence-and-operator-control"]["status"],
            "PASS",
        )
        self.assertEqual(
            dimensions["UA-02-autonomous-market-to-opportunity-loop"]["status"],
            "PARTIAL",
        )
        self.assertIn(
            "真实列表页候选发现器",
            dimensions["UA-02-autonomous-market-to-opportunity-loop"]["gaps"][0],
        )
        self.assertEqual(
            dimensions["UA-06-commercial-hook-boundary"]["status"],
            "PASS",
        )
        self.assertEqual(
            dimensions["UA-07-governed-outreach-and-delivery"]["status"],
            "PARTIAL",
        )
        self.assertEqual(
            dimensions["UA-10-chinese-information-architecture"]["status"],
            "PASS",
        )
        self.assertIn(
            "真实公开来源候选发现器",
            [item["title"] for item in matrix["topPriorities"]],
        )

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
            "objectSummary",
            "navigateArtifactSection",
            "/customer-artifact-portal-readback/",
            "内部验收可用",
            "renderEvidencePackage",
            "邮件发送包预览",
            "下载内部证据包文件",
            "/customer-artifact-portal-download/",
            "公开来源",
            "来源网址",
            "数据模式",
            "客户交付判断",
            "来源网址精度",
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

        download_response = client.request(
            "GET",
            f"/customer-artifact-portal-download/{opportunity_id}",
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("application/json", download_response.headers["content-type"])
        self.assertIn(
            "attachment",
            download_response.headers.get("content-disposition", ""),
        )
        package = download_response.json()
        self.assertEqual(package["商机编号"], opportunity_id)
        for expected in (
            "说明",
            "未来交付方式",
            "数据真实性边界",
            "公开来源验证",
            "证据包",
            "拟邮件发送包",
            "证据项清单",
            "字段策略",
            "模拟下载审计",
            "读回摘要",
        ):
            self.assertIn(expected, package)
        self.assertFalse(package["拟邮件发送包"]["真实邮件已发送"])
        self.assertIn("客户可交付判断", package["数据真实性边界"])
        self.assertIsInstance(package["证据项清单"], list)
        self.assertNotIn("原始读回", package)
        self.assertNotIn("原始授权状态摘要", package["模拟下载审计"])

    def test_customer_artifact_portal_download_includes_search_source_context(self) -> None:
        client = TestClient(create_app())
        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_codes": ["CN-GD", "CN-JS"],
                "query": "公共建筑工程",
                "project_types": ["construction", "municipal"],
                "amount_min": 8000000,
                "amount_max": 30000000,
                "candidate_count": 3,
                "allow_offline_sample_candidates": True,
                "now": "2026-04-30T00:00:00+00:00",
            },
        )
        self.assertEqual(response.status_code, 200)
        opportunity_id = response.json()["opportunity_id"]

        readback_response = client.request(
            "GET",
            f"/customer-artifact-portal-readback/{opportunity_id}",
        )
        self.assertEqual(readback_response.status_code, 200)
        readback = readback_response.json()
        self.assertTrue(readback["source_verification"]["source_url"])
        self.assertIn("公开来源验证", readback["source_verification"]["verification_hint"])
        self.assertEqual(readback["data_boundary"]["数据模式"], "离线样本验证")
        self.assertTrue(readback["data_boundary"]["是否离线样本"])
        self.assertFalse(readback["data_boundary"]["是否真实市场发现"])
        self.assertIn("不可作为客户可售证据", readback["data_boundary"]["客户可交付判断"])

        download_response = client.request(
            "GET",
            f"/customer-artifact-portal-download/{opportunity_id}",
        )
        self.assertEqual(download_response.status_code, 200)
        package = download_response.json()
        self.assertEqual(
            package["公开来源验证"]["公开来源网址"],
            readback["source_verification"]["source_url"],
        )
        self.assertTrue(package["证据项清单"][0]["公开来源网址"])
        self.assertEqual(package["数据真实性边界"]["数据模式"], "离线样本验证")
        self.assertIn("不可作为客户可售证据", package["数据真实性边界"]["客户可交付判断"])
        self.assertNotIn("source_url", package["公开来源验证"])

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
