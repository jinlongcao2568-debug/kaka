from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from typing import Any, Mapping
from urllib.parse import urlparse
from xml.etree import ElementTree

from shared.model_assist_governance import (
    MODEL_ASSIST_INPUT_KEY,
    build_model_assist_summary,
    build_parser_model_assist,
)
from shared.utils import utc_now_iso
from stage3_parsing.ocr_text import (
    OCR_REQUIRED,
    PDF_TEXT_OCR_EXTRACTED,
    extract_image_text_with_ocr,
    extract_pdf_text_with_ocr,
)
from storage.repositories.object_storage_repo import ObjectStorageRepository


PARSER_VERSION = "stage3-real-parser-v1"
PARSER_MODE = "DETERMINISTIC_READBACK"
UNVERIFIED_STATE = "UNVERIFIED"

UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"
ENCODING_DECODE_FAILED = "ENCODING_DECODE_FAILED"
PDF_TEXT_UNAVAILABLE = "PDF_TEXT_UNAVAILABLE"
OCR_LOW_CONFIDENCE = "OCR_LOW_CONFIDENCE"
TABLE_EXTRACTION_AMBIGUOUS = "TABLE_EXTRACTION_AMBIGUOUS"
WORD_PARSE_FAILED = "WORD_PARSE_FAILED"
EXCEL_SHEET_AMBIGUOUS = "EXCEL_SHEET_AMBIGUOUS"
ATTACHMENT_TYPE_UNKNOWN = "ATTACHMENT_TYPE_UNKNOWN"

FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "project_name": ("项目名称", "工程名称", "工程项目名称", "项目名"),
    "tenderer_or_purchaser": ("招标人", "采购人", "建设单位", "招标单位", "采购单位"),
    "announcement_title": ("公告标题", "公告名称", "标题"),
    "announcement_date": ("公告日期", "发布日期", "发布时间", "公示日期"),
    "candidate_company": ("中标候选人", "第一中标候选人", "中标单位", "单位名称", "投标人名称", "候选人名称"),
    "project_manager_name": (
        "项目经理姓名",
        "项目负责人姓名",
        "拟派项目负责人姓名",
        "总监理工程师姓名",
        "项目经理",
        "项目负责人",
        "拟派项目负责人",
        "总监理工程师",
    ),
    "project_manager_public_identifier_optional": ("注册编号", "注册证书编号", "证书编号", "注册号"),
    "project_manager_certificate_type": ("证书类型", "资质资格", "项目负责人资质", "项目负责人资格"),
    "project_manager_cert_specialty": ("注册专业", "证书专业", "专业"),
    "project_manager_professional_title": ("职称", "技术职称", "职称证书"),
}

DATE_VALUE_RE = re.compile(
    r"(?P<value>\d{4}\s*(?:-|/|年)\s*\d{1,2}\s*(?:-|/|月)\s*\d{1,2}\s*(?:日)?)"
)


@dataclass(frozen=True)
class ParsedField:
    field_name: str
    field_value_optional: str | None
    source_page_optional: int | None
    source_file_ref: str
    source_slice: str
    source_slice_sha256: str
    raw_text: str
    locator: dict[str, Any]
    confidence: float
    parser_version: str = PARSER_VERSION
    review_required: bool = False
    parse_warnings: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["locator"] = dict(self.locator)
        payload["parse_warnings"] = list(self.parse_warnings)
        return payload


@dataclass(frozen=True)
class Stage3ParserCarrier:
    parse_run_id: str
    snapshot_id: str
    source_url: str | None
    source_family: str | None
    source_registry_id: str | None
    content_type: str
    attachment_type: str
    parser_family: str
    parser_version: str
    parser_mode: str
    parse_state: str
    verification_state: str
    stage4_verification_required: bool
    customer_visible: bool
    parsed_fields: list[dict[str, Any]]
    parser_audit: dict[str, Any]
    parse_error_taxonomy: list[str]
    review_required: bool
    model_assist_governance: dict[str, Any]
    model_assist_governance_summary: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parsed_fields"] = [dict(field) for field in self.parsed_fields]
        payload["parser_audit"] = dict(self.parser_audit)
        payload["parse_error_taxonomy"] = list(self.parse_error_taxonomy)
        return payload


@dataclass(frozen=True)
class _AttachmentDetection:
    attachment_type: str
    parser_family: str
    normalized_content_type: str


class Stage3RealParser:
    def __init__(
        self,
        *,
        repository: ObjectStorageRepository | None = None,
    ) -> None:
        self.repository = repository

    def parse_snapshot(
        self,
        snapshot_id: str,
        *,
        repository: ObjectStorageRepository | None = None,
    ) -> dict[str, Any]:
        resolved_repository = repository or self.repository or ObjectStorageRepository()
        readback = resolved_repository.replay_snapshot(snapshot_id)
        return self.parse_readback(readback)

    def parse_readback(self, readback: Mapping[str, Any]) -> dict[str, Any]:
        started_at = utc_now_iso()
        parser_steps: list[str] = ["read_stage2_snapshot_readback"]
        fallback_steps: list[str] = []
        parser_errors: list[dict[str, str]] = []

        manifest = _manifest(readback)
        raw_snapshot_metadata = _mapping(manifest.get("raw_snapshot_metadata"))
        lineage_refs = _mapping(manifest.get("lineage_refs"))
        snapshot_id = str(
            readback.get("snapshot_id")
            or manifest.get("snapshot_id")
            or raw_snapshot_metadata.get("snapshot_id")
            or "UNKNOWN_SNAPSHOT"
        )
        source_file_ref = str(
            readback.get("object_key")
            or manifest.get("object_key")
            or raw_snapshot_metadata.get("object_key")
            or snapshot_id
        )
        content_type = str(
            readback.get("content_type")
            or manifest.get("content_type")
            or raw_snapshot_metadata.get("content_type")
            or "application/octet-stream"
        )
        source_url = _optional_str(
            manifest.get("source_url_optional") or raw_snapshot_metadata.get("source_url")
        )
        source_family = _optional_str(
            manifest.get("source_family_optional")
            or raw_snapshot_metadata.get("source_family")
            or lineage_refs.get("source_family")
        )
        source_registry_id = _optional_str(
            raw_snapshot_metadata.get("source_registry_id")
            or lineage_refs.get("source_registry_id")
        )
        data = readback.get("bytes")
        input_sha256 = str(readback.get("sha256") or manifest.get("sha256") or "")
        if isinstance(data, bytes) and not input_sha256:
            input_sha256 = hashlib.sha256(data).hexdigest()

        if not readback.get("replayable") or not isinstance(data, bytes):
            _add_error(
                parser_errors,
                UNSUPPORTED_CONTENT_TYPE,
                "stage2 snapshot readback is not replayable",
            )
            fallback_steps.append("degrade_to_review:readback_not_replayable")
            return self._carrier(
                snapshot_id=snapshot_id,
                source_url=source_url,
                source_family=source_family,
                source_registry_id=source_registry_id,
                content_type=content_type,
                attachment_type="UNKNOWN_ATTACHMENT",
                parser_family="attachment",
                parsed_fields=[],
                started_at=started_at,
                parser_steps=parser_steps,
                fallback_steps=fallback_steps,
                parser_errors=parser_errors,
                input_sha256=input_sha256,
                parse_state="REVIEW_REQUIRED",
            ).as_payload()

        detection = _detect_attachment(
            content_type=content_type,
            source_url=source_url,
            source_file_ref=source_file_ref,
            data=data,
        )
        parser_steps.append(f"detect_attachment_type:{detection.attachment_type}")

        parsed_fields: list[ParsedField] = []
        try:
            if detection.attachment_type == "HTML":
                parsed_fields = self._parse_html(
                    data,
                    source_file_ref=source_file_ref,
                    parser_steps=parser_steps,
                    parser_errors=parser_errors,
                    fallback_steps=fallback_steps,
                )
            elif detection.attachment_type == "PDF":
                pdf_result = extract_pdf_text_with_ocr(data)
                if pdf_result.text:
                    parser_steps.append(
                        "extract_pdf_ocr_text"
                        if pdf_result.state == PDF_TEXT_OCR_EXTRACTED
                        else "extract_pdf_text"
                    )
                    parsed_fields = _extract_fields_from_text(
                        pdf_result.text,
                        source_file_ref=source_file_ref,
                        locator_type="pdf_text",
                        base_locator={"source": "pdf_text", "extractor": pdf_result.extractor},
                        confidence=pdf_result.confidence,
                        review_required=pdf_result.review_required,
                        parse_warnings=pdf_result.warnings,
                    )
                else:
                    _add_error(parser_errors, PDF_TEXT_UNAVAILABLE, pdf_result.state)
                    if OCR_REQUIRED in pdf_result.warnings or OCR_REQUIRED in pdf_result.state:
                        _add_error(parser_errors, OCR_REQUIRED, pdf_result.state)
                        fallback_steps.append("degrade_to_review:ocr_required")
                    fallback_steps.append("degrade_to_review:pdf_text_unavailable")
            elif detection.attachment_type == "SCANNED_IMAGE":
                image_result = extract_image_text_with_ocr(data)
                if image_result.text:
                    parser_steps.append("extract_image_ocr_text")
                    parsed_fields = _extract_fields_from_text(
                        image_result.text,
                        source_file_ref=source_file_ref,
                        locator_type="ocr_text",
                        base_locator={"source": "ocr_text", "extractor": image_result.extractor},
                        confidence=image_result.confidence,
                        review_required=image_result.review_required,
                        parse_warnings=image_result.warnings,
                    )
                else:
                    _add_error(parser_errors, OCR_LOW_CONFIDENCE, image_result.state)
                    _add_error(parser_errors, OCR_REQUIRED, image_result.state)
                    fallback_steps.append("degrade_to_review:ocr_unavailable_or_low_confidence")
            elif detection.attachment_type == "WORD_DOCX":
                parsed_fields = self._parse_docx(
                    data,
                    source_file_ref=source_file_ref,
                    parser_steps=parser_steps,
                    parser_errors=parser_errors,
                    fallback_steps=fallback_steps,
                )
            elif detection.attachment_type == "EXCEL_XLSX":
                parsed_fields = self._parse_xlsx(
                    data,
                    source_file_ref=source_file_ref,
                    parser_steps=parser_steps,
                    parser_errors=parser_errors,
                    fallback_steps=fallback_steps,
                )
            else:
                _add_error(
                    parser_errors,
                    ATTACHMENT_TYPE_UNKNOWN,
                    "attachment type cannot be identified from content type, extension, or zip structure",
                )
                _add_error(
                    parser_errors,
                    UNSUPPORTED_CONTENT_TYPE,
                    f"unsupported content type: {content_type}",
                )
                fallback_steps.append("degrade_to_review:attachment_type_unknown")
        except UnicodeDecodeError:
            _add_error(
                parser_errors,
                ENCODING_DECODE_FAILED,
                "text decoding failed for parser input",
            )
            fallback_steps.append("degrade_to_review:encoding_decode_failed")
            parsed_fields = []
        except Exception as exc:
            code = _failure_code_for_attachment(detection.attachment_type)
            _add_error(parser_errors, code, str(exc) or code)
            fallback_steps.append(f"degrade_to_review:{code.lower()}")
            parsed_fields = []

        review_required = bool(parser_errors) or any(field.review_required for field in parsed_fields)
        if not parsed_fields and detection.attachment_type in {"HTML", "PDF", "WORD_DOCX", "EXCEL_XLSX"}:
            review_required = True
            fallback_steps.append("degrade_to_review:no_field_candidates")
        parse_state = "PARSED"
        if review_required and parsed_fields:
            parse_state = "PARSED_WITH_REVIEW"
        elif review_required:
            parse_state = "REVIEW_REQUIRED"

        return self._carrier(
            snapshot_id=snapshot_id,
            source_url=source_url,
            source_family=source_family,
            source_registry_id=source_registry_id,
            content_type=content_type,
            attachment_type=detection.attachment_type,
            parser_family=detection.parser_family,
            parsed_fields=[field.as_payload() for field in parsed_fields],
            started_at=started_at,
            parser_steps=parser_steps,
            fallback_steps=fallback_steps,
            parser_errors=parser_errors,
            input_sha256=input_sha256,
            parse_state=parse_state,
        ).as_payload()

    def _parse_html(
        self,
        data: bytes,
        *,
        source_file_ref: str,
        parser_steps: list[str],
        parser_errors: list[dict[str, str]],
        fallback_steps: list[str],
    ) -> list[ParsedField]:
        html = _decode_text(data)
        parser = _HTMLCarrierParser()
        parser.feed(html)
        parser.close()
        parser_steps.append("extract_html_text_and_tables")

        fields, table_ambiguous = _extract_fields_from_tables(
            parser.tables,
            source_file_ref=source_file_ref,
            parser_family="html",
        )
        if table_ambiguous:
            _add_error(
                parser_errors,
                TABLE_EXTRACTION_AMBIGUOUS,
                "html table structure produced ambiguous label/value cells",
            )
            fallback_steps.append("review_table_cells:html_table_ambiguous")

        text_fields = _extract_fields_from_text(
            parser.normalized_text,
            source_file_ref=source_file_ref,
            locator_type="html_text",
            base_locator={"source": "html_visible_text"},
            confidence=0.82,
        )
        title_field = _field_from_tag_records(
            parser.tag_records,
            source_file_ref=source_file_ref,
            parser_family="html",
        )
        return _merge_fields(fields, [title_field] if title_field else [], text_fields)

    def _parse_docx(
        self,
        data: bytes,
        *,
        source_file_ref: str,
        parser_steps: list[str],
        parser_errors: list[dict[str, str]],
        fallback_steps: list[str],
    ) -> list[ParsedField]:
        try:
            docx = _read_docx(data)
        except Exception as exc:
            _add_error(parser_errors, WORD_PARSE_FAILED, str(exc) or WORD_PARSE_FAILED)
            fallback_steps.append("degrade_to_review:word_parse_failed")
            return []
        parser_steps.append("extract_docx_text_and_tables")

        fields, table_ambiguous = _extract_fields_from_tables(
            docx["tables"],
            source_file_ref=source_file_ref,
            parser_family="docx",
        )
        if table_ambiguous:
            _add_error(
                parser_errors,
                TABLE_EXTRACTION_AMBIGUOUS,
                "docx table structure produced ambiguous label/value cells",
            )
            fallback_steps.append("review_table_cells:docx_table_ambiguous")

        text_fields = _extract_fields_from_text(
            "\n".join(docx["paragraphs"]),
            source_file_ref=source_file_ref,
            locator_type="docx_text",
            base_locator={"source": "word/document.xml"},
            confidence=0.78,
        )
        return _merge_fields(fields, text_fields)

    def _parse_xlsx(
        self,
        data: bytes,
        *,
        source_file_ref: str,
        parser_steps: list[str],
        parser_errors: list[dict[str, str]],
        fallback_steps: list[str],
    ) -> list[ParsedField]:
        try:
            sheets = _read_xlsx_tables(data)
        except Exception as exc:
            _add_error(parser_errors, EXCEL_SHEET_AMBIGUOUS, str(exc) or EXCEL_SHEET_AMBIGUOUS)
            fallback_steps.append("degrade_to_review:excel_sheet_ambiguous")
            return []
        parser_steps.append("extract_xlsx_tables")

        fields_by_sheet: list[tuple[list[ParsedField], bool]] = [
            _extract_fields_from_tables(
                [sheet["table"]],
                source_file_ref=source_file_ref,
                parser_family="xlsx",
            )
            for sheet in sheets
        ]
        non_empty = [(fields, ambiguous) for fields, ambiguous in fields_by_sheet if fields]
        if len(non_empty) > 1:
            _add_error(
                parser_errors,
                EXCEL_SHEET_AMBIGUOUS,
                "multiple xlsx sheets contain parseable field candidates",
            )
            fallback_steps.append("degrade_to_review:multiple_xlsx_sheets_with_candidates")
            return []
        if not non_empty:
            _add_error(
                parser_errors,
                EXCEL_SHEET_AMBIGUOUS,
                "xlsx sheets do not expose a stable label/value table",
            )
            fallback_steps.append("degrade_to_review:no_xlsx_field_candidates")
            return []
        fields, table_ambiguous = non_empty[0]
        if table_ambiguous:
            _add_error(
                parser_errors,
                TABLE_EXTRACTION_AMBIGUOUS,
                "xlsx table structure produced ambiguous label/value cells",
            )
            fallback_steps.append("review_table_cells:xlsx_table_ambiguous")
        return fields

    def _carrier(
        self,
        *,
        snapshot_id: str,
        source_url: str | None,
        source_family: str | None,
        source_registry_id: str | None,
        content_type: str,
        attachment_type: str,
        parser_family: str,
        parsed_fields: list[dict[str, Any]],
        started_at: str,
        parser_steps: list[str],
        fallback_steps: list[str],
        parser_errors: list[dict[str, str]],
        input_sha256: str,
        parse_state: str,
    ) -> Stage3ParserCarrier:
        taxonomy = _unique([error["code"] for error in parser_errors])
        parser_audit = {
            "input_snapshot_id": snapshot_id,
            "input_sha256": input_sha256,
            "parser_steps": list(parser_steps),
            "fallback_steps": list(_unique(fallback_steps)),
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "parser_errors": [dict(error) for error in parser_errors],
        }
        review_required = bool(taxonomy) or any(
            bool(field.get("review_required")) for field in parsed_fields
        )
        carrier = Stage3ParserCarrier(
            parse_run_id=_parse_run_id(snapshot_id, input_sha256, attachment_type),
            snapshot_id=snapshot_id,
            source_url=source_url,
            source_family=source_family,
            source_registry_id=source_registry_id,
            content_type=content_type,
            attachment_type=attachment_type,
            parser_family=parser_family,
            parser_version=PARSER_VERSION,
            parser_mode=PARSER_MODE,
            parse_state=parse_state,
            verification_state=UNVERIFIED_STATE,
            stage4_verification_required=True,
            customer_visible=False,
            parsed_fields=parsed_fields,
            parser_audit=parser_audit,
            parse_error_taxonomy=taxonomy,
            review_required=review_required,
            model_assist_governance={},
            model_assist_governance_summary={},
        )
        model_assist = build_parser_model_assist(carrier.as_payload())
        return Stage3ParserCarrier(
            **{
                **carrier.as_payload(),
                MODEL_ASSIST_INPUT_KEY: model_assist,
                "model_assist_governance_summary": build_model_assist_summary(model_assist),
            }
        )


class _HTMLCarrierParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.tag_records: list[dict[str, Any]] = []
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._tag_stack: list[dict[str, Any]] = []
        self._current_table: list[list[dict[str, Any]]] | None = None
        self._current_row: list[dict[str, Any]] | None = None
        self._current_cell: dict[str, Any] | None = None

    @property
    def normalized_text(self) -> str:
        return _normalize_text("\n".join(self.text_parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"title", "h1", "h2"}:
            self._tag_stack.append({"tag": tag, "parts": [], "start": self.getpos()})
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = {
                "text": "",
                "parts": [],
                "locator": {
                    "type": "html_table_cell",
                    "tag": tag,
                    "line": self.getpos()[0],
                    "offset": self.getpos()[1],
                },
            }

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.text_parts.append(data)
        for entry in self._tag_stack:
            entry["parts"].append(data)
        if self._current_cell is not None:
            self._current_cell["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"title", "h1", "h2"}:
            for index in range(len(self._tag_stack) - 1, -1, -1):
                entry = self._tag_stack[index]
                if entry["tag"] == tag:
                    text = _normalize_text("".join(entry["parts"]))
                    if text:
                        self.tag_records.append(
                            {
                                "tag": tag,
                                "text": text,
                                "line": entry["start"][0],
                                "offset": entry["start"][1],
                            }
                        )
                    del self._tag_stack[index]
                    break
        elif tag in {"td", "th"} and self._current_cell is not None:
            text = _normalize_text("".join(self._current_cell.pop("parts")))
            self._current_cell["text"] = text
            self._current_row.append(self._current_cell)
            self._current_cell = None
        elif tag == "tr" and self._current_table is not None and self._current_row is not None:
            if any(cell.get("text") for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None


def _extract_fields_from_tables(
    tables: list[list[list[dict[str, Any]]]],
    *,
    source_file_ref: str,
    parser_family: str,
) -> tuple[list[ParsedField], bool]:
    fields: list[ParsedField] = []
    ambiguous = False
    for table_index, table in enumerate(tables):
        for row_index, row in enumerate(table):
            non_empty_cells = [cell for cell in row if str(cell.get("text", "")).strip()]
            if len(non_empty_cells) < 2:
                continue
            label_cell = non_empty_cells[0]
            value_cells = non_empty_cells[1:]
            if len(value_cells) > 1:
                ambiguous = True
            label = str(label_cell.get("text", "")).strip()
            field_name = _field_name_for_label(label)
            if not field_name:
                continue
            value_cell = value_cells[0]
            value = _field_value_for_name(field_name, str(value_cell.get("text", "")))
            if not value:
                continue
            locator = dict(value_cell.get("locator", {}))
            locator.update(
                {
                    "parser_family": parser_family,
                    "table_index": table_index,
                    "row_index": row_index,
                    "column_index": row.index(value_cell),
                    "label_column_index": row.index(label_cell),
                    "label": label,
                }
            )
            source_slice = f"{label}: {value}"
            warnings = [TABLE_EXTRACTION_AMBIGUOUS] if len(value_cells) > 1 else []
            fields.append(
                _build_field(
                    field_name=field_name,
                    value=value,
                    source_file_ref=source_file_ref,
                    source_slice=source_slice,
                    locator=locator,
                    confidence=0.88 if parser_family == "xlsx" else 0.9,
                    review_required=bool(warnings),
                    parse_warnings=warnings,
                )
            )
    return fields, ambiguous


def _extract_fields_from_text(
    text: str,
    *,
    source_file_ref: str,
    locator_type: str,
    base_locator: Mapping[str, Any],
    confidence: float,
    review_required: bool = False,
    parse_warnings: list[str] | None = None,
) -> list[ParsedField]:
    search_text = re.sub(r"[ \t]+", " ", str(text or ""))
    fields: list[ParsedField] = []
    for field_name, labels in FIELD_LABELS.items():
        pattern = re.compile(
            rf"(?P<label>{'|'.join(re.escape(label) for label in labels)})\s*[:：]\s*(?P<value>[^\n\r;；。]+)"
        )
        match = pattern.search(search_text)
        if not match:
            continue
        value = _field_value_for_name(field_name, _trim_value_before_next_label(match.group("value")))
        if not value:
            continue
        source_slice = _normalize_text(match.group(0))
        locator = {
            **dict(base_locator),
            "type": locator_type,
            "field_label": match.group("label"),
            "char_start": match.start(),
            "char_end": match.end(),
        }
        fields.append(
            _build_field(
                field_name=field_name,
                value=value,
                source_file_ref=source_file_ref,
                source_slice=source_slice,
                locator=locator,
                confidence=confidence,
                review_required=review_required,
                parse_warnings=list(parse_warnings or []),
            )
        )
    return fields


def _trim_value_before_next_label(value: str) -> str:
    labels = sorted(
        {label for labels in FIELD_LABELS.values() for label in labels},
        key=len,
        reverse=True,
    )
    pattern = rf"\s+(?:{'|'.join(re.escape(label) for label in labels)})\s*[:：]"
    return re.split(pattern, value, maxsplit=1)[0]


def _field_from_tag_records(
    tag_records: list[dict[str, Any]],
    *,
    source_file_ref: str,
    parser_family: str,
) -> ParsedField | None:
    priority = {"h1": 0, "title": 1, "h2": 2}
    ordered = sorted(tag_records, key=lambda item: priority.get(str(item.get("tag")), 99))
    for record in ordered:
        text = _normalize_text(str(record.get("text", "")))
        if not text:
            continue
        return _build_field(
            field_name="announcement_title",
            value=text,
            source_file_ref=source_file_ref,
            source_slice=text,
            locator={
                "type": f"{parser_family}_tag_text",
                "tag": record.get("tag"),
                "line": record.get("line"),
                "offset": record.get("offset"),
            },
            confidence=0.78,
        )
    return None


def _read_docx(data: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", ns):
        text = _normalize_text("".join(node.text or "" for node in para.findall(".//w:t", ns)))
        if text:
            paragraphs.append(text)
    tables: list[list[list[dict[str, Any]]]] = []
    for table_index, table in enumerate(root.findall(".//w:tbl", ns)):
        rows: list[list[dict[str, Any]]] = []
        for row_index, row in enumerate(table.findall("./w:tr", ns)):
            cells: list[dict[str, Any]] = []
            for column_index, cell in enumerate(row.findall("./w:tc", ns)):
                text = _normalize_text("".join(node.text or "" for node in cell.findall(".//w:t", ns)))
                cells.append(
                    {
                        "text": text,
                        "locator": {
                            "type": "docx_table_cell",
                            "xml_path": "word/document.xml",
                            "table_index": table_index,
                            "row_index": row_index,
                            "column_index": column_index,
                        },
                    }
                )
            rows.append(cells)
        tables.append(rows)
    return {"paragraphs": paragraphs, "tables": tables}


def _read_xlsx_tables(data: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = set(archive.namelist())
        if not any(name.startswith("xl/worksheets/") and name.endswith(".xml") for name in names):
            raise ValueError("xlsx workbook has no worksheet xml")
        shared_strings = _read_shared_strings(archive) if "xl/sharedStrings.xml" in names else []
        worksheet_names = sorted(
            name for name in names if name.startswith("xl/worksheets/") and name.endswith(".xml")
        )
        sheets: list[dict[str, Any]] = []
        for sheet_index, worksheet_name in enumerate(worksheet_names):
            root = ElementTree.fromstring(archive.read(worksheet_name))
            rows: list[list[dict[str, Any]]] = []
            for row_index, row in enumerate(_xml_children_by_suffix(root, "row")):
                cells: list[dict[str, Any]] = []
                for cell in _xml_children_by_suffix(row, "c"):
                    cell_ref = str(cell.attrib.get("r", ""))
                    text = _xlsx_cell_text(cell, shared_strings)
                    cells.append(
                        {
                            "text": text,
                            "locator": {
                                "type": "xlsx_table_cell",
                                "worksheet": worksheet_name,
                                "sheet_index": sheet_index,
                                "row_index": row_index,
                                "cell_ref": cell_ref,
                                "column_index": _column_index_from_cell_ref(cell_ref),
                            },
                        }
                    )
                if any(cell["text"] for cell in cells):
                    rows.append(cells)
            sheets.append({"worksheet": worksheet_name, "table": rows})
    return sheets


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for si in _xml_children_by_suffix(root, "si"):
        text = "".join(node.text or "" for node in si.iter() if _xml_suffix(node.tag) == "t")
        strings.append(_normalize_text(text))
    return strings


def _xlsx_cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text = "".join(node.text or "" for node in cell.iter() if _xml_suffix(node.tag) == "t")
        return _normalize_text(text)
    value_node = next((child for child in cell if _xml_suffix(child.tag) == "v"), None)
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError):
            return ""
    return _normalize_text(value)


def _xml_children_by_suffix(root: ElementTree.Element, suffix: str) -> list[ElementTree.Element]:
    return [child for child in root.iter() if _xml_suffix(child.tag) == suffix]


def _xml_suffix(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _merge_fields(*field_groups: list[ParsedField]) -> list[ParsedField]:
    by_name: dict[str, ParsedField] = {}
    for group in field_groups:
        for field in group:
            existing = by_name.get(field.field_name)
            if existing is None:
                by_name[field.field_name] = field
                continue
            if existing.field_value_optional == field.field_value_optional:
                continue
            warnings = _unique(existing.parse_warnings + [TABLE_EXTRACTION_AMBIGUOUS])
            by_name[field.field_name] = ParsedField(
                field_name=existing.field_name,
                field_value_optional=existing.field_value_optional,
                source_page_optional=existing.source_page_optional,
                source_file_ref=existing.source_file_ref,
                source_slice=existing.source_slice,
                source_slice_sha256=existing.source_slice_sha256,
                raw_text=existing.raw_text,
                locator=existing.locator,
                confidence=min(existing.confidence, field.confidence, 0.55),
                parser_version=existing.parser_version,
                review_required=True,
                parse_warnings=warnings,
            )
    return list(by_name.values())


def _build_field(
    *,
    field_name: str,
    value: str,
    source_file_ref: str,
    source_slice: str,
    locator: Mapping[str, Any],
    confidence: float,
    source_page_optional: int | None = None,
    review_required: bool = False,
    parse_warnings: list[str] | None = None,
) -> ParsedField:
    normalized_slice = _normalize_text(source_slice)
    return ParsedField(
        field_name=field_name,
        field_value_optional=_normalize_text(value),
        source_page_optional=source_page_optional,
        source_file_ref=source_file_ref,
        source_slice=normalized_slice,
        source_slice_sha256=hashlib.sha256(normalized_slice.encode("utf-8")).hexdigest(),
        raw_text=normalized_slice,
        locator=dict(locator),
        confidence=round(float(confidence), 4),
        review_required=review_required,
        parse_warnings=list(parse_warnings or []),
    )


def _field_name_for_label(label: str) -> str | None:
    normalized_label = _normalize_text(label)
    for field_name, labels in FIELD_LABELS.items():
        if any(candidate in normalized_label for candidate in labels):
            return field_name
    return None


def _field_value_for_name(field_name: str, raw_value: str) -> str | None:
    value = _normalize_text(raw_value).strip(":： \t")
    if not value:
        return None
    if field_name == "announcement_date":
        match = DATE_VALUE_RE.search(value)
        return _normalize_text(match.group("value")) if match else value
    return value


def _detect_attachment(
    *,
    content_type: str,
    source_url: str | None,
    source_file_ref: str,
    data: bytes,
) -> _AttachmentDetection:
    normalized = content_type.split(";", 1)[0].strip().lower()
    extension = _extension(source_url or source_file_ref)
    if normalized in {"text/html", "application/xhtml+xml"} or extension in {".html", ".htm"}:
        return _AttachmentDetection("HTML", "html", normalized)
    if normalized == "application/pdf" or extension == ".pdf" or data.startswith(b"%PDF"):
        return _AttachmentDetection("PDF", "pdf", normalized)
    if normalized.startswith("image/") or extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        return _AttachmentDetection("SCANNED_IMAGE", "ocr", normalized)
    if (
        normalized
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or extension == ".docx"
    ):
        return _AttachmentDetection("WORD_DOCX", "word", normalized)
    if (
        normalized == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        or extension == ".xlsx"
    ):
        return _AttachmentDetection("EXCEL_XLSX", "excel", normalized)
    if zipfile.is_zipfile(BytesIO(data)):
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
        if "word/document.xml" in names:
            return _AttachmentDetection("WORD_DOCX", "word", normalized)
        if any(name.startswith("xl/worksheets/") for name in names):
            return _AttachmentDetection("EXCEL_XLSX", "excel", normalized)
    return _AttachmentDetection("UNKNOWN_ATTACHMENT", "attachment", normalized)


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", data, 0, min(len(data), 1), "decode failed")


def _extract_pdf_text(data: bytes) -> tuple[str, str]:
    result = extract_pdf_text_with_ocr(data)
    return result.text, result.state


def _failure_code_for_attachment(attachment_type: str) -> str:
    if attachment_type == "WORD_DOCX":
        return WORD_PARSE_FAILED
    if attachment_type == "EXCEL_XLSX":
        return EXCEL_SHEET_AMBIGUOUS
    if attachment_type == "HTML":
        return ENCODING_DECODE_FAILED
    if attachment_type == "PDF":
        return PDF_TEXT_UNAVAILABLE
    if attachment_type == "SCANNED_IMAGE":
        return OCR_LOW_CONFIDENCE
    return UNSUPPORTED_CONTENT_TYPE


def _add_error(errors: list[dict[str, str]], code: str, message: str) -> None:
    if not any(error["code"] == code and error["message"] == message for error in errors):
        errors.append({"code": code, "message": message})


def _manifest(readback: Mapping[str, Any]) -> dict[str, Any]:
    manifest = readback.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _parse_run_id(snapshot_id: str, input_sha256: str, attachment_type: str) -> str:
    digest = hashlib.sha256(
        f"{snapshot_id}|{input_sha256}|{attachment_type}|{PARSER_VERSION}".encode("utf-8")
    ).hexdigest()
    return f"ST3PARSE-{digest[:20]}"


def _extension(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path or value.split("?", 1)[0].split("#", 1)[0]
    if "." not in path:
        return ""
    return "." + path.rsplit(".", 1)[-1].lower()


def _column_index_from_cell_ref(cell_ref: str) -> int | None:
    letters = re.match(r"([A-Za-z]+)", cell_ref or "")
    if not letters:
        return None
    index = 0
    for char in letters.group(1).upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


__all__ = [
    "ATTACHMENT_TYPE_UNKNOWN",
    "ENCODING_DECODE_FAILED",
    "EXCEL_SHEET_AMBIGUOUS",
    "OCR_LOW_CONFIDENCE",
    "OCR_REQUIRED",
    "PARSER_VERSION",
    "PDF_TEXT_UNAVAILABLE",
    "TABLE_EXTRACTION_AMBIGUOUS",
    "UNSUPPORTED_CONTENT_TYPE",
    "UNVERIFIED_STATE",
    "WORD_PARSE_FAILED",
    "ParsedField",
    "Stage3ParserCarrier",
    "Stage3RealParser",
]
