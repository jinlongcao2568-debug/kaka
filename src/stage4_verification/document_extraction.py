# Stage: stage4_verification
# Optional PDF/OCR extraction helpers for public attachment evidence.

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


PERSON_NAME_PATTERN = r"[\u4e00-\u9fff·]{2,8}"
CERT_NO_PATTERN = (
    r"(?:粤\s*)?(?:[A-Z]{1,3}\s*)?\d{6,20}"
    r"|[A-Z]{1,3}\s*\d{6,20}"
    r"|[鲁闽京津沪渝冀豫云辽黑湘皖新苏浙赣鄂桂甘晋蒙陕吉贵青藏川宁琼]\s*\d{9,20}"
)


@dataclass(frozen=True)
class ExtractedDocumentPage:
    page_no: int
    text: str
    method: str

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentExtractionResult:
    document_path: str
    sha256: str
    extraction_methods: tuple[str, ...]
    pages: tuple[ExtractedDocumentPage, ...]
    text: str
    extracted_fields: dict[str, Any] = field(default_factory=dict)
    failure_reasons: tuple[str, ...] = ()
    public_only: bool = True
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pages"] = [page.as_payload() for page in self.pages]
        return payload


def extract_document_text(
    document_path: str | Path,
    *,
    enable_ocr: bool = False,
    max_pages: int = 20,
    ocr_max_pages: int | None = None,
    ocr_page_ranges: str | None = None,
    opportunity_priority_class: str | None = None,
) -> dict[str, Any]:
    path = Path(document_path)
    failures: list[str] = []
    methods: list[str] = []
    pages: list[ExtractedDocumentPage] = []
    if not path.exists():
        return DocumentExtractionResult(
            document_path=str(path),
            sha256="",
            extraction_methods=(),
            pages=(),
            text="",
            failure_reasons=("document_path_missing",),
        ).as_payload()

    sha = _sha256_file(path)
    suffix = path.suffix.lower()
    pdf_like = suffix == ".pdf" or _looks_like_pdf(path)
    if pdf_like:
        pdf_pages, pdf_methods, pdf_failures = _extract_pdf_text(path, max_pages=max_pages)
        pages.extend(pdf_pages)
        methods.extend(pdf_methods)
        failures.extend(pdf_failures)
    else:
        failures.append(f"unsupported_document_suffix:{suffix or '<none>'}")

    if enable_ocr and _needs_ocr(pages):
        ocr_pages, ocr_methods, ocr_failures = _extract_ocr_text(
            path,
            max_pages=ocr_max_pages or max_pages,
            page_ranges=ocr_page_ranges,
        )
        pages.extend(ocr_pages)
        methods.extend(ocr_methods)
        failures.extend(ocr_failures)
    if pdf_like and _needs_ocr(pages):
        failures.append("pdf_text_unavailable_or_ocr_required")

    text = "\n".join(page.text for page in pages if page.text.strip())
    fields = extract_responsible_person_fields(text, opportunity_priority_class=opportunity_priority_class)
    return DocumentExtractionResult(
        document_path=str(path),
        sha256=sha,
        extraction_methods=tuple(dict.fromkeys(methods)),
        pages=tuple(pages),
        text=text,
        extracted_fields=fields,
        failure_reasons=tuple(dict.fromkeys(failures)),
    ).as_payload()


def extract_responsible_person_fields(
    text: str,
    *,
    opportunity_priority_class: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_text(text)
    role_patterns = _role_patterns(opportunity_priority_class)
    matches: list[dict[str, Any]] = []
    for role_key, role_label_pattern in role_patterns:
        pattern = re.compile(
            rf"({role_label_pattern})\s*[:：]?\s*({PERSON_NAME_PATTERN})"
            rf"(?:[^\n\r]{{0,80}}?({CERT_NO_PATTERN}))?",
            re.IGNORECASE,
        )
        for match in pattern.finditer(normalized):
            name = _clean_name(match.group(2))
            if not _looks_like_person_name(name):
                continue
            matches.append(
                {
                    "role_key": role_key,
                    "role_label": match.group(1),
                    "person_name": name,
                    "certificate_no_optional": _clean_cert(match.group(3) or ""),
                    "source_text": match.group(0)[:160],
                }
            )
    primary = matches[0] if matches else {}
    return {
        "responsible_person_candidates": matches,
        "primary_responsible_person_name": primary.get("person_name", ""),
        "primary_responsible_role": primary.get("role_key", ""),
        "primary_certificate_no_optional": primary.get("certificate_no_optional", ""),
        "extraction_state": "FIELDS_EXTRACTED" if matches else "NO_RESPONSIBLE_PERSON_FIELD_FOUND",
    }


def build_attachment_document_evidence(
    document_path: str | Path,
    *,
    source_url: str,
    detail_page_url: str = "",
    opportunity_priority_class: str | None = None,
    enable_ocr: bool = False,
    ocr_max_pages: int | None = None,
    ocr_page_ranges: str | None = None,
) -> dict[str, Any]:
    extraction = extract_document_text(
        document_path,
        enable_ocr=enable_ocr,
        ocr_max_pages=ocr_max_pages,
        ocr_page_ranges=ocr_page_ranges,
        opportunity_priority_class=opportunity_priority_class,
    )
    return {
        "evidence_type": "attachment_document_text_extraction",
        "source_url": source_url,
        "detail_page_url": detail_page_url,
        "document_path": str(document_path),
        "document_sha256": extraction.get("sha256", ""),
        "extraction_methods": extraction.get("extraction_methods", []),
        "extracted_fields": extraction.get("extracted_fields", {}),
        "failure_reasons": extraction.get("failure_reasons", []),
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "replayable": bool(extraction.get("sha256")),
    }


def _extract_pdf_text(path: Path, *, max_pages: int) -> tuple[list[ExtractedDocumentPage], list[str], list[str]]:
    pages: list[ExtractedDocumentPage] = []
    methods: list[str] = []
    failures: list[str] = []
    try:
        import fitz  # type: ignore

        with fitz.open(str(path)) as doc:
            page_count = min(int(getattr(doc, "page_count", 0) or 0), max(1, max_pages))
            for zero_index in range(page_count):
                page = doc.load_page(zero_index)
                index = zero_index + 1
                text = str(page.get_text("text") or "").strip()
                if text:
                    pages.append(ExtractedDocumentPage(page_no=index, text=text, method="pymupdf_text"))
            methods.append("pymupdf_text")
    except Exception as exc:
        failures.append(f"pymupdf_unavailable_or_failed:{type(exc).__name__}:{exc}")

    if pages:
        return pages, methods, failures

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages[: max(1, max_pages)], start=1):
                text = str(page.extract_text() or "").strip()
                if text:
                    pages.append(ExtractedDocumentPage(page_no=index, text=text, method="pdfplumber_text"))
            methods.append("pdfplumber_text")
    except Exception as exc:
        failures.append(f"pdfplumber_unavailable_or_failed:{type(exc).__name__}:{exc}")
    return pages, methods, failures


def _extract_ocr_text(
    path: Path,
    *,
    max_pages: int,
    page_ranges: str | None = None,
) -> tuple[list[ExtractedDocumentPage], list[str], list[str]]:
    pages: list[ExtractedDocumentPage] = []
    methods: list[str] = []
    failures: list[str] = []
    engine_attempted = False

    tesseract_pages, tesseract_methods, tesseract_failures, tesseract_attempted = _extract_tesseract_ocr_text(
        path,
        max_pages=max_pages,
        page_ranges=page_ranges,
    )
    pages.extend(tesseract_pages)
    methods.extend(tesseract_methods)
    failures.extend(tesseract_failures)
    engine_attempted = engine_attempted or tesseract_attempted
    if pages:
        return pages, methods, failures

    paddle_pages, paddle_methods, paddle_failures, paddle_attempted = _extract_paddle_ocr_text(path, max_pages=max_pages)
    pages.extend(paddle_pages)
    methods.extend(paddle_methods)
    failures.extend(paddle_failures)
    engine_attempted = engine_attempted or paddle_attempted
    if pages:
        return pages, methods, failures

    if engine_attempted:
        failures.append("ocr_text_unavailable")
    else:
        failures.insert(0, "ocr_engine_unavailable")
    return pages, list(dict.fromkeys(methods)), list(dict.fromkeys(failures))


def _extract_tesseract_ocr_text(
    path: Path,
    *,
    max_pages: int,
    page_ranges: str | None = None,
) -> tuple[list[ExtractedDocumentPage], list[str], list[str], bool]:
    try:
        import fitz  # type: ignore
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except Exception as exc:
        return [], [], [f"tesseract_ocr_unavailable:{type(exc).__name__}:{exc}"], False

    if not shutil.which("tesseract"):
        windows_default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if windows_default.exists():
            pytesseract.pytesseract.tesseract_cmd = str(windows_default)

    try:
        languages = set(str(item) for item in pytesseract.get_languages(config=""))
        lang = _best_tesseract_language(languages)
    except Exception as exc:
        return [], ["tesseract_ocr"], [f"tesseract_language_probe_failed:{type(exc).__name__}:{exc}"], False

    language_failures = []
    if languages and not ({"chi_sim", "chi_tra"} & languages):
        language_failures.append("tesseract_chinese_language_unavailable")

    pages: list[ExtractedDocumentPage] = []
    try:
        if _looks_like_pdf(path) or path.suffix.lower() == ".pdf":
            with fitz.open(str(path)) as doc:
                page_count = int(getattr(doc, "page_count", 0) or 0)
                matrix = fitz.Matrix(160 / 72, 160 / 72)
                for zero_index in _ocr_page_indices(page_count, max_pages=max_pages, page_ranges=page_ranges):
                    page = doc.load_page(zero_index)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    mode = "RGB" if int(getattr(pix, "n", 0) or 0) >= 3 else "L"
                    image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                    text = str(pytesseract.image_to_string(image, lang=lang) or "").strip()
                    if text:
                        pages.append(
                            ExtractedDocumentPage(
                                page_no=zero_index + 1,
                                text=text,
                                method="tesseract_ocr",
                            )
                        )
        else:
            image = Image.open(str(path))
            text = str(pytesseract.image_to_string(image, lang=lang) or "").strip()
            if text:
                pages.append(ExtractedDocumentPage(page_no=1, text=text, method="tesseract_ocr"))
    except Exception as exc:
        return pages, ["tesseract_ocr"], [f"tesseract_ocr_failed:{type(exc).__name__}:{exc}"], True

    failures = language_failures if pages else [*language_failures, "tesseract_ocr_no_text"]
    return pages, ["tesseract_ocr"], failures, True


def _extract_paddle_ocr_text(path: Path, *, max_pages: int) -> tuple[list[ExtractedDocumentPage], list[str], list[str], bool]:
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception as exc:
        return [], [], [f"paddleocr_unavailable:{type(exc).__name__}:{exc}"], False

    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = ocr.ocr(str(path), cls=True)
    except Exception as exc:
        return [], ["paddleocr"], [f"paddleocr_failed:{type(exc).__name__}:{exc}"], True

    pages: list[ExtractedDocumentPage] = []
    page_groups = result if isinstance(result, list) else [result]
    for index, page_result in enumerate(page_groups[: max(1, max_pages)], start=1):
        lines: list[str] = []
        for item in page_result or []:
            try:
                text = str(item[1][0] or "").strip()
            except Exception:
                text = ""
            if text:
                lines.append(text)
        if lines:
            pages.append(ExtractedDocumentPage(page_no=index, text="\n".join(lines), method="paddleocr"))
    failures = [] if pages else ["paddleocr_no_text"]
    return pages, ["paddleocr"], failures, True


def _best_tesseract_language(languages: set[str]) -> str:
    candidates = [
        ("chi_sim+eng", ("chi_sim", "eng")),
        ("chi_tra+eng", ("chi_tra", "eng")),
        ("chi_sim", ("chi_sim",)),
        ("chi_tra", ("chi_tra",)),
        ("eng", ("eng",)),
    ]
    for lang, required in candidates:
        if all(item in languages for item in required):
            return lang
    return ""


def _ocr_page_indices(page_count: int, *, max_pages: int, page_ranges: str | None) -> list[int]:
    if page_count <= 0:
        return []
    budget = max(1, max_pages)
    if not page_ranges:
        return list(range(min(page_count, budget)))
    indices: list[int] = []
    seen: set[int] = set()
    for start, end in _parse_page_ranges(page_ranges):
        for page_no in range(start, end + 1):
            zero_index = page_no - 1
            if zero_index < 0 or zero_index >= page_count or zero_index in seen:
                continue
            seen.add(zero_index)
            indices.append(zero_index)
            if len(indices) >= budget:
                return indices
    return indices


def _parse_page_ranges(value: str | None) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for part in str(value or "").split(","):
        text = part.strip()
        if not text:
            continue
        if "-" in text:
            left, right = text.split("-", 1)
            start = _safe_positive_int(left)
            end = _safe_positive_int(right)
        else:
            start = end = _safe_positive_int(text)
        if start <= 0 or end <= 0:
            continue
        if end < start:
            start, end = end, start
        ranges.append((start, end))
    return ranges


def _safe_positive_int(value: str) -> int:
    try:
        number = int(str(value or "").strip())
    except ValueError:
        return 0
    return number if number > 0 else 0


def _role_patterns(opportunity_priority_class: str | None) -> list[tuple[str, str]]:
    base = [
        ("project_manager_name", r"项目经理|拟派项目经理|项目负责人|拟派项目负责人"),
        ("chief_supervision_engineer_name", r"总监理工程师|项目总监|拟派总监|总监"),
        ("design_lead_name", r"设计负责人|设计项目负责人|设计主持人"),
        ("survey_lead_name", r"勘察负责人|勘察项目负责人"),
        ("survey_design_project_lead", r"勘察设计负责人|勘察设计项目负责人"),
    ]
    priority = str(opportunity_priority_class or "")
    if priority.startswith("B_"):
        return [base[1], *base[:1], *base[2:]]
    if priority.startswith("C_"):
        return [*base[2:], *base[:2]]
    return base


def _needs_ocr(pages: list[ExtractedDocumentPage]) -> bool:
    text_len = sum(len(page.text.strip()) for page in pages)
    return text_len < 80


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", str(text or "").replace("\u3000", " "))


def _looks_like_person_name(value: str) -> bool:
    if not value or len(value) < 2 or len(value) > 8:
        return False
    blacklist = {"详见附件", "详见投标", "按招标文件", "满足要求", "合格", "无"}
    return value not in blacklist and not any(token in value for token in ("要求", "附件", "投标", "文件"))


def _clean_name(value: str) -> str:
    return re.sub(r"[^\u4e00-\u9fff·]", "", str(value or "")).strip()


def _clean_cert(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip("：:，,；;。")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except Exception:
        return False
