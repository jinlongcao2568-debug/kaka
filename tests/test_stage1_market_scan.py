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
from stage2_ingestion.real_candidate_capture import _extract_deadline
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
        self.assertFalse(scan["unregistered_capture_enabled"])
        self.assertFalse(scan["manual_url_picker_primary_flow"])
        self.assertEqual(scan["selected_candidate_count"], 1)
        self.assertEqual(scan["review_candidate_count"], 1)
        self.assertEqual(scan["skipped_candidate_count"], 1)

        selected = scan["opportunity_candidates"][0]
        self.assertEqual(selected["analysis_decision"], "ANALYZE")
        self.assertEqual(selected["analysis_priority"], "HIGH")
        self.assertIn("active_objection_window", selected["why_analyze"])
        self.assertIn("high_value_amount_band", selected["why_analyze"])
        self.assertIn("engineering_project_type", selected["why_analyze"])
        self.assertEqual(selected["why_skip"], [])
        self.assertTrue(selected["selected_for_capture_plan"])
        self.assertEqual(selected["score_components"]["project_type"], 10)
        self.assertEqual(selected["market_segment"]["project_type"], "construction")
        self.assertEqual(selected["market_segment"]["amount_band"], "HIGH_VALUE")

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
        self.assertFalse(replay["unregistered_capture_executed"])

    def test_service_and_api_helpers_expose_market_scan_without_mounting_stage1_route(self) -> None:
        result = Stage1Service().scan_market(self.payload)
        api_result = create_stage1_market_scan({**self.payload, "scan_run_id": "MKTSCAN-API-001"})
        api_readback = read_stage1_market_scan({"scan_run_id": "MKTSCAN-API-001"})

        self.assertEqual(result["next_action"], "CREATE_STAGE2_CAPTURE_PLAN")
        self.assertEqual(api_result["scan_run_id"], "MKTSCAN-API-001")
        self.assertEqual(api_readback["readback_state"], "READBACK_READY")
        self.assertEqual(len(register_stage1_routes()), 1)

    def test_market_scan_blocks_manual_url_primary_and_live_requests(self) -> None:
        blocked_payloads = [
            {"source_selection_mode": "MANUAL_URL_PRIMARY"},
            {"real_external_fetch_enabled": True},
            {"unregistered_capture_enabled": True},
            {"provider_call_enabled": True},
        ]
        for extra in blocked_payloads:
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    Stage1MarketScanEngine().run({**self.payload, "scan_run_id": "MKTSCAN-BLOCK", **extra})

    def test_market_scan_routes_login_captcha_antibot_markers_to_review_not_skip(self) -> None:
        payload = {
            **self.payload,
            "scan_run_id": "MKTSCAN-CHALLENGE-001",
            "notice_candidates": [
                {
                    **self.payload["notice_candidates"][0],
                    "notice_id": "NOTICE-CAPTCHA-001",
                    "source_url": "https://public.example.local/provincial-bidding-platforms/captcha/notice",
                    "source_visibility_state": "CAPTCHA_REQUIRED",
                }
            ],
        }

        scan = Stage1MarketScanEngine().run(payload)

        self.assertEqual(scan["selected_candidate_count"], 0)
        self.assertEqual(scan["review_candidate_count"], 1)
        candidate = scan["review_candidates"][0]
        self.assertEqual(candidate["analysis_decision"], "REVIEW")
        self.assertIn("controlled_challenge_marker_captcha", candidate["review_reasons"])
        self.assertEqual(candidate["why_skip"], [])

    def test_market_scan_uses_project_type_to_skip_non_engineering_notices(self) -> None:
        payload = {
            **self.payload,
            "scan_run_id": "MKTSCAN-NON-ENGINEERING-001",
            "notice_candidates": [
                {
                    **self.payload["notice_candidates"][0],
                    "notice_id": "NOTICE-GOODS-001",
                    "project_type": "office_supplies",
                    "amount": 30000000,
                    "objection_deadline_at_optional": "2026-05-02T00:00:00+00:00",
                }
            ],
        }

        scan = Stage1MarketScanEngine().run(payload)

        self.assertEqual(scan["selected_candidate_count"], 0)
        self.assertEqual(scan["skipped_candidate_count"], 1)
        candidate = scan["skipped_candidates"][0]
        self.assertEqual(candidate["analysis_decision"], "SKIP")
        self.assertIn("project_type_not_engineering", candidate["why_skip"])
        self.assertEqual(candidate["score_components"]["project_type"], 0)
        self.assertEqual(candidate["market_segment"]["project_type"], "office_supplies")

    def test_market_scan_honors_maximum_amount_range(self) -> None:
        payload = {
            **self.payload,
            "scan_run_id": "MKTSCAN-AMOUNT-RANGE-001",
            "minimum_amount": 1_000_000,
            "maximum_amount": 30_000_000,
            "notice_candidates": [
                {
                    **self.payload["notice_candidates"][0],
                    "notice_id": "NOTICE-ABOVE-MAX-001",
                    "amount": 50_000_000,
                }
            ],
        }

        scan = Stage1MarketScanEngine().run(payload)

        self.assertEqual(scan["selected_candidate_count"], 0)
        self.assertEqual(scan["skipped_candidate_count"], 1)
        candidate = scan["skipped_candidates"][0]
        self.assertIn("amount_above_maximum", candidate["why_skip"])
        self.assertEqual(candidate["market_segment"]["minimum_amount"], 1_000_000)
        self.assertEqual(candidate["market_segment"]["maximum_amount"], 30_000_000)

    def test_real_discovery_tender_with_detail_snapshot_can_enter_analysis_without_objection_deadline(self) -> None:
        payload = {
            **self.payload,
            "scan_run_id": "MKTSCAN-REAL-DISCOVERY-TENDER-001",
            "minimum_amount": 0,
            "maximum_amount": 500_000_000,
            "notice_candidates": [
                {
                    "notice_id": "NOTICE-GD-REAL-001",
                    "project_id": "PROJ-GD-REAL-001",
                    "project_name": "白坭镇水利设施提升改造工程",
                    "region_code": "CN-GD",
                    "project_type": "water_conservancy",
                    "notice_stage": "tender_notice",
                    "amount": 44_000_000,
                    "candidate_company": "",
                    "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
                    "stage2_detail_snapshot_id_optional": "REAL-DETAIL-GD-001",
                    "stage2_attachment_snapshot_count": 2,
                    "source_url": "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A",
                    "key_fields_present": ["project_name", "notice_stage"],
                }
            ],
        }

        scan = Stage1MarketScanEngine().run(payload)

        self.assertEqual(scan["selected_candidate_count"], 1)
        candidate = scan["opportunity_candidates"][0]
        self.assertEqual(candidate["analysis_decision"], "ANALYZE")
        self.assertIn("discovery_stage_window_not_required", candidate["why_analyze"])
        self.assertIn("real_detail_attachment_evidence_ready_for_discovery_stage", candidate["why_analyze"])
        self.assertNotIn("objection_window_unknown", candidate["review_reasons"])
        self.assertEqual(candidate["why_skip"], [])

    def test_detail_deadline_parser_does_not_treat_publication_window_as_objection_deadline(self) -> None:
        deadline, state = _extract_deadline(
            "公告发布时间 2026-05-01 09:00:00 至 2026-05-21 18:00:00 "
            "招标文件获取方式 网上获取"
        )
        self.assertEqual(deadline, "")
        self.assertEqual(state, "DETAIL_TEXT_NOT_FOUND")

        deadline, state = _extract_deadline(
            "公告质疑截止时间 2026-05-11 17:00:00 公告答疑截止时间 2026-05-16 17:00:00"
        )
        self.assertEqual(deadline, "2026-05-11T17:00:00+08:00")
        self.assertEqual(state, "DETAIL_TEXT")


if __name__ == "__main__":
    unittest.main()
