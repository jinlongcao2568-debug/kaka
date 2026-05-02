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
from stage4_verification.service import Stage4Service  # noqa: E402
from stage4_verification.verification_scope_policy import (  # noqa: E402
    build_stage45_verification_scope_policy,
    scope_rule_by_key,
)


class Stage4VerificationScopePolicyTests(unittest.TestCase):
    def test_project_manager_active_conflict_is_national_not_current_region_only(self) -> None:
        policy = build_stage45_verification_scope_policy(
            {
                "project_id": "PROJ-GD-001",
                "project_name": "广东市政道路工程",
                "candidate_company": "广东测试建设有限公司",
                "project_manager_name": "张三",
                "region_code": "CN-GD",
            }
        )

        active_conflict = scope_rule_by_key(policy, "project_manager_active_conflict")
        current_project = scope_rule_by_key(policy, "current_project_permit_contract_completion")

        self.assertEqual(active_conflict["scope_mode"], "NATIONAL_REQUIRED")
        self.assertTrue(active_conflict["cross_region_required"])
        self.assertTrue(active_conflict["current_region_only_is_insufficient"])
        self.assertEqual(active_conflict["primary_regions"], ["CN-NATIONAL"])
        self.assertIn("CN-GD", active_conflict["supplementary_regions"])
        self.assertIn("JZSC-NATIONAL-PERSON", active_conflict["primary_profile_ids"])
        self.assertEqual(current_project["scope_mode"], "CURRENT_PROJECT_JURISDICTION_ONLY")
        self.assertEqual(current_project["primary_regions"], ["CN-GD"])
        self.assertIn("project_manager_active_conflict", policy["expanded_scope_keys"])
        self.assertIn("current_project_permit_contract_completion", policy["fixed_scope_keys"])

    def test_guangdong_source_plan_exposes_national_active_conflict_entry(self) -> None:
        plan = build_regional_hard_defect_source_plan(
            {
                "project_id": "PROJ-GD-001",
                "project_name": "广东市政道路工程",
                "candidate_company": "广东测试建设有限公司",
                "project_manager_name": "张三",
                "region_code": "CN-GD",
            }
        )

        entries = {entry["entry_id"]: entry for entry in plan["source_entries"]}
        national_pm = entries["NATIONAL-JZSC-PM-ACTIVE-CONFLICT"]
        gd_project = entries["GD-GDCIC-SKYPT-PROJECT"]

        self.assertEqual(national_pm["scope_mode"], "NATIONAL_REQUIRED")
        self.assertTrue(national_pm["cross_region_required"])
        self.assertTrue(national_pm["current_region_only_is_insufficient"])
        self.assertIn("performance_public_record", national_pm["target_source_types"])
        self.assertIn("completion_filing", national_pm["target_source_types"])
        self.assertEqual(
            gd_project["scope_mode"],
            "CURRENT_PROJECT_JURISDICTION_ONLY_FOR_CURRENT_PROJECT_RECORDS",
        )
        self.assertIn(
            "project_manager_active_conflict_requires_national_scope",
            plan["scope_warnings"],
        )
        self.assertIn(
            "jzsc_company_first_project_manager_active_conflict_query",
            plan["next_required_runtime_adapters"],
        )

    def test_active_conflict_readback_carries_national_scope_warning(self) -> None:
        carrier = Stage4Service().evaluate_project_manager_active_conflict(
            {
                "current_project_id": "PRJ-CURRENT-001",
                "current_project_name": "广东当前项目",
                "candidate_company_name": "广东测试建设有限公司",
                "project_manager_name": "张三",
                "region_code": "CN-GD",
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            public_verification_carriers=[],
            possible_conflicting_projects=[],
        )
        readback = Stage4Service().build_project_manager_active_conflict_readback(carrier)

        self.assertEqual(
            carrier["verification_scope_policy"]["active_conflict_scope_mode"],
            "NATIONAL_REQUIRED",
        )
        self.assertTrue(carrier["verification_scope_policy"]["current_region_only_is_insufficient"])
        self.assertEqual(readback["active_conflict_scope_mode"], "NATIONAL_REQUIRED")
        self.assertTrue(readback["current_region_only_is_insufficient"])
        self.assertIn(
            "possible_conflicting_project_public_record_missing",
            carrier["failure_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
