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
    ACTIVE_CONFLICT_SCOPE_MODE,
    build_stage45_verification_scope_policy,
    scope_rule_by_key,
)


class Stage4VerificationScopePolicyTests(unittest.TestCase):
    def test_project_manager_active_conflict_uses_national_discovery_then_targeted_regions(self) -> None:
        policy = build_stage45_verification_scope_policy(
            {
                "project_id": "PROJ-GD-001",
                "project_name": "广东市政道路工程",
                "candidate_company": "广东测试建设有限公司",
                "project_manager_name": "张三",
                "region_code": "CN-GD",
            }
        )

        region_discovery = scope_rule_by_key(policy, "company_manager_project_region_discovery")
        active_conflict = scope_rule_by_key(policy, "project_manager_active_conflict")
        current_project = scope_rule_by_key(policy, "current_project_permit_contract_completion")

        self.assertEqual(region_discovery["scope_mode"], ACTIVE_CONFLICT_SCOPE_MODE)
        self.assertEqual(active_conflict["scope_mode"], ACTIVE_CONFLICT_SCOPE_MODE)
        self.assertTrue(active_conflict["cross_region_required"])
        self.assertTrue(active_conflict["current_region_only_is_insufficient"])
        self.assertTrue(active_conflict["targeted_region_verification_required"])
        self.assertFalse(active_conflict["all_region_bruteforce_required"])
        self.assertIn("candidate_company_first", region_discovery["query_sequence"])
        self.assertIn("appeared_region_codes", region_discovery["discovery_outputs"])
        self.assertEqual(active_conflict["primary_regions"], ["CN-NATIONAL"])
        self.assertIn("CN-GD", active_conflict["supplementary_regions"])
        self.assertIn("JZSC-NATIONAL-PERSON", active_conflict["primary_profile_ids"])
        self.assertEqual(current_project["scope_mode"], "CURRENT_PROJECT_JURISDICTION_ONLY")
        self.assertEqual(current_project["primary_regions"], ["CN-GD"])
        self.assertIn("company_manager_project_region_discovery", policy["expanded_scope_keys"])
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
        region_discovery = entries["NATIONAL-JZSC-COMPANY-MANAGER-REGION-DISCOVERY"]
        national_pm = entries["NATIONAL-JZSC-PM-ACTIVE-CONFLICT"]
        gd_project = entries["GD-GDCIC-SKYPT-PROJECT"]

        self.assertEqual(region_discovery["scope_mode"], ACTIVE_CONFLICT_SCOPE_MODE)
        self.assertEqual(national_pm["scope_mode"], ACTIVE_CONFLICT_SCOPE_MODE)
        self.assertTrue(national_pm["cross_region_required"])
        self.assertTrue(national_pm["current_region_only_is_insufficient"])
        self.assertFalse(region_discovery["all_region_bruteforce_required"])
        self.assertIn("appeared_region_codes", region_discovery["discovery_outputs"])
        self.assertIn("discovered_region_codes", national_pm["query_keys"])
        self.assertIn("performance_public_record", national_pm["target_source_types"])
        self.assertIn("completion_filing", national_pm["target_source_types"])
        self.assertEqual(
            gd_project["scope_mode"],
            "CURRENT_PROJECT_JURISDICTION_ONLY_FOR_CURRENT_PROJECT_RECORDS",
        )
        self.assertIn(
            "project_manager_active_conflict_requires_national_discovery_then_targeted_regions",
            plan["scope_warnings"],
        )
        self.assertIn("all_region_bruteforce_not_required", plan["scope_warnings"])
        self.assertIn(
            "jzsc_company_manager_project_region_discovery",
            plan["next_required_runtime_adapters"],
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
            ACTIVE_CONFLICT_SCOPE_MODE,
        )
        self.assertTrue(carrier["verification_scope_policy"]["current_region_only_is_insufficient"])
        self.assertEqual(readback["active_conflict_scope_mode"], ACTIVE_CONFLICT_SCOPE_MODE)
        self.assertTrue(readback["current_region_only_is_insufficient"])
        self.assertFalse(readback["all_region_bruteforce_required"])
        self.assertTrue(readback["targeted_region_verification_required"])
        self.assertEqual(
            readback["active_conflict_region_discovery"]["scope_mode"],
            ACTIVE_CONFLICT_SCOPE_MODE,
        )
        self.assertFalse(readback["active_conflict_region_discovery"]["discovery_completed"])
        self.assertIn(
            "possible_conflicting_project_public_record_missing",
            carrier["failure_reasons"],
        )
        self.assertIn(
            "company_manager_project_region_discovery_missing",
            carrier["failure_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
