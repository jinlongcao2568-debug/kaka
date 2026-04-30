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
from api.projections import build_real_sample_autonomous_opportunity_acceptance_surface
from api.routes.operator_customer_access import (
    OPERATOR_CUSTOMER_ACCESS_ROUTES,
    list_operator_region_adapters,
    preview_real_sample_autonomous_opportunity_acceptance,
)
from helpers import load_fixture
from shared.pipeline import run_internal_chain
from stage1_tasking.market_scan import Stage1MarketScanEngine
from stage1_tasking.source_blueprint import Stage1SourceBlueprintOrchestrator
from storage import reset_default_storage


class RealSampleAutonomousOpportunityAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

    def _run_real_sample_acceptance_payload(self) -> dict[str, object]:
        real_sample_payload = copy.deepcopy(
            load_fixture("stage1_to_stage5_real_source_vertical_slice_proc_national_html.json")
        )
        real_sample_payload.update(
            {
                "task_id": "TASK-149-REAL-SAMPLE-001",
                "project_id": "PROJ-149-REAL-SAMPLE-001",
                "project_name": "Sichuan public construction real sample",
                "region_code": "CN-SC",
                "project_type": "construction",
                "procurement_regime": "OPEN_TENDER",
                "notice_stage": "candidate_notice",
                "amount": 22800000,
                "candidate_count": 3,
                "candidate_company": "First Rank Construction Co",
                "objection_deadline_at_optional": "2026-05-02T00:00:00+00:00",
                "key_fields_present": [
                    "project_name",
                    "candidate_company",
                    "notice_stage",
                ],
                "source_mode": "OFFLINE_REAL_PUBLIC_SAMPLE",
                "run_mode": "DRY_RUN",
                "automation_level": "AUTONOMOUS",
                "live_execution_enabled": False,
                "real_provider_call_enabled": False,
            }
        )
        market_scan = Stage1MarketScanEngine().run(
            {
                **real_sample_payload,
                "scan_run_id": "MKTSCAN-149-REAL-SAMPLE-001",
                "batch_id": "PTL-I100-ROADMAP-01",
                "minimum_amount": 1000000,
                "analysis_score_threshold": 50,
            }
        )
        source_blueprint = Stage1SourceBlueprintOrchestrator().build(
            {
                "scan_run_id": market_scan["scan_run_id"],
                "source_blueprint_plan_id": "SRCBLUE-149-REAL-SAMPLE-001",
                "coverage_gap_signals": [
                    "province_platform_missing_detail_or_attachment",
                ],
            }
        )
        selected = market_scan["opportunity_candidates"][0]
        chain_payload = {
            **real_sample_payload,
            "announcement_url": selected["source_refs"]["source_url"]
            or real_sample_payload["announcement_url"],
            "source_blueprint_plan_id": source_blueprint["source_blueprint_plan_id"],
            "stage2_capture_plan_id": source_blueprint["stage2_capture_plan"]["capture_plan_id"],
        }
        chain = run_internal_chain(chain_payload)
        return {
            **chain,
            "market_scan": market_scan,
            "source_blueprint_plan": source_blueprint,
        }

    def test_real_sample_acceptance_closes_market_scan_to_hook_and_delivery_candidate(self) -> None:
        payload = self._run_real_sample_acceptance_payload()

        surface = build_real_sample_autonomous_opportunity_acceptance_surface(payload)

        self.assertEqual(
            surface["acceptance_state"],
            "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED",
        )
        self.assertEqual(surface["capability_state"], "PRODUCTION_READY")
        self.assertEqual(surface["fail_closed_reasons"], [])
        flow = surface["real_sample_flow"]
        self.assertTrue(flow["market_scan_observed"])
        self.assertTrue(flow["market_scan_autonomous_decision"])
        self.assertEqual(flow["selected_candidate_count"], 1)
        self.assertTrue(flow["source_blueprint_observed"])
        self.assertTrue(flow["source_blueprint_auto_selection"])
        self.assertTrue(flow["stage2_capture_plan_observed"])
        self.assertGreaterEqual(flow["stage2_capture_step_count"], 6)
        self.assertTrue(flow["stage1_to_stage9_chain_observed"])
        self.assertTrue(flow["commercial_hook_observed"])
        self.assertTrue(flow["leadpack_delivery_candidate_observed"])
        self.assertTrue(flow["operator_workbench_observed"])
        self.assertTrue(flow["controlled_opening_requirements_preserved"])

        owner = surface["owner_workbench_acceptance"]
        self.assertTrue(owner["owner_can_observe_without_raw_json"])
        self.assertTrue(owner["opportunity_queue_visible"])
        self.assertTrue(owner["commercial_hook_review_visible"])
        self.assertTrue(owner["buyer_ranking_visible"])
        self.assertTrue(owner["evidence_risk_visible"])
        self.assertTrue(owner["delivery_state_visible"])
        self.assertTrue(owner["next_action_visible"])
        self.assertFalse(surface["raw_json_required"])
        self.assertFalse(surface["manual_url_picker_primary_flow"])
        self.assertTrue(
            all(ref["observed"] for ref in surface["stage_refs"].values())
        )
        self.assertFalse(
            any(surface["controlled_opening_requirements"].values())
        )

        hook = surface["commercial_hook_acceptance"]
        self.assertEqual(hook["disclosure_level"], "L1_HOOK")
        self.assertTrue(hook["no_full_evidence_leakage"])
        self.assertTrue(hook["forbidden_claims_filter_passed"])
        self.assertIn("source_url", hook["withheld_fields"])

        delivery = surface["delivery_candidate_acceptance"]
        self.assertTrue(delivery["readback_ready"])
        self.assertFalse(delivery["customer_visible_enabled"])
        self.assertFalse(delivery["external_delivery_enabled"])
        self.assertFalse(delivery["customer_download_enabled"])

    def test_operator_route_registers_real_sample_acceptance_without_live_execution(self) -> None:
        routes = {route["operationId"]: route for route in OPERATOR_CUSTOMER_ACCESS_ROUTES}
        route = routes["previewRealSampleAutonomousOpportunityAcceptance"]

        self.assertEqual(route["path"], "/operator-console/real-sample-autonomous-acceptance")
        self.assertTrue(route["real_sample_autonomous_acceptance"])
        self.assertTrue(route["real_sample_flow_visible"])
        self.assertTrue(route["productized_owner_workbench"])
        self.assertFalse(route["raw_json_required"])
        self.assertFalse(route["live_execution_enabled"])
        self.assertFalse(route["external_release_enabled"])
        self.assertFalse(route["real_provider_call_enabled"])

        surface = preview_real_sample_autonomous_opportunity_acceptance(
            self._run_real_sample_acceptance_payload()
        )
        self.assertEqual(surface["surface_id"], "real_sample_autonomous_opportunity_acceptance")
        self.assertEqual(surface["fail_closed_reasons"], [])

    def test_region_adapters_are_visible_for_owner_search(self) -> None:
        catalog = list_operator_region_adapters({})

        self.assertEqual(catalog["surface_id"], "operator_region_source_adapters")
        self.assertTrue(catalog["region_adapter_catalog"])
        self.assertIn("CN-GD", catalog["searchable_region_codes"])
        self.assertIn("CN-SC", catalog["commercial_pilot_region_codes"])
        by_code = {
            adapter["region_code"]: adapter
            for adapter in catalog["region_adapters"]
        }
        self.assertTrue(by_code["CN-GD"]["dedicated_local_profiles"])
        self.assertTrue(by_code["CN-SC"]["onboarding_required"])
        self.assertFalse(by_code["CN-SC"]["manual_url_picker_primary_flow"])

    def test_operator_autonomous_search_runs_region_to_workbench_loop(self) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_code": "CN-GD",
                "query": "市政工程",
                "project_type": "municipal",
                "amount_min": 8000000,
                "amount_max": 30000000,
                "candidate_count": 3,
                "now": "2026-04-30T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "operator_autonomous_opportunity_search")
        self.assertEqual(payload["search_state"], "AUTONOMOUS_SEARCH_ACCEPTED")
        self.assertEqual(payload["region_adapter"]["region_code"], "CN-GD")
        self.assertTrue(payload["region_adapter"]["dedicated_local_profiles"])
        self.assertEqual(
            payload["acceptance"]["acceptance_state"],
            "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED",
        )
        self.assertFalse(payload["manual_url_picker_primary_flow"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["real_provider_call_enabled"])
        self.assertEqual(payload["amount_range"]["minimum"], 8000000)
        self.assertEqual(payload["amount_range"]["maximum"], 30000000)
        self.assertTrue(payload["runtime_flow"]["test_path_unblocked"])
        self.assertTrue(payload["runtime_flow"]["live_delivery_gates_preserved"])
        self.assertEqual(payload["runtime_flow"]["totals"]["stage_count"], 9)
        self.assertEqual(len(payload["runtime_flow"]["stage_stats"]), 9)
        self.assertEqual(payload["search_scope"]["candidate_count"], 1)
        self.assertEqual(payload["search_scope"]["closed_loop_generated_count"], 1)
        self.assertEqual(len(payload["candidate_options"]), 1)
        self.assertEqual(payload["candidate_options"][0]["region_code"], "CN-GD")
        self.assertEqual(payload["candidate_options"][0]["project_type"], "municipal")
        self.assertTrue(payload["search_run_id"])
        self.assertEqual(
            payload["search_run_record"]["search_state"],
            "AUTONOMOUS_SEARCH_ACCEPTED",
        )

        opportunity_id = payload["opportunity_id"]
        self.assertTrue(opportunity_id)
        runs_response = client.request("GET", "/operator-console/autonomous-search-runs")
        self.assertEqual(runs_response.status_code, 200)
        runs = runs_response.json()
        self.assertEqual(runs["surface_id"], "operator_autonomous_search_runs")
        self.assertEqual(runs["run_count"], 1)
        self.assertTrue(runs["autonomous_search_run_list"])
        self.assertFalse(runs["raw_json_required"])
        self.assertEqual(runs["runs"][0]["opportunity_id"], opportunity_id)
        self.assertEqual(runs["runs"][0]["region_code"], "CN-GD")
        self.assertEqual(runs["latest_runtime_flow"]["totals"]["stage_count"], 9)
        self.assertEqual(runs["runs"][0]["search_scope"]["candidate_count"], 1)
        self.assertEqual(runs["runs"][0]["candidate_options"][0]["region_code"], "CN-GD")
        self.assertEqual(
            runs["runs"][0]["search_state"],
            "AUTONOMOUS_SEARCH_ACCEPTED",
        )
        workbench_response = client.request(
            "GET",
            "/operator-console/autonomous-workbench",
            params={"opportunity_id": opportunity_id},
        )
        self.assertEqual(workbench_response.status_code, 200)
        workbench = workbench_response.json()
        self.assertEqual(workbench["opportunity_queue"][0]["opportunity_id"], opportunity_id)
        self.assertIn(
            "公开风险信号",
            workbench["opportunity_queue"][0]["commercial_hook_teaser"],
        )
        self.assertEqual(
            workbench["opportunity_queue"][0]["next_action"],
            "PREPARE_LEADPACK_REVIEW_AND_DELIVERY_GATE",
        )
        self.assertEqual(
            workbench["panels"]["commercial_hook_panel"]["disclosure_level"],
            "L1_HOOK",
        )
        self.assertEqual(
            workbench["panels"]["evidence_risk_panel"]["evidence_strength_label"],
            "REVIEWABLE_PUBLIC_SIGNAL",
        )
        self.assertFalse(workbench["raw_json_required"])
        self.assertFalse(workbench["safe_display_contract"]["customer_download_enabled"])

    def test_operator_autonomous_search_runs_collapse_duplicate_opportunities(self) -> None:
        client = TestClient(create_app())
        search_payload = {
            "region_code": "CN-GD",
            "query": "市政工程",
            "project_type": "municipal",
            "amount_min": 8000000,
            "amount_max": 30000000,
            "candidate_count": 3,
            "now": "2026-04-30T00:00:00+00:00",
        }

        first_response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json=search_payload,
        )
        second_response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json=search_payload,
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        opportunity_id = second_response.json()["opportunity_id"]

        runs_response = client.request("GET", "/operator-console/autonomous-search-runs")
        self.assertEqual(runs_response.status_code, 200)
        runs = runs_response.json()
        self.assertEqual(runs["run_count"], 1)
        self.assertEqual(runs["raw_run_count"], 2)
        self.assertEqual(runs["duplicate_collapsed_count"], 1)
        self.assertEqual(runs["latest_opportunity_id"], opportunity_id)
        self.assertEqual(
            runs["latest_customer_artifact_portal_path"],
            f"/customer-artifact-portal/{opportunity_id}",
        )
        self.assertEqual(runs["runs"][0]["opportunity_id"], opportunity_id)
        self.assertEqual(runs["runs"][0]["amount_min"], "8000000")
        self.assertEqual(runs["runs"][0]["amount_max"], "30000000")
        self.assertEqual(runs["runs"][0]["search_scope"]["closed_loop_generated_count"], 1)
        self.assertTrue(runs["runs"][0]["runtime_flow"]["stage_stats"])

    def test_operator_autonomous_search_accepts_multi_region_and_project_type_scope(self) -> None:
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
                "now": "2026-04-30T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["search_state"], "AUTONOMOUS_SEARCH_ACCEPTED")
        self.assertEqual(payload["search_scope"]["region_codes"], ["CN-GD", "CN-JS"])
        self.assertEqual(payload["search_scope"]["project_types"], ["construction", "municipal"])
        self.assertEqual(payload["search_scope"]["candidate_count"], 4)
        self.assertEqual(payload["search_scope"]["closed_loop_generated_count"], 1)
        self.assertEqual(payload["region_adapter"]["region_code"], "CN-GD")
        self.assertEqual(payload["candidate"]["project_type"], "construction")
        self.assertEqual(len(payload["candidate_options"]), 4)
        self.assertTrue(payload["candidate_options"][0]["project_name"])
        self.assertEqual(payload["runtime_flow"]["stage_stats"][0]["produced_count"], 4)


if __name__ == "__main__":
    unittest.main()
