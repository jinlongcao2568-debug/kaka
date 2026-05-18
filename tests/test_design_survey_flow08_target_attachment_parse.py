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

from storage.design_survey_flow08_target_attachment_parse import (  # noqa: E402
    TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED,
    TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED,
    build_design_survey_flow08_target_attachment_parse,
)


class DesignSurveyFlow08TargetAttachmentParseTests(unittest.TestCase):
    def test_parse_consumes_existing_snapshot_and_extracts_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readback_root = root / "flow08"
            _write_flow08_readback(readback_root, snapshot_id="SNAP-ATTACH-1")

            result = build_design_survey_flow08_target_attachment_parse(
                design_survey_flow08_readback_root=readback_root,
                output_root=root / "out",
                enable_ocr=False,
                created_at="2026-05-18T20:30:00+08:00",
                snapshot_reader=lambda snapshot_id: b"%PDF-1.4\nfake target attachment\n",
                document_extractor=_fake_extractor_fields,
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(
                result["summary"]["attachment_parse_state_counts"],
                {TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED: 1},
            )
            record = result["manifest"]["target_attachment_parse_table"]["records"][0]
            self.assertEqual(record["attachment_snapshot_id_optional"], "SNAP-ATTACH-1")
            self.assertEqual(record["extracted_fields"]["primary_responsible_person_name"], "胡昌华")
            self.assertTrue(Path(record["extraction_json_path"]).exists())
            self.assertFalse(result["manifest"]["safety"]["download_enabled"])
            self.assertTrue(result["manifest"]["scope_guardrails"]["targeted_parse_only"])

    def test_parse_marks_ocr_required_without_claiming_clearance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readback_root = root / "flow08"
            _write_flow08_readback(readback_root, snapshot_id="SNAP-ATTACH-1")

            result = build_design_survey_flow08_target_attachment_parse(
                design_survey_flow08_readback_root=readback_root,
                output_root=root / "out",
                enable_ocr=False,
                created_at="2026-05-18T20:30:00+08:00",
                snapshot_reader=lambda snapshot_id: b"%PDF-1.4\nfake target attachment\n",
                document_extractor=_fake_extractor_no_text,
            )

            record = result["manifest"]["target_attachment_parse_table"]["records"][0]
            self.assertEqual(record["attachment_parse_state"], "TARGET_ATTACHMENT_OCR_REQUIRED")
            self.assertEqual(record["next_action"], "rerun_design_survey_flow08_target_attachment_parse_with_ocr")
            self.assertFalse(record["customer_visible_allowed"])
            self.assertTrue(record["no_legal_conclusion"])

    def test_person_dossier_uses_directory_page_window_and_redacts_sensitive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readback_root = root / "flow08"
            _write_flow08_readback(readback_root, snapshot_id="SNAP-ATTACH-1")

            result = build_design_survey_flow08_target_attachment_parse(
                design_survey_flow08_readback_root=readback_root,
                output_root=root / "out",
                enable_ocr=True,
                created_at="2026-05-18T20:30:00+08:00",
                snapshot_reader=lambda snapshot_id: b"%PDF-1.4\nfake target attachment\n",
                document_extractor=_fake_extractor_person_dossier,
            )

            record = result["manifest"]["target_attachment_parse_table"]["records"][0]
            dossier = record["person_dossier_evidence"]
            self.assertEqual(record["attachment_parse_state"], TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED)
            self.assertEqual(dossier["page_window_strategy_state"], "DIRECTORY_PERSONNEL_ENTRY")
            self.assertEqual(dossier["planned_page_ranges"], "214-286")
            self.assertEqual(dossier["current_project_binding_state"], "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND")
            self.assertGreaterEqual(dossier["supporting_identity_or_credential_evidence_count"], 2)
            all_text = json.dumps(dossier["evidence_records"], ensure_ascii=False)
            self.assertIn("人员简历表-胡昌华", all_text)
            self.assertIn("4401********567X", all_text)
            self.assertNotIn("44010119900101567X", all_text)
            self.assertEqual(
                result["summary"]["attachment_parse_state_counts"],
                {TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED: 1},
            )
            self.assertEqual(result["summary"]["person_dossier_current_binding_record_count"], 1)


def _write_flow08_readback(root: Path, *, snapshot_id: str) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    attachment = {
        "target_attachment_id": "DESIGN-SURVEY-FLOW08-ATTACH-1",
        "project_id": project_id,
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
        "target_attachment_match_state": "TARGET_CANDIDATE_ATTACHMENT_BOUND",
        "attachment_fetch_state": "FETCHED",
        "attachment_snapshot_id_optional": snapshot_id,
        "attachment_url": "https://jsgc.gzggzy.cn/download?AttachGuid=union",
    }
    _write_json(
        root / "design-survey-flow08-targeted-readback-v1.json",
        {
            "manifest": {
                "target_attachment_table": {"records": [attachment]},
                "flow08_targeted_readback_table": {
                    "records": [
                        {
                            "project_id": project_id,
                            "flow08_readback_state": "FLOW08_TARGET_ATTACHMENT_FETCHED",
                            "target_attachment_records": [attachment],
                        }
                    ]
                },
            }
        },
    )


def _fake_extractor_fields(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
    return {
        "sha256": "abc123",
        "extraction_methods": ["pymupdf_text"],
        "pages": [{"page_no": 1, "text": "勘察设计项目负责人：胡昌华 粤测绘20260001"}],
        "text": "勘察设计项目负责人：胡昌华 粤测绘20260001",
        "extracted_fields": {
            "extraction_state": "FIELDS_EXTRACTED",
            "primary_responsible_person_name": "胡昌华",
            "primary_responsible_role": "survey_design_project_lead",
            "primary_certificate_no_optional": "粤测绘20260001",
            "responsible_person_candidates": [
                {
                    "role_key": "survey_design_project_lead",
                    "person_name": "胡昌华",
                    "certificate_no_optional": "粤测绘20260001",
                }
            ],
        },
        "failure_reasons": [],
    }


def _fake_extractor_no_text(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
    return {
        "sha256": "abc123",
        "extraction_methods": ["pymupdf_text", "pdfplumber_text"],
        "pages": [],
        "text": "",
        "extracted_fields": {"extraction_state": "NO_RESPONSIBLE_PERSON_FIELD_FOUND"},
        "failure_reasons": ["pdf_text_unavailable_or_ocr_required"],
    }


def _fake_extractor_person_dossier(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
    ranges = str(kwargs.get("ocr_page_ranges") or "")
    if ranges == "1-8":
        return {
            "sha256": "abc123",
            "extraction_methods": ["tesseract_ocr"],
            "pages": [
                {
                    "page_no": 2,
                    "text": "目录\n拟在本工程任职的人员汇总表 214\n人员简历表 216\n身份证 职称证书 学位证书 社保 217",
                }
            ],
            "text": "目录\n拟在本工程任职的人员汇总表 214\n人员简历表 216\n身份证 职称证书 学位证书 社保 217",
            "extracted_fields": {"extraction_state": "NO_RESPONSIBLE_PERSON_FIELD_FOUND"},
            "failure_reasons": [],
        }
    if ranges == "214-286":
        text = "\n".join(
            [
                "拟在本工程任职的人员汇总表 姓名 胡昌华 职务 项目负责人 职称 正高级工程师 注册测绘师",
                "人员简历表-胡昌华 姓名 胡昌华 在本项目担任 项目负责人 毕业院校 武汉大学 执业资格 注册测绘师",
                "居民身份证 公民身份号码 44010119900101567X 姓名 胡昌华",
                "硕士学位证书 胡昌华 武汉大学",
                "社保证明 姓名 胡昌华 单位 广州市城市规划勘测设计研究院有限公司 2026-04",
                "人员简历表-李奇 姓名 李奇",
            ]
        )
        return {
            "sha256": "abc123",
            "extraction_methods": ["tesseract_ocr"],
            "pages": [
                {"page_no": 216, "text": "拟在本工程任职的人员汇总表 姓名 胡昌华 职务 项目负责人 职称 正高级工程师 注册测绘师"},
                {"page_no": 218, "text": "人员简历表-胡昌华 姓名 胡昌华 在本项目担任 项目负责人 毕业院校 武汉大学 执业资格 注册测绘师"},
                {"page_no": 219, "text": "居民身份证 公民身份号码 44010119900101567X 姓名 胡昌华"},
                {"page_no": 221, "text": "硕士学位证书 胡昌华 武汉大学"},
                {"page_no": 222, "text": "社保证明 姓名 胡昌华 单位 广州市城市规划勘测设计研究院有限公司 2026-04"},
                {"page_no": 223, "text": "人员简历表-李奇 姓名 李奇"},
            ],
            "text": text,
            "extracted_fields": {"extraction_state": "NO_RESPONSIBLE_PERSON_FIELD_FOUND"},
            "failure_reasons": [],
        }
    return _fake_extractor_no_text(*args, **kwargs)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
