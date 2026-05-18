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

from storage.company_first_stage4_execution import build_company_first_stage4_execution  # noqa: E402
from storage.design_survey_responsible_adapter_plan import (  # noqa: E402
    CONSTRUCTION_RELEASE_TARGETS,
    build_design_survey_responsible_adapter_plan,
)


class DesignSurveyResponsibleAdapterPlanTests(unittest.TestCase):
    def test_builds_design_survey_stage4_inputs_and_plan_only_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_json = root / "storage.json"
            _write_stage16_storage(storage_json)

            result = build_design_survey_responsible_adapter_plan(
                stage16_storage_json=storage_json,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["design_survey_project_count"], 1)
            self.assertEqual(summary["ready_project_count"], 1)
            self.assertEqual(summary["stage4_input_count"], 2)
            self.assertEqual(summary["verification_task_count"], 7)
            self.assertEqual(
                summary["task_type_counts"],
                {
                    "CURRENT_NOTICE_BINDING_AND_ROLE_LINEAGE": 1,
                    "CURRENT_PROJECT_DESIGN_SURVEY_SERVICE_CLOCK": 1,
                    "DESIGN_SURVEY_ENTERPRISE_QUALIFICATION_CHECK": 2,
                    "DESIGN_SURVEY_PERSON_COMPANY_CERTIFICATE_MATCH": 2,
                    "PRIOR_DESIGN_SURVEY_AWARD_HISTORY_REVIEW": 1,
                },
            )

            stage4_inputs = result["manifest"]["stage4_candidate_verification_inputs"]
            companies = {item["candidate_company_name"] for item in stage4_inputs["items"]}
            self.assertEqual(
                companies,
                {"广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"},
            )
            self.assertEqual({item["responsible_role"] for item in stage4_inputs["items"]}, {"survey_mapping_project_lead"})
            self.assertEqual({item["responsible_person_name"] for item in stage4_inputs["items"]}, {"胡昌华"})

            task_table = result["manifest"]["design_survey_verification_task_table"]
            task_text = json.dumps(task_table, ensure_ascii=False)
            for forbidden_target in CONSTRUCTION_RELEASE_TARGETS:
                self.assertNotIn(forbidden_target, task_text)
            self.assertTrue(
                result["manifest"]["scope_guardrails"]["does_not_apply_construction_project_manager_release_rule"]
            )
            self.assertFalse(
                result["manifest"]["scope_guardrails"]["construction_release_source_targets_default_enabled"]
            )
            self.assertTrue((root / "out" / "design-survey-stage4-candidate-verification-inputs.json").exists())

    def test_generated_stage4_inputs_do_not_default_to_construction_certificate_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_json = root / "storage.json"
            _write_stage16_storage(storage_json)

            build_design_survey_responsible_adapter_plan(
                stage16_storage_json=storage_json,
                output_root=root / "plan",
                created_at="2026-05-18T00:00:00+08:00",
            )
            result = build_company_first_stage4_execution(
                input_root=root / "missing-provider-jobs",
                stage4_inputs_json=root / "plan" / "design-survey-stage4-candidate-verification-inputs.json",
                output_root=root / "stage4",
                execute=False,
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["job_count"], 2)
            self.assertEqual(
                {item["required_registration_category_optional"] for item in result["manifest"]["items"]},
                {""},
            )
            self.assertEqual(
                {item["supplement_after_execution_state"] for item in result["manifest"]["items"]},
                {"COMPANY_FIRST_PROVIDER_TASKS_READY"},
            )


def _write_stage16_storage(path: Path) -> None:
    candidates = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "project_name": "燃气管道迁改工程设计施工总承包RQSG2标段中标候选人公示",
            "source_url": "https://example.test/rqsg2.html",
            "candidate_company": "（主）中国化学工程第六建设有限公司,（成）中国市政工程华北设计研究总院有限公司",
            "primary_responsible_person_name": "曾凡伟",
            "project_manager_name": "曾凡伟",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "project_name": "规划测绘项目中标候选人公示",
            "source_url": "https://example.test/design.html",
            "candidate_company": "(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司",
            "primary_responsible_person_name": "胡昌华",
            "primary_responsible_role": "",
            "project_manager_name": "",
            "project_manager_certificate_no": "",
            "engineering_work_lane": "survey_design",
            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
            "current_project_period_text": "服务期：按招标文件要求完成规划测绘服务",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
    ]
    closed = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        }
    ]
    payload = {
        "operator_actions": {
            "operator-autonomous-opportunity-search-runs": [
                {
                    "object_refs": {
                        "candidate_options_json": json.dumps(candidates, ensure_ascii=False),
                        "closed_loop_results_json": json.dumps(closed, ensure_ascii=False),
                    }
                }
            ]
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
