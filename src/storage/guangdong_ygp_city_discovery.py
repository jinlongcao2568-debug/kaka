from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso
from storage.guangdong_ygp_flow_matrix import build_guangdong_ygp_flow_matrix


GUANGDONG_YGP_CITY_DISCOVERY_KIND = "guangdong_ygp_city_discovery_v1_manifest"
GUANGDONG_YGP_CITY_DISCOVERY_VERSION = 1
GUANGDONG_YGP_CITY_DISCOVERY_ADAPTER_ID = "guangdong-ygp-city-discovery-v1-builder"

DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-ygp-city-discovery-v1")
DEFAULT_CITY_CODES = ("440400", "440500", "440600")
YGP_SEARCH_URL = "https://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items"
YGP_HASH_ROOT = "https://ygp.gdzwfw.gov.cn/ggzy-portal/#/44/new/jygg"
FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_guangdong_ygp_city_discovery(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    city_codes: list[str] | None = None,
    per_city_candidate_limit: int = 2,
    max_pages_per_city: int = 3,
    build_flow_matrix: bool = False,
    enable_live_public_query: bool = False,
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    cities = _dedupe(city_codes or list(DEFAULT_CITY_CODES))
    execution_mode = "LIVE_PUBLIC_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED"
    city_task_records = _city_task_records(cities, created_at=created)
    getter = http_getter or _default_http_getter
    search_records: list[dict[str, Any]] = []
    candidate_records: list[dict[str, Any]] = []
    if enable_live_public_query:
        search_records, candidate_records = _execute_city_searches(
            city_task_records,
            getter=getter,
            per_city_candidate_limit=per_city_candidate_limit,
            max_pages_per_city=max_pages_per_city,
            created_at=created,
        )
    flow_matrix_result: dict[str, Any] | None = None
    candidate_urls = [str(record.get("ygp_project_url") or "") for record in candidate_records if record.get("ygp_project_url")]
    if build_flow_matrix and candidate_urls:
        flow_matrix_result = build_guangdong_ygp_flow_matrix(
            input_root=out_dir / "_no_input_required",
            source_urls=candidate_urls,
            output_root=out_dir / "flow-matrix",
            enable_live_public_query=enable_live_public_query,
            max_live_source_urls=len(candidate_urls) if enable_live_public_query else None,
            http_getter=getter,
            created_at=created,
        )
    manual_table = _manual_url_check_table(candidate_records, flow_matrix_result=flow_matrix_result)
    summary = _summary(
        city_task_records=city_task_records,
        search_records=search_records,
        candidate_records=candidate_records,
        flow_matrix_result=flow_matrix_result,
        execution_mode=execution_mode,
    )
    manifest = {
        "manifest_version": GUANGDONG_YGP_CITY_DISCOVERY_VERSION,
        "manifest_kind": GUANGDONG_YGP_CITY_DISCOVERY_KIND,
        "adapter_id": GUANGDONG_YGP_CITY_DISCOVERY_ADAPTER_ID,
        "pipeline_stage": "GuangdongYgpCityDiscoveryV1",
        "manifest_id": f"GUANGDONG-YGP-CITY-DISCOVERY-{_fingerprint({'summary': summary, 'cities': cities})[:16]}",
        "created_at": created,
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "build_flow_matrix": bool(build_flow_matrix),
        "city_codes": cities,
        "per_city_candidate_limit": per_city_candidate_limit,
        "max_pages_per_city": max_pages_per_city,
        "ygp_city_task_records": city_task_records,
        "ygp_city_search_records": search_records,
        "ygp_candidate_project_records": candidate_records,
        "manual_url_check_table": manual_table,
        "flow_matrix_summary": (flow_matrix_result or {}).get("summary", {}),
        "flow_matrix_manifest_path": str(out_dir / "flow-matrix" / "guangdong-ygp-flow-matrix-v1.json") if flow_matrix_result else "",
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
            "not_shenzhen_primary_source": True,
            "guangdong_city_adapter_base_capability": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "guangdong_ygp_city_discovery_mode": "BUILT",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [f"forbidden_report_term:{term}" for term in forbidden_hits]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangdong-ygp-city-discovery-v1.json").write_text(text, encoding="utf-8")
    (out_dir / "manual-url-check-table.json").write_text(
        json.dumps(manual_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _city_task_records(city_codes: list[str], *, created_at: str) -> list[dict[str, Any]]:
    return [
        {
            "ygp_city_task_id": _stable_id("YGP-CITY", city_code),
            "city_code": city_code,
            "search_url": YGP_SEARCH_URL,
            "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for city_code in city_codes
    ]


def _execute_city_searches(
    city_tasks: list[Mapping[str, Any]],
    *,
    getter: HttpGetter,
    per_city_candidate_limit: int,
    max_pages_per_city: int,
    created_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    search_records: list[dict[str, Any]] = []
    candidate_records: list[dict[str, Any]] = []
    seen_candidates: set[str] = set()
    for task in city_tasks:
        city_code = str(task.get("city_code") or "")
        city_candidates = 0
        for page_no in range(1, max(1, max_pages_per_city) + 1):
            if city_candidates >= per_city_candidate_limit:
                break
            payload = {
                "type": "trading-type",
                "openConvert": False,
                "siteCode": city_code,
                "keyword": "中标候选人",
                "pageNo": page_no,
                "pageSize": 10,
            }
            response = _post_search(payload, getter, task=task)
            items = _search_items(response)
            response_total = _search_total(response)
            accepted: list[dict[str, Any]] = []
            rejected_count = 0
            for item in items:
                if not _is_candidate_notice_item(item):
                    rejected_count += 1
                    continue
                candidate = _candidate_record_from_item(task, item, created_at=created_at)
                key = str(candidate.get("ygp_candidate_project_id") or "")
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                accepted.append(candidate)
                candidate_records.append(candidate)
                city_candidates += 1
                if city_candidates >= per_city_candidate_limit:
                    break
            blockers = _blockers_from_response(response)
            search_records.append(
                {
                    "ygp_city_search_record_id": _stable_id("YGP-CITY-SEARCH", city_code, page_no),
                    "ygp_city_task_id": str(task.get("ygp_city_task_id") or ""),
                    "city_code": city_code,
                    "search_url": YGP_SEARCH_URL,
                    "request_payload": payload,
                    "page_no": page_no,
                    "status_code": response["status_code"],
                    "content_type": response["content_type"],
                    "response_body_sha256": _sha256(str(response.get("body") or "")) if response.get("body") else "",
                    "response_body_probe": _body_probe(response),
                    "response_total": response_total,
                    "record_count": len(items),
                    "accepted_candidate_count": len(accepted),
                    "rejected_record_count": rejected_count,
                    "search_state": "YGP_CITY_SEARCH_READY" if response["status_code"] == 200 else "YGP_CITY_SEARCH_BLOCKED",
                    "blocker_taxonomy": blockers,
                    "created_at": created_at,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return search_records, candidate_records


def _post_search(payload: Mapping[str, Any], getter: HttpGetter, *, task: Mapping[str, Any]) -> dict[str, Any]:
    response = dict(
        getter(
            YGP_SEARCH_URL,
            {
                "route": "ygp_city_search",
                "method": "POST",
                "json_body": dict(payload),
                "task": dict(task),
            },
        )
    )
    status_code = int(response.get("status_code") or response.get("status") or 0)
    headers = response.get("headers") if isinstance(response.get("headers"), Mapping) else {}
    body = str(response.get("body") or response.get("content") or response.get("text") or "")
    return {
        "url": str(response.get("url") or YGP_SEARCH_URL),
        "status_code": status_code,
        "content_type": str(response.get("content_type") or headers.get("Content-Type") or headers.get("content-type") or ""),
        "headers": dict(headers),
        "body": body,
        "error": str(response.get("error") or ""),
    }


def _search_items(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    try:
        payload = json.loads(str(response.get("body") or ""))
    except json.JSONDecodeError:
        return []
    data = payload.get("data") if isinstance(payload, Mapping) else {}
    page_data = data.get("pageData") if isinstance(data, Mapping) else []
    return [item for item in _list(page_data) if isinstance(item, Mapping)]


def _search_total(response: Mapping[str, Any]) -> int:
    try:
        payload = json.loads(str(response.get("body") or ""))
    except json.JSONDecodeError:
        return 0
    data = payload.get("data") if isinstance(payload, Mapping) else {}
    if not isinstance(data, Mapping):
        return 0
    for key in ("total", "totalCount", "recordCount"):
        value = data.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _body_probe(response: Mapping[str, Any]) -> str:
    body = str(response.get("body") or "")
    if not body:
        return ""
    return body[:500]


def _is_candidate_notice_item(item: Mapping[str, Any]) -> bool:
    primary_text = " ".join(
        str(item.get(key) or "")
        for key in ("datasetName", "noticeThirdTypeDesc")
    )
    title = str(item.get("noticeTitle") or "")
    biz_code = re.sub(r"\s+", "", str(item.get("tradingProcess") or item.get("bizCode") or ""))
    trading_type = re.sub(r"\s+", "", str(item.get("noticeSecondType") or ""))
    if biz_code and biz_code != "3C51":
        return False
    if trading_type and trading_type != "A":
        return False
    if "中标候选人公示" in primary_text:
        return True
    if "中标候选人公示" in title and "中标结果" not in title and "结果公告" not in title:
        return True
    return False


def _candidate_record_from_item(task: Mapping[str, Any], item: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    notice_id = str(item.get("noticeId") or "")
    project_code = str(item.get("projectCode") or "")
    city_code = str(task.get("city_code") or "")
    region_code = str(item.get("regionCode") or item.get("siteCode") or city_code)
    trading_type = str(item.get("noticeSecondType") or "")
    biz_code = str(item.get("tradingProcess") or item.get("bizCode") or "")
    publish_date = str(item.get("publishDate") or "")
    title = str(item.get("noticeTitle") or "")
    ygp_url = _ygp_hash_url(
        edition=str(item.get("edition") or "v3"),
        trading_type=trading_type,
        notice_id=notice_id,
        project_code=project_code,
        biz_code=biz_code,
        site_code=region_code,
        publish_date=publish_date,
        source=str(item.get("pubServicePlat") or ""),
        title_details=str(item.get("noticeSecondTypeDesc") or ""),
        classify=str(item.get("projectType") or ""),
    )
    return {
        "ygp_candidate_project_id": _stable_id("YGP-CANDIDATE", region_code, project_code, notice_id, biz_code),
        "ygp_city_task_id": str(task.get("ygp_city_task_id") or ""),
        "city_code": city_code,
        "site_code": str(item.get("siteCode") or ""),
        "region_code": region_code,
        "site_name": str(item.get("siteName") or ""),
        "region_name": str(item.get("regionName") or ""),
        "notice_id": notice_id,
        "project_code": project_code,
        "project_name": title,
        "project_owner": str(item.get("projectOwner") or ""),
        "notice_second_type": trading_type,
        "notice_second_type_desc": str(item.get("noticeSecondTypeDesc") or ""),
        "notice_third_type": str(item.get("noticeThirdType") or ""),
        "notice_third_type_desc": str(item.get("noticeThirdTypeDesc") or ""),
        "dataset_name": str(item.get("datasetName") or ""),
        "trading_process": biz_code,
        "project_type": str(item.get("projectType") or ""),
        "project_type_name": str(item.get("projectTypeName") or ""),
        "publish_date": publish_date,
        "pub_service_platform": str(item.get("pubServicePlat") or ""),
        "ygp_project_url": ygp_url,
        "discovery_state": "YGP_CITY_CANDIDATE_07_DISCOVERED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _ygp_hash_url(
    *,
    edition: str,
    trading_type: str,
    notice_id: str,
    project_code: str,
    biz_code: str,
    site_code: str,
    publish_date: str,
    source: str,
    title_details: str,
    classify: str,
) -> str:
    query = {
        "noticeId": notice_id,
        "projectCode": project_code,
        "bizCode": biz_code,
        "siteCode": site_code,
        "publishDate": publish_date,
        "source": source,
        "titleDetails": title_details,
    }
    if classify:
        query["classify"] = classify
    return f"{YGP_HASH_ROOT}/{edition or 'v3'}/{trading_type}?{urllib.parse.urlencode(query)}"


def _manual_url_check_table(candidate_records: list[Mapping[str, Any]], *, flow_matrix_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    matrix = ((flow_matrix_result or {}).get("manifest") or {}) if isinstance(flow_matrix_result, Mapping) else {}
    buckets = _list(matrix.get("ygp_flow_bucket_records"))
    bucket_by_url: dict[str, list[Mapping[str, Any]]] = {}
    for bucket in buckets:
        if isinstance(bucket, Mapping):
            bucket_by_url.setdefault(str(bucket.get("source_url") or ""), []).append(bucket)
    rows: list[dict[str, Any]] = []
    for candidate in candidate_records:
        url = str(candidate.get("ygp_project_url") or "")
        flow_rows = sorted(bucket_by_url.get(url, []), key=lambda row: str(row.get("flow_no") or ""))
        rows.append(
            {
                "city_code": candidate.get("city_code"),
                "region_name": candidate.get("region_name"),
                "project_code": candidate.get("project_code"),
                "project_name": candidate.get("project_name"),
                "candidate_notice_url": url,
                "publish_date": candidate.get("publish_date"),
                "flow_summary": [
                    {
                        "flow_no": row.get("flow_no"),
                        "flow_title": row.get("flow_title"),
                        "flow_item_state": row.get("flow_item_state"),
                        "present_item_count": row.get("present_item_count"),
                        "detail_urls": row.get("detail_urls"),
                    }
                    for row in flow_rows
                ],
            }
        )
    return rows


def _summary(
    *,
    city_task_records: list[Mapping[str, Any]],
    search_records: list[Mapping[str, Any]],
    candidate_records: list[Mapping[str, Any]],
    flow_matrix_result: Mapping[str, Any] | None,
    execution_mode: str,
) -> dict[str, Any]:
    flow_summary = dict((flow_matrix_result or {}).get("summary") or {}) if isinstance(flow_matrix_result, Mapping) else {}
    return {
        "guangdong_ygp_city_discovery_state": "GUANGDONG_YGP_CITY_DISCOVERY_READY",
        "execution_mode": execution_mode,
        "city_task_count": len(city_task_records),
        "city_search_record_count": len(search_records),
        "candidate_project_count": len(candidate_records),
        "candidate_project_by_city_counts": _counts(record.get("city_code") for record in candidate_records),
        "search_state_counts": _counts(record.get("search_state") for record in search_records),
        "blocker_taxonomy_counts": _counts(
            blocker
            for record in search_records
            for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "build_flow_matrix": bool(flow_matrix_result),
        "flow_matrix_state": flow_summary.get("guangdong_ygp_flow_matrix_state", "NOT_RUN"),
        "flow_matrix_project_readback_count": flow_summary.get("ygp_project_readback_count", 0),
        "flow_matrix_detail_readback_ready_count": flow_summary.get("ygp_detail_readback_ready_count", 0),
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _blockers_from_response(response: Mapping[str, Any]) -> list[str]:
    status = int(response.get("status_code") or 0)
    body = str(response.get("body") or "")
    error = str(response.get("error") or "")
    blockers: list[str] = []
    if status in {403, 429}:
        blockers.append("ygp_city_search_forbidden_or_rate_limited_review")
    if status in {500, 502, 503, 504}:
        blockers.append("ygp_city_search_temporary_unavailable_retry_required")
    if status == 0 and error:
        blockers.append("ygp_city_search_transport_error_retry_required")
    if "验证码" in body or "captcha" in body.lower():
        blockers.append("ygp_city_search_captcha_or_challenge_review")
    if "\"errcode\"" in body and "\"errcode\":0" not in body.replace(" ", ""):
        blockers.append("ygp_city_search_interface_error_review")
    if "请求方法错误" in body:
        blockers.append("ygp_city_search_request_method_error")
    if status == 200 and not body.strip():
        blockers.append("ygp_city_search_empty_body_review")
    return _dedupe(blockers)


def _default_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    attempts = _http_attempt_count()
    last_result: Mapping[str, Any] = {}
    for attempt_no in range(1, attempts + 1):
        result = _default_http_getter_once(url, context)
        last_result = result
        if not _should_retry_http_result(result, attempt_no=attempt_no, attempts=attempts):
            return result
        time.sleep(_http_retry_delay_seconds(result, attempt_no=attempt_no))
    return dict(last_result)


def _default_http_getter_once(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    method = str(context.get("method") or "GET").upper()
    body: bytes | None = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaYgpCityDiscovery/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://ygp.gdzwfw.gov.cn/",
    }
    if method == "POST":
        body = json.dumps(context.get("json_body") or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=UTF-8"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            text = response.read().decode("utf-8", errors="replace")
            return {
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": response.headers.get("Content-Type", ""),
                "headers": dict(response.headers.items()),
                "body": text,
                "url": response.geturl(),
            }
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "status_code": int(exc.code),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body": text,
            "url": url,
            "error": str(exc),
        }
    except urllib.error.URLError as exc:
        return {"status_code": 0, "content_type": "", "headers": {}, "body": "", "url": url, "error": str(exc.reason)}


def _http_attempt_count() -> int:
    raw = os.environ.get("KAKA_YGP_HTTP_ATTEMPTS")
    if raw is None or not str(raw).strip():
        return 3
    try:
        return max(1, min(5, int(raw)))
    except ValueError:
        return 3


def _should_retry_http_result(result: Mapping[str, Any], *, attempt_no: int, attempts: int) -> bool:
    if attempt_no >= attempts:
        return False
    status_code = int(result.get("status_code") or 0)
    error = str(result.get("error") or "").lower()
    if status_code in {429, 500, 502, 503, 504}:
        return True
    if status_code == 0 and any(token in error for token in ("ssl", "eof", "timeout", "timed out", "connection reset", "temporarily unavailable")):
        return True
    return False


def _http_retry_delay_seconds(result: Mapping[str, Any], *, attempt_no: int) -> float:
    headers = result.get("headers") if isinstance(result.get("headers"), Mapping) else {}
    retry_after = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    body = str(result.get("body") or result.get("text") or "")
    candidates: list[float] = []
    if retry_after:
        try:
            candidates.append(float(retry_after))
        except ValueError:
            pass
    match = re.search(r"请\s*(\d{1,3})\s*秒后重试", body)
    if match:
        candidates.append(float(match.group(1)))
    delay = max(candidates) if candidates else min(2.0, 0.5 * attempt_no)
    return min(delay, _http_retry_after_max_seconds())


def _http_retry_after_max_seconds() -> float:
    raw = os.environ.get("KAKA_YGP_RETRY_AFTER_MAX_SECONDS")
    if raw is None or not str(raw).strip():
        return 90.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 90.0


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
        out.append(key)
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
    parser = argparse.ArgumentParser(description="Discover Guangdong YGP city candidate notices and build optional 01-12 flow matrix.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--city-code", action="append", default=[])
    parser.add_argument("--per-city-candidate-limit", type=int, default=2)
    parser.add_argument("--max-pages-per-city", type=int, default=3)
    parser.add_argument("--build-flow-matrix", action="store_true")
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_guangdong_ygp_city_discovery(
        output_root=args.output_root,
        city_codes=args.city_code or list(DEFAULT_CITY_CODES),
        per_city_candidate_limit=args.per_city_candidate_limit,
        max_pages_per_city=args.max_pages_per_city,
        build_flow_matrix=args.build_flow_matrix,
        enable_live_public_query=args.enable_live_public_query,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
