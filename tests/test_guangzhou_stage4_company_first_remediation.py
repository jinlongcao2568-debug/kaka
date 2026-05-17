from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.guangzhou_stage4_company_first_remediation import (  # noqa: E402
    build_guangzhou_stage4_company_first_remediation,
)


class GuangzhouStage4CompanyFirstRemediationTests(unittest.TestCase):
    def test_filters_four_candidates_and_maps_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_run_result(root / "run-result.json")
            _write_candidate_pressure(root / "candidate-pressure-table.json")

            result = build_guangzhou_stage4_company_first_remediation(
                run_result_json=root / "run-result.json",
                candidate_pressure_json=root / "candidate-pressure-table.json",
                output_root=root / "out",
                execute=True,
                execution_builder=_fake_execution_builder,
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["candidate_count"], 4)
            self.assertEqual(summary["stage4_input_count"], 4)
            self.assertEqual(summary["remediation_state_counts"]["COMPANY_FIRST_CERTIFICATE_RESOLVED"], 2)
            self.assertEqual(summary["remediation_state_counts"]["NAME_ENUMERATION_FALLBACK_REQUIRED"], 1)
            self.assertEqual(summary["remediation_state_counts"]["REVIEW_REQUIRED"], 1)
            records = {row["project_id"]: row for row in result["manifest"]["candidate_records"]}
            self.assertEqual(records["PROJ-1"]["remediation_state"], "COMPANY_FIRST_CERTIFICATE_RESOLVED")
            self.assertEqual(records["PROJ-2"]["remediation_state"], "COMPANY_FIRST_CERTIFICATE_RESOLVED")
            self.assertEqual(records["PROJ-3"]["remediation_state"], "NAME_ENUMERATION_FALLBACK_REQUIRED")
            self.assertEqual(records["PROJ-4"]["remediation_state"], "REVIEW_REQUIRED")
            self.assertTrue(records["PROJ-1"]["replay_field_writeback"]["project_manager_certificate_no"])
            self.assertEqual(records["PROJ-4"]["recommended_next_action"], "run_stage4_source_gap_probe_for_role_identity_completion")
            self.assertTrue((root / "out" / "company-first-remediation-v1.json").exists())
            self.assertTrue((root / "out" / "company-first-candidate-table.json").exists())

    def test_forbidden_terms_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_run_result(root / "run-result.json", project_name="无风险项目")
            _write_candidate_pressure(root / "candidate-pressure-table.json")

            result = build_guangzhou_stage4_company_first_remediation(
                run_result_json=root / "run-result.json",
                candidate_pressure_json=root / "candidate-pressure-table.json",
                output_root=root / "out",
                execute=False,
                execution_builder=_fake_execution_builder,
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["summary"]["forbidden_term_scan_state"], "FAIL")


def _write_run_result(path: Path, project_name: str = "广州候选项目") -> None:
    payload = {
        "candidate_options": [
            {
                "project_id": "PROJ-1",
                "project_name": project_name,
                "source_url": "https://example.invalid/1",
                "candidate_company": "(主)广东甲公司;(成)广东乙公司",
                "project_manager_name": "张三",
                "project_manager_certificate_no": "",
                "primary_responsible_person_name": "张三",
                "primary_responsible_role": "project_manager",
                "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            },
            {
                "project_id": "PROJ-2",
                "project_name": "广州候选项目二",
                "source_url": "https://example.invalid/2",
                "candidate_company": "广州丙公司",
                "project_manager_name": "李四",
                "project_manager_certificate_no": "",
                "primary_responsible_person_name": "李四",
                "primary_responsible_role": "project_manager",
                "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            },
            {
                "project_id": "PROJ-3",
                "project_name": "广州候选项目三",
                "source_url": "https://example.invalid/3",
                "candidate_company": "广州丁公司",
                "project_manager_name": "王五",
                "project_manager_certificate_no": "",
                "primary_responsible_person_name": "王五",
                "primary_responsible_role": "project_manager",
                "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            },
            {
                "project_id": "PROJ-4",
                "project_name": "广州候选项目四",
                "source_url": "https://example.invalid/4",
                "candidate_company": "广州戊公司",
                "project_manager_name": "",
                "project_manager_certificate_no": "",
                "primary_responsible_person_name": "",
                "primary_responsible_role": "project_manager",
                "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            },
            {
                "project_id": "PROJ-5",
                "project_name": "广州候选项目五",
                "source_url": "https://example.invalid/5",
                "candidate_company": "广州己公司",
                "project_manager_name": "赵六",
                "project_manager_certificate_no": "粤144202020202020",
                "primary_responsible_person_name": "赵六",
                "primary_responsible_role": "project_manager",
                "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            },
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_candidate_pressure(path: Path) -> None:
    payload = {
        "records": [
            {"project_id": "PROJ-1", "jzsc_company_first_identity_resolution_required": True, "responsible_role_gap_code": ""},
            {"project_id": "PROJ-2", "jzsc_company_first_identity_resolution_required": True, "responsible_role_gap_code": ""},
            {"project_id": "PROJ-3", "jzsc_company_first_identity_resolution_required": True, "responsible_role_gap_code": ""},
            {"project_id": "PROJ-4", "jzsc_company_first_identity_resolution_required": False, "responsible_role_gap_code": "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY"},
            {"project_id": "PROJ-5", "jzsc_company_first_identity_resolution_required": False, "responsible_role_gap_code": ""},
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fake_execution_builder(**kwargs: object) -> dict[str, object]:
    stage4_inputs_json = Path(str(kwargs["stage4_inputs_json"]))
    payload = json.loads(stage4_inputs_json.read_text(encoding="utf-8"))
    items = [
        {
            "project_id": "PROJ-1",
            "candidate_group_id": payload["items"][0]["candidate_group_id"],
            "responsible_person_name": "张三",
            "candidate_company_name": "广东甲公司",
            "candidate_group_resolution_state": "RESOLVED_BY_THIS_MEMBER",
            "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
            "resolved_certificate_no_optional": "粤1442020202100011",
            "person_public_id_optional": "person-zhang",
            "matched_company_name_optional": "广东甲公司",
        },
        {
            "project_id": "PROJ-1",
            "candidate_group_id": payload["items"][1]["candidate_group_id"],
            "responsible_person_name": "张三",
            "candidate_company_name": "广东乙公司",
            "candidate_group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER",
            "supplement_after_execution_state": "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED",
            "resolved_certificate_no_optional": "",
            "person_public_id_optional": "",
            "matched_company_name_optional": "广东甲公司",
        },
        {
            "project_id": "PROJ-2",
            "candidate_group_id": payload["items"][2]["candidate_group_id"],
            "responsible_person_name": "李四",
            "candidate_company_name": "广州丙公司",
            "candidate_group_resolution_state": "RESOLVED_BY_THIS_MEMBER",
            "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
            "resolved_certificate_no_optional": "粤1442020202100012",
            "person_public_id_optional": "person-li",
            "matched_company_name_optional": "广州丙公司",
        },
        {
            "project_id": "PROJ-3",
            "candidate_group_id": payload["items"][3]["candidate_group_id"],
            "responsible_person_name": "王五",
            "candidate_company_name": "广州丁公司",
            "candidate_group_resolution_state": "UNRESOLVED_NO_MEMBER_MATCHED",
            "supplement_after_execution_state": "NAME_ENUMERATION_FALLBACK_REQUIRED",
            "resolved_certificate_no_optional": "",
            "person_public_id_optional": "",
            "matched_company_name_optional": "",
        },
    ]
    return {
        "summary": {"job_count": len(items), "stage4_input_count": 2},
        "manifest": {"items": items},
    }


if __name__ == "__main__":
    unittest.main()
