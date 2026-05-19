from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.provider_registry import NATURAL_RESOURCE_REGISTERED_SURVEYOR  # noqa: E402
from storage.design_survey_public_registry_fallback import (  # noqa: E402
    REGISTERED_SURVEYOR_REGISTRY_URL,
    build_design_survey_public_registry_fallback,
)


class DesignSurveyPublicRegistryFallbackTests(unittest.TestCase):
    def test_flow08_jzsc_miss_builds_registered_surveyor_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stage4_root = root / "stage4"
            flow08_inputs = root / "flow08-inputs.json"
            flow08_parse_root = root / "parse"
            _write_stage4_public_registry_required(stage4_root, with_certificate=False)
            _write_flow08_stage4_inputs(flow08_inputs, with_certificate=False)
            _write_flow08_parse(flow08_parse_root)

            result = build_design_survey_public_registry_fallback(
                design_survey_stage4_execution_root=stage4_root,
                flow08_stage4_inputs_json=flow08_inputs,
                flow08_attachment_parse_root=flow08_parse_root,
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["target_record_count"], 1)
            self.assertEqual(summary["primary_registered_surveyor_task_count"], 1)
            self.assertEqual(summary["flow08_certificate_extraction_task_count"], 1)

            task_table = result["manifest"]["public_registry_task_table"]
            task_types = {record["task_type"] for record in task_table["records"]}
            self.assertIn("NATURAL_RESOURCE_REGISTERED_SURVEYOR_PERSON_COMPANY_MATCH", task_types)
            self.assertIn("FLOW08_REGISTERED_SURVEYOR_CERTIFICATE_FIELD_EXTRACTION", task_types)
            natural_task = next(
                record
                for record in task_table["records"]
                if record["task_type"] == "NATURAL_RESOURCE_REGISTERED_SURVEYOR_PERSON_COMPANY_MATCH"
            )
            self.assertEqual(natural_task["provider_id"], NATURAL_RESOURCE_REGISTERED_SURVEYOR)
            self.assertEqual(natural_task["source_entry"]["entry_url"], REGISTERED_SURVEYOR_REGISTRY_URL)
            self.assertEqual(natural_task["query_fields"]["person_name"], "胡昌华")
            self.assertTrue(natural_task["matching_policy"]["name_only_is_not_final_proof"])

            jobs = result["manifest"]["stage4_provider_jobs"]["jobs"]
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["provider_id"], NATURAL_RESOURCE_REGISTERED_SURVEYOR)
            self.assertTrue((root / "out" / "stage4_provider_jobs.json").exists())

    def test_existing_certificate_skips_flow08_certificate_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stage4_root = root / "stage4"
            _write_stage4_public_registry_required(stage4_root, with_certificate=True)

            result = build_design_survey_public_registry_fallback(
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["primary_registered_surveyor_task_count"], 1)
            self.assertEqual(result["summary"]["flow08_certificate_extraction_task_count"], 0)
            target = result["manifest"]["public_registry_target_table"]["records"][0]
            self.assertEqual(target["certificate_no_optional"], "粤测绘20260001")


def _write_stage4_public_registry_required(root: Path, *, with_certificate: bool) -> None:
    item = {
        "job_id": "STAGE4-FLOW08-INPUT-JOB-1",
        "project_id": "PROJ-CN-GD-JG2026-11327",
        "project_name": "规划测绘项目中标候选人公示",
        "candidate_company_name": "广州市城市规划勘测设计研究院有限公司",
        "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
        "candidate_group_members": [
            "广州市城市规划勘测设计研究院有限公司",
            "广州湾区规划勘测设计院有限公司",
        ],
        "responsible_person_name": "胡昌华",
        "responsible_role": "survey_mapping_project_lead",
        "source_probe_adapter_id": "design-survey-flow08-stage4-inputs-v1",
        "source_flow08_attachment_url": "https://jsgc.gzggzy.cn/download?AttachGuid=union",
        "source_flow08_attachment_snapshot_id": "SNAP-FLOW08",
        "stage4_execution_state": "FAIL_CLOSED",
        "identity_resolution_state": "UNKNOWN",
        "supplement_after_execution_state": "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
        "source_certificate_no_optional": "粤测绘20260001" if with_certificate else "",
        "flow_08_targeted_parse_required": False,
        "candidate_group_resolution_state": "UNRESOLVED_NO_MEMBER_MATCHED",
        "fail_closed_reasons": ["project_manager_not_found_by_company_name_person_name_after_1_attempts"],
    }
    _write_json(
        root / "company-first-stage4-execution.json",
        {
            "manifest": {
                "items": [item],
                "stage4_candidate_verification_inputs": {"items": []},
                "summary": {"project_count": 1, "job_count": 1},
            }
        },
    )


def _write_flow08_stage4_inputs(path: Path, *, with_certificate: bool) -> None:
    _write_json(
        path,
        {
            "manifest_kind": "stage4_candidate_verification_inputs",
            "items": [
                {
                    "source_probe_adapter_id": "design-survey-flow08-stage4-inputs-v1",
                    "project_id": "PROJ-CN-GD-JG2026-11327",
                    "project_name": "规划测绘项目中标候选人公示",
                    "candidate_company_name": "广州市城市规划勘测设计研究院有限公司",
                    "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
                    "candidate_group_members": [
                        "广州市城市规划勘测设计研究院有限公司",
                        "广州湾区规划勘测设计院有限公司",
                    ],
                    "responsible_person_name": "胡昌华",
                    "responsible_role": "survey_mapping_project_lead",
                    "certificate_no": "粤测绘20260001" if with_certificate else "",
                    "source_flow08_attachment_url": "https://jsgc.gzggzy.cn/download?AttachGuid=union",
                    "source_flow08_attachment_snapshot_id": "SNAP-FLOW08",
                    "flow08_current_candidate_binding_evidence": {
                        "current_project_binding_state": "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND",
                        "planned_page_ranges": "216-282",
                        "document_work_path": "tmp/work/SNAP-FLOW08.pdf",
                        "extraction_json_path": "tmp/extractions/flow08.json",
                        "not_public_registration_proof": True,
                    },
                }
            ],
        },
    )


def _write_flow08_parse(root: Path) -> None:
    _write_json(
        root / "design-survey-flow08-target-attachment-parse-v1.json",
        {
            "manifest": {
                "target_attachment_parse_table": {
                    "records": [
                        {
                            "target_attachment_parse_id": "PARSE-1",
                            "project_id": "PROJ-CN-GD-JG2026-11327",
                            "attachment_parse_state": "TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED",
                            "attachment_snapshot_id_optional": "SNAP-FLOW08",
                            "document_work_path": "tmp/work/SNAP-FLOW08.pdf",
                            "extraction_json_path": "tmp/extractions/flow08.json",
                            "person_dossier_evidence": {
                                "person_dossier_state": "PERSON_DOSSIER_EXTRACTED",
                                "planned_page_ranges": "216-282",
                                "current_project_binding_state": "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND",
                            },
                        }
                    ]
                }
            }
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
