from __future__ import annotations

import hashlib
import json
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
from storage.db import DatabaseSession
from storage.legacy_attachment_parse import (
    LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE,
    PARSE_STATE_PARSED,
    PARSE_STATE_PARSED_WITH_REVIEW,
    PARSE_STATE_REVIEW_REQUIRED,
    build_legacy_attachment_parse,
)
from storage.legacy_object_triage import build_legacy_object_triage
from storage.object_storage import EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE, OBJECT_STORAGE_OBJECT_TYPE
from storage.object_storage_inventory import build_object_storage_inventory


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class LegacyAttachmentParseTests(unittest.TestCase):
    def test_dry_run_execute_and_idempotent_parse_legacy_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "objects"
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "legacy-attachment-parse.sqlite")
            docx_key = _write_content_addressed_object(root, _build_docx_bytes())
            xlsx_key = _write_content_addressed_object(root, _build_xlsx_bytes())
            pdf_key = _write_content_addressed_object(root, _build_blank_pdf_bytes())
            zip_key = _write_content_addressed_object(root, _build_generic_zip_bytes())

            _prepare_triage(root=root, database_url=database_url)

            dry_run = build_legacy_attachment_parse(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=root,
                execute=False,
                created_at="2026-05-07T07:00:00+00:00",
            )
            self.assertTrue(dry_run["safe_to_execute"])
            self.assertFalse(dry_run["execution"]["executed"])
            self.assertEqual(dry_run["summary"]["attachment_candidate_count"], 4)

            settings = _settings(root=root, database_url=database_url)
            dry_session = DatabaseSession(settings=settings)
            try:
                self.assertEqual(dry_session.list_records(LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE), [])
            finally:
                dry_session.close()

            executed = build_legacy_attachment_parse(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=root,
                execute=True,
                created_at="2026-05-07T07:00:00+00:00",
            )
            self.assertTrue(executed["execution"]["executed"])
            self.assertEqual(executed["execution"]["upserted_legacy_attachment_parse_manifest_count"], 1)
            self.assertEqual(executed["summary"]["parsed_with_fields_count"], 2)

            session = DatabaseSession(settings=settings)
            try:
                manifests = session.list_records(LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(manifests), 1)
                self.assertEqual(len(session.list_records(OBJECT_STORAGE_OBJECT_TYPE)), 4)
                self.assertEqual(len(session.list_records(EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE)), 0)
                payload = manifests[0].payload
                items = {item["object_key"]: item for item in payload["items"]}
                self.assertGreater(items[docx_key]["parsed_field_count"], 0)
                self.assertGreater(items[xlsx_key]["parsed_field_count"], 0)
                self.assertEqual(items[zip_key]["parse_state"], PARSE_STATE_REVIEW_REQUIRED)
                self.assertEqual(items[zip_key]["parser_family"], "zip")
                self.assertGreater(items[zip_key]["zip_entry_count_optional"], 0)
                self.assertEqual(items[pdf_key]["parse_state"], PARSE_STATE_REVIEW_REQUIRED)
                self.assertTrue(items[pdf_key]["review_required"])
                self.assertTrue(all(item["customer_visible_allowed"] is False for item in items.values()))
                self.assertTrue(all(item["no_legal_conclusion"] is True for item in items.values()))
                self.assert_no_blob_payload(payload)
            finally:
                session.close()

            repeated = build_legacy_attachment_parse(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=root,
                execute=True,
                created_at="2026-05-07T07:05:00+00:00",
            )
            self.assertTrue(repeated["execution"]["executed"])
            repeated_session = DatabaseSession(settings=settings)
            try:
                self.assertEqual(
                    len(repeated_session.list_records(LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE)),
                    1,
                )
            finally:
                repeated_session.close()

    def test_hash_mismatch_fails_closed_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "objects"
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "legacy-attachment-integrity.sqlite")
            docx_key = _write_content_addressed_object(root, _build_docx_bytes())
            _prepare_triage(root=root, database_url=database_url)
            (root / docx_key).write_bytes(b"changed after triage")

            result = build_legacy_attachment_parse(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=root,
                execute=True,
                created_at="2026-05-07T07:10:00+00:00",
            )

            self.assertTrue(result["execution"]["executed"])
            item = result["manifest"]["items"][0]
            self.assertEqual(item["object_key"], docx_key)
            self.assertEqual(item["parse_state"], PARSE_STATE_REVIEW_REQUIRED)
            self.assertFalse(item["sha256_verified"])
            self.assertIn("sha256_mismatch", item["review_reasons"])
            self.assertEqual(item["parsed_field_count"], 0)

    def test_missing_triage_manifest_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "objects"
            root.mkdir(parents=True)
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "legacy-attachment-missing.sqlite")

            result = build_legacy_attachment_parse(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=root,
                execute=True,
                created_at="2026-05-07T07:15:00+00:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("legacy_object_triage_manifest_missing", result["blocking_reasons"])
            self.assertFalse(result["execution"]["executed"])
            session = DatabaseSession(settings=_settings(root=root, database_url=database_url))
            try:
                self.assertEqual(session.list_records(LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE), [])
            finally:
                session.close()

    def test_pdf_with_embedded_text_can_emit_internal_field_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "objects"
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "legacy-attachment-pdf.sqlite")
            pdf_key = _write_content_addressed_object(
                root,
                _build_text_pdf_bytes(
                    [
                        "测试道路工程招标公告",
                        "项目名称：测试道路工程",
                        "招标人：测试招标公司",
                    ]
                ),
            )
            _prepare_triage(root=root, database_url=database_url)

            result = build_legacy_attachment_parse(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=root,
                execute=True,
                created_at="2026-05-07T07:20:00+00:00",
            )

            item = {row["object_key"]: row for row in result["manifest"]["items"]}[pdf_key]
            self.assertIn(item["parse_state"], {PARSE_STATE_PARSED, PARSE_STATE_PARSED_WITH_REVIEW})
            self.assertGreater(item["parsed_field_count"], 0)
            field_names = {field["field_name"] for field in item["parsed_fields_summary"]}
            self.assertIn("project_name", field_names)
            self.assert_no_blob_payload(result["manifest"])

    def assert_no_blob_payload(self, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn('"bytes"', encoded)
        self.assertNotIn("%PDF", encoded)
        self.assertNotIn("PK\\u0003\\u0004", encoded)
        self.assertLess(len(encoded), 256_000)


def _prepare_triage(*, root: Path, database_url: str) -> None:
    build_object_storage_inventory(
        object_storage_path=root,
        database_url=database_url,
        target_backend="sqlalchemy",
        execute=True,
        created_at="2026-05-07T06:40:00+00:00",
    )
    build_legacy_object_triage(
        object_storage_path=root,
        database_url=database_url,
        target_backend="sqlalchemy",
        execute=True,
        created_at="2026-05-07T06:45:00+00:00",
    )


def _settings(*, root: Path, database_url: str) -> Settings:
    return Settings(
        storage_backend="sqlalchemy",
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(root),
    )


def _write_content_addressed_object(root: Path, data: bytes) -> str:
    sha256 = hashlib.sha256(data).hexdigest()
    object_key = f"objects/{sha256[:2]}/{sha256}"
    path = root / object_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return object_key


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
        archive.writestr("xl/workbook.xml", "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"/>")
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
    return buffer.getvalue()


def _build_generic_zip_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "legacy generic archive")
    return buffer.getvalue()


def _build_text_pdf_bytes(lines: list[str]) -> bytes:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
        from pypdf import PdfReader  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional renderer/extractor dependency
        raise unittest.SkipTest(f"PDF text fixture dependencies unavailable: {exc}") from exc
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
    except Exception:
        return b"%PDF-1.7\nmalformed legacy pdf"
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
