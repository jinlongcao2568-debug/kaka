from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
        reset_default_storage()

    def test_get_settings_returns_formal_internal_settings(self) -> None:
        settings = get_settings()

        self.assertEqual(settings.environment, "INTERNAL_ONLY")
        self.assertEqual(Path(settings.repo_root).resolve(), ROOT.resolve())

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

    def test_stage6_route_registrar_exposes_read_only_preview_surface(self) -> None:
        routes = register_stage6_routes()

        self.assertEqual(len(routes), 1)
        preview_route = routes[0]
        self.assertEqual(preview_route["operationId"], "previewStage6ReviewReportWorkbench")
        self.assertEqual(preview_route["method"], "GET")
        self.assertEqual(preview_route["path"], "/review-report-workbench")
        self.assertEqual(preview_route["surface_mode"], "preview-only")
        self.assertTrue(preview_route["internal_only"])
        self.assertFalse(preview_route["live_execution_enabled"])
        self.assertFalse(preview_route["blocked_by_default"])

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
