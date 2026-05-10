from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings
from stage2_ingestion.real_public_url_fetcher import (
    PUBLIC_ATTACHMENT_PROFILE_IDS,
    REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID,
    REAL_PUBLIC_ENTRY_PROFILE_BY_ID,
    RealPublicFetchResponse,
)
from stage2_ingestion.service import Stage2Service
from stage3_parsing import markitdown_adapter
from stage3_parsing.real_parser import (
    ATTACHMENT_TYPE_UNKNOWN,
    OCR_LOW_CONFIDENCE,
    OCR_REQUIRED,
    PDF_TEXT_UNAVAILABLE,
    UNSUPPORTED_CONTENT_TYPE,
    UNVERIFIED_STATE,
    WORD_PARSE_FAILED,
)
from stage3_parsing.ocr_text import ExtractedText, PDF_TEXT_OCR_EXTRACTED
from stage3_parsing.service import Stage3Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
REAL_PUBLIC_HTML_SNAPSHOT_PROFILE_IDS_FOR_138 = (
    "GGZY-DEAL-LIST",
    "CCGP-CENTRAL-NOTICES",
    "CCGP-CENTRAL-AWARD-LIST",
    "BEIJING-PLATFORM-HOME",
    "BEIJING-GCJS-LIST",
    "BEIJING-BDA-HOME",
    "JZSC-NATIONAL-HOME",
    "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
    "JIANGSU-GGZY-HOME",
    "ZHEJIANG-GGZY-JYXXGK-LIST",
    "SHANDONG-GGZY-JYXXGK-LIST",
    "HUBEI-BIDCLOUD-JYXX-LIST",
    "SICHUAN-GGZY-TRANSACTION-INFO",
)


class Stage3RealParserTests(unittest.TestCase):
    def _repo(self, tmp_dir: str) -> ObjectStorageRepository:
        settings = Settings(
            storage_backend="json-file",
            storage_path_optional=str(Path(tmp_dir) / "stage3-parser-storage.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(Path(tmp_dir) / "objects"),
        )
        return ObjectStorageRepository(
            session=DatabaseSession(settings=settings),
            settings=settings,
        )

    def _save_snapshot(
        self,
        repo: ObjectStorageRepository,
        *,
        data: bytes,
        snapshot_id: str,
        content_type: str,
        source_url: str,
        snapshot_kind: str,
    ) -> None:
        repo.save_snapshot(
            data,
            snapshot_id=snapshot_id,
            snapshot_kind=snapshot_kind,
            content_type=content_type,
            source_url_optional=source_url,
            source_family_optional="local_public_resource_trading_center",
            lineage_refs={
                "project_id": "P-STAGE3-REAL-PARSER",
                "source_registry_id": "SRC-REG-PROC-NATIONAL-HTML",
                "source_family": "local_public_resource_trading_center",
                "stage_scope": "2",
            },
            created_at="2026-04-25T00:00:00+00:00",
        )

    def _parse(
        self,
        *,
        data: bytes,
        snapshot_id: str,
        content_type: str,
        source_url: str,
        snapshot_kind: str,
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            self._save_snapshot(
                repo,
                data=data,
                snapshot_id=snapshot_id,
                content_type=content_type,
                source_url=source_url,
                snapshot_kind=snapshot_kind,
            )
            return dict(Stage3Service().parse_raw_snapshot(snapshot_id, repository=repo))

    def _assert_unverified_internal_carrier(self, carrier: dict) -> None:
        self.assertEqual(carrier["verification_state"], UNVERIFIED_STATE)
        self.assertTrue(carrier["stage4_verification_required"])
        self.assertFalse(carrier["customer_visible"])
        self.assertEqual(carrier["parser_mode"], "DETERMINISTIC_READBACK")
        self.assertEqual(carrier["source_registry_id"], "SRC-REG-PROC-NATIONAL-HTML")

    def _assert_real_public_parser_boundary(self, carrier: dict) -> None:
        self.assertEqual(carrier["verification_state"], UNVERIFIED_STATE)
        self.assertTrue(carrier["stage4_verification_required"])
        self.assertFalse(carrier["customer_visible"])
        self.assertEqual(carrier["parser_mode"], "DETERMINISTIC_READBACK")
        self.assertIn("parser_audit", carrier)
        self.assertIn("model_assist_governance_summary", carrier)

    def test_html_parse_happy_path_fields_slice_locator_confidence_and_audit(self) -> None:
        html = """
        <html>
          <head><title>测试道路工程施工招标公告</title></head>
          <body>
            <h1>测试道路工程施工招标公告</h1>
            <table>
              <tr><th>项目名称</th><td>测试道路工程</td></tr>
              <tr><th>招标人</th><td>测试市建设单位</td></tr>
              <tr><th>公告日期</th><td>2026-04-25</td></tr>
            </table>
          </body>
        </html>
        """.encode("utf-8")

        carrier = self._parse(
            data=html,
            snapshot_id="SNAP-STAGE3-HTML-1",
            content_type="text/html; charset=utf-8",
            source_url="sandbox://local-public-resource-trading-centers/notices/notice.html",
            snapshot_kind="raw_html",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "HTML")
        self.assertEqual(carrier["parser_family"], "html")
        self.assertEqual(carrier["parse_state"], "PARSED")
        self.assertFalse(carrier["review_required"])
        self.assertEqual(carrier["parse_error_taxonomy"], [])

        fields = {field["field_name"]: field for field in carrier["parsed_fields"]}
        self.assertEqual(fields["project_name"]["field_value_optional"], "测试道路工程")
        self.assertEqual(
            fields["tenderer_or_purchaser"]["field_value_optional"],
            "测试市建设单位",
        )
        self.assertEqual(fields["announcement_date"]["field_value_optional"], "2026-04-25")
        self.assertEqual(
            fields["announcement_title"]["field_value_optional"],
            "测试道路工程施工招标公告",
        )

        project_field = fields["project_name"]
        self.assertIn("项目名称", project_field["source_slice"])
        self.assertIn("测试道路工程", project_field["source_slice"])
        self.assertEqual(
            project_field["source_slice_sha256"],
            hashlib.sha256(project_field["source_slice"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(project_field["raw_text"], project_field["source_slice"])
        self.assertEqual(project_field["locator"]["type"], "html_table_cell")
        self.assertEqual(project_field["locator"]["table_index"], 0)
        self.assertEqual(project_field["locator"]["row_index"], 0)
        self.assertGreaterEqual(project_field["confidence"], 0.8)
        self.assertFalse(project_field["review_required"])

        audit = carrier["parser_audit"]
        self.assertEqual(audit["input_snapshot_id"], "SNAP-STAGE3-HTML-1")
        self.assertEqual(audit["input_sha256"], hashlib.sha256(html).hexdigest())
        self.assertIn("read_stage2_snapshot_readback", audit["parser_steps"])
        self.assertIn("extract_html_text_and_tables", audit["parser_steps"])
        self.assertTrue(audit["started_at"])
        self.assertTrue(audit["completed_at"])
        self.assertEqual(audit["parser_errors"], [])

    def test_real_public_html_snapshot_profiles_enter_stage3_parser_readback(self) -> None:
        responses = {
            REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id].url: RealPublicFetchResponse(
                url=REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id].url,
                status_code=200,
                content=_real_public_profile_html(profile_id),
                content_type="text/html; charset=utf-8",
                final_url=REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id].url,
                headers={"x-ax9s-fetch-transport": "unit_controlled_transport"},
            )
            for profile_id in REAL_PUBLIC_HTML_SNAPSHOT_PROFILE_IDS_FOR_138
        }
        transport = _FakeRealPublicFetchTransport(responses)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            for profile_id in REAL_PUBLIC_HTML_SNAPSHOT_PROFILE_IDS_FOR_138:
                profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id]
                with self.subTest(profile_id=profile_id):
                    stage2_carrier = Stage2Service().fetch_real_public_entry_url(
                        profile.url,
                        profile_id=profile_id,
                        repository=repo,
                        transport=transport,
                        lineage_refs={
                            "source_blueprint_batch_id": "PTL-I100-138",
                            "entry_profile_id": profile_id,
                        },
                    )
                    self.assertEqual(stage2_carrier["status"], "FETCHED")
                    snapshot_id = stage2_carrier["snapshot_id_optional"]
                    replay = repo.replay_snapshot(snapshot_id)
                    self.assertTrue(replay["replayable"])

                    carrier = dict(Stage3Service().parse_raw_snapshot(snapshot_id, repository=repo))
                    self._assert_real_public_parser_boundary(carrier)
                    self.assertEqual(carrier["snapshot_id"], snapshot_id)
                    self.assertEqual(carrier["source_url"], profile.url)
                    self.assertEqual(carrier["source_family"], profile.source_family)
                    self.assertEqual(carrier["attachment_type"], "HTML")
                    self.assertIn(carrier["parse_state"], {"PARSED", "PARSED_WITH_REVIEW"})

                    fields = {field["field_name"]: field for field in carrier["parsed_fields"]}
                    self.assertIn("project_name", fields)
                    project_field = fields["project_name"]
                    self.assertEqual(project_field["field_value_optional"], f"{profile_id} 测试项目")
                    self.assertEqual(
                        project_field["source_slice_sha256"],
                        hashlib.sha256(project_field["source_slice"].encode("utf-8")).hexdigest(),
                    )
                    self.assertGreater(project_field["confidence"], 0)
                    self.assertEqual(project_field["parser_version"], carrier["parser_version"])
                    self.assertIn("locator", project_field)
                    self.assertFalse(project_field["review_required"])
                    self.assertIn("read_stage2_snapshot_readback", carrier["parser_audit"]["parser_steps"])
                    self.assertIn("extract_html_text_and_tables", carrier["parser_audit"]["parser_steps"])
                    self.assertNotIn("stage4_verified_fact", carrier)
                    self.assertNotIn("rule_hit", carrier)
                    self.assertNotIn("customer_material", carrier)

    def test_real_public_pdf_attachment_snapshots_enter_stage3_as_review_required(self) -> None:
        responses = {
            REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID[profile_id].url: RealPublicFetchResponse(
                url=REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID[profile_id].url,
                status_code=200,
                content=_pdf_like_attachment(profile_id),
                content_type="application/pdf",
                final_url=REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID[profile_id].url,
                headers={"x-ax9s-fetch-transport": "unit_controlled_transport"},
            )
            for profile_id in PUBLIC_ATTACHMENT_PROFILE_IDS
        }
        transport = _FakeRealPublicFetchTransport(responses)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            for profile_id in PUBLIC_ATTACHMENT_PROFILE_IDS:
                profile = REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID[profile_id]
                with self.subTest(profile_id=profile_id):
                    stage2_carrier = Stage2Service().fetch_real_public_attachment_url(
                        profile.url,
                        profile_id=profile_id,
                        repository=repo,
                        transport=transport,
                        detail_page_url=profile.detail_page_url_optional,
                        lineage_refs={
                            "source_blueprint_batch_id": "PTL-I100-138",
                            "attachment_profile_id": profile_id,
                        },
                    )
                    self.assertEqual(stage2_carrier["status"], "FETCHED")
                    snapshot_id = stage2_carrier["snapshot_id_optional"]

                    carrier = dict(Stage3Service().parse_raw_snapshot(snapshot_id, repository=repo))
                    self._assert_real_public_parser_boundary(carrier)
                    self.assertEqual(carrier["snapshot_id"], snapshot_id)
                    self.assertEqual(carrier["source_url"], profile.url)
                    self.assertEqual(carrier["source_family"], profile.source_family)
                    self.assertEqual(carrier["attachment_type"], "PDF")
                    self.assertEqual(carrier["parse_state"], "REVIEW_REQUIRED")
                    self.assertEqual(carrier["parsed_fields"], [])
                    self.assertTrue(carrier["review_required"])
                    self.assertIn(PDF_TEXT_UNAVAILABLE, carrier["parse_error_taxonomy"])
                    self.assertIn(
                        "degrade_to_review:pdf_text_unavailable",
                        carrier["parser_audit"]["fallback_steps"],
                    )

    def test_pdf_degrades_to_review_without_fabricated_fields(self) -> None:
        carrier = self._parse(
            data=b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF",
            snapshot_id="SNAP-STAGE3-PDF-1",
            content_type="application/pdf",
            source_url="sandbox://local-public-resource-trading-centers/notices/notice.pdf",
            snapshot_kind="raw_pdf",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "PDF")
        self.assertTrue(carrier["review_required"])
        self.assertEqual(carrier["parsed_fields"], [])
        self.assertIn(PDF_TEXT_UNAVAILABLE, carrier["parse_error_taxonomy"])
        self.assertIn(
            "degrade_to_review:pdf_text_unavailable",
            carrier["parser_audit"]["fallback_steps"],
        )

    def test_pdf_text_attachment_extracts_stage3_fields(self) -> None:
        carrier = self._parse(
            data=_build_text_pdf_bytes(
                [
                    "项目名称: 广东机电安装工程",
                    "第一中标候选人: 广东省机电建设有限公司",
                    "项目负责人: 张建明",
                    "注册编号: 144202412345",
                ]
            ),
            snapshot_id="SNAP-STAGE3-PDF-TEXT-1",
            content_type="application/pdf",
            source_url="sandbox://local-public-resource-trading-centers/notices/text.pdf",
            snapshot_kind="raw_pdf",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "PDF")
        self.assertEqual(carrier["parse_state"], "PARSED")
        self.assertFalse(carrier["review_required"])
        self.assertIn("extract_pdf_text", carrier["parser_audit"]["parser_steps"])
        fields = {field["field_name"]: field for field in carrier["parsed_fields"]}
        self.assertEqual(fields["project_name"]["field_value_optional"], "广东机电安装工程")
        self.assertEqual(fields["project_manager_name"]["field_value_optional"], "张建明")
        self.assertEqual(
            fields["project_manager_public_identifier_optional"]["field_value_optional"],
            "144202412345",
        )

    def test_ocr_scanned_image_degrades_to_review_without_low_confidence_facts(self) -> None:
        carrier = self._parse(
            data=b"\x89PNG\r\n\x1a\nscanned-bytes",
            snapshot_id="SNAP-STAGE3-OCR-1",
            content_type="image/png",
            source_url="sandbox://local-public-resource-trading-centers/notices/scan.png",
            snapshot_kind="raw_attachment",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "SCANNED_IMAGE")
        self.assertEqual(carrier["parser_family"], "ocr")
        self.assertTrue(carrier["review_required"])
        self.assertEqual(carrier["parsed_fields"], [])
        self.assertIn(OCR_LOW_CONFIDENCE, carrier["parse_error_taxonomy"])
        self.assertIn(OCR_REQUIRED, carrier["parse_error_taxonomy"])

    def test_empty_pdf_can_use_ocr_fallback_but_keeps_review_state(self) -> None:
        with patch(
            "stage3_parsing.real_parser.extract_pdf_text_with_ocr",
            return_value=ExtractedText(
                text="项目名称: 扫描件道路工程\n项目负责人: 张建明\n注册编号: 144202412345",
                state=PDF_TEXT_OCR_EXTRACTED,
                extractor="provided_pdf_ocr",
                confidence=0.62,
                review_required=True,
                warnings=[OCR_REQUIRED],
            ),
        ):
            carrier = self._parse(
                data=_build_blank_pdf_bytes(),
                snapshot_id="SNAP-STAGE3-PDF-OCR-1",
                content_type="application/pdf",
                source_url="sandbox://local-public-resource-trading-centers/notices/scanned.pdf",
                snapshot_kind="raw_pdf",
            )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "PDF")
        self.assertEqual(carrier["parse_state"], "PARSED_WITH_REVIEW")
        self.assertTrue(carrier["review_required"])
        self.assertIn("extract_pdf_ocr_text", carrier["parser_audit"]["parser_steps"])
        fields = {field["field_name"]: field for field in carrier["parsed_fields"]}
        self.assertEqual(fields["project_name"]["field_value_optional"], "扫描件道路工程")
        self.assertEqual(fields["project_manager_name"]["field_value_optional"], "张建明")
        self.assertEqual(
            fields["project_manager_public_identifier_optional"]["field_value_optional"],
            "144202412345",
        )
        self.assertTrue(fields["project_name"]["review_required"])
        self.assertIn(OCR_REQUIRED, fields["project_name"]["parse_warnings"])

    def test_word_docx_attachment_extracts_structured_fields_with_locator(self) -> None:
        carrier = self._parse(
            data=_build_docx_bytes(),
            snapshot_id="SNAP-STAGE3-DOCX-1",
            content_type=DOCX_CONTENT_TYPE,
            source_url="sandbox://provincial-bidding-platforms/mirror/notice.docx",
            snapshot_kind="raw_attachment",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "WORD_DOCX")
        self.assertEqual(carrier["parse_state"], "PARSED")
        fields = {field["field_name"]: field for field in carrier["parsed_fields"]}
        self.assertEqual(fields["project_name"]["field_value_optional"], "测试桥梁工程")
        self.assertEqual(fields["project_name"]["locator"]["type"], "docx_table_cell")
        self.assertEqual(fields["project_name"]["locator"]["xml_path"], "word/document.xml")
        self.assertFalse(fields["project_name"]["review_required"])

    def test_excel_xlsx_attachment_extracts_table_cell_locator(self) -> None:
        carrier = self._parse(
            data=_build_xlsx_bytes(),
            snapshot_id="SNAP-STAGE3-XLSX-1",
            content_type=XLSX_CONTENT_TYPE,
            source_url="sandbox://provincial-bidding-platforms/mirror/notice.xlsx",
            snapshot_kind="raw_attachment",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "EXCEL_XLSX")
        fields = {field["field_name"]: field for field in carrier["parsed_fields"]}
        self.assertEqual(fields["project_name"]["field_value_optional"], "测试管网工程")
        locator = fields["project_name"]["locator"]
        self.assertEqual(locator["type"], "xlsx_table_cell")
        self.assertEqual(locator["cell_ref"], "B1")
        self.assertEqual(locator["row_index"], 0)
        self.assertEqual(locator["column_index"], 1)

    def test_unknown_attachment_degrades_to_review(self) -> None:
        carrier = self._parse(
            data=b"unknown attachment bytes",
            snapshot_id="SNAP-STAGE3-UNKNOWN-1",
            content_type="application/octet-stream",
            source_url="sandbox://local-public-resource-trading-centers/mirror/attachment.bin",
            snapshot_kind="raw_attachment",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "UNKNOWN_ATTACHMENT")
        self.assertTrue(carrier["review_required"])
        self.assertEqual(carrier["parsed_fields"], [])
        self.assertIn(ATTACHMENT_TYPE_UNKNOWN, carrier["parse_error_taxonomy"])
        self.assertIn(UNSUPPORTED_CONTENT_TYPE, carrier["parse_error_taxonomy"])

    def test_parser_failure_degrades_to_review_and_does_not_fabricate_fields(self) -> None:
        carrier = self._parse(
            data=b"not a zip based docx",
            snapshot_id="SNAP-STAGE3-BAD-DOCX-1",
            content_type=DOCX_CONTENT_TYPE,
            source_url="sandbox://provincial-bidding-platforms/mirror/broken.docx",
            snapshot_kind="raw_attachment",
        )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "WORD_DOCX")
        self.assertTrue(carrier["review_required"])
        self.assertEqual(carrier["parsed_fields"], [])
        self.assertIn(WORD_PARSE_FAILED, carrier["parse_error_taxonomy"])

    def test_markitdown_fallback_extracts_docx_fields_with_review_locator(self) -> None:
        text = "项目名称: MarkItDown附件工程\n项目负责人: 张建明\n资格条件: 须提供厂家授权和本地社保。"
        with patch(
            "stage3_parsing.real_parser.markitdown_adapter.convert_bytes_to_markdown_text",
            return_value=markitdown_adapter.MarkItDownText(
                text=text,
                state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                text_length=len(text),
                text_probe=text,
            ),
        ):
            carrier = self._parse(
                data=b"not a zip based docx",
                snapshot_id="SNAP-STAGE3-MARKITDOWN-DOCX-1",
                content_type=DOCX_CONTENT_TYPE,
                source_url="sandbox://provincial-bidding-platforms/mirror/broken.docx",
                snapshot_kind="raw_attachment",
            )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "WORD_DOCX")
        self.assertEqual(carrier["parse_state"], "PARSED_WITH_REVIEW")
        self.assertTrue(carrier["review_required"])
        self.assertIn(WORD_PARSE_FAILED, carrier["parse_error_taxonomy"])
        audit = carrier["parser_audit"]
        self.assertEqual(audit["markitdown_state"], markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED)
        self.assertEqual(audit["markitdown_text_length"], len(text))
        self.assertIn("厂家授权", audit["markitdown_text_probe"])
        fields = {field["field_name"]: field for field in carrier["parsed_fields"]}
        self.assertEqual(fields["project_name"]["field_value_optional"], "MarkItDown附件工程")
        self.assertEqual(fields["project_name"]["locator"]["type"], "markitdown_text")
        self.assertTrue(fields["project_name"]["review_required"])
        self.assertIn(
            markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
            fields["project_name"]["parse_warnings"],
        )

    def test_markitdown_unavailable_keeps_review_degradation_without_exception(self) -> None:
        with patch(
            "stage3_parsing.real_parser.markitdown_adapter.convert_bytes_to_markdown_text",
            return_value=markitdown_adapter.MarkItDownText(
                text="",
                state=markitdown_adapter.MARKITDOWN_UNAVAILABLE,
                warnings=["MARKITDOWN_UNAVAILABLE:ImportError"],
            ),
        ):
            carrier = self._parse(
                data=b"not a zip based docx",
                snapshot_id="SNAP-STAGE3-MARKITDOWN-UNAVAILABLE-1",
                content_type=DOCX_CONTENT_TYPE,
                source_url="sandbox://provincial-bidding-platforms/mirror/broken.docx",
                snapshot_kind="raw_attachment",
            )

        self._assert_unverified_internal_carrier(carrier)
        self.assertEqual(carrier["attachment_type"], "WORD_DOCX")
        self.assertEqual(carrier["parse_state"], "REVIEW_REQUIRED")
        self.assertEqual(carrier["parsed_fields"], [])
        self.assertIn(WORD_PARSE_FAILED, carrier["parse_error_taxonomy"])
        self.assertIn(
            markitdown_adapter.MARKITDOWN_UNAVAILABLE,
            carrier["parse_error_taxonomy"],
        )
        self.assertEqual(
            carrier["parser_audit"]["markitdown_state"],
            markitdown_adapter.MARKITDOWN_UNAVAILABLE,
        )

    def test_stage3_parser_does_not_import_stage2_adapter_or_stage4_to_stage9_runtime(self) -> None:
        parser_source = (ROOT / "src/stage3_parsing/real_parser.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("stage2_ingestion.public_source_adapters", parser_source)
        for forbidden_import in (
            "stage4_verification",
            "stage5_rules_evidence",
            "stage6_fact_review",
            "stage7_sales",
            "stage8_outreach",
            "stage9_delivery",
        ):
            self.assertNotIn(f"from {forbidden_import}", parser_source)
            self.assertNotIn(f"import {forbidden_import}", parser_source)


def _build_docx_bytes() -> bytes:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>测试桥梁工程施工招标公告</w:t></w:r></w:p>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>项目名称</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>测试桥梁工程</w:t></w:r></w:p></w:tc>
          </w:tr>
          <w:tr>
            <w:tc><w:p><w:r><w:t>采购人</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>测试采购中心</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
      </w:body>
    </w:document>
    """
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>
    """
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _build_xlsx_bytes() -> bytes:
    worksheet_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row r="1">
          <c r="A1" t="inlineStr"><is><t>项目名称</t></is></c>
          <c r="B1" t="inlineStr"><is><t>测试管网工程</t></is></c>
        </row>
        <row r="2">
          <c r="A2" t="inlineStr"><is><t>招标人</t></is></c>
          <c r="B2" t="inlineStr"><is><t>测试招标公司</t></is></c>
        </row>
      </sheetData>
    </worksheet>
    """
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
    return buffer.getvalue()


class _FakeRealPublicFetchTransport:
    def __init__(self, responses: dict[str, RealPublicFetchResponse]) -> None:
        self.responses = responses
        self.call_log: list[dict[str, object]] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        self.call_log.append(
            {
                "url": url,
                "timeout_seconds": timeout_seconds,
                "user_agent": user_agent,
            }
        )
        return self.responses[url]


def _real_public_profile_html(profile_id: str) -> bytes:
    profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id]
    markers = profile.visible_entry_markers or profile.lightweight_public_entry_markers
    if profile.lightweight_public_entry_markers and profile_id in {
        "JZSC-NATIONAL-HOME",
        "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
    }:
        markers = profile.lightweight_public_entry_markers
    marker_text = " ".join(markers)
    filler = "公开入口说明" * 80
    html = f"""
    <html>
      <head>
        <title>{profile.expected_title_contains} - {profile.site_name}</title>
        <meta name="description" content="{marker_text}">
      </head>
      <body>
        <h1>{profile.expected_title_contains}</h1>
        <p>{marker_text}</p>
        <p>{filler}</p>
        <table>
          <tr><th>项目名称</th><td>{profile_id} 测试项目</td></tr>
          <tr><th>招标人</th><td>{profile.site_name} 测试招标人</td></tr>
          <tr><th>公告日期</th><td>2026-04-28</td></tr>
        </table>
        <a href="{profile.sample_detail_url}">公开详情样例</a>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _pdf_like_attachment(profile_id: str) -> bytes:
    return b"%PDF-1.4\n" + (f"{profile_id} public attachment\n".encode("utf-8") * 60)


def _build_text_pdf_bytes(lines: list[str]) -> bytes:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except Exception as exc:  # pragma: no cover - optional test rendering dependency
        raise unittest.SkipTest(f"reportlab unavailable: {exc}") from exc
    buffer = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    page = canvas.Canvas(buffer)
    page.setFont("STSong-Light", 12)
    y = 780
    for line in lines:
        page.drawString(72, y, line)
        y -= 24
    page.save()
    return buffer.getvalue()


def _build_blank_pdf_bytes() -> bytes:
    try:
        from pypdf import PdfWriter
    except Exception as exc:  # pragma: no cover - optional test dependency
        raise unittest.SkipTest(f"pypdf unavailable: {exc}") from exc
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
