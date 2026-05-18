from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso
from storage.p13b_original_notice_backtrace import (
    _extract_award_date,
    _extract_company_names,
    _extract_period_text,
    _extract_responsible_people,
    _fingerprint,
    _html_to_text,
    _list,
    _looks_like_browser_readback_required,
    _sha256,
)


P13B_BROWSER_ORIGINAL_READBACK_KIND = "p13b_browser_original_readback_v1_manifest"
P13B_BROWSER_ORIGINAL_READBACK_VERSION = 1
P13B_BROWSER_ORIGINAL_READBACK_ADAPTER_ID = "p13b-browser-original-readback-v1-builder"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-original-notice-backtrace-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-browser-original-readback-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

BrowserReadbackGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_p13b_browser_original_readback(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    input_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_public_query: bool = False,
    max_live_browser_readbacks: int | None = None,
    browser_readback_getter: BrowserReadbackGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_dir = Path(input_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(input_json) if input_json else in_dir / "original-notice-backtrace-v1.json"
    blocking_reasons: list[str] = []
    source_payload = _load_json(source_path, blocking_reasons, "p13b_original_notice_backtrace_missing")
    source_manifest = _source_manifest(source_payload)
    execution_mode = "LIVE_PUBLIC_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED"
    task_records = _task_records_from_original_backtrace(source_manifest, created_at=created)
    readback_records = _execute_browser_readback_tasks(
        task_records,
        created_at=created,
        enable_live_public_query=enable_live_public_query,
        max_live_browser_readbacks=max_live_browser_readbacks,
        browser_readback_getter=browser_readback_getter,
    )
    summary = _summary(
        task_records=task_records,
        readback_records=readback_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": P13B_BROWSER_ORIGINAL_READBACK_VERSION,
        "manifest_kind": P13B_BROWSER_ORIGINAL_READBACK_KIND,
        "adapter_id": P13B_BROWSER_ORIGINAL_READBACK_ADAPTER_ID,
        "pipeline_stage": "P13BBrowserOriginalReadbackV1",
        "manifest_id": f"P13B-BROWSER-ORIGINAL-READBACK-{_fingerprint({'summary': summary, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_input_root": str(in_dir),
        "source_input_json": str(source_path),
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "max_live_browser_readbacks": max_live_browser_readbacks,
        "browser_original_readback_task_records": task_records,
        "browser_original_readback_records": readback_records,
        "summary": summary,
        "safety": {
            "network_enabled": bool(enable_live_public_query),
            "browser_execution_enabled": bool(enable_live_public_query),
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "only_browser_blocked_original_notice_urls": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "p13b_browser_original_readback_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *blocking_reasons,
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
        text = json.dumps(result, ensure_ascii=False, indent=2)
    _write_json(out_dir / "browser-original-readback-v1.json", result)
    _write_json(out_dir / "browser-original-readback-task-records.json", task_records)
    _write_json(out_dir / "browser-original-readback-records.json", readback_records)
    return result


def _task_records_from_original_backtrace(source_manifest: Mapping[str, Any], *, created_at: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in _list(source_manifest.get("original_notice_extraction_records")):
        if not isinstance(record, Mapping):
            continue
        blockers = {str(item) for item in _list(record.get("blocker_taxonomy"))}
        if "original_notice_browser_readback_required" not in blockers:
            continue
        original_url = str(record.get("original_notice_url") or record.get("source_url") or "").strip()
        if not original_url:
            continue
        key = f"{record.get('original_notice_task_id') or ''}|{original_url}"
        if key in seen:
            continue
        seen.add(key)
        tasks.append(_browser_task_from_original_task(record, original_url=original_url, created_at=created_at))
    return tasks


def _browser_task_from_original_task(task: Mapping[str, Any], *, original_url: str, created_at: str) -> dict[str, Any]:
    return {
        "browser_original_readback_task_id": _stable_id("P13B-BROWSER-ORIGINAL", task.get("original_notice_task_id"), original_url),
        "original_notice_task_id": str(task.get("original_notice_task_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "candidate_company_name": str(task.get("candidate_company_name") or ""),
        "responsible_person_names": _list(task.get("responsible_person_names")),
        "bid_project_name": str(task.get("bid_project_name") or ""),
        "original_notice_url": original_url,
        "source_blocker_taxonomy": _list(task.get("blocker_taxonomy")),
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "browser_readback_state": "PLAN_ONLY_NOT_EXECUTED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _execute_browser_readback_tasks(
    tasks: list[dict[str, Any]],
    *,
    created_at: str,
    enable_live_public_query: bool,
    max_live_browser_readbacks: int | None,
    browser_readback_getter: BrowserReadbackGetter | None,
) -> list[dict[str, Any]]:
    if not enable_live_public_query:
        return []
    getter = browser_readback_getter or _playwright_browser_readback
    records: list[dict[str, Any]] = []
    attempted = 0
    for task in tasks:
        if max_live_browser_readbacks is not None and attempted >= max_live_browser_readbacks:
            records.append(
                {
                    **task,
                    "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                    "browser_readback_state": "BROWSER_ORIGINAL_READBACK_BLOCKED",
                    "blocker_taxonomy": ["max_live_browser_readbacks_deferred"],
                    "route_attempt": {},
                    "created_at": created_at,
                }
            )
            continue
        attempted += 1
        records.append(_readback_one_browser_original(task, getter=getter, created_at=created_at))
    return records


def _readback_one_browser_original(
    task: Mapping[str, Any],
    *,
    getter: BrowserReadbackGetter,
    created_at: str,
) -> dict[str, Any]:
    original_url = str(task.get("original_notice_url") or "")
    try:
        response = dict(getter(original_url, {"route": "browser_original_readback", "task": dict(task)}))
    except Exception as exc:  # pragma: no cover - defensive around optional browser stacks
        response = {"status_code": 0, "content_type": "", "body": "", "url": original_url, "error": f"{type(exc).__name__}:{exc}"}
    status_code = int(response.get("status_code") or response.get("status") or 0)
    body = _response_body(response)
    content_type = str(response.get("content_type") or "")
    source_url = str(response.get("url") or original_url)
    error = str(response.get("error") or "")
    text = _payload_to_text(body, content_type)
    route_attempt = {
        "route": "browser_original_readback",
        "url": source_url,
        "status_code": status_code,
        "content_type": content_type,
        "body_sha256": _sha256(body) if body else "",
        "error": error,
    }
    blockers = _browser_blockers(status_code=status_code, text=text, source_url=source_url, error=error)
    if blockers:
        return {
            **dict(task),
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "browser_readback_state": "BROWSER_ORIGINAL_READBACK_BLOCKED",
            "source_url": source_url,
            "status_code": status_code,
            "content_type": content_type,
            "route_attempt": route_attempt,
            "blocker_taxonomy": blockers,
            "text_probe": text[:800],
            "text_probe_sha256": _sha256(text[:800]) if text else "",
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    extraction = _extract_notice_fields(text)
    return {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "browser_readback_state": "BROWSER_ORIGINAL_READBACK_READY",
        "source_url": source_url,
        "status_code": status_code,
        "content_type": content_type,
        "readback_payload_sha256": _sha256(body) if body else "",
        "text_probe": text[:800],
        "text_probe_sha256": _sha256(text[:800]) if text else "",
        "extracted_responsible_person_names": _list(extraction.get("extracted_responsible_person_names")),
        "extracted_company_names": _list(extraction.get("extracted_company_names")),
        "extracted_period_text": str(extraction.get("extracted_period_text") or ""),
        "extracted_award_date": str(extraction.get("extracted_award_date") or ""),
        "field_signal_count": int(extraction.get("field_signal_count") or 0),
        "record_payload_sha256": _fingerprint(
            {
                "source_url": source_url,
                "people": extraction.get("extracted_responsible_person_names"),
                "companies": extraction.get("extracted_company_names"),
                "period": extraction.get("extracted_period_text"),
                "award_date": extraction.get("extracted_award_date"),
            }
        ),
        "route_attempt": route_attempt,
        "blocker_taxonomy": [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _browser_blockers(*, status_code: int, text: str, source_url: str, error: str) -> list[str]:
    blockers: list[str] = []
    if error:
        blockers.append("browser_original_readback_transport_error_retry_required")
    if status_code and status_code >= 400:
        blockers.append("browser_original_readback_http_error_retry_required")
    if not text.strip():
        blockers.append("browser_original_readback_empty_payload_retry_required")
    if _looks_like_browser_readback_required(text, source_url):
        blockers.append("browser_original_readback_still_js_shell")
    return _dedupe(blockers)


def _extract_notice_fields(text: str) -> dict[str, Any]:
    people = _extract_responsible_people(text)
    period = _extract_period_text(text)
    award_date = _extract_award_date(text)
    companies = _extract_company_names(text)
    return {
        "extracted_responsible_person_names": people,
        "extracted_company_names": companies,
        "extracted_period_text": period,
        "extracted_award_date": award_date,
        "field_signal_count": len(people) + len(companies) + int(bool(period)) + int(bool(award_date)),
    }


def _playwright_browser_readback(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional local browser stack
        return {"status_code": 0, "content_type": "", "body": "", "url": url, "error": f"playwright_unavailable:{exc}"}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page_context = browser.new_context(ignore_https_errors=True, locale="zh-CN", timezone_id="Asia/Shanghai")
            page = page_context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            body_text = ""
            try:
                body_text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                pass
            if not body_text:
                body_text = _html_to_text(page.content())
            status_code = int(getattr(response, "status", 200) or 200) if response else 200
            final_url = page.url or url
            page_context.close()
            browser.close()
            return {
                "status_code": status_code,
                "content_type": "text/plain; charset=utf-8",
                "body": body_text,
                "url": final_url,
            }
    except Exception as exc:  # pragma: no cover - depends on live browser behavior
        return {"status_code": 0, "content_type": "", "body": "", "url": url, "error": f"playwright_route_failed:{exc}"}


def _response_body(response: Mapping[str, Any]) -> str:
    for key in ("body", "content", "text"):
        value = response.get(key)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        if value is not None:
            return str(value)
    return ""


def _payload_to_text(body: str, content_type: str) -> str:
    text = str(body or "")
    lowered = str(content_type or "").lower()
    if "<" in text[:500] or "html" in lowered:
        return _html_to_text(text)
    return text.strip()


def _summary(
    *,
    task_records: list[Mapping[str, Any]],
    readback_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    ready_records = [
        record
        for record in readback_records
        if str(record.get("browser_readback_state") or "") == "BROWSER_ORIGINAL_READBACK_READY"
    ]
    person_period_count = sum(
        1
        for record in ready_records
        if _list(record.get("extracted_responsible_person_names")) and str(record.get("extracted_period_text") or "").strip()
    )
    return {
        "execution_mode": execution_mode,
        "browser_original_readback_task_count": len(task_records),
        "browser_original_readback_count": len(readback_records),
        "browser_original_readback_ready_count": len(ready_records),
        "browser_original_readback_blocked_count": sum(
            1
            for record in readback_records
            if str(record.get("browser_readback_state") or "") == "BROWSER_ORIGINAL_READBACK_BLOCKED"
        ),
        "browser_original_person_period_extracted_count": person_period_count,
        "browser_readback_state_counts": _counts(record.get("browser_readback_state") for record in readback_records),
        "blocker_taxonomy_counts": _counts(
            blocker
            for record in readback_records
            for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{hashlib.sha256('|'.join(str(part or '') for part in parts).encode('utf-8')).hexdigest()[:12]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B browser original notice readback manifest.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--input-json", default=None)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--max-live-browser-readbacks", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_browser_original_readback(
        input_root=args.input_root,
        input_json=args.input_json,
        output_root=args.output_root,
        enable_live_public_query=args.enable_live_public_query,
        max_live_browser_readbacks=args.max_live_browser_readbacks,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
