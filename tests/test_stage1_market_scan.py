from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for search_path in (SRC, ROOT / "tests"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.routes.stage1 import create_stage1_market_scan, read_stage1_market_scan, register_stage1_routes
from stage1_tasking.market_scan import Stage1MarketScanEngine
from stage1_tasking.service import Stage1Service
from storage import reset_default_storage


class TestStage1MarketScan(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()
        self.payload = {
            "scan_run_id": "MKTSCAN-TEST-001",
            "task_id": "TASK-MARKET-SCAN-001",
            "batch_id": "MARKET-SCAN-BATCH-001",
            "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            "now": "2026-04-29T00:00:00+00:00",
            "minimum_amount": 1000000,
            "analysis_score_threshold": 50,
            "notice_candidates": [
                {
                    "notice_id": "NOTICE-HIGH-001",
                    "project_id": "PROJ-HIGH-001",
                    "project_name": "四川高价值候选公示项目",
                    "region_code": "CN-SC",
                    "project_type": "construction",
                    "notice_stage": "candidate_notice",
                    "amount": 22000000,
                    "candidate_count": 3,
                    "candidate_company": "第一名建设公司",
                    "objection_deadline_at_optional": "2026-05-02T00:00:00+00:00",
                    "source_url": "https://public.example.local/provincial-bidding-platforms/detail/notice-high",
                    "source_family": "provincial_bidding_platform",
                    "source_registry_id": "SRC-REG-PROVINCIAL-BIDDING-PLATFORM",
                    "key_fields_present": ["project_name", "candidate_company", "notice_stage"],
                },
                {
                    "notice_id": "NOTICE-EXPIRED-001",
                    "project_id": "PROJ-EXPIRED-001",
                    "project_name": "窗口过期项目",
                    "region_code": "CN-JS",
                    "project_type": "construction",
                    "notice_stage": "award_result",
                    "amount": 5000000,
                    "candidate_count": 2,
                    "candidate_company": "过期候选公司",
                    "objection_deadline_at_optional": "2026-04-20T00:00:00+00:00",
                    "key_fields_present": ["project_name", "candidate_company", "notice_stage"],
                },
                {
                    "notice_id": "NOTICE-REVIEW-001",
                    "project_id": "PROJ-REVIEW-001",
                    "project_name": "缺关键字段项目",
                    "region_code": "CN-GD",
                    "project_type": "construction",
                    "notice_stage": "candidate_notice",
                    "amount": 3000000,
                    "candidate_count": 1,
                    "objection_deadline_at_optional": "2026-05-01T00:00:00+00:00",
                    "key_fields_present": ["project_name", "notice_stage"],
                },
            ],
        }

    def test_market_scan_selects_opportunity_candidate_and_persists_readback(self) -> None:
        scan = Stage1MarketScanEngine().run(self.payload)
        readback = Stage1MarketScanEngine().readback("MKTSCAN-TEST-001")
        replay = Stage1MarketScanEngine().replay("MKTSCAN-TEST-001")

        self.assertEqual(scan["capability_state"], "INTERNAL_READY")
        self.assertTrue(scan["internal_only"])
        self.assertFalse(scan["customer_visible"])
        self.assertFalse(scan["real_external_fetch_enabled"])
        self.assertFalse(scan["crawler_enabled"])
        self.assertFalse(scan["manual_url_picker_primary_flow"])
        self.assertEqual(scan["selected_candidate_count"], 1)
        self.assertEqual(scan["review_candidate_count"], 1)
        self.assertEqual(scan["skipped_candidate_count"], 1)

        selected = scan["opportunity_candidates"][0]
        self.assertEqual(selected["analysis_decision"], "ANALYZE")
        self.assertEqual(selected["analysis_priority"], "HIGH")
        self.assertIn("active_objection_window", selected["why_analyze"])
        self.assertIn("high_value_amount_band", selected["why_analyze"])
        self.assertEqual(selected["why_skip"], [])
        self.assertTrue(selected["selected_for_capture_plan"])

        skipped = scan["skipped_candidates"][0]
        self.assertEqual(skipped["analysis_decision"], "SKIP")
        self.assertIn("objection_window_expired", skipped["why_skip"])

        review = scan["review_candidates"][0]
        self.assertEqual(review["analysis_decision"], "REVIEW")
        self.assertIn("missing_key_fields:candidate_company", review["review_reasons"])

        controller = scan["run_controller"]
        self.assertTrue(controller["autonomous_decision"])
        self.assertFalse(controller["manual_url_picker_primary_flow"])
        self.assertEqual(controller["next_action"], "CREATE_STAGE2_CAPTURE_PLAN")
        self.assertEqual(
            controller["source_policy"]["market_segment_selection_source"],
            "market_scan_policy",
        )
        self.assertEqual(
            scan["stage_state_machine"]["stage_progression"][1]["state"],
            "WAITING_FOR_145",
        )
        self.assertEqual(readback["market_scan"]["scan_run_id"], "MKTSCAN-TEST-001")
        self.assertEqual(readback["governed_state"]["selected_candidate_count"], 1)
        self.assertEqual(replay["replay_state"], "REPLAY_READY")
        self.assertFalse(replay["stage2_fetch_executed"])
        self.assertFalse(replay["crawler_executed"])

    def test_service_and_api_helpers_expose_market_scan_without_mounting_stage1_route(self) -> None:
        result = Stage1Service().scan_market(self.payload)
        api_result = create_stage1_market_scan({**self.payload, "scan_run_id": "MKTSCAN-API-001"})
        api_readback = read_stage1_market_scan({"scan_run_id": "MKTSCAN-API-001"})

        self.assertEqual(result["next_action"], "CREATE_STAGE2_CAPTURE_PLAN")
        self.assertEqual(api_result["scan_run_id"], "MKTSCAN-API-001")
        self.assertEqual(api_readback["readback_state"], "READBACK_READY")
        self.assertEqual(len(register_stage1_routes()), 1)

    def test_market_scan_blocks_manual_url_primary_and_live_or_private_requests(self) -> None:
        blocked_payloads = [
            {"source_selection_mode": "MANUAL_URL_PRIMARY"},
            {"real_external_fetch_enabled": True},
            {"crawler_enabled": True},
            {"provider_call_enabled": True},
        ]
        for extra in blocked_payloads:
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    Stage1MarketScanEngine().run({**self.payload, "scan_run_id": "MKTSCAN-BLOCK", **extra})

        private_payload = {
            **self.payload,
            "scan_run_id": "MKTSCAN-PRIVATE",
            "notice_candidates": [
                {
                    "notice_id": "NOTICE-PRIVATE",
                    "project_name": "private",
                    "region_code": "CN-SC",
                    "notice_stage": "candidate_notice",
                    "amount": 9000000,
                    "candidate_count": 2,
                    "candidate_company": "private company",
                    "objection_deadline_at_optional": "2026-05-01T00:00:00+00:00",
                    "source_mode": "PRIVATE_SOURCE",
                    "key_fields_present": ["project_name", "candidate_company", "notice_stage"],
                }
            ],
        }
        scan = Stage1MarketScanEngine().run(private_payload)
        self.assertEqual(scan["selected_candidate_count"], 0)
        self.assertEqual(scan["skipped_candidates"][0]["analysis_decision"], "SKIP")
        self.assertIn("blocked_source_marker_private", scan["skipped_candidates"][0]["why_skip"])


if __name__ == "__main__":
    unittest.main()
