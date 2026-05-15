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


P13B_YGP_ORIGINAL_READBACK_KIND = "p13b_ygp_original_readback_v1_manifest"
P13B_YGP_ORIGINAL_READBACK_VERSION = 1
P13B_YGP_ORIGINAL_READBACK_ADAPTER_ID = "p13b-ygp-original-readback-v1-builder"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-original-notice-backtrace-v1-smoke")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-ygp-original-readback-v1")

YGP_HOST = "ygp.gdzwfw.gov.cn"
FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
BrowserReadbackGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_p13b_ygp_original_readback(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    input_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_public_query: bool = False,
    max_live_original_notices: int | None = None,
    http_getter: HttpGetter | None = None,
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
    readback_records = _execute_ygp_readback_tasks(
        task_records,
        created_at=created,
        enable_live_public_query=enable_live_public_query,
        max_live_original_notices=max_live_original_notices,
        http_getter=http_getter,
        browser_readback_getter=browser_readback_getter,
    )
    summary = _summary(
        task_records=task_records,
        readback_records=readback_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": P13B_YGP_ORIGINAL_READBACK_VERSION,
        "manifest_kind": P13B_YGP_ORIGINAL_READBACK_KIND,
        "adapter_id": P13B_YGP_ORIGINAL_READBACK_ADAPTER_ID,
        "pipeline_stage": "P13BYgpOriginalReadbackV1",
        "manifest_id": f"P13B-YGP-ORIGINAL-READBACK-{_fingerprint({'summary': summary, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_input_root": str(in_dir),
        "source_input_json": str(source_path),
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "max_live_original_notices": max_live_original_notices,
        "ygp_original_readback_task_records": task_records,
        "ygp_original_readback_records": readback_records,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "network_enabled": bool(enable_live_public_query),
            "manifest_stores_raw_html_or_blob": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "not_guangzhou_primary_source": True,
            "p13b_original_readback_allowed": True,
            "guangdong_city_adapter_base_capability": True,
            "active_sample_calibration_disabled_until_city_validated": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "p13b_ygp_original_readback_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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
    (out_dir / "ygp-original-readback-v1.json").write_text(text, encoding="utf-8")
    return result


def _task_records_from_original_backtrace(source_manifest: Mapping[str, Any], *, created_at: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in _list(source_manifest.get("original_notice_task_records")):
        if not isinstance(task, Mapping):
            continue
        original_url = str(task.get("original_notice_url") or "").strip()
        if not original_url or YGP_HOST not in original_url.lower():
            continue
        key = f"{task.get('original_notice_task_id') or ''}|{original_url}"
        if key in seen:
            continue
        seen.add(key)
        tasks.append(_ygp_task_from_original_task(task, original_url=original_url, created_at=created_at))
    if tasks:
        return tasks
    for record in _list(source_manifest.get("original_notice_extraction_records")):
        if not isinstance(record, Mapping):
            continue
        original_url = str(record.get("original_notice_url") or record.get("source_url") or "").strip()
        state = str(record.get("original_notice_extraction_state") or "")
        if YGP_HOST not in original_url.lower() or state != "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED":
            continue
        key = f"{record.get('original_notice_task_id') or ''}|{original_url}"
        if key in seen:
            continue
        seen.add(key)
        tasks.append(_ygp_task_from_original_task(record, original_url=original_url, created_at=created_at))
    return tasks


def _ygp_task_from_original_task(task: Mapping[str, Any], *, original_url: str, created_at: str) -> dict[str, Any]:
    return {
        "ygp_original_readback_task_id": _stable_id("P13B-YGP-ORIGINAL", task.get("original_notice_task_id"), original_url),
        "original_notice_task_id": str(task.get("original_notice_task_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "candidate_company_name": str(task.get("candidate_company_name") or ""),
        "responsible_person_names": _list(task.get("responsible_person_names")),
        "bid_project_name": str(task.get("bid_project_name") or ""),
        "original_notice_url": original_url,
        "ygp_url_mapping_parts": _url_mapping_parts(original_url),
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "ygp_readback_state": "PLAN_ONLY_NOT_EXECUTED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _execute_ygp_readback_tasks(
    tasks: list[dict[str, Any]],
    *,
    created_at: str,
    enable_live_public_query: bool,
    max_live_original_notices: int | None,
    http_getter: HttpGetter | None,
    browser_readback_getter: BrowserReadbackGetter | None,
) -> list[dict[str, Any]]:
    if not enable_live_public_query:
        return []
    getter = http_getter or _default_http_getter
    browser_getter = browser_readback_getter or _playwright_network_readback
    records: list[dict[str, Any]] = []
    attempted = 0
    for task in tasks:
        if max_live_original_notices is not None and attempted >= max_live_original_notices:
            records.append(
                {
                    **task,
                    "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                    "ygp_readback_state": "YGP_ORIGINAL_URL_BLOCKED",
                    "blocker_taxonomy": ["max_live_original_notices_deferred"],
                    "route_attempts": [],
                    "created_at": created_at,
                }
            )
            continue
        attempted += 1
        records.append(_readback_one_ygp_original(task, getter=getter, browser_getter=browser_getter, created_at=created_at))
    return records


def _readback_one_ygp_original(
    task: Mapping[str, Any],
    *,
    getter: HttpGetter,
    browser_getter: BrowserReadbackGetter,
    created_at: str,
) -> dict[str, Any]:
    original_url = str(task.get("original_notice_url") or "")
    route_attempts: list[dict[str, Any]] = []
    first = _fetch_url(original_url, getter, route="ygp_url_mapping_fetch", task=task)
    route_attempts.append(first["attempt"])
    blockers = _blockers_from_response(
        status=first["status_code"],
        body_probe=first["body"][:300],
        error=first["error"],
        prefix="ygp_original",
    )
    if blockers:
        return _blocked_record(task, route_attempts=route_attempts, blockers=blockers, created_at=created_at)
    first_text = _payload_to_text(first["body"], first["content_type"])
    first_extraction = _extract_notice_fields(first_text)
    if first_extraction["field_signal_count"] > 0 and not _is_spa_shell(first["body"], first_text):
        return _ready_record(
            task,
            source_url=first["url"],
            status_code=first["status_code"],
            content_type=first["content_type"],
            payload=first["body"],
            text=first_text,
            extraction=first_extraction,
            route_attempts=route_attempts,
            readback_state="YGP_ORIGINAL_URL_READBACK_READY",
            api_discovery_state="YGP_DIRECT_ORIGINAL_READBACK_READY",
            created_at=created_at,
        )

    api_discovery_state = "YGP_SPA_SHELL_FETCHED" if _is_spa_shell(first["body"], first_text) else "YGP_DETAIL_API_NOT_DISCOVERED"
    api_candidates = _discover_api_candidates(first["body"], first["url"], getter=getter, task=task, route_attempts=route_attempts)
    if api_candidates:
        api_discovery_state = "YGP_DETAIL_API_DISCOVERED"
    for api_url in api_candidates:
        response = _fetch_url(api_url, getter, route="ygp_detail_api_candidate_fetch", task=task)
        route_attempts.append(response["attempt"])
        blockers = _blockers_from_response(
            status=response["status_code"],
            body_probe=response["body"][:300],
            error=response["error"],
            prefix="ygp_detail_api",
        )
        if blockers:
            continue
        text = _payload_to_text(response["body"], response["content_type"])
        extraction = _extract_notice_fields(text)
        if extraction["field_signal_count"] > 0:
            return _ready_record(
                task,
                source_url=response["url"],
                status_code=response["status_code"],
                content_type=response["content_type"],
                payload=response["body"],
                text=text,
                extraction=extraction,
                route_attempts=route_attempts,
                readback_state="YGP_ORIGINAL_URL_READBACK_READY",
                api_discovery_state=api_discovery_state,
                created_at=created_at,
            )

    browser = dict(browser_getter(original_url, {"route": "ygp_browser_network_readback", "task": dict(task)}))
    browser_attempt = _attempt_from_response(browser, route="ygp_browser_network_readback", fallback_url=original_url)
    route_attempts.append(browser_attempt)
    browser_blockers = _blockers_from_response(
        status=browser_attempt["status_code"],
        body_probe=str(browser.get("body") or browser.get("text") or "")[:300],
        error=str(browser.get("error") or ""),
        prefix="ygp_browser",
    )
    body = str(browser.get("body") or browser.get("content") or browser.get("text") or "")
    if body and not browser_blockers:
        text = _payload_to_text(body, str(browser.get("content_type") or ""))
        extraction = _extract_notice_fields(text)
        if extraction["field_signal_count"] > 0:
            return _ready_record(
                task,
                source_url=str(browser.get("url") or original_url),
                status_code=browser_attempt["status_code"],
                content_type=str(browser.get("content_type") or ""),
                payload=body,
                text=text,
                extraction=extraction,
                route_attempts=route_attempts,
                readback_state="YGP_BROWSER_NETWORK_READBACK_READY",
                api_discovery_state=api_discovery_state,
                created_at=created_at,
            )
    blockers = browser_blockers or ["ygp_original_detail_payload_not_discovered"]
    state = "YGP_ORIGINAL_URL_UNSUPPORTED" if "ygp_original_detail_payload_not_discovered" in blockers else "YGP_ORIGINAL_URL_BLOCKED"
    return {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "ygp_readback_state": state,
        "ygp_api_discovery_state": api_discovery_state,
        "source_url": original_url,
        "route_attempts": route_attempts,
        "blocker_taxonomy": _dedupe(blockers),
        "text_probe": first_text[:600],
        "text_probe_sha256": _sha256(first_text[:600]) if first_text else "",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fetch_url(url: str, getter: HttpGetter, *, route: str, task: Mapping[str, Any]) -> dict[str, Any]:
    response = dict(getter(url, {"route": route, "task": dict(task)}))
    status_code = int(response.get("status_code") or response.get("status") or 0)
    body = str(response.get("body") or response.get("content") or response.get("text") or "")
    content_type = str(response.get("content_type") or "")
    final_url = str(response.get("url") or url)
    error = str(response.get("error") or "")
    return {
        "url": final_url,
        "status_code": status_code,
        "content_type": content_type,
        "body": body,
        "error": error,
        "attempt": {
            "route": route,
            "url": final_url,
            "status_code": status_code,
            "content_type": content_type,
            "body_sha256": _sha256(body) if body else "",
            "error": error,
        },
    }


def _attempt_from_response(response: Mapping[str, Any], *, route: str, fallback_url: str) -> dict[str, Any]:
    body = str(response.get("body") or response.get("content") or response.get("text") or "")
    return {
        "route": route,
        "url": str(response.get("url") or fallback_url),
        "status_code": int(response.get("status_code") or response.get("status") or 0),
        "content_type": str(response.get("content_type") or ""),
        "body_sha256": _sha256(body) if body else "",
        "error": str(response.get("error") or ""),
    }


def _blocked_record(
    task: Mapping[str, Any],
    *,
    route_attempts: list[dict[str, Any]],
    blockers: list[str],
    created_at: str,
) -> dict[str, Any]:
    return {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "ygp_readback_state": "YGP_ORIGINAL_URL_BLOCKED",
        "ygp_api_discovery_state": "YGP_DETAIL_API_NOT_DISCOVERED",
        "source_url": str(task.get("original_notice_url") or ""),
        "route_attempts": route_attempts,
        "blocker_taxonomy": _dedupe(blockers),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _ready_record(
    task: Mapping[str, Any],
    *,
    source_url: str,
    status_code: int,
    content_type: str,
    payload: str,
    text: str,
    extraction: Mapping[str, Any],
    route_attempts: list[dict[str, Any]],
    readback_state: str,
    api_discovery_state: str,
    created_at: str,
) -> dict[str, Any]:
    if extraction.get("extracted_responsible_person_names") and extraction.get("extracted_period_text"):
        extraction_state = "YGP_ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED"
    else:
        extraction_state = "YGP_ORIGINAL_URL_READBACK_READY"
    return {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "ygp_readback_state": readback_state,
        "ygp_api_discovery_state": api_discovery_state,
        "ygp_extraction_state": extraction_state,
        "source_url": source_url,
        "status_code": status_code,
        "content_type": content_type,
        "readback_payload_sha256": _sha256(payload) if payload else "",
        "text_probe": text[:800],
        "text_probe_sha256": _sha256(text[:800]) if text else "",
        "extracted_notice_title": str(extraction.get("extracted_notice_title") or ""),
        "extracted_project_name": str(extraction.get("extracted_project_name") or ""),
        "extracted_responsible_person_names": _list(extraction.get("extracted_responsible_person_names")),
        "extracted_company_names": _list(extraction.get("extracted_company_names")),
        "extracted_period_text": str(extraction.get("extracted_period_text") or ""),
        "extracted_award_date": str(extraction.get("extracted_award_date") or ""),
        "record_payload_sha256": _fingerprint(
            {
                "source_url": source_url,
                "title": extraction.get("extracted_notice_title"),
                "project": extraction.get("extracted_project_name"),
                "people": extraction.get("extracted_responsible_person_names"),
                "companies": extraction.get("extracted_company_names"),
                "period": extraction.get("extracted_period_text"),
                "award_date": extraction.get("extracted_award_date"),
            }
        ),
        "route_attempts": route_attempts,
        "blocker_taxonomy": [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _discover_api_candidates(
    shell_body: str,
    shell_url: str,
    *,
    getter: HttpGetter,
    task: Mapping[str, Any],
    route_attempts: list[dict[str, Any]],
) -> list[str]:
    parts = _url_mapping_parts(str(task.get("original_notice_url") or shell_url))
    assets = _discover_js_assets(shell_body, shell_url)
    candidates: list[str] = []
    for asset_url in assets[:8]:
        response = _fetch_url(asset_url, getter, route="ygp_asset_js_fetch", task=task)
        route_attempts.append(response["attempt"])
        if response["status_code"] != 200 or not response["body"]:
            continue
        candidates.extend(_api_candidates_from_script(response["body"], shell_url, parts))
        chunks = [
            chunk
            for chunk in _discover_js_assets(response["body"], response["url"])
            if any(token in chunk.lower() for token in ("detail", "notice", "jygg", "new"))
        ][:10]
        for chunk in chunks:
            if chunk in assets:
                continue
            chunk_response = _fetch_url(chunk, getter, route="ygp_detail_chunk_fetch", task=task)
            route_attempts.append(chunk_response["attempt"])
            if chunk_response["status_code"] == 200 and chunk_response["body"]:
                candidates.extend(_api_candidates_from_script(chunk_response["body"], shell_url, parts))
    return _dedupe(candidates)


def _discover_js_assets(body: str, base_url: str) -> list[str]:
    assets: list[str] = []
    for match in re.finditer(r"""(?:src|href)\s*=\s*["']([^"']+\.js(?:\?[^"']*)?)["']""", body, flags=re.I):
        assets.append(urllib.parse.urljoin(base_url, match.group(1)))
    for match in re.finditer(r"""["']([^"']*(?:detail|index|chunk)[^"']*\.js(?:\?[^"']*)?)["']""", body, flags=re.I):
        assets.append(urllib.parse.urljoin(base_url, match.group(1)))
    return _dedupe(assets)


def _api_candidates_from_script(script: str, base_url: str, parts: Mapping[str, str]) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"""["']([^"']*/ggzy-portal/center/apis/[^"']+)["']""", script):
        materialized = _materialize_api_candidate(match.group(1), base_url, parts)
        if materialized:
            candidates.append(materialized)
    for match in re.finditer(r"""["'](/?center/apis/[^"']+)["']""", script):
        materialized = _materialize_api_candidate("/ggzy-portal/" + match.group(1).lstrip("/"), base_url, parts)
        if materialized:
            candidates.append(materialized)
    return _dedupe(candidates)


def _materialize_api_candidate(raw: str, base_url: str, parts: Mapping[str, str]) -> str:
    candidate = html.unescape(raw)
    replacements = {
        "{notice_id}": parts.get("notice_id", ""),
        "{id}": parts.get("notice_id", ""),
        "{mapping_id}": parts.get("mapping_id", ""),
        "{notice_type}": parts.get("notice_type", ""),
        "{trading_type}": parts.get("notice_type", ""),
    }
    for token, value in replacements.items():
        candidate = candidate.replace(token, urllib.parse.quote(value))
    if "{" in candidate or "}" in candidate:
        return ""
    return urllib.parse.urljoin(base_url, candidate)


def _playwright_network_readback(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on optional local browser stack
        return {"status_code": 0, "content_type": "", "body": "", "url": url, "error": f"playwright_unavailable:{exc}"}

    captures: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page_context = browser.new_context(ignore_https_errors=True, locale="zh-CN")
            page = page_context.new_page()

            def on_response(response: Any) -> None:
                response_url = str(response.url)
                if "/ggzy-portal/center/apis/" not in response_url:
                    return
                try:
                    content_type = str(response.headers.get("content-type", ""))
                    body = response.text()
                    captures.append(
                        {
                            "status_code": int(response.status),
                            "content_type": content_type,
                            "body": body,
                            "url": response_url,
                        }
                    )
                except Exception:
                    return

            page.on("response", on_response)
            page.goto(url, wait_until="load", timeout=20000)
            page.wait_for_timeout(8000)
            rendered_text = ""
            try:
                rendered_text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                pass
            if not rendered_text:
                try:
                    rendered_text = _html_to_text(page.content())
                except Exception:
                    rendered_text = ""
            if rendered_text:
                captures.append(
                    {
                        "status_code": 200,
                        "content_type": "text/plain",
                        "body": rendered_text,
                        "url": page.url,
                    }
                )
            page_context.close()
            browser.close()
    except Exception as exc:  # pragma: no cover - depends on live browser behavior
        return {"status_code": 0, "content_type": "", "body": "", "url": url, "error": f"playwright_route_failed:{exc}"}
    best = _best_capture(captures)
    if best:
        return best
    return {"status_code": 0, "content_type": "", "body": "", "url": url, "error": "playwright_no_detail_api_capture"}


def _best_capture(captures: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    scored: list[tuple[int, Mapping[str, Any]]] = []
    for capture in captures:
        body = str(capture.get("body") or "")
        text = _payload_to_text(body, str(capture.get("content_type") or ""))
        score = 0
        for token in (
            "项目负责人",
            "项目经理",
            "中标人",
            "中标单位",
            "成交供应商",
            "中标（成交）结果公告",
            "采购项目名称",
            "公告信息",
            "公告内容",
            "相关附件",
            "服务期",
            "工期",
            "中标日期",
            "公告日期",
        ):
            if token in text:
                score += 1
        if score:
            scored.append((score, capture))
    if not scored:
        return None
    return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]


def _default_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaP13B/1.0",
            "Accept": "text/html,application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://ygp.gdzwfw.gov.cn/",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": response.headers.get("Content-Type", ""),
                "body": body,
                "url": url,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "status_code": int(exc.code),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "body": body,
            "url": url,
            "error": str(exc),
        }
    except urllib.error.URLError as exc:
        return {"status_code": 0, "content_type": "", "body": "", "url": url, "error": str(exc.reason)}


def _blockers_from_response(*, status: int, body_probe: str, error: str, prefix: str) -> list[str]:
    blockers: list[str] = []
    if status in {403, 429}:
        blockers.append(f"{prefix}_forbidden_or_rate_limited_review")
    if status in {500, 502, 503, 504}:
        blockers.append(f"{prefix}_temporary_unavailable_retry_required")
    if status == 0 and error:
        blockers.append(f"{prefix}_transport_error_retry_required")
    if "验证码" in body_probe or "captcha" in body_probe.lower():
        blockers.append(f"{prefix}_captcha_or_challenge_review")
    if status == 200 and not body_probe.strip():
        blockers.append(f"{prefix}_empty_body_review")
    return _dedupe(blockers)


def _is_spa_shell(body: str, text: str) -> bool:
    probe = body[:2000].lower()
    if "id=\"app\"" in probe and "/ggzy-portal/assets/" in probe:
        return True
    if "广东省公共资源交易平台" in text and "项目负责人" not in text and "中标人" not in text:
        return True
    return False


def _extract_notice_fields(text: str) -> dict[str, Any]:
    title = _extract_first(text, [r"(?:公告标题|标题)\s*[:：\t ]+\s*([^。；;\n]{4,120})"])
    project = _extract_first(text, [r"(?:采购项目名称|项目名称|工程名称)\s*[:：\t ]+\s*([^。；;\n]{4,120})"])
    people = _extract_responsible_people(text)
    companies = _extract_company_names(text)
    period = _extract_period_text(text)
    award_date = _extract_award_date(text)
    field_signal_count = sum(1 for item in [title, project, period, award_date] if item) + len(people) + len(companies)
    return {
        "extracted_notice_title": title,
        "extracted_project_name": project,
        "extracted_responsible_person_names": people,
        "extracted_company_names": companies,
        "extracted_period_text": period,
        "extracted_award_date": award_date,
        "field_signal_count": field_signal_count,
    }


def _extract_first(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_responsible_people(text: str) -> list[str]:
    patterns = [
        r"(?:项目负责人|项目经理|施工项目负责人|设计负责人|勘察负责人|总监理工程师|工程总承包项目经理)\s*[:：]\s*([\u4e00-\u9fa5·]{2,8})",
        r"(?:负责人姓名|姓名)\s*[:：]\s*([\u4e00-\u9fa5·]{2,8})",
    ]
    people: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            people.append(match.group(1).strip())
    return _dedupe(people)


def _extract_period_text(text: str) -> str:
    patterns = [
        r"(?:工期（交货期）|工期\(交货期\)|工期|服务期|合同履行期限|履行期限|服务期限)\s*[:：]\s*([^。；;\n]{2,100})",
        r"(?:计划工期)\s*[:：]\s*([^。；;\n]{2,100})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_award_date(text: str) -> str:
    patterns = [
        r"(?:中标日期|成交日期|公告日期|发布日期)\s*[:：]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_company_names(text: str) -> list[str]:
    patterns = [
        r"(?:中标人|成交供应商|中标单位|中标候选人|第一中标候选人)\s*[:：]\s*([^。；;\n]{4,140})",
        r"(?:联合体成员|联合体\(成\)|联合体（成）)\s*[:：]\s*([^。；;\n]{4,140})",
    ]
    names: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            segment = match.group(1)
            for part in re.split(r"[;,，、；]|(?:联合体)|(?:\(成\))|(?:（成）)|(?:\(主\))|(?:（主）)", segment):
                part = part.strip()
                if "公司" in part or "集团" in part or "院" in part:
                    names.append(part)
    return _dedupe(names)


def _payload_to_text(content: str, content_type: str) -> str:
    if "json" in content_type.lower():
        try:
            return _json_to_text(json.loads(content))
        except json.JSONDecodeError:
            return content[:2000]
    stripped = content.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return _json_to_text(json.loads(content))
        except json.JSONDecodeError:
            pass
    return _html_to_text(content)


def _json_to_text(value: Any) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(child, (str, int, float)):
                    parts.append(f"{key}：{child}")
                else:
                    walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, (str, int, float)):
            parts.append(str(item))

    walk(value)
    return "\n".join(parts)


def _html_to_text(content: str) -> str:
    text = re.sub(r"<\s*br\s*/?>", "\n", content, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _url_mapping_parts(url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    mapping_id = parsed.path.rstrip("/").split("/")[-1]
    notice_id = mapping_id
    notice_type = ""
    if "-" in mapping_id:
        notice_id, notice_type = mapping_id.rsplit("-", 1)
    return {
        "mapping_id": mapping_id,
        "notice_id": notice_id,
        "notice_type": notice_type,
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


def _summary(
    *,
    task_records: list[Mapping[str, Any]],
    readback_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "p13b_ygp_original_readback_state": "P13B_YGP_ORIGINAL_READBACK_READY" if not blocking_reasons else "P13B_YGP_INPUT_BLOCKED",
        "execution_mode": execution_mode,
        "ygp_original_readback_task_count": len(task_records),
        "ygp_original_readback_count": len(readback_records),
        "ygp_readback_ready_count": sum(
            1
            for record in readback_records
            if str(record.get("ygp_readback_state") or "") in {"YGP_ORIGINAL_URL_READBACK_READY", "YGP_BROWSER_NETWORK_READBACK_READY"}
        ),
        "ygp_person_period_extracted_count": sum(
            1
            for record in readback_records
            if str(record.get("ygp_extraction_state") or "") == "YGP_ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED"
        ),
        "ygp_readback_state_counts": _counts(record.get("ygp_readback_state") for record in readback_records),
        "ygp_api_discovery_state_counts": _counts(record.get("ygp_api_discovery_state") for record in readback_records),
        "blocker_taxonomy_counts": _counts(
            blocker for record in readback_records for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        key = str(value).strip()
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
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B YGP original notice readback manifest.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--input-json", default=None)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--max-live-original-notices", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_ygp_original_readback(
        input_root=args.input_root,
        input_json=args.input_json,
        output_root=args.output_root,
        enable_live_public_query=args.enable_live_public_query,
        max_live_original_notices=args.max_live_original_notices,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
