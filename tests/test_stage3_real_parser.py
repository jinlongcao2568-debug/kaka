from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings
from stage3_parsing.real_parser import (
    ATTACHMENT_TYPE_UNKNOWN,
    OCR_LOW_CONFIDENCE,
    PDF_TEXT_UNAVAILABLE,
    UNSUPPORTED_CONTENT_TYPE,
    UNVERIFIED_STATE,
    WORD_PARSE_FAILED,
)
from stage3_parsing.service import Stage3Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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


if __name__ == "__main__":
    unittest.main()
