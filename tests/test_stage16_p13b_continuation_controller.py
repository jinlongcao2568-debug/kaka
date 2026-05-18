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

from storage.stage16_p13b_continuation_controller import (  # noqa: E402
    build_stage16_p13b_continuation_controller,
)


class Stage16P13BContinuationControllerTests(unittest.TestCase):
    def test_builds_p13b_input_for_ready_construction_projects_and_defers_design(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_json = root / "storage.json"
            supplement_inputs = root / "stage4-inputs.json"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_inputs)

            result = build_stage16_p13b_continuation_controller(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_inputs,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["source_project_count"], 3)
            self.assertEqual(summary["ready_for_p13b_count"], 2)
            self.assertEqual(
                summary["continuation_state_counts"],
                {
                    "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER": 1,
                    "READY_FOR_P13B_DATA_GGZY": 2,
                },
            )

            project_table = json.loads((root / "out" / "project-value-table.json").read_text(encoding="utf-8"))
            candidate_table = json.loads(
                (root / "out" / "candidate-group-verification-table.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(project_table["records"]), 2)
            by_project = {record["project_id"]: record for record in candidate_table["records"]}
            self.assertEqual(
                by_project["PROJ-CN-GD-JG2026-11398-002"]["certificate_no"],
                "鄂1422014201516008",
            )
            self.assertEqual(
                by_project["PROJ-CN-GD-JG2026-11398-002"]["candidate_group_members"],
                ["中国化学工程第六建设有限公司", "中国市政工程华北设计研究总院有限公司"],
            )
            self.assertEqual(
                by_project["PROJ-CN-GD-JG2026-11398-001"]["candidate_group_members"],
                ["上海能源建设集团有限公司", "上海能源建设工程设计研究有限公司"],
            )
            self.assertEqual(
                by_project["PROJ-CN-GD-JG2026-11398-001"]["current_project_time_window"]["start_at"],
                "2026-08-01",
            )
            self.assertEqual(
                project_table["records"][1]["current_project_time_window"]["end_at"],
                "2027-02-01",
            )


def _write_stage16_storage(path: Path) -> None:
    candidates = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "project_name": "RQSG2中标候选人公示",
            "source_url": "https://example.test/rqsg2.html",
            "candidate_company": "（主）中国化学工程第六建设有限公司,（成）中国市政工程华北设计研究总院有限公司",
            "primary_responsible_person_name": "曾凡伟",
            "project_manager_name": "曾凡伟",
            "project_manager_certificate_no": "",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-001",
            "project_name": "RQSG1中标候选人公示",
            "source_url": "https://example.test/rqsg1.html",
            "candidate_company": "（主）上海能源建设集团有限公司,（成）上海能源建设工程设计研究有限公司",
            "primary_responsible_person_name": "王杰",
            "project_manager_name": "王杰",
            "project_manager_certificate_no": "22ZEZACJ0034",
            "current_project_time_window": {"start_at": "2026-08-01", "end_at": "2027-02-01"},
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
            "project_manager_name": "",
            "project_manager_certificate_no": "",
            "engineering_work_lane": "survey_design",
            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
    ]
    closed = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": True,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "REVIEW",
            },
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-001",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        },
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


def _write_company_first_inputs(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "project_name": "RQSG2中标候选人公示",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "candidate_group_id": "CANDIDATE-GROUP-JG2026-11398-002-COMPANY-FIRST-1",
                        "candidate_group_members": ["中国化学工程第六建设有限公司", "中国市政工程华北设计研究总院有限公司"],
                        "responsible_person_name": "曾凡伟",
                        "certificate_no": "鄂1422014201516008",
                        "person_public_id_optional": "002303160131952780",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
