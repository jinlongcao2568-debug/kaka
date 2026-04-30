from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.projections import build_real_sample_autonomous_opportunity_acceptance_surface
from api.routes.operator_customer_access import (
    OPERATOR_CUSTOMER_ACCESS_ROUTES,
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


if __name__ == "__main__":
    unittest.main()
