from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from api.deps import get_settings
from api.main import create_app
from api.routes.stage1 import register_stage1_routes
from api.routes.stage2 import register_stage2_routes
from api.routes.stage3 import register_stage3_routes
from api.routes.stage4 import register_stage4_routes
from api.routes.stage5 import register_stage5_routes
from api.routes.stage6 import register_stage6_routes
from helpers import load_fixture
from shared.pipeline import run_internal_chain
from storage import persist_stage_bundle, reset_default_storage


class TestApiTransportBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        reset_default_storage()

    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_get_settings_returns_formal_internal_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp_dir}, clear=False):
                for key in (
                    "KAKA_STORAGE_BACKEND",
                    "KAKA_STORAGE_PATH",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                settings = get_settings()
                resolved_storage_path = settings.resolved_storage_path()

        self.assertEqual(settings.environment, "INTERNAL_ONLY")
        self.assertEqual(Path(settings.repo_root).resolve(), ROOT.resolve())
        self.assertEqual(settings.storage_backend, "json-file")
        self.assertIsNone(settings.storage_path_optional)
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")
        self.assertEqual(
            resolved_storage_path,
            Path(tmp_dir) / "kaka" / "internal_operator_loop_store.json",
        )

    def test_get_settings_consumes_storage_backend_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "postgres",
                    "LOCALAPPDATA": tmp_dir,
                },
                clear=False,
            ):
                for key in ("KAKA_STORAGE_PATH", "KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                settings = get_settings()

        self.assertEqual(settings.storage_backend, "postgres")
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")

    def test_create_app_mounts_storage_bootstrap_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "storage" / "custom-store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "json-file",
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "KAKA_STORAGE_SCOPE": "process",
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                os.environ.pop("KAKA_STORAGE_TEST_ISOLATION", None)
                get_settings.cache_clear()
                app = create_app()

        self.assertEqual(app.state.settings.storage_backend, "json-file")
        self.assertEqual(app.state.settings.storage_path_optional, str(explicit_path))
        self.assertEqual(app.state.settings.storage_scope, "process")
        self.assertEqual(app.state.settings.storage_runtime_mode, "explicit-path")
        self.assertEqual(app.state.storage_session.storage_backend, "json-file")
        self.assertEqual(app.state.storage_session.storage_path, explicit_path)
        self.assertEqual(
            app.state.storage_bootstrap,
            {
                "storage_backend": "json-file",
                "storage_path": str(explicit_path),
                "storage_path_optional": str(explicit_path),
                "storage_scope": "process",
                "storage_runtime_mode": "explicit-path",
            },
        )

    def test_create_app_exposes_single_transport_bootstrap_readback_projection(self) -> None:
        app = create_app()

        self.assertTrue(hasattr(app.state, "transport_bootstrap"))
        bootstrap = app.state.transport_bootstrap
        self.assertTrue(bootstrap["internal_only"])
        self.assertFalse(bootstrap["live_execution_enabled"])

        disabled_registry = bootstrap["stage1_to_stage5_transport_state"]
        self.assertEqual(disabled_registry, app.state.disabled_stage_transports)
        for stage_scope in range(1, 6):
            stage_key = f"stage{stage_scope}"
            self.assertIn(stage_key, disabled_registry)
            self.assertEqual(len(disabled_registry[stage_key]), 1)
            transport_status = disabled_registry[stage_key][0]
            self.assertEqual(transport_status["stage_scope"], stage_scope)
            self.assertEqual(transport_status["availability_state"], "CONTROLLED_UNAVAILABLE")
            self.assertEqual(transport_status["transport_state"], "TRANSPORT_NOT_WIRED")
            self.assertFalse(transport_status["live_execution_enabled"])
            self.assertTrue(transport_status["internal_only"])

        mounted_operations = bootstrap["stage6_to_stage9_mounted_operations"]
        mounted_by_id = {operation["operationId"]: operation for operation in mounted_operations}
        expected_operations = {
            "previewStage6ReviewReportWorkbench",
            "listSaleableOpportunities",
            "listContactTargets",
            "listOrders",
            "createOutreachPlan",
            "createOrder",
        }
        self.assertTrue(expected_operations.issubset(mounted_by_id))
        for operation_id in expected_operations:
            operation = mounted_by_id[operation_id]
            for key in (
                "stage_scope",
                "operationId",
                "method",
                "path",
                "surface_mode",
                "internal_only",
                "live_execution_enabled",
                "blocked_by_default",
            ):
                self.assertIn(key, operation)
            self.assertTrue(operation["internal_only"])
            self.assertFalse(operation["live_execution_enabled"])

        self.assertEqual(mounted_by_id["previewStage6ReviewReportWorkbench"]["stage_scope"], 6)
        self.assertEqual(mounted_by_id["listSaleableOpportunities"]["stage_scope"], 7)
        self.assertEqual(mounted_by_id["listContactTargets"]["stage_scope"], 8)
        self.assertEqual(mounted_by_id["listOrders"]["stage_scope"], 9)
        self.assertTrue(mounted_by_id["listContactTargets"]["blocked_by_default"])
        self.assertTrue(mounted_by_id["createOutreachPlan"]["blocked_by_default"])
        self.assertTrue(mounted_by_id["listOrders"]["blocked_by_default"])
        self.assertTrue(mounted_by_id["createOrder"]["blocked_by_default"])

        leadpack_candidate = mounted_by_id["previewLeadpackExternalDeliveryCandidate"]
        self.assertTrue(leadpack_candidate["candidate_only"])
        self.assertFalse(leadpack_candidate["external_delivery_enabled"])
        self.assertTrue(leadpack_candidate["requires_review"])

        entry_strategy = bootstrap["entry_strategy"]
        self.assertFalse(entry_strategy["stage1_to_stage5"]["http_entry_enabled"])
        self.assertFalse(entry_strategy["stage1_to_stage5"]["real_transport_enabled"])
        self.assertTrue(entry_strategy["stage6"]["http_entry_enabled"])
        self.assertIn(
            "previewStage6ReviewReportWorkbench",
            entry_strategy["stage6"]["mounted_operations"],
        )
        self.assertTrue(entry_strategy["stage7_to_stage9"]["http_entry_enabled"])
        self.assertIn(
            "listSaleableOpportunities",
            entry_strategy["stage7_to_stage9"]["mounted_operations_by_stage"]["stage7"],
        )
        self.assertFalse(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_stage1_to_stage5_transport"]
        )
        self.assertFalse(entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_real_orchestrator"])

        redlines = bootstrap["redlines"]
        self.assertFalse(redlines["new_http_endpoint_added"])
        self.assertFalse(redlines["stage1_to_stage5_real_transport_enabled"])
        self.assertFalse(redlines["external_software_release_enabled"])
        self.assertTrue(redlines["external_leadpack_delivery_requires_approval_and_audit"])
        self.assertFalse(redlines["stage8_real_execution_enabled"])
        self.assertFalse(redlines["stage9_real_payment_delivery_refund_enabled"])

        self.assertEqual(len(app.state.disabled_stage_transports), 5)
        self.assertEqual(
            app.state.mounted_transport_operations,
            [operation["operationId"] for operation in mounted_operations],
        )
        self.assertEqual(app.state.storage_bootstrap, app.state.settings.storage_bootstrap_payload())

    def test_create_app_fast_fails_unsupported_storage_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "postgres",
                    "LOCALAPPDATA": tmp_dir,
                },
                clear=False,
            ):
                for key in ("KAKA_STORAGE_PATH", "KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
                    os.environ.pop(key, None)
                get_settings.cache_clear()

                with self.assertRaisesRegex(ValueError, "postgres"):
                    create_app()

    def test_stage1_to_stage5_route_registrars_are_controlled_unavailable(self) -> None:
        registrars = [
            register_stage1_routes,
            register_stage2_routes,
            register_stage3_routes,
            register_stage4_routes,
            register_stage5_routes,
        ]

        for stage_scope, registrar in enumerate(registrars, start=1):
            routes = registrar()
            self.assertEqual(len(routes), 1)
            transport_status = routes[0]
            self.assertEqual(transport_status["stage_scope"], stage_scope)
            self.assertEqual(transport_status["availability_state"], "CONTROLLED_UNAVAILABLE")
            self.assertEqual(transport_status["contract_state"], "CONTRACT_READY")
            self.assertEqual(transport_status["transport_state"], "TRANSPORT_NOT_WIRED")
            self.assertTrue(transport_status["internal_only"])
            self.assertFalse(transport_status["live_execution_enabled"])

    def test_stage6_route_registrar_exposes_internal_queue_surface(self) -> None:
        routes = register_stage6_routes()

        self.assertEqual(len(routes), 3)
        preview_route = next(route for route in routes if route["operationId"] == "previewStage6ReviewReportWorkbench")
        self.assertEqual(preview_route["operationId"], "previewStage6ReviewReportWorkbench")
        self.assertEqual(preview_route["method"], "GET")
        self.assertEqual(preview_route["path"], "/review-report-workbench")
        self.assertEqual(preview_route["surface_mode"], "preview-only")
        self.assertTrue(preview_route["internal_only"])
        self.assertFalse(preview_route["live_execution_enabled"])
        self.assertFalse(preview_route["blocked_by_default"])
        list_route = next(route for route in routes if route["operationId"] == "listStage6WorkItems")
        action_route = next(route for route in routes if route["operationId"] == "submitStage6OperatorAction")
        self.assertEqual(list_route["method"], "GET")
        self.assertEqual(list_route["path"], "/review-report-work-items")
        self.assertEqual(action_route["method"], "POST")
        self.assertEqual(action_route["path"], "/review-report-workbench/{project_fact_id}/operator-actions")
        self.assertTrue(action_route["internal_only"])
        self.assertFalse(action_route["live_execution_enabled"])

    def test_create_app_mounts_stage7_to_stage9_transport_routes(self) -> None:
        app = create_app()

        mounted_operation_ids = {
            route.operation_id
            for route in app.routes
            if getattr(route, "operation_id", None)
        }
        self.assertTrue(
            {
                "previewStage6ReviewReportWorkbench",
                "listStage6WorkItems",
                "submitStage6OperatorAction",
                "listSaleableOpportunities",
                "listContactTargets",
                "listOrders",
                "createOutreachPlan",
                "createOrder",
            }.issubset(mounted_operation_ids)
        )
        self.assertEqual(len(app.state.disabled_stage_transports), 5)
        self.assertIn("stage1", app.state.disabled_stage_transports)
        self.assertNotIn("stage6", app.state.disabled_stage_transports)

    def test_stage6_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage6 = result["stage6"]
        persist_stage_bundle(stage6)
        project_id = stage6.record("project_fact").get("project_id")

        client = TestClient(create_app())
        response = client.request("GET", "/review-report-workbench", json={"project_id": project_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "review_report_workbench")
        self.assertEqual(payload["surface_mode"], "preview-only")
        self.assertTrue(payload["internal_only"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["blocked_by_default"])
        self.assertEqual(
            payload["formal_object_refs"]["project_fact"]["object_id"],
            stage6.record("project_fact").get("project_fact_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["report_record"]["object_id"],
            stage6.record("report_record").get("report_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["review_queue_profile"]["object_id"],
            stage6.record("review_queue_profile").get("queue_profile_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["challenger_candidate_profile"]["object_id"],
            stage6.record("challenger_candidate_profile").get("challenger_profile_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["legal_action_recommendation"]["object_id"],
            stage6.record("legal_action_recommendation").get("action_id"),
        )
        self.assertEqual(
            payload["preview_projection"]["project_fact_summary"]["sale_gate_status"],
            stage6.record("project_fact").get("sale_gate_status"),
        )

    def test_stage6_http_transport_lists_and_submits_operator_actions(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage6 = result["stage6"]
        persist_stage_bundle(stage6)
        project_id = stage6.record("project_fact").get("project_id")
        project_fact_id = stage6.record("project_fact").get("project_fact_id")

        client = TestClient(create_app())
        list_response = client.request("GET", "/review-report-work-items", json={"project_id": project_id})
        action_response = client.request(
            "POST",
            f"/review-report-workbench/{project_fact_id}/operator-actions",
            json={
                "project_id": project_id,
                "action_id": "stage6_return_for_revision",
                "button_flow_id": "submit_stage6_return_for_revision",
                "reason": "transport-level stage6 revision return",
                "requested_by_role": "single_operator",
                "requested_by": "卡卡罗特",
            },
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(action_response.status_code, 200)
        list_payload = list_response.json()
        action_payload = action_response.json()
        self.assertEqual(len(list_payload["work_items"]), 1)
        self.assertEqual(list_payload["work_items"][0]["primary_object_type"], "project_fact")
        self.assertEqual(action_payload["action_result"]["action_id"], "stage6_return_for_revision")
        self.assertEqual(
            action_payload["persisted_operational_context"]["current_operational_state"],
            "action_returned_for_revision",
        )
        self.assertEqual(action_payload["persisted_operational_context"]["pending_actions"], ["stage6_mark_reviewed"])

    def test_stage7_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", "/saleable-opportunities", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "opportunity_pool")
        self.assertTrue(payload["internal_only"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_ONLY")
        self.assertIn("refreshSaleableOpportunity", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["offer_recommendation"]["object_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["buyer_fit"]["object_id"],
            stage7.record("buyer_fit").get("buyer_fit_id"),
        )

    def test_stage8_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        persist_stage_bundle(stage8)
        opportunity_id = stage8.record("touch_record").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", "/contact-targets", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "outreach_workbench")
        self.assertTrue(payload["blocked_by_default"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        self.assertIn("createOutreachPlan", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["contact_target"]["object_id"],
            stage8.record("contact_target").get("contact_target_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["outreach_plan"]["object_id"],
            stage8.record("outreach_plan").get("outreach_plan_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["touch_record"]["object_id"],
            stage8.record("touch_record").get("touch_record_id"),
        )

    def test_stage9_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        persist_stage_bundle(stage9)
        opportunity_id = stage9.record("order_record").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", "/orders", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "order_delivery_workbench")
        self.assertTrue(payload["blocked_by_default"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        self.assertIn("createOrder", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["payment_record"]["object_id"],
            stage9.record("payment_record").get("payment_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["delivery_record"]["object_id"],
            stage9.record("delivery_record").get("delivery_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["opportunity_outcome_event"]["object_id"],
            stage9.record("opportunity_outcome_event").get("outcome_event_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["governance_feedback_event"]["object_id"],
            stage9.record("governance_feedback_event").get("governance_feedback_event_id"),
        )


if __name__ == "__main__":
    unittest.main()
