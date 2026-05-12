from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.regional_hard_defect_sources import (  # noqa: E402
    build_regional_hard_defect_source_plan,
)


class Stage4RegionalHardDefectSourcePlanTests(unittest.TestCase):
    def test_guangdong_plan_lists_project_level_hard_defect_sources(self) -> None:
        plan = build_regional_hard_defect_source_plan(
            {
                "project_id": "PROJ-GD-001",
                "project_name": "广东市政道路工程",
                "candidate_company": "广东测试建设有限公司",
                "project_manager_name": "张三",
                "region_code": "CN-GD",
                "source_url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260501/mock.html?noticeId=1",
            },
            covered_source_types={"performance_public_record"},
        )

        self.assertEqual(plan["region_code"], "CN-GD")
        self.assertEqual(plan["coverage_state"], "PARTIAL")
        self.assertEqual(plan["plan_state"], "ENTRY_SOURCES_IDENTIFIED_PROJECT_LEVEL_QUERY_PENDING")
        self.assertIn("construction_permit", plan["missing_source_types"])
        self.assertIn("contract_public_info", plan["missing_source_types"])
        self.assertIn("completion_filing", plan["missing_source_types"])
        self.assertIn("project_manager_change_notice", plan["missing_source_types"])
        self.assertIn("administrative_penalty_public_record", plan["missing_source_types"])
        entry_ids = {entry["entry_id"] for entry in plan["source_entries"]}
        self.assertIn("GD-GDCIC-SKYPT-PROJECT", entry_ids)
        self.assertIn("GD-GDCIC-CONTRACT-PERFORMANCE", entry_ids)
        self.assertIn("GD-ZFCXJST-PENALTY", entry_ids)
        self.assertIn("GD-CREDIT-GD", entry_ids)
        self.assertIn("GZ-ZFCJ-CREDIT-DOUBLE-PUBLICITY", entry_ids)
        self.assertIn("ZJ-JZSC-PUBLIC-SERVICE", entry_ids)
        self.assertIn("SC-JZSC-PUBLIC-SERVICE", entry_ids)
        self.assertIn("JS-JZSC-INTEGRATED-PLATFORM", entry_ids)
        self.assertIn("HB-JZSC-INTEGRITY-PLATFORM", entry_ids)
        self.assertIn("SD-JZSC-CREDIT-SUPERVISION-PLATFORM", entry_ids)
        self.assertIn("HN-JZSC-PUBLIC-SERVICE", entry_ids)
        self.assertIn("HA-JZSC-PUBLIC-SERVICE", entry_ids)
        self.assertEqual(
            plan["major_target_region_policy"]["scope_mode"],
            "NATIONAL_DISCOVERY_THEN_MAJOR_REGION_TARGETED_VERIFICATION",
        )
        self.assertFalse(plan["major_target_region_policy"]["all_region_bruteforce_required"])
        self.assertIn("CN-ZJ", plan["major_target_region_policy"]["target_region_codes"])
        self.assertIn("CN-SD", plan["major_target_region_policy"]["target_region_codes"])
        self.assertIn(
            "zhejiang_construction_market_public_service_query_adapter",
            plan["next_required_runtime_adapters"],
        )
        gz_entry = next(
            entry
            for entry in plan["source_entries"]
            if entry["entry_id"] == "GZ-ZFCJ-CREDIT-DOUBLE-PUBLICITY"
        )
        self.assertEqual(gz_entry["runtime_status"], "CITY_PUBLIC_API_QUERY_ADAPTER_AVAILABLE")
        self.assertEqual(gz_entry["next_adapter"], "guangzhou_zfcj_xyxx_api_query_v1")
        credit_entry = next(entry for entry in plan["source_entries"] if entry["entry_id"] == "GD-CREDIT-GD")
        self.assertEqual(
            credit_entry["runtime_status"],
            "PUBLIC_CREDIT_LIST_QUERY_ADAPTER_AVAILABLE_WITH_WAF_GUARD",
        )
        self.assertIn("administrative_license_public_record", credit_entry["target_source_types"])
        self.assertIn("administrative_penalty_public_record", credit_entry["target_source_types"])
        self.assertEqual(credit_entry["next_adapter"], "guangdong_credit_gd_public_credit_query_v1")
        self.assertEqual(plan["query_context"]["project_name"], "广东市政道路工程")
        self.assertTrue(plan["no_no-risk_inference_without_sources"])

    def test_generic_plan_still_exposes_major_region_catalog_for_cross_region_checks(self) -> None:
        plan = build_regional_hard_defect_source_plan(
            {
                "project_id": "PROJ-OTHER-001",
                "project_name": "跨省业绩项目",
                "candidate_company": "外省测试建设有限公司",
                "project_manager_name": "李四",
                "region_code": "CN-NATIONAL",
            }
        )

        entry_regions = {entry["region_code"] for entry in plan["source_entries"]}
        self.assertIn("CN-ZJ", entry_regions)
        self.assertIn("CN-SC", entry_regions)
        self.assertIn("CN-JS", entry_regions)
        self.assertIn("CN-SD", entry_regions)
        self.assertIn("major_region_source_catalog_is_plan_only_until_adapter_verified", plan["scope_warnings"])
        self.assertIn(
            "jiangsu_construction_market_integrated_platform_query_adapter",
            plan["next_required_runtime_adapters"],
        )


if __name__ == "__main__":
    unittest.main()
