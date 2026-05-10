from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MARKITDOWN_TEXT_EXTRACTED = "MARKITDOWN_TEXT_EXTRACTED"
MARKITDOWN_TEXT_EMPTY = "MARKITDOWN_TEXT_EMPTY"
MARKITDOWN_UNAVAILABLE = "MARKITDOWN_UNAVAILABLE"
MARKITDOWN_CONVERT_FAILED = "MARKITDOWN_CONVERT_FAILED"

MARKITDOWN_TEXT_PROBE_LIMIT = 4000


@dataclass(frozen=True)
class MarkItDownText:
    text: str
    state: str
    extractor: str = "markitdown"
    text_sha256: str = ""
    text_length: int = 0
    text_probe: str = ""
    warnings: list[str] = field(default_factory=list)


def convert_bytes_to_markdown_text(
    data: bytes,
    *,
    source_url: str | None = None,
    content_type: str = "",
    source_file_ref: str = "",
) -> MarkItDownText:
    try:
        from markitdown import MarkItDown  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency varies by environment
        return MarkItDownText(
            text="",
            state=MARKITDOWN_UNAVAILABLE,
            warnings=[f"{MARKITDOWN_UNAVAILABLE}:{type(exc).__name__}"],
        )

    suffix = _suffix(source_url=source_url, content_type=content_type, source_file_ref=source_file_ref)
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(bytes(data))
            path = Path(handle.name)
        result = MarkItDown().convert(str(path))
        text = str(getattr(result, "text_content", "") or "").strip()
    except Exception as exc:  # pragma: no cover - public documents and optional deps vary
        return MarkItDownText(
            text="",
            state=MARKITDOWN_CONVERT_FAILED,
            warnings=[f"{MARKITDOWN_CONVERT_FAILED}:{type(exc).__name__}"],
        )
    finally:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
    if not text:
        return MarkItDownText(
            text="",
            state=MARKITDOWN_TEXT_EMPTY,
            warnings=[MARKITDOWN_TEXT_EMPTY],
        )
    normalized = _normalize_probe(text)
    return MarkItDownText(
        text=text,
        state=MARKITDOWN_TEXT_EXTRACTED,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text_length=len(text),
        text_probe=(
            normalized[:MARKITDOWN_TEXT_PROBE_LIMIT] + "...[TRUNCATED]"
            if len(normalized) > MARKITDOWN_TEXT_PROBE_LIMIT
            else normalized
        ),
    )


def _suffix(*, source_url: str | None, content_type: str, source_file_ref: str) -> str:
    parsed_path = urlparse(str(source_url or "")).path or str(source_file_ref or "")
    suffix = Path(parsed_path).suffix.lower()
    if suffix in {".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm"}:
        return suffix
    normalized = str(content_type or "").split(";", 1)[0].lower()
    if normalized == "application/pdf":
        return ".pdf"
    if normalized == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return ".docx"
    if normalized == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return ".xlsx"
    if normalized in {"text/html", "application/xhtml+xml"}:
        return ".html"
    return ".bin"


def _normalize_probe(text: Any) -> str:
    return "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())


__all__ = [
    "MARKITDOWN_CONVERT_FAILED",
    "MARKITDOWN_TEXT_EMPTY",
    "MARKITDOWN_TEXT_EXTRACTED",
    "MARKITDOWN_UNAVAILABLE",
    "MarkItDownText",
    "convert_bytes_to_markdown_text",
]
