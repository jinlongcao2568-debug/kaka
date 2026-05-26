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

from api.main import create_app
from api.routes.operator_frontend import OPERATOR_FRONTEND_ROUTES
from helpers import load_fixture
from shared.pipeline import run_internal_chain
from storage import persist_stage_bundle
from storage_test_support import IsolatedStorageTestMixin


class TestOperatorFrontendPortal(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="operator-frontend-portal.json")

    def tearDown(self) -> None:
        self.tearDown_storage_test_env()

    def test_owner_console_frontend_is_mounted_and_exposes_operator_workflow(self) -> None:
        app = create_app()
        client = TestClient(app)

        self.assertEqual(
            set(app.state.operator_frontend_operations),
            {
                "renderOwnerOperatorConsole",
                "renderStage6ReviewLoopPage",
                "renderCustomerArtifactPortal",
                "renderCustomerArtifactPortalReadback",
                "renderCustomerArtifactPortalDownload",
                "renderOperatorUserAcceptanceContract",
                "renderOperatorUserAcceptanceGapMatrix",
                "renderRuntimeProjectionReadback",
            },
        )
        route_metadata = {
            route["operationId"]: route
            for route in OPERATOR_FRONTEND_ROUTES
        }
        self.assertTrue(route_metadata["renderOwnerOperatorConsole"]["productized_owner_workbench"])
        self.assertTrue(route_metadata["renderOwnerOperatorConsole"]["stage1_to_stage9_operations_board"])
        self.assertTrue(route_metadata["renderOwnerOperatorConsole"]["business_closure_dashboard"])
        self.assertTrue(route_metadata["renderStage6ReviewLoopPage"]["stage6_review_loop_frontend"])
        self.assertTrue(route_metadata["renderStage6ReviewLoopPage"]["owner_can_observe_without_raw_json"])
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
        self.assertTrue(route_metadata["renderRuntimeProjectionReadback"]["runtime_projection_frontend"])
        self.assertTrue(route_metadata["renderRuntimeProjectionReadback"]["repository_backed_readback"])
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
            "第六阶段批次复核 · 极简版",
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
            "第六阶段批次复核状态",
            "项目到了哪里、是否还能续跑、为什么停、下一步做什么",
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
            "/operator-console/stage6-review-loop-status",
            "/operator-console/runtime-projection",
            "/operator-console/stage6-review-loop",
            "Runtime Controller 投影",
            "统一 RunController 状态",
            "runtimeProjectionMetrics",
            "runtimeProjectionBoundary",
            "runtimeProjectionDetails",
            "controller 派生任务",
            "Controller 派生任务明细",
            "派生入口",
            "人工复核族",
            "Stage4 释放证据下一步",
            "Stage4 项目码召回",
            "需要授权浏览器",
            "项目经理变更命中",
            "解析阻断",
            "field_query_operator_next_action_counts",
            "release_chain_next_action_counts",
            "release_chain_manual_action_family_counts",
            "Stage1-6 批量稳定性",
            "附件快照缺口",
            "推荐动作",
            "缺口动作",
            "Stage5 规则门校准",
            "证据强度",
            "复核桶",
            "复核族",
            "建议动作",
            "Stage4/5 样本回放",
            "阻断账本",
            "阻断路由",
            "Runtime 审计回放",
            "审计回放只用于内部复核",
            "Stage8/9 受控开放边界",
            "自动退款受控测试/试点",
            "放行前置门禁",
            "生产未授权阻断动作",
            "可测试动作",
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
            "async function loadStage6ReviewLoopStatus()",
            "function renderRuntimeProjection(surface)",
            "async function loadRuntimeProjection()",
            "renderStage6ReviewLoopStatus",
            "function showView(view)",
            "id=\"sellabilityDecision\"",
            "id=\"sellabilityMetrics\"",
            "id=\"sellabilityBoundary\"",
            "id=\"sellabilityLaneList\"",
            "id=\"stageObjectFlow\"",
            "id=\"stageRunBoundary\"",
            "id=\"runtimeProjectionNarrative\"",
            "id=\"runtimeProjectionMetrics\"",
            "id=\"runtimeProjectionBoundary\"",
            "id=\"runtimeProjectionDetails\"",
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
            'Promise.all([loadReadiness(false), loadAutonomousWorkbench(), loadRegionAdapters(), loadAutonomousSearchRuns(), loadRealCandidateDiscoveryDiagnostics(), loadRealCandidateCatalog(), loadRealCandidateStage2Captures(), loadRealSourceProfiles(), loadRealSourceRuns(), loadUserAcceptanceContract(), loadAcceptanceGapMatrix(), loadRealWorldSellability(), loadStage6ReviewLoopStatus(), loadRuntimeProjection()])',
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
        self.assertIn('"/operator-console/stage6-review-loop-status"', html)
        self.assertIn('"/operator-console/runtime-projection"', html)
        self.assertIn('href="/operator-console/stage6-review-loop"', html)
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

    def test_runtime_projection_readback_uses_repository_and_keeps_safety_closed(self) -> None:
        from storage.repositories.runtime_state_repo import RuntimeStateRepository

        repository = RuntimeStateRepository()
        repository.save_controller_result(
            {
                "runtime_controller_mode": "STAGE1_6_RUNTIME_CYCLE",
                "run_state": {
                    "run_id": "RUN-FRONTEND-RUNTIME-PROJECTION",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "project_id": "PROJ-FRONTEND-RUNTIME-PROJECTION",
                    "current_stage_id": "stage6_fact_review",
                    "run_state": "REVIEW_REQUIRED",
                    "next_action": {
                        "action_type": "ENTRYPOINT",
                        "entrypoint_id": "stage6_review_cycle_runner",
                        "reason": "runtime_blocker_queue_ready",
                    },
                    "stage123_front_chain_summary": {
                        "stage123_front_chain_state": "READY",
                        "stage1_selected_candidate_count": 1,
                        "stage2_capture_record_count": 1,
                        "stage3_parse_record_count": 1,
                        "stage123_stability_summary": {
                            "stage2_attachment_snapshot_missing_count": 1,
                            "attachment_snapshot_readback_missing_count": 1,
                            "stage3_attachment_ocr_pending_count": 1,
                            "stage3_responsible_role_gap_count": 1,
                            "query_miss_is_not_clearance": True,
                        },
                    },
                    "stage1_6_readiness_summary": {
                        "stage1_6_batch_regression_ledger_state": "READY",
                        "stage1_6_pressure_coverage_state": "PARTIAL_SOURCE_COVERAGE",
                        "stage1_6_pressure_candidate_count": 3,
                        "stage1_6_pressure_closed_loop_results_count": 2,
                        "stage1_6_pressure_stage5_calibration_sample_count": 1,
                        "stage1_6_readiness_record_count": 3,
                        "stage1_6_review_or_blocked_count": 2,
                        "stage1_3_stability_summary": {
                            "stage2_attachment_snapshot_missing_count": 2,
                            "attachment_snapshot_readback_missing_count": 1,
                            "stage3_attachment_ocr_pending_count": 2,
                            "stage3_responsible_role_gap_count": 2,
                            "stage3_parse_blocker_count": 1,
                        },
                        "stage1_6_next_action_counts": {
                            "run_stage4_release_evidence_bridge_builder": 1,
                        },
                        "stage1_6_gap_next_action_counts": {
                            "review_stage3_parse_fields": 1,
                        },
                        "stage4_release_adapter_bridge_project_code_recall_summary": {
                            "project_code_recall_state": "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
                            "bridge_task_count": 3,
                            "with_gdcic_project_code_variant_task_count": 2,
                            "missing_gdcic_project_code_variant_task_count": 1,
                            "trade_project_code_only_task_count": 1,
                            "query_miss_is_not_clearance": True,
                        },
                    },
                    "stage4_release_field_query_summary": {
                        "release_field_query_project_count": 1,
                        "release_field_query_authorization_state_counts": {
                            "LOGIN_OR_SSO_REQUIRED": 1,
                        },
                        "release_field_query_authorized_session_input_state_counts": {
                            "NO_AUTHORIZED_SESSION_INPUT": 1,
                        },
                        "release_field_query_operator_next_action_counts": {
                            "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1,
                        },
                        "release_field_query_project_manager_change_ready_count": 1,
                        "release_field_query_project_manager_change_interpretation_counts": {
                            "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1,
                        },
                        "query_miss_is_not_clearance": True,
                    },
                    "stage4_release_chain_bootstrap_summary": {
                        "stage4_release_chain_bootstrap_source_kind": "STAGE16_P13B_CONTINUATION_JSON",
                        "stage4_release_chain_input_refs": {
                            "source_stage16_p13b_continuation_json": "memory://stage16/frontend-runtime-projection",
                            "source_gdcic_browser_readback_json": "memory://gdcic/frontend-runtime-readback",
                        },
                        "stage4_gdcic_authorized_readback_summary": {
                            "source_gdcic_browser_readback_json": "memory://gdcic/frontend-runtime-readback",
                            "authorized_session_input_state": "INJECTED_BROWSER_RUNNER",
                            "gdcic_authorized_session_overall_state": "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
                            "gdcic_browser_readback_ready_count": 1,
                            "project_manager_change_ready_count": 1,
                            "project_manager_change_interpretation_counts": {
                                "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1,
                            },
                            "query_miss_is_not_clearance": True,
                            "customer_visible_allowed": False,
                            "no_legal_conclusion": True,
                        },
                        "stage4_release_chain_project_count": 1,
                        "stage4_release_chain_runtime_blocker_ledger_count": 1,
                        "stage4_release_chain_runtime_blocker_state_counts": {
                            "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1,
                        },
                        "stage4_release_chain_next_action_counts": {
                            "rerun_stage6_review_cycle_after_reopen_input_is_recorded": 1,
                        },
                        "stage4_release_chain_manual_action_family_counts": {
                            "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW": 1,
                        },
                        "query_miss_is_not_clearance": True,
                    },
                    "stage6_cycle_summary": {
                        "stage5_calibration_sample_count": 1,
                        "stage5_calibration_truth_label_required_count": 1,
                        "stage5_abcd_calibration_counts": {
                            "B_PUBLIC_READBACK_REVIEW_REQUIRED": 1,
                        },
                        "stage5_calibration_review_bucket_counts": {
                            "POTENTIAL_FALSE_POSITIVE_REVIEW": 1,
                        },
                        "stage5_calibration_evidence_strength_counts": {
                            "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED": 1,
                        },
                        "stage5_calibration_review_family_counts": {
                            "manual_public_readback_review": 1,
                        },
                        "stage5_calibration_suggested_action_counts": {
                            "review_truth_label_before_rule_relaxation_or_tightening": 1,
                        },
                    },
                    "stage45_replay_summary": {
                        "stage4_probe_replay_count": 2,
                        "stage4_blocker_ledger_count": 2,
                        "operator_action_count": 2,
                        "runtime_blocker_subqueue_route_counts": {
                            "browser_worker": 1,
                            "fallback_source": 1,
                        },
                        "stage5_executed_rule_codes": ["CREDIT-001"],
                        "stage5_skipped_rule_codes": ["REL-001"],
                        "stage5_missing_readback_count": 1,
                        "stage5_calibration_sample_count": 2,
                        "stage5_calibration_truth_label_required_count": 1,
                        "stage5_abcd_calibration_counts": {
                            "A_OFFICIAL_PUBLIC_READBACK_PASS": 1,
                            "C_MISSING_RELEVANT_PUBLIC_READBACK": 1,
                        },
                        "stage5_calibration_evidence_strength_counts": {
                            "OFFICIAL_PUBLIC_READBACK_PASS": 1,
                            "PUBLIC_READBACK_MISSING_OR_INSUFFICIENT": 1,
                        },
                        "query_miss_is_not_clearance": True,
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                    "runtime_blocker_controller_summary": {
                        "next_subqueue_input_state": "READY",
                        "controller_dispatch_task_count": 2,
                        "dispatch_ready_count": 1,
                        "dispatch_runner_task_count": 1,
                        "dispatch_runner_followup_task_count": 1,
                        "controller_derived_dispatch_task_count": 1,
                        "controller_derived_dispatch_ready_count": 1,
                        "controller_derived_dispatch_entrypoint_counts": {
                            "guangdong_local_field_query_probe": 1,
                        },
                        "controller_derived_dispatch_review_family_counts": {
                            "manual_public_readback_review": 1,
                            "stage1_3_attachment_ocr_repair": 1,
                        },
                        "stage1_3_repair_task_count": 1,
                        "stage1_3_repair_metric_counts": {
                            "stage3_attachment_ocr_pending_count": 2,
                        },
                        "stage1_3_repair_review_family_counts": {
                            "stage1_3_attachment_ocr_repair": 1,
                        },
                    },
                    "controlled_boundary": {
                        "stage8_outreach_boundary_state": "CONTROLLED_OPENING_PREREQUISITES_ONLY",
                        "stage9_payment_delivery_refund_boundary_state": "CONTROLLED_OPENING_PREREQUISITES_ONLY",
                        "automatic_refund_policy_state": "CONTROLLED_TEST_AND_PILOT_REQUIRED",
                        "required_before_live_execution": [
                            "release_checklist_passed",
                            "approval_chain_passed",
                            "audit_chain_ready",
                            "operator_action_confirmed",
                        ],
                        "blocked_action_families": [
                            "real_outreach",
                            "real_payment",
                            "real_delivery",
                            "real_refund",
                            "automatic_refund",
                        ],
                        "operator_next_action": "complete_release_approval_audit_and_operator_action_before_live_execution",
                        "external_customer_action_enabled": False,
                        "real_payment_enabled": False,
                        "real_delivery_enabled": False,
                        "automatic_refund_enabled": False,
                        "customer_visible_allowed": False,
                    },
                    "safety": {
                        "external_customer_action_enabled": False,
                        "real_payment_enabled": False,
                        "real_delivery_enabled": False,
                        "automatic_refund_enabled": False,
                    },
                },
                "audit_ledger": {
                    "events": [
                        {
                            "event_id": "AUD-FRONTEND-RUNTIME-PROJECTION-1",
                            "event_type": "RUN_STARTED",
                            "run_id": "RUN-FRONTEND-RUNTIME-PROJECTION",
                            "stage_id": "stage1_tasking",
                        }
                    ]
                },
                "dispatch_queue": {
                    "records": [
                        {
                            "dispatch_task_id": "RUN-FRONTEND-RUNTIME-PROJECTION:guangdong-local-field-query",
                            "action_type": "ENTRYPOINT",
                            "entrypoint_id": "guangdong_local_field_query_probe",
                            "dispatch_state": "READY_FOR_INTERNAL_DISPATCH",
                            "reason": "stage4_release_field_query_authorization_gap",
                            "external_customer_action_enabled": False,
                        },
                        {
                            "dispatch_task_id": "RUN-FRONTEND-RUNTIME-PROJECTION:stage5-calibration-truth-label-review",
                            "action_type": "REVIEW",
                            "review_family": "stage1_3_attachment_ocr_repair",
                            "review_state": "WAITING_FOR_STAGE3_ATTACHMENT_OCR_REPAIR",
                            "dispatch_state": "WAITING_FOR_REVIEW",
                            "reason": "stage3_attachment_ocr_pending_count",
                            "source_metric": "stage3_attachment_ocr_pending_count",
                            "metric_count": 2,
                            "operator_next_action": "对待处理附件执行 OCR/结构化回读，并回灌解析字段与审计链。",
                            "external_customer_action_enabled": False,
                        },
                    ]
                },
                "customer_visible_allowed": False,
            }
        )
        repository.save_worker_result(
            {
                "worker_id": "stage1_3_repair_worker",
                "worker_mode": "INTERNAL_REPAIR_PLAN_ONLY",
                "repair_worker_state": "REPAIR_PLAN_READY",
                "created_at": "2026-05-24T00:00:01+08:00",
                "repair_task_count": 1,
                "repair_metric_counts": {"stage3_attachment_ocr_pending_count": 2},
                "repair_worker_family_counts": {"stage3_attachment_ocr_repair_worker": 1},
                "repair_review_family_counts": {"stage1_3_attachment_ocr_repair": 1},
                "repair_tasks": [
                    {
                        "repair_task_id": "REPAIR-RUN-FRONTEND-RUNTIME-PROJECTION:stage3-ocr",
                        "source_dispatch_task_id": "RUN-FRONTEND-RUNTIME-PROJECTION:stage5-calibration-truth-label-review",
                        "review_family": "stage1_3_attachment_ocr_repair",
                        "source_metric": "stage3_attachment_ocr_pending_count",
                        "metric_count": 2,
                        "worker_family": "stage3_attachment_ocr_repair_worker",
                        "execution_state": "PLAN_READY_INTERNAL_REPAIR_NOT_EXECUTED",
                        "external_customer_action_enabled": False,
                        "customer_visible_allowed": False,
                    }
                ],
                "live_execution_enabled": False,
                "customer_visible_allowed": False,
                "external_customer_action_enabled": False,
                "real_payment_enabled": False,
                "real_delivery_enabled": False,
                "automatic_refund_enabled": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
        repository.save_worker_result(
            {
                "worker_id": "gdcic_browser_authorized_readback_worker",
                "worker_mode": "LIVE_BROWSER_EXECUTION_ATTEMPTED",
                "worker_result_state": "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
                "repair_worker_state": "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
                "created_at": "2026-05-24T00:00:02+08:00",
                "gdcic_browser_readback_task_count": 2,
                "gdcic_browser_readback_record_count": 1,
                "gdcic_browser_readback_ready_count": 1,
                "project_manager_change_ready_count": 1,
                "project_manager_change_interpretation_counts": {
                    "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1,
                },
                "stage5_calibration_sample_count": 1,
                "stage5_calibration_truth_label_required_count": 1,
                "stage5_abcd_calibration_counts": {
                    "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
                },
                "stage5_calibration_review_family_counts": {
                    "gdcic_project_manager_change_reverse_explanation_review": 1,
                },
                "stage5_calibration_evidence_strength_counts": {
                    "OFFICIAL_REVERSE_EXPLANATION_REVIEW_REQUIRED": 1,
                },
                "stage5_calibration_suggested_action_counts": {
                    "manual_review_gdcic_project_manager_change_readback_before_stage5_rule_change": 1,
                },
                "authorized_session_input_state": "INJECTED_BROWSER_RUNNER",
                "live_execution_enabled": True,
                "customer_visible_allowed": False,
                "external_customer_action_enabled": False,
                "real_payment_enabled": False,
                "real_delivery_enabled": False,
                "automatic_refund_enabled": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )

        client = TestClient(create_app())
        response = client.request("GET", "/operator-console/runtime-projection")

        self.assertEqual(response.status_code, 200)
        surface = response.json()
        self.assertEqual(surface["surface_id"], "runtime_controller_operator_projection")
        self.assertTrue(surface["runtime_projection_frontend"])
        self.assertEqual(surface["latest_projection"]["run_id"], "RUN-FRONTEND-RUNTIME-PROJECTION")
        self.assertEqual(surface["projection_object_refs"]["run_id"], "RUN-FRONTEND-RUNTIME-PROJECTION")
        self.assertEqual(surface["projection_object_refs"]["entrypoint_id"], "stage6_review_cycle_runner")
        self.assertEqual(surface["runtime_audit_replay"]["replay_state"], "REPLAY_READY")
        self.assertEqual(surface["runtime_audit_replay"]["run_id"], "RUN-FRONTEND-RUNTIME-PROJECTION")
        self.assertEqual(surface["runtime_audit_replay"]["event_count"], 1)
        self.assertEqual(surface["runtime_audit_replay"]["event_type_counts"]["RUN_STARTED"], 1)
        self.assertFalse(surface["runtime_audit_replay"]["external_customer_action_enabled"])
        self.assertFalse(surface["runtime_audit_replay"]["automatic_refund_enabled"])
        self.assertTrue(surface["runtime_audit_replay"]["query_miss_is_not_clearance"])
        self.assertEqual(surface["projection_trace_refs"]["stage4_release_chain_project_count"], "1")
        self.assertIn(
            "memory://stage16/frontend-runtime-projection",
            surface["projection_trace_refs"]["stage4_release_chain_input_refs_json"],
        )
        self.assertEqual(surface["projection_history"][0]["run_id"], "RUN-FRONTEND-RUNTIME-PROJECTION")
        self.assertEqual(surface["projection_history"][0]["trace_refs"]["stage5_calibration_sample_count"], "2")
        self.assertIn(
            "B_PUBLIC_READBACK_REVIEW_REQUIRED",
            surface["projection_history"][0]["trace_refs"]["stage5_abcd_calibration_counts_json"],
        )
        self.assertIn(
            "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            surface["projection_history"][0]["trace_refs"]["stage5_abcd_calibration_counts_json"],
        )
        self.assertEqual(
            surface["projection_history"][0]["trace_refs"]["stage5_calibration_merged_source_count"],
            "2",
        )
        self.assertEqual(surface["latest_projection"]["stage123_front_chain_summary"]["stage123_front_chain_state"], "READY")
        self.assertEqual(surface["stage123_stability"]["stage2_attachment_snapshot_missing_count"], 1)
        self.assertEqual(surface["stage123_stability"]["stage3_attachment_ocr_pending_count"], 1)
        self.assertEqual(surface["stage123_stability"]["stage3_responsible_role_gap_count"], 1)
        self.assertEqual(
            surface["projection_trace_refs"]["stage123_attachment_snapshot_missing_count"],
            "1",
        )
        self.assertEqual(surface["stage1_6_readiness"]["stage1_6_review_or_blocked_count"], 2)
        self.assertEqual(surface["stage1_6_readiness"]["stage1_6_pressure_coverage_state"], "PARTIAL_SOURCE_COVERAGE")
        self.assertEqual(surface["projection_trace_refs"]["stage1_6_pressure_candidate_count"], "3")
        self.assertEqual(surface["projection_trace_refs"]["stage1_6_pressure_closed_loop_results_count"], "2")
        self.assertEqual(surface["projection_trace_refs"]["stage1_6_pressure_stage5_calibration_sample_count"], "1")
        self.assertEqual(surface["stage1_6_stability"]["stage2_attachment_snapshot_missing_count"], 2)
        self.assertEqual(surface["stage1_6_stability"]["attachment_snapshot_readback_missing_count"], 1)
        self.assertEqual(surface["stage1_6_stability"]["stage3_attachment_ocr_pending_count"], 2)
        self.assertEqual(surface["stage1_6_stability"]["stage3_parse_blocker_count"], 1)
        self.assertEqual(
            surface["stage1_6_readiness"]["stage1_6_next_action_counts"],
            {"run_stage4_release_evidence_bridge_builder": 1},
        )
        self.assertEqual(
            surface["stage1_6_readiness"]["stage1_6_gap_next_action_counts"],
            {"review_stage3_parse_fields": 1},
        )
        self.assertEqual(surface["projection_trace_refs"]["stage1_6_attachment_snapshot_missing_count"], "2")
        self.assertEqual(surface["projection_trace_refs"]["stage1_6_attachment_ocr_pending_count"], "2")
        self.assertIn(
            "run_stage4_release_evidence_bridge_builder",
            surface["projection_trace_refs"]["stage1_6_next_action_counts_json"],
        )
        self.assertIn(
            "review_stage3_parse_fields",
            surface["projection_trace_refs"]["stage1_6_gap_next_action_counts_json"],
        )
        self.assertEqual(
            surface["stage4_project_code_recall"]["project_code_recall_state"],
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
        )
        self.assertEqual(
            surface["stage4_project_code_recall"]["with_gdcic_project_code_variant_task_count"],
            2,
        )
        self.assertEqual(
            surface["stage4_project_code_recall"]["missing_gdcic_project_code_variant_task_count"],
            1,
        )
        self.assertEqual(
            surface["stage4_project_code_recall"]["trade_project_code_only_task_count"],
            1,
        )
        self.assertFalse(surface["stage4_project_code_recall"]["customer_visible_allowed"])
        self.assertTrue(surface["stage4_project_code_recall"]["no_legal_conclusion"])
        self.assertTrue(surface["stage4_project_code_recall"]["query_miss_is_not_clearance"])
        self.assertEqual(
            surface["projection_trace_refs"]["stage4_release_adapter_bridge_project_code_recall_state"],
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
        )
        self.assertIn(
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
            surface["projection_trace_refs"][
                "stage4_release_adapter_bridge_project_code_recall_summary_json"
            ],
        )
        self.assertEqual(surface["stage4_release_field_query"]["release_field_query_project_count"], 1)
        self.assertEqual(
            surface["stage4_release_field_query"]["release_field_query_authorization_state_counts"],
            {"LOGIN_OR_SSO_REQUIRED": 1},
        )
        self.assertEqual(
            surface["stage4_release_field_query"]["release_field_query_project_manager_change_ready_count"],
            1,
        )
        self.assertEqual(
            surface["stage4_release_field_query"][
                "release_field_query_project_manager_change_interpretation_counts"
            ],
            {"ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1},
        )
        self.assertIn(
            "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED",
            surface["projection_trace_refs"][
                "stage4_release_field_query_project_manager_change_interpretation_counts_json"
            ],
        )
        self.assertTrue(surface["stage4_next_actions"]["requires_authorized_browser_session"])
        self.assertEqual(
            surface["stage4_next_actions"]["field_query_operator_next_action_counts"],
            {"provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1},
        )
        self.assertEqual(
            surface["stage4_next_actions"]["release_chain_next_action_counts"],
            {"rerun_stage6_review_cycle_after_reopen_input_is_recorded": 1},
        )
        self.assertEqual(
            surface["stage4_next_actions"]["release_chain_manual_action_family_counts"],
            {"P13B_RELEASE_EVIDENCE_TARGETED_REVIEW": 1},
        )
        self.assertEqual(
            surface["stage4_next_actions"]["release_chain_runtime_blocker_state_counts"],
            {"TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1},
        )
        self.assertTrue(surface["stage4_next_actions"]["query_miss_is_not_clearance"])
        self.assertEqual(
            surface["stage4_release_chain_bootstrap"]["stage4_release_chain_bootstrap_source_kind"],
            "STAGE16_P13B_CONTINUATION_JSON",
        )
        self.assertEqual(surface["stage4_release_chain_bootstrap"]["stage4_release_chain_project_count"], 1)
        self.assertEqual(
            surface["stage4_gdcic_authorized_readback"]["source_gdcic_browser_readback_json"],
            "memory://gdcic/frontend-runtime-readback",
        )
        self.assertEqual(surface["stage4_gdcic_authorized_readback"]["gdcic_browser_readback_ready_count"], 1)
        self.assertEqual(surface["stage4_gdcic_authorized_readback"]["project_manager_change_ready_count"], 1)
        self.assertEqual(
            surface["stage4_gdcic_authorized_readback_worker_result"]["worker_id"],
            "gdcic_browser_authorized_readback_worker",
        )
        self.assertEqual(
            surface["stage4_gdcic_authorized_readback_worker_result"]["worker_result_state"],
            "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
        )
        self.assertEqual(
            surface["stage4_gdcic_authorized_readback_worker_result"]["project_manager_change_ready_count"],
            1,
        )
        self.assertEqual(
            surface["stage4_gdcic_authorized_readback_worker_result"]["stage5_calibration_sample_count"],
            1,
        )
        self.assertEqual(
            surface["stage4_gdcic_authorized_readback_worker_result"]["stage5_abcd_calibration_counts"],
            {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
        )
        self.assertFalse(
            surface["stage4_gdcic_authorized_readback_worker_result"]["external_customer_action_enabled"]
        )
        self.assertEqual(
            surface["stage4_gdcic_authorized_readback"]["project_manager_change_interpretation_counts"],
            {"ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1},
        )
        self.assertIn(
            "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED",
            surface["projection_trace_refs"][
                "stage4_gdcic_authorized_readback_project_manager_change_interpretation_counts_json"
            ],
        )
        self.assertFalse(surface["stage4_gdcic_authorized_readback"]["customer_visible_allowed"])
        self.assertEqual(surface["stage5_calibration"]["stage5_calibration_sample_count"], 2)
        self.assertEqual(surface["stage5_calibration"]["stage5_calibration_truth_label_required_count"], 2)
        self.assertEqual(
            surface["stage5_calibration"]["stage5_abcd_calibration_counts"],
            {
                "B_PUBLIC_READBACK_REVIEW_REQUIRED": 1,
                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
            },
        )
        self.assertEqual(
            surface["stage5_calibration"]["stage5_calibration_evidence_strength_counts"],
            {
                "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED": 1,
                "OFFICIAL_REVERSE_EXPLANATION_REVIEW_REQUIRED": 1,
            },
        )
        self.assertEqual(
            surface["stage5_calibration"]["stage5_calibration_review_bucket_counts"],
            {
                "POTENTIAL_FALSE_POSITIVE_REVIEW": 1,
                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
            },
        )
        self.assertEqual(
            surface["stage5_calibration"]["stage5_calibration_review_family_counts"],
            {
                "manual_public_readback_review": 1,
                "gdcic_project_manager_change_reverse_explanation_review": 1,
            },
        )
        self.assertEqual(
            surface["stage5_calibration"]["stage5_calibration_suggested_action_counts"],
            {
                "review_truth_label_before_rule_relaxation_or_tightening": 1,
                "manual_review_gdcic_project_manager_change_readback_before_stage5_rule_change": 1,
            },
        )
        self.assertEqual(surface["stage5_calibration"]["merged_source_count"], 2)
        self.assertEqual(
            surface["stage5_calibration_source_summaries"]["gdcic_authorized_readback_worker"][
                "stage5_abcd_calibration_counts"
            ],
            {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
        )
        self.assertIn(
            "POTENTIAL_FALSE_POSITIVE_REVIEW",
            surface["projection_trace_refs"]["stage5_calibration_review_bucket_counts_json"],
        )
        self.assertIn(
            "review_truth_label_before_rule_relaxation_or_tightening",
            surface["projection_trace_refs"]["stage5_calibration_suggested_action_counts_json"],
        )
        self.assertEqual(surface["stage45_replay"]["stage4_probe_replay_count"], 2)
        self.assertEqual(surface["stage45_replay"]["stage4_blocker_ledger_count"], 2)
        self.assertEqual(
            surface["stage45_replay"]["runtime_blocker_subqueue_route_counts"],
            {"browser_worker": 1, "fallback_source": 1},
        )
        self.assertEqual(surface["stage45_replay"]["stage5_missing_readback_count"], 1)
        self.assertEqual(surface["stage45_replay"]["stage5_calibration_sample_count"], 2)
        self.assertEqual(surface["stage45_replay"]["stage5_calibration_truth_label_required_count"], 1)
        self.assertEqual(
            surface["stage45_replay"]["stage5_abcd_calibration_counts"],
            {
                "A_OFFICIAL_PUBLIC_READBACK_PASS": 1,
                "C_MISSING_RELEVANT_PUBLIC_READBACK": 1,
            },
        )
        self.assertIn(
            "C_MISSING_RELEVANT_PUBLIC_READBACK",
            surface["projection_trace_refs"]["stage45_replay_stage5_abcd_calibration_counts_json"],
        )
        self.assertFalse(surface["stage45_replay"]["customer_visible_allowed"])
        self.assertTrue(surface["stage45_replay"]["query_miss_is_not_clearance"])
        self.assertEqual(surface["runtime_blocker_queue"]["next_subqueue_input_state"], "READY")
        self.assertEqual(surface["runtime_blocker_queue"]["controller_derived_dispatch_task_count"], 1)
        self.assertEqual(surface["controller_dispatch_queue"]["summary"]["dispatch_record_count"], 2)
        self.assertEqual(
            surface["controller_dispatch_queue"]["records"][0]["entrypoint_id"],
            "guangdong_local_field_query_probe",
        )
        self.assertEqual(
            surface["controller_dispatch_queue"]["records"][1]["review_family"],
            "stage1_3_attachment_ocr_repair",
        )
        self.assertEqual(
            surface["controller_dispatch_queue"]["records"][1]["source_metric"],
            "stage3_attachment_ocr_pending_count",
        )
        self.assertEqual(surface["controller_dispatch_queue"]["records"][1]["metric_count"], 2)
        self.assertFalse(surface["controller_dispatch_queue"]["records"][0]["external_customer_action_enabled"])
        self.assertFalse(surface["controller_dispatch_queue"]["external_customer_action_enabled"])
        self.assertEqual(surface["controller_dispatch_queue"]["summary"]["stage1_3_repair_task_count"], 1)
        self.assertEqual(
            surface["controller_dispatch_queue"]["summary"]["stage1_3_repair_metric_counts"],
            {"stage3_attachment_ocr_pending_count": 2},
        )
        self.assertEqual(surface["stage1_3_repair_tasks"]["stage1_3_repair_task_count"], 1)
        self.assertEqual(
            surface["stage1_3_repair_tasks"]["stage1_3_repair_metric_counts"],
            {"stage3_attachment_ocr_pending_count": 2},
        )
        self.assertEqual(surface["stage1_3_repair_worker_result"]["worker_id"], "stage1_3_repair_worker")
        self.assertEqual(surface["stage1_3_repair_worker_result"]["repair_worker_state"], "REPAIR_PLAN_READY")
        self.assertEqual(surface["stage1_3_repair_worker_result"]["repair_task_count"], 1)
        self.assertEqual(
            surface["stage1_3_repair_worker_result"]["repair_worker_family_counts"],
            {"stage3_attachment_ocr_repair_worker": 1},
        )
        self.assertFalse(surface["stage1_3_repair_worker_result"]["external_customer_action_enabled"])
        self.assertFalse(surface["stage1_3_repair_worker_result"]["live_execution_enabled"])
        self.assertEqual(
            surface["runtime_blocker_queue"]["controller_derived_dispatch_entrypoint_counts"],
            {"guangdong_local_field_query_probe": 1},
        )
        self.assertEqual(
            surface["runtime_blocker_queue"]["controller_derived_dispatch_review_family_counts"],
            {"manual_public_readback_review": 1, "stage1_3_attachment_ocr_repair": 1},
        )
        self.assertIn(
            "guangdong_local_field_query_probe",
            surface["projection_trace_refs"]["runtime_controller_derived_dispatch_entrypoint_counts_json"],
        )
        self.assertIn(
            "manual_public_readback_review",
            surface["projection_trace_refs"]["runtime_controller_derived_dispatch_review_family_counts_json"],
        )
        self.assertIn(
            "stage1_3_attachment_ocr_repair",
            surface["projection_trace_refs"]["runtime_controller_derived_dispatch_review_family_counts_json"],
        )
        self.assertEqual(
            surface["controlled_boundary"]["stage8_outreach_boundary_state"],
            "CONTROLLED_OPENING_PREREQUISITES_ONLY",
        )
        self.assertEqual(surface["controlled_boundary"]["automatic_refund_policy_state"], "CONTROLLED_TEST_AND_PILOT_REQUIRED")
        self.assertEqual(
            surface["controlled_boundary"]["required_before_live_execution"],
            [
                "release_checklist_passed",
                "approval_chain_passed",
                "audit_chain_ready",
                "operator_action_confirmed",
            ],
        )
        self.assertIn("real_payment", surface["controlled_boundary"]["blocked_action_families"])
        self.assertIn(
            "approval_chain_passed",
            surface["projection_trace_refs"]["controlled_boundary_required_before_live_execution_json"],
        )
        self.assertEqual(
            surface["projection_trace_refs"]["controlled_boundary_required_before_live_execution_count"],
            "4",
        )
        self.assertEqual(surface["worker_followup"]["dispatch_runner_followup_task_count"], 1)
        self.assertEqual(surface["operator_action"]["next_action_entrypoint_id"], "stage6_review_cycle_runner")
        self.assertFalse(surface["customer_visible_allowed"])
        self.assertFalse(surface["external_customer_action_enabled"])
        self.assertFalse(surface["real_payment_enabled"])
        self.assertFalse(surface["real_delivery_enabled"])
        self.assertFalse(surface["automatic_refund_enabled"])

    def test_stage6_review_loop_page_is_plain_owner_readback(self) -> None:
        client = TestClient(create_app())

        response = client.request("GET", "/operator-console/stage6-review-loop")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        html = response.text
        for expected in (
            "第六阶段批次复核",
            "现在这批项目到底到哪了",
            "一句话结论",
            "选择历史批次",
            "项目逐个看",
            "我应该怎么用这个页面",
            "不能继续自动空转",
            "默认策略",
            "默认优先显示最新多项目批次",
            "当前阶段",
            "证据等级",
            "为什么停/卡在哪里",
            "重新开启条件",
            "如果最新只剩一个终态项目，也会保留在这里供你切换查看",
            "batchSelector",
            "renderBatchSelector",
            "loadBatch",
            "第七阶段只做内部复核",
            "/operator-console/stage6-review-loop-status",
            "fetch(\"/operator-console/stage6-review-loop-status\")",
            "不会写排除性结论",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("JSON.stringify(value, null, 2)", html)

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
        self.assertTrue(contract["acceptanceAuthority"]["l0AndDSeriesAreAuthoritative"])
        self.assertIn("docs/AX9S_产品主图与验收总则.md", contract["ownerDocs"])
        self.assertIn("docs/AX9S_Stage1-9_执行矩阵与子漏斗.md", contract["ownerDocs"])
        self.assertIn("docs/AX9S_Stage4-5_核验双闸门SOP.md", contract["ownerDocs"])
        self.assertIn("docs/D2_正式对象契约与字段字典.md", contract["ownerDocs"])
        self.assertIn("docs/D3_正式规则码总表与判定说明书.md", contract["ownerDocs"])
        self.assertIn("docs/D4_OpenAPI接口契约.md", contract["ownerDocs"])
        self.assertIn("docs/D6_字段策略字典与客户交付字段规范.md", contract["ownerDocs"])
        self.assertIn("docs/D7_对象级交付矩阵与外发治理规范.md", contract["ownerDocs"])
        self.assertIn("docs/D14_AI模型治理规范.md", contract["ownerDocs"])
        hard_gates = {item["gateId"]: item for item in contract["authoritativeHardGates"]}
        self.assertIn("AUTH-06-public-verification-before-rules", hard_gates)
        self.assertIn("AUTH-07-dual-gate-required", hard_gates)
        self.assertIn("AUTH-08-project-fact-and-saleability", hard_gates)
        real_states = {item["state"]: item for item in contract["realWorldAcceptanceStates"]}
        self.assertIn("REAL_PUBLIC_REVIEW_REQUIRED", real_states)
        self.assertIn("REAL_PUBLIC_RESTRICTED_SALEABLE", real_states)
        self.assertIn("CUSTOMER_DELIVERY_READY", real_states)
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
        self.assertEqual(matrix["summary"]["passCount"], 3)
        self.assertEqual(matrix["summary"]["partialCount"], 8)
        self.assertEqual(matrix["summary"]["notExposedCount"], 0)
        self.assertEqual(matrix["summary"]["failCount"], 0)
        self.assertIn("L0/D2-D14", matrix["summary"]["operatorConclusion"])
        self.assertIn("formal real_public readback", matrix["summary"]["operatorConclusion"])
        self.assertTrue(matrix["authorityFindings"])
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
            "PARTIAL",
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
            "PARTIAL",
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
            "PARTIAL",
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
            "真实候选 Stage1-6 formal 回链",
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
        self.assertEqual(download_response.status_code, 403)
        blocked = download_response.json()["detail"]
        self.assertEqual(
            blocked["download_state"],
            "BLOCKED_INTERNAL_PREVIEW_DOWNLOAD_REQUIRES_OPERATOR_AUTH_APPROVAL_AUDIT_AND_MASKING",
        )
        self.assertFalse(blocked["customer_download_enabled"])
        self.assertIn("operator_authenticated", blocked["blocked_reasons"])

        download_response = client.request(
            "GET",
            f"/customer-artifact-portal-download/{opportunity_id}",
            params={
                "operator_authenticated": "true",
                "internal_preview_download_authorized": "true",
                "approval_audit_confirmed": "true",
                "field_allowlist_masking_confirmed": "true",
            },
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
        self.assertEqual(download_response.status_code, 403)
        self.assertFalse(download_response.json()["detail"]["customer_download_enabled"])

        download_response = client.request(
            "GET",
            f"/customer-artifact-portal-download/{opportunity_id}",
            params={
                "operator_authenticated": "true",
                "internal_preview_download_authorized": "true",
                "approval_audit_confirmed": "true",
                "field_allowlist_masking_confirmed": "true",
            },
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
