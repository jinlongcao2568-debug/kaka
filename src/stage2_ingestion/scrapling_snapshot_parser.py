from __future__ import annotations

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit


SCRAPLING_SNAPSHOT_PARSER_ADAPTER_ID = "stage2.scrapling_snapshot_parser.v1"

_ATTACHMENT_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
)
_ATTACHMENT_TEXT_HINTS = (
    "attachment",
    "download",
    "qualification",
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "zip",
    "rar",
    "附件",
    "下载",
    "招标文件",
    "采购文件",
    "结果文件",
    "资格要求",
    "评标报告",
    "定标报告",
)
_ATTACHMENT_URL_HINTS = (
    "/download",
    "/attach",
    "/attachment",
    "/files/",
    "downloadztbattach",
    "attachguid=",
    "filecode=",
)
_FIELD_SIGNAL_LABELS: dict[str, tuple[str, ...]] = {
    "project_name": ("项目名称", "工程名称", "工程项目名称", "招标项目名称"),
    "project_code": ("项目编号", "招标编号", "采购编号", "标段编号", "项目代码"),
    "tenderer_or_purchaser": ("招标人", "采购人", "建设单位", "招标单位", "采购单位"),
    "announcement_date": ("公告日期", "发布日期", "发布时间", "公示日期"),
    "candidate_company": ("第一中标候选人", "第一成交候选人", "中标候选人", "成交候选人", "中标单位", "单位名称", "投标人名称", "候选人名称"),
    "primary_responsible_person_name": (
        "拟派项目负责人",
        "项目负责人姓名",
        "项目负责人",
        "项目经理姓名",
        "项目经理",
        "总监理工程师",
        "设计负责人",
        "勘察负责人",
    ),
}
_FIELD_SIGNAL_LABEL_ORDER = tuple(
    sorted({label for labels in _FIELD_SIGNAL_LABELS.values() for label in labels}, key=len, reverse=True)
)
_GENERIC_TITLES = {
    "广州交易集团有限公司",
    "全国公共资源交易平台",
    "全国公共资源交易平台（广东省）",
}
_DATE_VALUE_RE = re.compile(r"\d{4}\s*(?:-|/|年)\s*\d{1,2}\s*(?:-|/|月)\s*\d{1,2}\s*(?:日)?")
_PROJECT_CODE_RE = re.compile(r"(?:[A-Z]{1,8}\d{4}[-A-Za-z0-9]{2,40}|\d{4}[-A-Za-z0-9]{6,40})")
_DATE_RANGE_RE = re.compile(
    r"\d{4}\s*(?:-|/|年)\s*\d{1,2}\s*(?:-|/|月)\s*\d{1,2}\s*(?:日)?"
    r"\s*(?:至|到|-|--|—|~)\s*"
    r"\d{4}\s*(?:-|/|年)\s*\d{1,2}\s*(?:-|/|月)\s*\d{1,2}\s*(?:日)?"
)
_DURATION_RE = re.compile(r"\d{1,4}\s*(?:日历天|个日历天|天|个月|月|年)")
_NOTICE_STAGE_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("candidate_notice", ("中标候选人", "成交候选人", "候选人公示")),
    ("award_result", ("中标公告", "成交公告", "结果公告", "中标结果", "成交结果")),
    ("correction_notice", ("更正公告", "变更公告", "澄清公告", "答疑")),
    ("tender_notice", ("招标公告", "采购公告", "竞争性谈判公告", "磋商公告")),
    ("contract_public_info", ("合同公告", "合同信息公开", "合同履约")),
)


class _StdlibHtmlSnapshotParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._tag_stack: list[str] = []
        self._active_anchor: dict[str, str] | None = None
        self._title_chunks: list[str] = []
        self._heading_chunks: list[str] = []
        self._text_chunks: list[str] = []
        self.anchor_records: list[dict[str, str]] = []
        self.table_records: list[dict[str, Any]] = []
        self._active_table: dict[str, Any] | None = None
        self._active_row: dict[str, Any] | None = None
        self._active_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        self._tag_stack.append(normalized_tag)
        if normalized_tag == "table" and self._active_table is None:
            self._active_table = {"row_records": []}
        elif normalized_tag == "tr" and self._active_table is not None and self._active_row is None:
            self._active_row = {"cell_records": []}
        elif normalized_tag in {"th", "td"} and self._active_row is not None and self._active_cell is None:
            self._active_cell = {"cell_tag": normalized_tag, "text_chunks": []}
        if normalized_tag != "a":
            return
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        hrefs = _href_candidates_from_attributes(attr_map)
        if hrefs:
            self._active_anchor = {"hrefs": "\n".join(hrefs), "text": ""}

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "a" and self._active_anchor is not None:
            for href in str(self._active_anchor.get("hrefs") or "").splitlines():
                if href.strip():
                    self.anchor_records.append({"href": href.strip(), "text": str(self._active_anchor.get("text") or "")})
            self._active_anchor = None
        if normalized_tag in {"th", "td"} and self._active_cell is not None and self._active_row is not None:
            text = _normalize_text(" ".join(list(self._active_cell.get("text_chunks") or [])))
            self._active_row["cell_records"].append(
                {
                    "cell_index": len(list(self._active_row.get("cell_records") or [])),
                    "cell_tag": str(self._active_cell.get("cell_tag") or normalized_tag),
                    "text": text,
                }
            )
            self._active_cell = None
        elif normalized_tag == "tr" and self._active_row is not None and self._active_table is not None:
            cells = [dict(cell) for cell in list(self._active_row.get("cell_records") or []) if str(cell.get("text") or "")]
            if cells:
                self._active_table["row_records"].append(
                    {
                        "row_index": len(list(self._active_table.get("row_records") or [])),
                        "cell_values": [str(cell.get("text") or "") for cell in cells],
                        "cell_records": cells,
                    }
                )
            self._active_row = None
        elif normalized_tag == "table" and self._active_table is not None:
            table = _finalize_table_record(
                self._active_table,
                table_index=len(self.table_records),
                extraction_backend="STDLIB_HTML_PARSER_FALLBACK",
            )
            if table:
                self.table_records.append(table)
            self._active_table = None
        for index in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[index] == normalized_tag:
                del self._tag_stack[index:]
                break

    def handle_data(self, data: str) -> None:
        cleaned = _normalize_text(data)
        if not cleaned:
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self._title_chunks.append(cleaned)
        if self._tag_stack and self._tag_stack[-1] in {"h1", "h2"}:
            self._heading_chunks.append(cleaned)
        if self._tag_stack and self._tag_stack[-1] in {"script", "style"}:
            return
        self._text_chunks.append(cleaned)
        if self._active_cell is not None:
            self._active_cell["text_chunks"].append(cleaned)
        if self._active_anchor is not None:
            existing = self._active_anchor.get("text") or ""
            self._active_anchor["text"] = _normalize_text(f"{existing} {cleaned}")

    @property
    def title(self) -> str:
        raw_title = _normalize_text(" ".join(self._title_chunks))
        heading = _normalize_text(" ".join(self._heading_chunks[:2]))
        return _prefer_headline_title(raw_title, heading)

    @property
    def all_text(self) -> str:
        return _normalize_text(" ".join(self._text_chunks))


def parse_snapshot_html_with_scrapling(
    html: str | bytes,
    *,
    base_url: str = "",
    keywords: Iterable[Any] = (),
    max_links: int = 120,
    selector_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    body = _decode_html(html)
    failure_taxonomy: list[str] = []
    selector_backend_available = False

    if selector_factory is None:
        try:
            from scrapling.parser import Selector  # type: ignore

            selector_factory = Selector
            selector_backend_available = True
        except Exception as exc:  # pragma: no cover - depends on optional runtime dependency
            selector_factory = None
            failure_taxonomy.append(f"scrapling_import_failed:{type(exc).__name__}")
    else:
        selector_backend_available = True

    if selector_factory is not None:
        try:
            parsed = _parse_with_scrapling_selector(
                selector_factory,
                body,
                base_url=base_url,
                max_links=max_links,
            )
            parser_backend = "SCRAPLING_SELECTOR"
            parser_state = "PARSED_WITH_SCRAPLING"
        except Exception as exc:  # pragma: no cover - Scrapling internals may vary by release
            failure_taxonomy.append(f"scrapling_selector_parse_failed:{type(exc).__name__}")
            parsed = _parse_with_stdlib_html_parser(body, base_url=base_url, max_links=max_links)
            parser_backend = "STDLIB_HTML_PARSER_FALLBACK"
            parser_state = "PARSED_WITH_STDLIB_FALLBACK"
    else:
        parsed = _parse_with_stdlib_html_parser(body, base_url=base_url, max_links=max_links)
        parser_backend = "STDLIB_HTML_PARSER_FALLBACK"
        parser_state = "PARSED_WITH_STDLIB_FALLBACK"

    keyword_hits = _keyword_hits(parsed["all_text"], keywords)
    field_signal_summary, field_candidate_records = _field_signal_summary(
        title=parsed["title"],
        all_text=parsed["all_text"],
        table_records=parsed["table_records"],
    )
    table_extraction_summary = _table_extraction_summary(parsed["table_records"])
    return {
        "parser_adapter_id": SCRAPLING_SNAPSHOT_PARSER_ADAPTER_ID,
        "parser_state": parser_state,
        "parser_backend": parser_backend,
        "scrapling_available": selector_backend_available,
        "scrapling_missing": not selector_backend_available,
        "no_live_request": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "base_url": base_url,
        "title": parsed["title"],
        "text_sha256": hashlib.sha256(parsed["all_text"].encode("utf-8")).hexdigest(),
        "text_probe": parsed["all_text"][:1000],
        "keyword_hits": keyword_hits,
        "table_extraction_summary": table_extraction_summary,
        "table_records": parsed["table_records"],
        "field_signal_summary": field_signal_summary,
        "field_candidate_records": field_candidate_records,
        "link_count": len(parsed["link_records"]),
        "attachment_link_count": len(parsed["attachment_link_records"]),
        "same_site_link_count": len(parsed["same_site_link_records"]),
        "link_records": parsed["link_records"],
        "attachment_link_records": parsed["attachment_link_records"],
        "same_site_link_records": parsed["same_site_link_records"],
        "failure_taxonomy": list(dict.fromkeys(failure_taxonomy)),
    }


def build_scrapling_snapshot_parser_summary(readback: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "parser_adapter_id": str(readback.get("parser_adapter_id") or ""),
        "parser_state": str(readback.get("parser_state") or ""),
        "parser_backend": str(readback.get("parser_backend") or ""),
        "scrapling_available": bool(readback.get("scrapling_available")),
        "scrapling_missing": bool(readback.get("scrapling_missing")),
        "no_live_request": bool(readback.get("no_live_request")),
        "customer_visible_allowed": bool(readback.get("customer_visible_allowed")),
        "no_legal_conclusion": bool(readback.get("no_legal_conclusion")),
        "link_count": int(readback.get("link_count") or 0),
        "same_site_link_count": int(readback.get("same_site_link_count") or 0),
        "attachment_link_count": int(readback.get("attachment_link_count") or 0),
        "keyword_hits": list(readback.get("keyword_hits") or []),
        "table_extraction_summary": dict(readback.get("table_extraction_summary") or {}),
        "field_signal_summary": dict(readback.get("field_signal_summary") or {}),
        "failure_taxonomy": list(readback.get("failure_taxonomy") or []),
    }


def _parse_with_scrapling_selector(
    selector_factory: Callable[..., Any],
    body: str,
    *,
    base_url: str,
    max_links: int,
) -> dict[str, Any]:
    selector = selector_factory(content=body, url=base_url)
    raw_title = _first_selector_text(selector.css("title"))
    heading = _first_selector_text(selector.css("h1")) or _first_selector_text(selector.css("h2"))
    title = _prefer_headline_title(raw_title, heading)
    all_text = _normalize_text(str(selector.get_all_text(separator=" ", strip=True)))
    table_records = _table_records_from_scrapling_selector(selector)
    anchor_records: list[dict[str, str]] = []
    for anchor in list(selector.css("a"))[: max_links * 2]:
        hrefs = _href_candidates_from_attributes(getattr(anchor, "attrib", {}))
        if not hrefs:
            continue
        link_text = _normalize_text(str(getattr(anchor, "text", "") or anchor.get_all_text(separator=" ", strip=True)))
        for href in hrefs:
            anchor_records.append({"href": href, "text": link_text})
    return _classify_anchor_records(
        anchor_records,
        title=title,
        all_text=all_text,
        base_url=base_url,
        max_links=max_links,
        table_records=table_records,
    )


def _parse_with_stdlib_html_parser(body: str, *, base_url: str, max_links: int) -> dict[str, Any]:
    parser = _StdlibHtmlSnapshotParser()
    parser.feed(body)
    return _classify_anchor_records(
        parser.anchor_records,
        title=parser.title,
        all_text=parser.all_text,
        base_url=base_url,
        max_links=max_links,
        table_records=parser.table_records,
    )


def _classify_anchor_records(
    anchor_records: Iterable[Mapping[str, str]],
    *,
    title: str,
    all_text: str,
    base_url: str,
    max_links: int,
    table_records: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_host = (urlsplit(base_url).hostname or "").lower()
    link_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in anchor_records:
        href = unescape(str(anchor.get("href") or "")).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full_url = urljoin(base_url, href).split("#", 1)[0]
        parsed = urlsplit(full_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        link_text = _normalize_text(str(anchor.get("text") or ""))
        if _has_template_placeholder(full_url, link_text):
            continue
        same_site = _source_host_allowed(expected_host, (parsed.hostname or "").lower())
        match_reasons = _attachment_match_reasons(full_url, link_text)
        link_kind = "attachment_candidate" if match_reasons else ("same_site_link" if same_site else "external_link")
        if full_url in seen:
            continue
        seen.add(full_url)
        link_records.append(
            {
                "url": full_url,
                "href": href,
                "text": link_text,
                "same_site": same_site,
                "link_kind": link_kind,
                "match_reasons": match_reasons,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
        if len(link_records) >= max_links:
            break
    attachment_link_records = [
        record
        for record in link_records
        if record.get("link_kind") == "attachment_candidate" and record.get("same_site")
    ][:50]
    same_site_link_records = [record for record in link_records if record.get("same_site")][:50]
    return {
        "title": title,
        "all_text": all_text,
        "table_records": table_records,
        "link_records": link_records,
        "attachment_link_records": attachment_link_records,
        "same_site_link_records": same_site_link_records,
    }


def _attachment_match_reasons(url: str, link_text: str) -> list[str]:
    lowered = f"{url} {link_text}".lower()
    path = urlsplit(url).path.lower()
    reasons: list[str] = []
    if path.endswith(_ATTACHMENT_EXTENSIONS):
        reasons.append("supported_attachment_extension")
    if any(token in lowered for token in _ATTACHMENT_URL_HINTS):
        reasons.append("attachment_url_hint")
    if any(token in lowered for token in _ATTACHMENT_TEXT_HINTS):
        reasons.append("attachment_text_hint")
    return list(dict.fromkeys(reasons))


def _table_records_from_scrapling_selector(selector: Any, *, max_tables: int = 20, max_rows: int = 80) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        tables = list(selector.css("table"))[:max_tables]
    except Exception:
        return records
    for table_index, table in enumerate(tables):
        row_records: list[dict[str, Any]] = []
        try:
            rows = list(table.css("tr"))[:max_rows]
        except Exception:
            rows = []
        for row_index, row in enumerate(rows):
            try:
                cell_selectors = list(row.css("th,td"))[:20]
            except Exception:
                cell_selectors = []
            cell_records: list[dict[str, Any]] = []
            for cell_index, cell in enumerate(cell_selectors):
                text = _normalize_text(str(cell.get_all_text(separator=" ", strip=True)))
                if not text:
                    continue
                cell_records.append(
                    {
                        "cell_index": cell_index,
                        "cell_tag": str(getattr(cell, "tag", "") or ""),
                        "text": text,
                    }
                )
            if cell_records:
                row_records.append(
                    {
                        "row_index": row_index,
                        "cell_values": [str(cell.get("text") or "") for cell in cell_records],
                        "cell_records": cell_records,
                    }
                )
        table_record = _finalize_table_record(
            {"row_records": row_records},
            table_index=table_index,
            extraction_backend="SCRAPLING_SELECTOR",
        )
        if table_record:
            records.append(table_record)
    return records


def _finalize_table_record(
    raw_table: Mapping[str, Any],
    *,
    table_index: int,
    extraction_backend: str,
) -> dict[str, Any] | None:
    row_records = [
        dict(row)
        for row in list(raw_table.get("row_records") or [])
        if isinstance(row, Mapping) and list(row.get("cell_values") or [])
    ]
    if not row_records:
        return None
    label_value_pairs = _table_label_value_pairs(row_records)
    candidate_row_records = _candidate_table_row_records(row_records)
    table_text = _normalize_text(" ".join(" ".join(list(row.get("cell_values") or [])) for row in row_records))
    return {
        "table_index": table_index,
        "extraction_backend": extraction_backend,
        "row_count": len(row_records),
        "column_count_max": max((len(list(row.get("cell_values") or [])) for row in row_records), default=0),
        "table_kind": _infer_table_kind(
            label_value_pairs=label_value_pairs,
            candidate_row_records=candidate_row_records,
            table_text=table_text,
        ),
        "row_records": row_records[:40],
        "label_value_pairs": label_value_pairs[:40],
        "candidate_row_records": candidate_row_records[:30],
        "text_sha256": hashlib.sha256(table_text.encode("utf-8")).hexdigest() if table_text else "",
        "text_probe": table_text[:600],
        "parser_only_signal": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _table_label_value_pairs(row_records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in row_records:
        values = [_normalize_text(str(value or "")) for value in list(row.get("cell_values") or [])]
        if len(values) < 2:
            continue
        for index in range(len(values) - 1):
            label = values[index].strip(" ：:")
            value = values[index + 1].strip(" ：:")
            field_name = _field_name_for_signal_label(label)
            if not field_name or not value:
                continue
            cleaned = _clean_field_signal_value(field_name, value)
            if not cleaned:
                continue
            key = (field_name, label, cleaned)
            if key in seen:
                continue
            seen.add(key)
            source_slice = _normalize_text(f"{label}: {cleaned}")
            pairs.append(
                {
                    "field_name": field_name,
                    "field_label": label,
                    "field_value_optional": cleaned,
                    "row_index": int(row.get("row_index") or 0),
                    "label_column_index": index,
                    "value_column_index": index + 1,
                    "source_slice": source_slice,
                    "source_slice_sha256": hashlib.sha256(source_slice.encode("utf-8")).hexdigest(),
                    "match_kind": "table_label_value",
                    "confidence": 0.86,
                    "review_required": True,
                    "parser_only_signal": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return pairs


def _candidate_table_row_records(row_records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in row_records:
        values = [_normalize_text(str(value or "")) for value in list(row.get("cell_values") or [])]
        row_text = _normalize_text(" ".join(values))
        if not row_text:
            continue
        signal_tokens = [
            token
            for token in ("第一中标候选人", "第一成交候选人", "中标候选人", "成交候选人", "候选人名称", "投标人名称", "单位名称")
            if token in row_text
        ]
        company = _company_signal_from_value(row_text)
        person = _person_signal_from_candidate_row(row_text)
        if not signal_tokens and not company:
            continue
        if not company and not person and not any(token in row_text for token in ("第一中标候选人", "第一成交候选人")):
            continue
        key = hashlib.sha256(row_text.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "row_index": int(row.get("row_index") or 0),
                "row_text": row_text[:500],
                "signal_tokens": signal_tokens,
                "candidate_company_optional": company,
                "primary_responsible_person_optional": person,
                "cell_values": values[:12],
                "match_kind": "candidate_table_row_signal",
                "confidence": 0.76 if company else 0.62,
                "review_required": True,
                "parser_only_signal": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _infer_table_kind(
    *,
    label_value_pairs: list[Mapping[str, Any]],
    candidate_row_records: list[Mapping[str, Any]],
    table_text: str,
) -> str:
    if candidate_row_records:
        return "candidate_or_bidder_table"
    field_names = {str(pair.get("field_name") or "") for pair in label_value_pairs}
    if {"project_name", "project_code"} & field_names:
        return "project_metadata_table"
    if any(token in table_text for token in ("附件", "下载", "文件")):
        return "attachment_or_file_table"
    return "generic_table"


def _table_extraction_summary(table_records: list[Mapping[str, Any]]) -> dict[str, Any]:
    table_kind_counts: dict[str, int] = {}
    for table in table_records:
        kind = str(table.get("table_kind") or "generic_table")
        table_kind_counts[kind] = table_kind_counts.get(kind, 0) + 1
    label_value_pair_count = sum(len(list(table.get("label_value_pairs") or [])) for table in table_records)
    candidate_row_signal_count = sum(len(list(table.get("candidate_row_records") or [])) for table in table_records)
    return {
        "table_extraction_state": "TABLES_FOUND" if table_records else "NO_TABLES_FOUND",
        "table_count": len(table_records),
        "table_row_total": sum(int(table.get("row_count") or 0) for table in table_records),
        "label_value_pair_count": label_value_pair_count,
        "candidate_row_signal_count": candidate_row_signal_count,
        "table_kind_counts": dict(sorted(table_kind_counts.items())),
        "parser_only": True,
        "no_live_request": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _href_candidates_from_attributes(attributes: Any) -> list[str]:
    candidates: list[str] = []
    primary_keys = ("href", "data-href", "data-url", "data-file", "data-fileurl", "fileurl", "url")
    attr_map = _attributes_as_mapping(attributes)
    for key in primary_keys:
        value = str(attr_map.get(key) or "").strip()
        if value:
            candidates.append(value)
    for key, value in attr_map.items():
        if key in primary_keys:
            continue
        raw_value = str(value or "")
        if not raw_value:
            continue
        for href in _explicit_download_hrefs_from_text(raw_value):
            candidates.append(href)
    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        href = unescape(str(candidate or "")).strip().strip("'\"")
        if not href or href in seen:
            continue
        seen.add(href)
        cleaned.append(href)
    return cleaned


def _explicit_download_hrefs_from_text(value: str) -> list[str]:
    text = unescape(str(value or ""))
    matches: list[str] = []
    for match in re.finditer(r"https?://[^'\"\s<>),]+", text, flags=re.IGNORECASE):
        href = match.group(0).strip()
        if _has_explicit_download_endpoint(href):
            matches.append(href)
    for match in re.finditer(r"['\"](?P<href>/[^'\"]*(?:downloadztbattach|download)[^'\"]*)['\"]", text, flags=re.IGNORECASE):
        href = match.group("href").strip()
        if _has_explicit_download_endpoint(href):
            matches.append(href)
    return matches


def _has_explicit_download_endpoint(value: str) -> bool:
    lowered = str(value or "").lower()
    return (
        "downloadztbattach" in lowered
        or "/download" in lowered
        or "attachguid=" in lowered
        or "filecode=" in lowered
    )


def _attributes_as_mapping(attributes: Any) -> dict[str, str]:
    if isinstance(attributes, Mapping):
        return {str(key).lower(): str(value or "") for key, value in attributes.items()}
    try:
        return {str(key).lower(): str(value or "") for key, value in dict(attributes).items()}
    except Exception:
        return {}


def _source_host_allowed(expected_host: str, candidate_host: str) -> bool:
    expected = str(expected_host or "").split(":", 1)[0].lower()
    candidate = str(candidate_host or "").split(":", 1)[0].lower()
    if not expected or not candidate:
        return False
    if expected == candidate:
        return True
    if expected == "ywtb.gzggzy.cn" and candidate == "jsgc.gzggzy.cn":
        return True
    return False


def _keyword_hits(text: str, keywords: Iterable[Any]) -> list[dict[str, Any]]:
    normalized_text = str(text or "")
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_keyword in keywords:
        keyword = _normalize_text(str(raw_keyword or ""))
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        count = normalized_text.count(keyword)
        if count > 0:
            hits.append({"keyword": keyword, "hit_count": count})
    return hits


def _field_signal_summary(
    *,
    title: str,
    all_text: str,
    table_records: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = _field_candidate_records(title=title, all_text=all_text, table_records=table_records)
    field_counts: dict[str, int] = {}
    for record in records:
        field_name = str(record.get("field_name") or "")
        field_counts[field_name] = field_counts.get(field_name, 0) + 1
    notice_stage, notice_hits = _notice_stage_signal(f"{title} {all_text[:4000]}")
    summary = {
        "field_signal_state": "FIELD_SIGNALS_FOUND" if records else "NO_FIELD_SIGNALS_FOUND",
        "field_candidate_count": len(records),
        "field_candidate_field_counts": dict(sorted(field_counts.items())),
        "notice_stage_signal": notice_stage,
        "notice_stage_hit_tokens": notice_hits,
        "project_code_signal_count": field_counts.get("project_code", 0),
        "responsible_person_signal_count": field_counts.get("primary_responsible_person_name", 0),
        "time_window_signal_count": field_counts.get("duration_or_period_optional", 0),
        "table_label_value_signal_count": sum(1 for record in records if record.get("match_kind") == "table_label_value"),
        "parser_only": True,
        "no_live_request": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return summary, records


def _field_candidate_records(
    *,
    title: str,
    all_text: str,
    table_records: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    text = _normalize_text(all_text)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    cleaned_title = _normalize_text(title)
    if cleaned_title and cleaned_title not in _GENERIC_TITLES:
        _append_field_record(
            records,
            seen,
            field_name="announcement_title",
            value=cleaned_title,
            source_slice=cleaned_title,
            label="title",
            match_kind="html_title",
            confidence=0.86,
        )

    for table in table_records:
        for pair in list(table.get("label_value_pairs") or []):
            if not isinstance(pair, Mapping):
                continue
            field_name = str(pair.get("field_name") or "")
            value = str(pair.get("field_value_optional") or "")
            label = str(pair.get("field_label") or "")
            source_slice = str(pair.get("source_slice") or "")
            if not field_name or not value:
                continue
            _append_field_record(
                records,
                seen,
                field_name=field_name,
                value=value,
                source_slice=source_slice,
                label=label,
                match_kind="table_label_value",
                confidence=0.86,
            )

    for field_name, labels in _FIELD_SIGNAL_LABELS.items():
        for label in labels:
            pattern = re.compile(rf"{re.escape(label)}\s*[:：]?\s*(?P<value>.{{1,220}})")
            for match in list(pattern.finditer(text))[:5]:
                value = _clean_field_signal_value(field_name, match.group("value"))
                if not value:
                    continue
                source_slice = _normalize_text(text[match.start() : min(match.end(), match.start() + 260)])
                _append_field_record(
                    records,
                    seen,
                    field_name=field_name,
                    value=value,
                    source_slice=source_slice,
                    label=label,
                    match_kind="visible_text_label",
                    confidence=_field_signal_confidence(field_name),
                )

    for record in _time_window_signal_records(text):
        key = (record["field_name"], record["field_value_optional"], record["field_label"])
        if key not in seen:
            seen.add(key)
            records.append(record)
    return records[:80]


def _append_field_record(
    records: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    field_name: str,
    value: str,
    source_slice: str,
    label: str,
    match_kind: str,
    confidence: float,
) -> None:
    cleaned_value = _normalize_text(value).strip(" ：:，,；;。")
    if not cleaned_value:
        return
    key = (field_name, cleaned_value, label)
    if key in seen:
        return
    seen.add(key)
    normalized_slice = _normalize_text(source_slice)
    records.append(
        {
            "field_name": field_name,
            "field_value_optional": cleaned_value,
            "field_label": label,
            "source_slice": normalized_slice[:300],
            "source_slice_sha256": hashlib.sha256(normalized_slice.encode("utf-8")).hexdigest() if normalized_slice else "",
            "match_kind": match_kind,
            "confidence": confidence,
            "review_required": True,
            "parser_only_signal": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    )


def _clean_field_signal_value(field_name: str, raw_value: str) -> str:
    value = _trim_before_next_field_label(raw_value)
    value = re.split(r"(?:公告附件|相关附件|附件下载|异议受理|公示结束|公示期|招标人|采购人)", value, maxsplit=1)[0]
    value = _normalize_text(value).strip(" ：:，,；;。")
    if not value:
        return ""
    if field_name == "announcement_date":
        match = _DATE_VALUE_RE.search(value)
        return _normalize_text(match.group(0)) if match else ""
    if field_name == "project_code":
        match = _PROJECT_CODE_RE.search(value)
        return _normalize_text(match.group(0)) if match else _bounded_signal_value(value, 80)
    if field_name == "primary_responsible_person_name":
        return _person_signal_from_value(value)
    if field_name == "candidate_company":
        return _company_signal_from_value(value)
    return _bounded_signal_value(value, 120)


def _field_name_for_signal_label(label: str) -> str:
    normalized = _normalize_text(label)
    if not normalized:
        return ""
    for field_name, labels in _FIELD_SIGNAL_LABELS.items():
        if any(candidate in normalized for candidate in labels):
            return field_name
    return ""


def _trim_before_next_field_label(raw_value: str) -> str:
    value = _normalize_text(raw_value)
    if not value:
        return ""
    label_pattern = "|".join(re.escape(label) for label in _FIELD_SIGNAL_LABEL_ORDER)
    split_value = re.split(rf"\s+(?:{label_pattern})\s*[:：]?", value, maxsplit=1)
    return split_value[0] if split_value else value


def _bounded_signal_value(value: str, limit: int) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" ：:，,；;。")


def _person_signal_from_value(value: str) -> str:
    for match in re.finditer(r"[\u4e00-\u9fff·]{2,8}", value):
        candidate = _normalize_text(match.group(0)).strip(" ：:，,；;。")
        if _looks_like_person_name_signal(candidate):
            return candidate
    return ""


def _person_signal_from_candidate_row(value: str) -> str:
    role_contexts = (
        "项目负责人",
        "项目经理",
        "拟派项目负责人",
        "总监理工程师",
        "设计负责人",
        "勘察负责人",
    )
    for role in role_contexts:
        position = value.find(role)
        if position < 0:
            continue
        person = _person_signal_from_value(value[position : position + 80])
        if person:
            return person
    return ""


def _looks_like_person_name_signal(value: str) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", value or ""):
        return False
    organization_tokens = (
        "公司",
        "集团",
        "工程",
        "建设",
        "设计",
        "研究",
        "有限",
        "项目",
        "负责人",
        "经理",
        "候选人",
        "投标人",
        "单位",
        "公告",
    )
    return not any(token in value for token in organization_tokens)


def _company_signal_from_value(value: str) -> str:
    company_suffix = (
        r"设计院\s*有限(?:\s*责任)?\s*公司",
        r"研究院\s*有限(?:\s*责任)?\s*公司",
        r"有限\s*责任\s*公司",
        r"股份\s*有限公司",
        r"集团\s*有限公司",
        r"工程建设\s*有限公司",
        r"建设管理\s*有限公司",
        r"工程咨询\s*有限公司",
        r"监理\s*有限公司",
        r"有限\s*公司",
        r"集团",
        r"设计院",
        r"研究院",
        r"事务所",
    )
    match = re.search(rf"[\u4e00-\u9fffA-Za-z0-9（）()·\-]{{2,100}}?(?:{'|'.join(company_suffix)})", value)
    if not match:
        return ""
    return _bounded_signal_value(match.group(0), 120)


def _time_window_signal_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    label_pattern = r"(?:合同周期|合同期|履约期限|履约期|服务期|服务期限|工期|计划工期|交付时间|交付期)"
    for match in re.finditer(rf"{label_pattern}.{{0,120}}", text):
        source_slice = _normalize_text(match.group(0))
        value_match = _DATE_RANGE_RE.search(source_slice) or _DURATION_RE.search(source_slice)
        if not value_match:
            continue
        label_match = re.match(label_pattern, source_slice)
        label = label_match.group(0) if label_match else "duration_or_period"
        value = _normalize_text(value_match.group(0))
        key = ("duration_or_period_optional", value, label)
        if key in seen:
            continue
        seen.add(key)
        normalized_slice = _normalize_text(source_slice)
        records.append(
            {
                "field_name": "duration_or_period_optional",
                "field_value_optional": value,
                "field_label": label,
                "source_slice": normalized_slice[:300],
                "source_slice_sha256": hashlib.sha256(normalized_slice.encode("utf-8")).hexdigest() if normalized_slice else "",
                "match_kind": "visible_text_time_window_signal",
                "confidence": 0.72,
                "review_required": True,
                "parser_only_signal": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records[:20]


def _notice_stage_signal(text: str) -> tuple[str, list[str]]:
    for stage, tokens in _NOTICE_STAGE_SIGNALS:
        stage_hits = [token for token in tokens if token in text]
        if stage_hits:
            return stage, list(dict.fromkeys(stage_hits))
    return "unknown", []


def _field_signal_confidence(field_name: str) -> float:
    if field_name in {"announcement_date", "project_code"}:
        return 0.78
    if field_name in {"candidate_company", "primary_responsible_person_name"}:
        return 0.7
    return 0.74


def _prefer_headline_title(raw_title: str, heading: str) -> str:
    title = _normalize_text(raw_title)
    headline = _normalize_text(heading)
    if headline and (not title or title in _GENERIC_TITLES):
        return headline
    return title or headline


def _first_selector_text(selectors: Any) -> str:
    first = getattr(selectors, "first", None)
    if first is None:
        try:
            first = list(selectors)[0]
        except Exception:
            return ""
    return _normalize_text(str(getattr(first, "text", "") or first.get_all_text(separator=" ", strip=True)))


def _decode_html(html: str | bytes) -> str:
    if isinstance(html, bytes):
        return html.decode("utf-8", errors="replace")
    return str(html or "")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def _has_template_placeholder(*values: Any) -> bool:
    text = " ".join(str(value or "") for value in values)
    lowered = text.lower()
    return "{{" in text or "}}" in text or "%7b%7b" in lowered or "%7d%7d" in lowered
