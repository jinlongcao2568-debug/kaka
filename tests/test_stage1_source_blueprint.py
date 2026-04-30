from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for search_path in (SRC, ROOT / "tests"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.routes.stage1 import (  # noqa: E402
    create_stage1_source_blueprint_plan,
    read_stage1_source_blueprint_plan,
)
from stage1_tasking.market_scan import Stage1MarketScanEngine  # noqa: E402
from stage1_tasking.service import Stage1Service  # noqa: E402
from stage1_tasking.source_blueprint import (  # noqa: E402
    PILOT_PROVINCE_PORTFOLIO,
    Stage1SourceBlueprintOrchestrator,
)
from storage import reset_default_storage  # noqa: E402


class TestStage1SourceBlueprint(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()
        self.market_scan_payload = {
            "scan_run_id": "MKTSCAN-145-001",
            "task_id": "TASK-145-001",
            "batch_id": "PTL-I100-ROADMAP-01",
            "now": "2026-04-29T00:00:00+00:00",
            "minimum_amount": 1000000,
            "analysis_score_threshold": 50,
            "notice_candidates": [
                {
                    "notice_id": "NOTICE-145-001",
                    "project_id": "PROJ-145-001",
                    "project_name": "Sichuan high-value construction candidate",
                    "region_code": "CN-SC",
                    "project_type": "construction",
                    "notice_stage": "candidate_notice",
                    "amount": 22000000,
                    "candidate_count": 3,
                    "candidate_company": "First Rank Construction Co",
                    "objection_deadline_at_optional": "2026-05-02T00:00:00+00:00",
                    "key_fields_present": [
                        "project_name",
                        "candidate_company",
                        "notice_stage",
                    ],
                }
            ],
        }
        self.market_scan = Stage1MarketScanEngine().run(self.market_scan_payload)

    def test_source_blueprint_auto_selects_source_mix_and_capture_plan_without_fetch(self) -> None:
        plan = Stage1SourceBlueprintOrchestrator().build({"scan_run_id": "MKTSCAN-145-001"})
        readback = Stage1SourceBlueprintOrchestrator().readback(plan["source_blueprint_plan_id"])
        replay = Stage1SourceBlueprintOrchestrator().replay(plan["source_blueprint_plan_id"])

        self.assertEqual(plan["capability_state"], "INTERNAL_READY")
        self.assertTrue(plan["source_blueprint_auto_selection"])
        self.assertTrue(plan["stage2_capture_plan_generation"])
        self.assertFalse(plan["stage2_fetch_executed"])
        self.assertFalse(plan["real_external_fetch_enabled"])
        self.assertFalse(plan["capture_execution_enabled"])
        self.assertFalse(plan["customer_visible"])
        self.assertFalse(plan["source_approval_summary"]["unapproved_source_selected"])

        source_mix = {source["surface_key"]: source for source in plan["source_mix"]}
        for required_surface in (
            "trading_platform",
            "government_procurement",
            "national_construction_market_platform",
            "credit_china",
            "national_enterprise_credit_publicity_system",
            "industry_authority_filing",
        ):
            self.assertIn(required_surface, source_mix)
            self.assertTrue(source_mix[required_surface]["selected"])
            self.assertTrue(source_mix[required_surface]["approved"])

        city = source_mix["city_adapter"]
        self.assertFalse(city["selected"])
        self.assertEqual(city["skip_reason"], "skipped_without_coverage_gap_signal")
        selected_registry_ids = set(
            plan["stage2_capture_plan"]["selected_source_registry_ids"]
        )
        self.assertNotIn("SRC-REG-PROC-CITY-PDF", selected_registry_ids)
        self.assertIn("SRC-REG-GOV-PROCUREMENT-NOTICE", selected_registry_ids)
        self.assertIn("SRC-REG-CREDIT-CHINA-PUBLIC-RECORD", selected_registry_ids)
        self.assertTrue(
            all(step["approved"] for step in plan["stage2_capture_plan"]["capture_steps"])
        )

        national_policy = plan["national_aggregator_policy"]
        self.assertEqual(national_policy["role"], "FIRST_LEVEL_DISCOVERY_AND_DEDUPE_ONLY")
        self.assertIn("full_coverage", national_policy["not_assumed"])
        self.assertIn("realtime_sync", national_policy["not_assumed"])

        pilot_codes = {row["region_code"] for row in plan["pilot_province_portfolio"]}
        self.assertEqual(pilot_codes, {row["region_code"] for row in PILOT_PROVINCE_PORTFOLIO})
        self.assertEqual(readback["readback_state"], "READBACK_READY")
        self.assertEqual(replay["replay_state"], "REPLAY_READY")
        self.assertFalse(replay["stage2_fetch_executed"])

    def test_city_adapter_is_gap_driven_not_blanket_rollout(self) -> None:
        plan = Stage1SourceBlueprintOrchestrator().build(
            {
                "scan_run_id": "MKTSCAN-145-001",
                "coverage_gap_signals": [
                    "province_platform_missing_detail_or_attachment",
                ],
            }
        )

        source_mix = {source["surface_key"]: source for source in plan["source_mix"]}
        city = source_mix["city_adapter"]
        self.assertTrue(city["selected"])
        self.assertTrue(city["triggered_by_coverage_gap"])
        self.assertIn(
            "province_platform_missing_detail_or_attachment",
            city["trigger_signals"],
        )
        self.assertEqual(
            plan["coverage_gap_policy"]["city_adapter_trigger_mode"],
            "GAP_DRIVEN_ONLY",
        )
        self.assertFalse(plan["coverage_gap_policy"]["blanket_city_rollout_enabled"])
        city_steps = [
            step
            for step in plan["stage2_capture_plan"]["capture_steps"]
            if step["source_registry_id"] == "SRC-REG-PROC-CITY-PDF"
        ]
        self.assertEqual(len(city_steps), 1)
        self.assertTrue(city_steps[0]["triggered_by_coverage_gap"])

    def test_beijing_candidate_is_technical_regression_not_first_batch_commercial_pilot(self) -> None:
        candidate = {
            **self.market_scan["opportunity_candidates"][0],
            "opportunity_candidate_id": "OPP-BEIJING-001",
            "project_id": "PROJ-BEIJING-001",
            "region_code": "CN-BJ",
        }

        plan = Stage1SourceBlueprintOrchestrator().build(
            {
                "source_blueprint_plan_id": "SRCBLUE-BEIJING-001",
                "opportunity_candidate": candidate,
            }
        )

        policy = plan["commercial_pilot_policy"]
        self.assertFalse(policy["commercial_pilot_eligible"])
        self.assertFalse(policy["beijing_first_batch_commercial_pilot"])
        self.assertEqual(policy["beijing_policy"], "TECHNICAL_REGRESSION_ONLY")

    def test_service_and_api_helpers_expose_source_blueprint_readback(self) -> None:
        service_plan = Stage1Service().build_source_blueprint(
            {
                "scan_run_id": "MKTSCAN-145-001",
                "source_blueprint_plan_id": "SRCBLUE-SERVICE-001",
            }
        )
        api_plan = create_stage1_source_blueprint_plan(
            {
                "scan_run_id": "MKTSCAN-145-001",
                "source_blueprint_plan_id": "SRCBLUE-API-001",
            }
        )
        api_readback = read_stage1_source_blueprint_plan(
            {"source_blueprint_plan_id": "SRCBLUE-API-001"}
        )

        self.assertEqual(service_plan["next_action"], "DISPATCH_STAGE2_CAPTURE_PLAN")
        self.assertEqual(api_plan["source_blueprint_plan_id"], "SRCBLUE-API-001")
        self.assertEqual(api_readback["readback_state"], "READBACK_READY")
        self.assertTrue(api_readback["readback_summary"]["stage2_capture_plan_generation"])

    def test_source_blueprint_blocks_execution_flags(self) -> None:
        for extra in (
            {"stage2_fetch_execute": True},
            {"real_external_fetch_enabled": True},
            {"capture_execution_enabled": True},
            {"unregistered_capture_enabled": True},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    Stage1SourceBlueprintOrchestrator().build(
                        {"scan_run_id": "MKTSCAN-145-001", **extra}
                    )


if __name__ == "__main__":
    unittest.main()
