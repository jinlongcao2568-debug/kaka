from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso
from stage4_verification.document_extraction import extract_document_text
from storage.p13b_original_notice_backtrace import (
    _default_http_getter,
    _fingerprint,
    _html_to_text,
    _list,
    _sha256,
    _stable_id,
    _write_json,
)


P13B_TARGETED_PERSON_READBACK_KIND = "p13b_targeted_person_readback_v1_manifest"
P13B_TARGETED_PERSON_READBACK_VERSION = 1
P13B_TARGETED_PERSON_READBACK_ADAPTER_ID = "p13b-targeted-person-readback-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-targeted-person-readback-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
ATTACHMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".zip", ".rar", ".xls", ".xlsx")
ATTACHMENT_HINT_PATTERN = re.compile(r"(附件|下载|pdf|doc|中标通知书|中标结果|候选人|公示|文件)", re.IGNORECASE)

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
BinaryGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
DocumentExtractor = Callable[..., Mapping[str, Any]]


def build_p13b_targeted_person_readback(
    *,
    continuation_json: str | Path | None = None,
    continuation_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    enable_live_public_query: bool = False,
    download_target_attachments: bool = False,
    max_live_readbacks: int | None = None,
    max_attachments_per_task: int = 3,
    enable_ocr: bool = False,
    max_pages: int = 20,
    created_at: str | None = None,
    http_getter: HttpGetter | None = None,
    binary_getter: BinaryGetter | None = None,
    document_extractor: DocumentExtractor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    blocking_reasons: list[str] = []
    source_path = _source_path(continuation_json=continuation_json, continuation_root=continuation_root)
    source_payload = _load_json(source_path)
    if not source_payload:
        blocking_reasons.append("p13b_original_backtrace_continuation_missing")
    source_manifest = _source_manifest(source_payload)
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    task_records = [
        _task_from_continuation_record(record, created_at=created)
        for record in _list(source_manifest.get("continuation_plan_records"))
        if isinstance(record, Mapping)
        and str(record.get("continuation_state") or "") == "TARGETED_PERSON_READBACK_REQUIRED"
        and (not selected_projects or _project_key(record.get("project_id")) in selected_projects)
    ]
    readback_records = _execute_tasks(
        task_records,
        output_root=out_dir,
        enable_live_public_query=enable_live_public_query,
        download_target_attachments=download_target_attachments,
        max_live_readbacks=max_live_readbacks,
        max_attachments_per_task=max_attachments_per_task,
        enable_ocr=enable_ocr,
        max_pages=max_pages,
        http_getter=http_getter or _default_http_getter,
        binary_getter=binary_getter or _default_binary_getter,
        document_extractor=document_extractor or extract_document_text,
        created_at=created,
    )
    summary = _summary(
        task_records,
        readback_records,
        blocking_reasons,
        enable_live_public_query=enable_live_public_query,
        download_target_attachments=download_target_attachments,
    )
    manifest = {
        "manifest_version": P13B_TARGETED_PERSON_READBACK_VERSION,
        "manifest_kind": P13B_TARGETED_PERSON_READBACK_KIND,
        "adapter_id": P13B_TARGETED_PERSON_READBACK_ADAPTER_ID,
        "pipeline_stage": "P13BTargetedPersonReadbackV1",
        "manifest_id": f"P13B-TARGETED-PERSON-{_fingerprint({'records': readback_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_continuation_json": str(source_path),
        "project_ids": list(project_ids),
        "targeted_person_readback_task_records": task_records,
        "targeted_person_readback_records": readback_records,
        "summary": summary,
        "scope_guardrails": {
            "only_targeted_person_readback_required_records": True,
            "does_not_expand_company_history_search": True,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "network_enabled": bool(enable_live_public_query),
            "download_enabled": bool(enable_live_public_query and download_target_attachments),
            "parse_enabled": bool(enable_live_public_query and download_target_attachments),
            "ocr_enabled": bool(enable_ocr),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "p13b_targeted_person_readback_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*blocking_reasons, *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    _write_json(out_dir / "p13b-targeted-person-readback-v1.json", result)
    _write_json(out_dir / "targeted-person-readback-task-records.json", task_records)
    _write_json(out_dir / "targeted-person-readback-records.json", readback_records)
    return result


def _task_from_continuation_record(record: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    return {
        "targeted_person_readback_task_id": _stable_id(
            "P13B-TARGETED-PERSON",
            record.get("original_notice_task_id"),
            record.get("original_notice_url"),
        ),
        "original_notice_task_id": str(record.get("original_notice_task_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "candidate_company_name": str(record.get("candidate_company_name") or ""),
        "responsible_person_names": _list(record.get("responsible_person_names")),
        "bid_project_name": str(record.get("bid_project_name") or ""),
        "historical_project_area_code": str(record.get("historical_project_area_code") or ""),
        "bid_area_code": str(record.get("bid_area_code") or ""),
        "original_notice_url": str(record.get("original_notice_url") or ""),
        "bid_show_url": str(record.get("bid_show_url") or ""),
        "extracted_period_text": str(record.get("extracted_period_text") or ""),
        "candidate_company_matched": bool(record.get("candidate_company_matched")),
        "performance_period_present": bool(record.get("performance_period_present")),
        "source_continuation_state": str(record.get("continuation_state") or ""),
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "targeted_person_readback_state": "PLAN_ONLY_NOT_EXECUTED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _execute_tasks(
    tasks: list[dict[str, Any]],
    *,
    output_root: Path,
    enable_live_public_query: bool,
    download_target_attachments: bool,
    max_live_readbacks: int | None,
    max_attachments_per_task: int,
    enable_ocr: bool,
    max_pages: int,
    http_getter: HttpGetter,
    binary_getter: BinaryGetter,
    document_extractor: DocumentExtractor,
    created_at: str,
) -> list[dict[str, Any]]:
    if not enable_live_public_query:
        return []
    records: list[dict[str, Any]] = []
    attempted = 0
    for task in tasks:
        if max_live_readbacks is not None and attempted >= max_live_readbacks:
            records.append(
                {
                    **task,
                    "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                    "targeted_person_readback_state": "TARGETED_PERSON_READBACK_DEFERRED_BY_LIMIT",
                    "blocker_taxonomy": ["max_live_readbacks_deferred"],
                    "created_at": created_at,
                }
            )
            continue
        attempted += 1
        records.append(
            _readback_one(
                task,
                output_root=output_root,
                download_target_attachments=download_target_attachments,
                max_attachments_per_task=max_attachments_per_task,
                enable_ocr=enable_ocr,
                max_pages=max_pages,
                http_getter=http_getter,
                binary_getter=binary_getter,
                document_extractor=document_extractor,
                created_at=created_at,
            )
        )
    return records


def _readback_one(
    task: Mapping[str, Any],
    *,
    output_root: Path,
    download_target_attachments: bool,
    max_attachments_per_task: int,
    enable_ocr: bool,
    max_pages: int,
    http_getter: HttpGetter,
    binary_getter: BinaryGetter,
    document_extractor: DocumentExtractor,
    created_at: str,
) -> dict[str, Any]:
    original_url = str(task.get("original_notice_url") or "")
    response = dict(http_getter(original_url, {"route": "p13b_targeted_person_page", "task": dict(task)}))
    status = int(response.get("status_code") or response.get("status") or 0)
    content_type = str(response.get("content_type") or "")
    body = str(response.get("body") or response.get("text") or response.get("content") or "")
    source_url = str(response.get("url") or original_url)
    text = _html_to_text(body) if _looks_like_html(body, content_type) else body
    page_hits = _person_hits(text, _list(task.get("responsible_person_names")))
    attachment_candidates = _discover_attachment_links(body, base_url=source_url)[: max(0, max_attachments_per_task)]
    base = {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "source_url": source_url,
        "status_code": status,
        "content_type": content_type,
        "page_text_probe": text[:1000],
        "page_text_probe_sha256": _sha256(text[:1000]) if text else "",
        "page_target_person_hits": page_hits,
        "attachment_candidate_records": attachment_candidates,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    if status < 200 or status >= 400 or not text.strip():
        return {
            **base,
            "targeted_person_readback_state": "TARGETED_PERSON_PAGE_FETCH_BLOCKED",
            "blocker_taxonomy": ["targeted_person_page_fetch_blocked_or_empty"],
            "attachment_readback_records": [],
            "same_person_company_period_signal_ready": False,
            "review_reasons": ["targeted_person_page_fetch_blocked_or_empty"],
        }
    if page_hits:
        return {
            **base,
            "targeted_person_readback_state": "TARGETED_PERSON_FOUND_ON_DETAIL_PAGE",
            "blocker_taxonomy": [],
            "attachment_readback_records": [],
            "same_person_company_period_signal_ready": _signal_ready(task, page_hits),
            "review_reasons": ["target_responsible_person_found_on_detail_page"],
        }
    if not attachment_candidates:
        return {
            **base,
            "targeted_person_readback_state": "TARGETED_PERSON_NOT_FOUND_NO_ATTACHMENT_LINKS",
            "blocker_taxonomy": ["targeted_person_not_found_no_attachment_links"],
            "attachment_readback_records": [],
            "same_person_company_period_signal_ready": False,
            "review_reasons": ["targeted_person_not_found_no_attachment_links"],
        }
    if not download_target_attachments:
        return {
            **base,
            "targeted_person_readback_state": "TARGETED_PERSON_ATTACHMENT_DOWNLOAD_DEFERRED",
            "blocker_taxonomy": ["targeted_attachment_download_deferred"],
            "attachment_readback_records": [],
            "same_person_company_period_signal_ready": False,
            "review_reasons": ["targeted_attachment_download_deferred"],
        }
    attachment_records = [
        _readback_attachment(
            task,
            attachment,
            output_root=output_root,
            binary_getter=binary_getter,
            document_extractor=document_extractor,
            enable_ocr=enable_ocr,
            max_pages=max_pages,
            created_at=created_at,
        )
        for attachment in attachment_candidates
    ]
    attachment_hits = [
        hit
        for record in attachment_records
        for hit in _list(record.get("attachment_target_person_hits"))
    ]
    if attachment_hits:
        state = "TARGETED_PERSON_FOUND_IN_ATTACHMENT"
        blockers: list[str] = []
        reasons = ["target_responsible_person_found_in_attachment"]
    else:
        state = "TARGETED_PERSON_NOT_FOUND_IN_TARGETED_READBACK"
        blockers = ["targeted_person_not_found_in_page_or_attachments"]
        reasons = ["targeted_person_not_found_in_page_or_attachments"]
    return {
        **base,
        "targeted_person_readback_state": state,
        "blocker_taxonomy": blockers,
        "attachment_readback_records": attachment_records,
        "same_person_company_period_signal_ready": _signal_ready(task, attachment_hits),
        "review_reasons": reasons,
    }


def _readback_attachment(
    task: Mapping[str, Any],
    attachment: Mapping[str, Any],
    *,
    output_root: Path,
    binary_getter: BinaryGetter,
    document_extractor: DocumentExtractor,
    enable_ocr: bool,
    max_pages: int,
    created_at: str,
) -> dict[str, Any]:
    url = str(attachment.get("attachment_url") or "")
    response = dict(binary_getter(url, {"route": "p13b_targeted_person_attachment", "task": dict(task)}))
    status = int(response.get("status_code") or response.get("status") or 0)
    content_type = str(response.get("content_type") or "")
    data = _response_bytes(response)
    attachment_id = _stable_id("P13B-TARGETED-ATTACH", task.get("targeted_person_readback_task_id"), url)
    base = {
        **dict(attachment),
        "attachment_readback_id": attachment_id,
        "status_code": status,
        "content_type": content_type,
        "payload_sha256": hashlib.sha256(data).hexdigest() if data else "",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if status < 200 or status >= 400 or not data:
        return {
            **base,
            "attachment_fetch_state": "ATTACHMENT_FETCH_BLOCKED_OR_EMPTY",
            "attachment_parse_state": "NOT_PARSED",
            "attachment_target_person_hits": [],
            "failure_reasons": ["attachment_fetch_blocked_or_empty"],
        }
    work_path = _write_attachment_work_file(output_root, attachment_id=attachment_id, url=url, data=data)
    if work_path.suffix.lower() != ".pdf":
        text = _decode_bytes(data, content_type)
        return {
            **base,
            "attachment_fetch_state": "ATTACHMENT_FETCHED",
            "attachment_parse_state": "NON_PDF_TEXT_SCAN_ONLY",
            "attachment_work_path": str(work_path),
            "attachment_target_person_hits": _person_hits(text, _list(task.get("responsible_person_names"))),
            "attachment_text_probe": text[:1000],
            "failure_reasons": [] if text.strip() else ["non_pdf_attachment_text_empty"],
        }
    extraction = dict(
        document_extractor(
            work_path,
            enable_ocr=enable_ocr,
            max_pages=max_pages,
            opportunity_priority_class="A_HIGH_CONSTRUCTION_EPC",
        )
    )
    text = str(extraction.get("text") or "")
    extraction_path = output_root / "extractions" / f"{attachment_id}.json"
    _write_json(extraction_path, extraction)
    return {
        **base,
        "attachment_fetch_state": "ATTACHMENT_FETCHED",
        "attachment_parse_state": "PDF_TEXT_PARSED" if text.strip() else "PDF_TEXT_EMPTY_OR_OCR_REQUIRED",
        "attachment_work_path": str(work_path),
        "attachment_extraction_json_path": str(extraction_path),
        "attachment_extraction_methods": _list(extraction.get("extraction_methods")),
        "attachment_failure_reasons": _list(extraction.get("failure_reasons")),
        "attachment_target_person_hits": _person_hits(text, _list(task.get("responsible_person_names"))),
        "attachment_text_probe": text[:1000],
    }


def _discover_attachment_links(body: str, *, base_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    anchor_pattern = re.compile(
        r"<a\b[^>]*href\s*=\s*['\"](?P<href>[^'\"]+)['\"][^>]*>(?P<label>.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in anchor_pattern.finditer(body):
        href = html.unescape(match.group("href")).strip()
        label = _html_to_text(html.unescape(match.group("label"))).strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        url = urllib.parse.urljoin(base_url, href)
        if not _looks_like_target_attachment(url, label):
            continue
        if url in seen:
            continue
        seen.add(url)
        records.append(
            {
                "attachment_url": url,
                "attachment_label": label[:200],
                "attachment_match_reason": _attachment_match_reason(url, label),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _looks_like_target_attachment(url: str, label: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    suffix_match = any(path.endswith(suffix) for suffix in ATTACHMENT_SUFFIXES)
    hint_match = bool(ATTACHMENT_HINT_PATTERN.search(label or url))
    return suffix_match or (hint_match and "download" in url.lower())


def _attachment_match_reason(url: str, label: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    if any(path.endswith(suffix) for suffix in ATTACHMENT_SUFFIXES):
        return "attachment_suffix_match"
    if ATTACHMENT_HINT_PATTERN.search(label or url):
        return "attachment_label_or_url_hint_match"
    return "attachment_candidate"


def _person_hits(text: str, names: Iterable[Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for name_value in names:
        name = str(name_value or "").strip()
        if not name or name not in text:
            continue
        index = text.find(name)
        hits.append(
            {
                "person_name": name,
                "source_text": text[max(0, index - 80) : index + len(name) + 80],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return hits


def _signal_ready(task: Mapping[str, Any], hits: list[Any]) -> bool:
    return bool(hits) and bool(task.get("candidate_company_matched")) and bool(task.get("performance_period_present"))


def _summary(
    tasks: list[Mapping[str, Any]],
    records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    *,
    enable_live_public_query: bool,
    download_target_attachments: bool,
) -> dict[str, Any]:
    attachment_records = [
        attachment
        for record in records
        for attachment in _list(record.get("attachment_readback_records"))
        if isinstance(attachment, Mapping)
    ]
    return {
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED",
        "targeted_person_task_count": len(tasks),
        "targeted_person_readback_count": len(records),
        "download_target_attachments": bool(download_target_attachments),
        "detail_page_fetched_count": sum(1 for record in records if int(record.get("status_code") or 0) == 200),
        "attachment_candidate_count": sum(len(_list(record.get("attachment_candidate_records"))) for record in records),
        "attachment_readback_count": len(attachment_records),
        "attachment_fetched_count": sum(1 for record in attachment_records if str(record.get("attachment_fetch_state") or "") == "ATTACHMENT_FETCHED"),
        "target_person_found_count": sum(
            1
            for record in records
            if _list(record.get("page_target_person_hits"))
            or any(_list(attachment.get("attachment_target_person_hits")) for attachment in _list(record.get("attachment_readback_records")))
        ),
        "same_person_company_period_signal_ready_count": sum(
            1 for record in records if bool(record.get("same_person_company_period_signal_ready"))
        ),
        "targeted_person_readback_state_counts": _counts(record.get("targeted_person_readback_state") for record in records),
        "blocker_taxonomy_counts": _counts(
            blocker
            for record in records
            for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _default_binary_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaP13B/1.0",
            "Accept": "application/pdf,application/octet-stream,text/html,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return {
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": response.headers.get("Content-Type", ""),
                "body": response.read(),
                "url": response.geturl(),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        return {
            "status_code": int(exc.code),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "body": body,
            "url": url,
            "error": str(exc),
        }
    except urllib.error.URLError as exc:
        return {"status_code": 0, "content_type": "", "body": b"", "url": url, "error": str(exc.reason)}
    except (UnicodeEncodeError, ValueError, OSError) as exc:
        return {"status_code": 0, "content_type": "", "body": b"", "url": url, "error": f"{type(exc).__name__}:{exc}"}


def _write_attachment_work_file(output_root: Path, *, attachment_id: str, url: str, data: bytes) -> Path:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix not in ATTACHMENT_SUFFIXES:
        suffix = ".pdf" if data[:5] == b"%PDF-" else ".bin"
    work_dir = output_root / "attachments"
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / f"{_safe_filename(attachment_id)}{suffix}"
    path.write_bytes(data)
    return path


def _response_bytes(response: Mapping[str, Any]) -> bytes:
    body = response.get("body")
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    content = response.get("content")
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return b""


def _decode_bytes(data: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    charsets = [charset_match.group(1)] if charset_match else []
    charsets.extend(["utf-8", "gb18030"])
    for charset in charsets:
        try:
            return data.decode(charset, errors="replace")
        except LookupError:
            continue
    return data.decode("utf-8", errors="replace")


def _looks_like_html(body: str, content_type: str) -> bool:
    return "html" in content_type.lower() or "<html" in body.lower() or "<a " in body.lower()


def _source_path(*, continuation_json: str | Path | None, continuation_root: str | Path | None) -> Path:
    if continuation_json:
        return Path(continuation_json)
    if continuation_root:
        return Path(continuation_root) / "p13b-original-backtrace-continuation-controller-v2.json"
    return DEFAULT_OUTPUT_ROOT / "p13b-original-backtrace-continuation-controller-v2.json"


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _project_key(value: Any) -> str:
    return str(value or "").strip()


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")[:120] or "attachment"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B targeted responsible-person readback manifest.")
    parser.add_argument("--continuation-json", default="")
    parser.add_argument("--continuation-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--download-target-attachments", action="store_true")
    parser.add_argument("--max-live-readbacks", type=int, default=0)
    parser.add_argument("--max-attachments-per-task", type=int, default=3)
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_targeted_person_readback(
        continuation_json=args.continuation_json or None,
        continuation_root=args.continuation_root or None,
        output_root=args.output_root,
        project_ids=[item.strip() for item in str(args.project_ids or "").split(",") if item.strip()],
        enable_live_public_query=bool(args.enable_live_public_query),
        download_target_attachments=bool(args.download_target_attachments),
        max_live_readbacks=args.max_live_readbacks if args.max_live_readbacks > 0 else None,
        max_attachments_per_task=max(0, int(args.max_attachments_per_task or 0)),
        enable_ocr=bool(args.enable_ocr),
        max_pages=max(1, int(args.max_pages or 1)),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
