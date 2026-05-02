from __future__ import annotations

import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Callable


OCR_REQUIRED = "OCR_REQUIRED"
OCR_ENGINE_UNAVAILABLE = "OCR_ENGINE_UNAVAILABLE"
OCR_TEXT_EMPTY = "OCR_TEXT_EMPTY"
PDF_TEXT_EMPTY = "PDF_TEXT_EMPTY"
PDF_TEXT_EXTRACTED = "PDF_TEXT_EXTRACTED"
PDF_TEXT_EXTRACT_FAILED = "PDF_TEXT_EXTRACT_FAILED"
PDF_TEXT_EXTRACTOR_UNAVAILABLE = "PDF_TEXT_EXTRACTOR_UNAVAILABLE"
PDF_TEXT_OCR_EXTRACTED = "PDF_TEXT_OCR_EXTRACTED"
PDF_RENDERER_UNAVAILABLE = "PDF_RENDERER_UNAVAILABLE"

OcrTextProvider = Callable[[bytes], str]


@dataclass(frozen=True)
class ExtractedText:
    text: str
    state: str
    extractor: str
    confidence: float
    review_required: bool = False
    warnings: list[str] = field(default_factory=list)


def extract_pdf_text_with_ocr(
    data: bytes,
    *,
    max_text_pages: int = 30,
    max_ocr_pages: int = 5,
    ocr_text_provider: OcrTextProvider | None = None,
) -> ExtractedText:
    embedded = _extract_pdf_embedded_text(data, max_pages=max_text_pages)
    if embedded.text:
        return embedded
    if embedded.state != PDF_TEXT_EMPTY:
        return embedded
    ocr = _extract_pdf_ocr_text(
        data,
        max_pages=max_ocr_pages,
        ocr_text_provider=ocr_text_provider,
    )
    if ocr.text:
        return ocr
    return ExtractedText(
        text="",
        state=f"{PDF_TEXT_EMPTY}:{OCR_REQUIRED}:{ocr.state}",
        extractor=ocr.extractor,
        confidence=0.0,
        review_required=True,
        warnings=[OCR_REQUIRED, ocr.state],
    )


def extract_image_text_with_ocr(
    data: bytes,
    *,
    ocr_text_provider: OcrTextProvider | None = None,
) -> ExtractedText:
    if ocr_text_provider is not None:
        return _provided_ocr_text(data, ocr_text_provider, extractor="provided_image_ocr")
    try:
        import pytesseract  # type: ignore
        from PIL import Image
    except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
        return ExtractedText(
            text="",
            state=f"{OCR_REQUIRED}:{OCR_ENGINE_UNAVAILABLE}:{type(exc).__name__}",
            extractor="pytesseract",
            confidence=0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, OCR_ENGINE_UNAVAILABLE],
        )
    try:
        image = Image.open(BytesIO(data))
        text = pytesseract.image_to_string(
            image,
            lang=os.environ.get("AX9S_OCR_LANG", "chi_sim+eng"),
        ).strip()
    except Exception as exc:  # pragma: no cover - public images and local OCR vary
        return ExtractedText(
            text="",
            state=f"{OCR_REQUIRED}:OCR_EXTRACT_FAILED:{type(exc).__name__}",
            extractor="pytesseract",
            confidence=0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, "OCR_EXTRACT_FAILED"],
        )
    if not text:
        return ExtractedText(
            text="",
            state=f"{OCR_REQUIRED}:{OCR_TEXT_EMPTY}",
            extractor="pytesseract",
            confidence=0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, OCR_TEXT_EMPTY],
        )
    return ExtractedText(
        text=text,
        state="IMAGE_OCR_TEXT_EXTRACTED",
        extractor="pytesseract",
        confidence=0.58,
        review_required=True,
        warnings=[OCR_REQUIRED],
    )


def _extract_pdf_embedded_text(data: bytes, *, max_pages: int) -> ExtractedText:
    if not data.startswith(b"%PDF"):
        return ExtractedText("", "NOT_PDF", "pypdf", 0.0, review_required=True)
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
        return ExtractedText(
            "",
            f"{PDF_TEXT_EXTRACTOR_UNAVAILABLE}:{type(exc).__name__}",
            "pypdf",
            0.0,
            review_required=True,
        )
    try:
        reader = PdfReader(BytesIO(data))
        page_texts: list[str] = []
        for page in list(reader.pages)[:max_pages]:
            text = page.extract_text() or ""
            if text.strip():
                page_texts.append(text)
        extracted = "\n".join(page_texts).strip()
    except Exception as exc:  # pragma: no cover - malformed public PDFs vary
        return ExtractedText(
            "",
            f"{PDF_TEXT_EXTRACT_FAILED}:{type(exc).__name__}",
            "pypdf",
            0.0,
            review_required=True,
        )
    if not extracted:
        return ExtractedText("", PDF_TEXT_EMPTY, "pypdf", 0.0, review_required=True, warnings=[OCR_REQUIRED])
    return ExtractedText(extracted, PDF_TEXT_EXTRACTED, "pypdf", 0.74)


def _extract_pdf_ocr_text(
    data: bytes,
    *,
    max_pages: int,
    ocr_text_provider: OcrTextProvider | None,
) -> ExtractedText:
    if ocr_text_provider is not None:
        return _provided_ocr_text(data, ocr_text_provider, extractor="provided_pdf_ocr")
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
        return ExtractedText(
            "",
            f"{PDF_RENDERER_UNAVAILABLE}:{type(exc).__name__}",
            "pymupdf+pytesseract",
            0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, PDF_RENDERER_UNAVAILABLE],
        )
    try:
        import pytesseract  # type: ignore
        from PIL import Image
    except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
        return ExtractedText(
            "",
            f"{OCR_ENGINE_UNAVAILABLE}:{type(exc).__name__}",
            "pymupdf+pytesseract",
            0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, OCR_ENGINE_UNAVAILABLE],
        )
    try:
        document = fitz.open(stream=data, filetype="pdf")
        page_texts: list[str] = []
        for page in list(document)[:max_pages]:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            text = pytesseract.image_to_string(
                image,
                lang=os.environ.get("AX9S_OCR_LANG", "chi_sim+eng"),
            )
            if text.strip():
                page_texts.append(text.strip())
        extracted = "\n".join(page_texts).strip()
    except Exception as exc:  # pragma: no cover - OCR engines and public PDFs vary
        return ExtractedText(
            "",
            f"OCR_EXTRACT_FAILED:{type(exc).__name__}",
            "pymupdf+pytesseract",
            0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, "OCR_EXTRACT_FAILED"],
        )
    if not extracted:
        return ExtractedText(
            "",
            OCR_TEXT_EMPTY,
            "pymupdf+pytesseract",
            0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, OCR_TEXT_EMPTY],
        )
    return ExtractedText(
        extracted,
        PDF_TEXT_OCR_EXTRACTED,
        "pymupdf+pytesseract",
        0.62,
        review_required=True,
        warnings=[OCR_REQUIRED],
    )


def _provided_ocr_text(data: bytes, provider: OcrTextProvider, *, extractor: str) -> ExtractedText:
    try:
        text = provider(data).strip()
    except Exception as exc:
        return ExtractedText(
            "",
            f"OCR_EXTRACT_FAILED:{type(exc).__name__}",
            extractor,
            0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, "OCR_EXTRACT_FAILED"],
        )
    if not text:
        return ExtractedText(
            "",
            f"{OCR_REQUIRED}:{OCR_TEXT_EMPTY}",
            extractor,
            0.0,
            review_required=True,
            warnings=[OCR_REQUIRED, OCR_TEXT_EMPTY],
        )
    state = PDF_TEXT_OCR_EXTRACTED if extractor == "provided_pdf_ocr" else "IMAGE_OCR_TEXT_EXTRACTED"
    return ExtractedText(
        text,
        state,
        extractor,
        0.62 if extractor == "provided_pdf_ocr" else 0.58,
        review_required=True,
        warnings=[OCR_REQUIRED],
    )
