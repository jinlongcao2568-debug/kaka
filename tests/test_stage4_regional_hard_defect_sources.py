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
        self.assertEqual(plan["query_context"]["project_name"], "广东市政道路工程")
        self.assertTrue(plan["no_no-risk_inference_without_sources"])


if __name__ == "__main__":
    unittest.main()
