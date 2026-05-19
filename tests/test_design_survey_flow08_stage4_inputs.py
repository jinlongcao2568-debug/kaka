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

from storage.design_survey_flow08_stage4_inputs import (  # noqa: E402
    build_design_survey_flow08_stage4_inputs,
)


class DesignSurveyFlow08Stage4InputsTests(unittest.TestCase):
    def test_person_dossier_builds_standard_stage4_inputs_for_consortium(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            parse_root = root / "parse"
            _write_parse_manifest(parse_root, state="TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED")

            result = build_design_survey_flow08_stage4_inputs(
                design_survey_flow08_attachment_parse_root=parse_root,
                output_root=root / "out",
                created_at="2026-05-18T21:30:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["stage4_input_count"], 2)
            items = result["manifest"]["stage4_candidate_verification_inputs"]["items"]
            self.assertEqual(
                {item["candidate_company_name"] for item in items},
                {"广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"},
            )
            self.assertTrue(all(item["candidate_group_match_mode"] == "ANY_CONSORTIUM_MEMBER" for item in items))
            self.assertTrue(all(item["responsible_person_name"] == "胡昌华" for item in items))
            evidence = items[0]["flow08_current_candidate_binding_evidence"]
            self.assertEqual(evidence["current_project_binding_state"], "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND")
            self.assertEqual(evidence["planned_page_ranges"], "214-286")
            self.assertTrue(evidence["not_public_registration_proof"])
            self.assertIn("4401********567X", json.dumps(evidence["evidence_page_refs"], ensure_ascii=False))
            self.assertNotIn("44010119900101567X", json.dumps(evidence["evidence_page_refs"], ensure_ascii=False))
            self.assertTrue((root / "out" / "stage4_candidate_verification_inputs.json").exists())

    def test_extracted_fields_keep_certificate_for_stage4_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            parse_root = root / "parse"
            _write_parse_manifest(parse_root, state="TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED")

            result = build_design_survey_flow08_stage4_inputs(
                design_survey_flow08_attachment_parse_root=parse_root,
                output_root=root / "out",
                created_at="2026-05-18T21:30:00+08:00",
            )

            items = result["manifest"]["stage4_candidate_verification_inputs"]["items"]
            self.assertEqual(items[0]["certificate_no"], "粤测绘20260001")
            self.assertEqual(items[0]["responsible_role"], "survey_design_project_lead")
            self.assertEqual(
                result["manifest"]["stage4_candidate_verification_inputs"]["summary"]["with_certificate_count"],
                2,
            )


def _write_parse_manifest(root: Path, *, state: str) -> None:
    record: dict[str, Any] = {
        "target_attachment_parse_id": "DESIGN-SURVEY-FLOW08-PARSE-1",
        "target_attachment_id": "DESIGN-SURVEY-FLOW08-ATTACH-1",
        "project_id": "PROJ-CN-GD-JG2026-11327",
        "project_name": "规划测绘项目中标候选人公示",
        "candidate_company_text": "(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司",
        "target_company_names": [
            "广州市城市规划勘测设计研究院有限公司",
            "广州湾区规划勘测设计院有限公司",
        ],
        "matched_target_company_names": [
            "广州市城市规划勘测设计研究院有限公司",
            "广州湾区规划勘测设计院有限公司",
        ],
        "responsible_person_name": "胡昌华",
        "attachment_url": "https://jsgc.gzggzy.cn/download?AttachGuid=union",
        "attachment_snapshot_id_optional": "SNAP-ATTACH",
        "document_sha256": "abc123",
        "document_work_path": "tmp/work/SNAP-ATTACH.pdf",
        "extraction_json_path": "tmp/extractions/DESIGN-SURVEY-FLOW08-PARSE-1.json",
        "attachment_parse_state": state,
        "extracted_fields": {
            "extraction_state": "FIELDS_EXTRACTED"
            if state == "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
            else "NO_RESPONSIBLE_PERSON_FIELD_FOUND",
            "primary_responsible_person_name": "胡昌华"
            if state == "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
            else "",
            "primary_responsible_role": "survey_design_project_lead",
            "primary_certificate_no_optional": "粤测绘20260001"
            if state == "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
            else "",
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if state == "TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED":
        record["person_dossier_evidence"] = {
            "person_dossier_state": "PERSON_DOSSIER_EXTRACTED",
            "target_person_name": "胡昌华",
            "page_window_strategy_state": "DIRECTORY_PERSONNEL_ENTRY",
            "planned_page_ranges": "214-286",
            "current_project_binding_state": "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND",
            "current_project_binding_evidence_count": 2,
            "supporting_identity_or_credential_evidence_count": 4,
            "evidence_category_counts": {
                "personnel_summary": 1,
                "personnel_resume": 1,
                "identity_document": 1,
                "social_security": 1,
            },
            "evidence_records": [
                {
                    "person_dossier_evidence_id": "EVIDENCE-216",
                    "page_no": 216,
                    "evidence_category": "personnel_summary",
                    "current_project_binding_candidate_state": "CURRENT_PROJECT_PERSONNEL_CANDIDATE",
                    "history_performance_page": False,
                    "redacted_text_probe": "拟在本工程任职的人员汇总表 姓名 胡昌华 项目负责人",
                },
                {
                    "person_dossier_evidence_id": "EVIDENCE-219",
                    "page_no": 219,
                    "evidence_category": "identity_document",
                    "current_project_binding_candidate_state": "SUPPORTING_OR_HISTORY_EVIDENCE",
                    "history_performance_page": False,
                    "redacted_text_probe": "居民身份证 公民身份号码 4401********567X 姓名 胡昌华",
                },
            ],
            "sensitive_fields_policy": {
                "id_card_number_redacted": True,
                "social_security_number_redacted": True,
                "store_page_no_and_redacted_text_only": True,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    _write_json(
        root / "design-survey-flow08-target-attachment-parse-v1.json",
        {
            "manifest": {
                "target_attachment_parse_table": {
                    "records": [record],
                    "summary": {
                        "target_attachment_parse_record_count": 1,
                        "attachment_parse_state_counts": {state: 1},
                    },
                }
            }
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
