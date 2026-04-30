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
from api.routes.stage7 import list_saleable_opportunities
from helpers import load_fixture, run_internal_chain_to_stage7
from storage import persist_stage_bundle, reset_default_storage


class ProductizedAutonomousOperatorWorkbenchTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

    def test_stage7_preview_exposes_owner_workbench_without_raw_json_dependency(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]

        response = list_saleable_opportunities(stage7)
        workbench = response["productized_operator_workbench"]
        queue_item = workbench["opportunity_queue"][0]
        panels = workbench["panels"]

        self.assertTrue(workbench["productized_owner_view"])
        self.assertTrue(workbench["owner_can_observe_without_raw_json"])
        self.assertFalse(workbench["raw_json_required"])
        self.assertFalse(workbench["raw_json_fallback_required"])
        self.assertEqual(workbench["opportunity_queue_count"], 1)
        self.assertEqual(
            queue_item["opportunity_id"],
            stage7.record("saleable_opportunity").get("opportunity_id"),
        )
        self.assertIn("evidence_strength_label", queue_item)
        self.assertIn("hard_defect_public_label", queue_item)
        self.assertIn("commercial_hook_teaser", queue_item)
        self.assertIn("buyer_rankings", queue_item)
        self.assertIn("next_action", queue_item)
        self.assertIn("delivery_state", queue_item)
        self.assertFalse(queue_item["customer_visible_enabled"])
        self.assertFalse(queue_item["external_send_enabled"])
        self.assertFalse(queue_item["live_execution_enabled"])
        self.assertTrue(panels["commercial_hook_panel"]["forbidden_claims_filter_passed"])
        self.assertEqual(panels["commercial_hook_panel"]["disclosure_level"], "L1_HOOK")
        self.assertFalse(workbench["safe_display_contract"]["source_url_visible"])
        self.assertFalse(workbench["safe_display_contract"]["raw_snapshot_visible"])
        self.assertFalse(workbench["safe_display_contract"]["complete_verification_path_visible"])
        self.assertFalse(workbench["safe_display_contract"]["internal_score_model_visible"])

    def test_operator_console_mounts_productized_autonomous_workbench_route(self) -> None:
        app = create_app()
        mounted = {
            operation["operationId"]: operation
            for operation in app.state.transport_bootstrap["operator_customer_access_mounted_operations"]
        }

        route = mounted["previewAutonomousOperatorWorkbench"]
        self.assertTrue(route["internal_only"])
        self.assertTrue(route["projection_only"])
        self.assertTrue(route["autonomous_operator_workbench"])
        self.assertTrue(route["productized_owner_workbench"])
        self.assertTrue(route["opportunity_queue_visible"])
        self.assertTrue(route["commercial_hook_review_visible"])
        self.assertTrue(route["buyer_ranking_visible"])
        self.assertTrue(route["evidence_risk_visible"])
        self.assertTrue(route["delivery_state_visible"])
        self.assertTrue(route["next_action_visible"])
        self.assertFalse(route["raw_json_required"])
        self.assertFalse(route["live_execution_enabled"])
        self.assertFalse(route["external_release_enabled"])

        client = TestClient(app)
        readiness = client.request("GET", "/operator-console/readiness").json()
        self.assertTrue(
            readiness["operator_console"]["autonomous_operator_workbench"]["entry_visible"]
        )
        self.assertFalse(
            readiness["operator_console"]["autonomous_operator_workbench"]["raw_json_required"]
        )

    def test_http_autonomous_workbench_reads_persisted_stage7_queue(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request(
            "GET",
            "/operator-console/autonomous-workbench",
            json={"opportunity_id": opportunity_id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "autonomous_operator_workbench")
        self.assertEqual(payload["capability_state"], "INTERNAL_READY")
        self.assertTrue(payload["productized_owner_workbench"])
        self.assertTrue(payload["owner_can_observe_without_raw_json"])
        self.assertFalse(payload["raw_json_required"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["external_release_enabled"])
        self.assertEqual(payload["opportunity_queue"][0]["opportunity_id"], opportunity_id)
        self.assertIn("commercial_hook_panel", payload["panels"])
        self.assertIn("buyer_ranking_panel", payload["panels"])
        self.assertIn("sales_next_action_panel", payload["panels"])
        self.assertIn("delivery_state_panel", payload["panels"])
        self.assertFalse(payload["safe_display_contract"]["source_url_visible"])
        self.assertFalse(payload["safe_display_contract"]["customer_download_enabled"])


if __name__ == "__main__":
    unittest.main()
