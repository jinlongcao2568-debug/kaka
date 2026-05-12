from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGDONG_LOCAL_FIELD_QUERY_PROBE_KIND = "guangdong_local_field_query_probe_v1_manifest"
GUANGDONG_LOCAL_FIELD_QUERY_PROBE_VERSION = 1
GUANGDONG_LOCAL_FIELD_QUERY_PROBE_ADAPTER_ID = "guangdong-local-field-query-probe-v1-builder"

DEFAULT_LOCAL_VERIFICATION_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-verification-probe-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-field-query-probe-v1")

DELEGATED_PROFILE_ADAPTERS = {
    "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM": "guangdong_gdcic_query_probe_v1",
}

FORBIDDEN_TERMS = ("在建冲突成立", "无在建", "无冲突", "造假成立", "违法成立", "确认本人", "是不是本人")

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_guangdong_local_field_query_probe(
    *,
    local_verification_root: str | Path = DEFAULT_LOCAL_VERIFICATION_ROOT,
    local_verification_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    source_profile_ids: list[str] | tuple[str, ...] | None = None,
    enable_live_public_query: bool = False,
    max_live_tasks: int | None = None,
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    local_dir = Path(local_verification_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = (
        Path(local_verification_json)
        if local_verification_json
        else local_dir / "guangdong-local-verification-probe-v1.json"
    )
    blocking_reasons: list[str] = []
    local_manifest = _source_manifest(
        _load_json(source_path, blocking_reasons, "guangdong_local_verification_probe_missing")
    )
    selected_profiles = _normalize_filter(source_profile_ids)
    execution_mode = "LIVE_PUBLIC_FIELD_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED"
    field_task_records = _field_task_records_from_local_verification(
        local_manifest,
        created_at=created,
        source_profile_ids=selected_profiles,
        enable_live_public_query=enable_live_public_query,
        max_live_tasks=max_live_tasks,
        http_getter=http_getter,
    )
    project_task_records = _project_task_records(field_task_records)
    manual_check_table = _manual_check_table(field_task_records)
    summary = _summary(
        field_task_records=field_task_records,
        project_task_records=project_task_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GUANGDONG_LOCAL_FIELD_QUERY_PROBE_VERSION,
        "manifest_kind": GUANGDONG_LOCAL_FIELD_QUERY_PROBE_KIND,
        "adapter_id": GUANGDONG_LOCAL_FIELD_QUERY_PROBE_ADAPTER_ID,
        "pipeline_stage": "GuangdongLocalFieldQueryProbeV1",
        "manifest_id": f"GUANGDONG-LOCAL-FIELD-QUERY-PROBE-{_fingerprint({'tasks': field_task_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_local_verification_root": str(local_dir),
        "source_local_verification_json": str(source_path),
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "max_live_tasks": max_live_tasks,
        "source_profile_ids": sorted(selected_profiles) if selected_profiles else "ALL_GUANGDONG_LOCAL_SOURCES",
        "project_task_records": project_task_records,
        "field_task_records": field_task_records,
        "manual_check_table": manual_check_table,
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
            "no_no_risk_inference": True,
            "field_query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "guangdong_local_field_query_probe_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangdong-local-field-query-probe-v1.json").write_text(text, encoding="utf-8")
    return result


def _field_task_records_from_local_verification(
    local_manifest: Mapping[str, Any],
    *,
    created_at: str,
    source_profile_ids: set[str],
    enable_live_public_query: bool,
    max_live_tasks: int | None,
    http_getter: HttpGetter | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    live_attempted = 0
    cache: dict[str, dict[str, Any]] = {}
    for task in _list(local_manifest.get("query_task_records")):
        if not isinstance(task, Mapping):
            continue
        profile_id = str(task.get("source_profile_id") or "").upper()
        if source_profile_ids and profile_id not in source_profile_ids:
            continue
        query_params = dict(task.get("query_params") or {})
        route_plan = _route_plan_for_task(task, query_params)
        if profile_id in DELEGATED_PROFILE_ADAPTERS:
            readback = _delegated_readback(profile_id, route_plan)
        elif enable_live_public_query:
            cache_key = _cache_key(task, route_plan)
            if cache_key in cache:
                readback = _copy_jsonable(cache[cache_key])
                readback["field_query_cache_hit"] = True
            elif max_live_tasks is not None and live_attempted >= max_live_tasks:
                readback = _live_deferred_readback(max_live_tasks, route_plan)
                cache[cache_key] = _copy_jsonable(readback)
            else:
                live_attempted += 1
                readback = _execute_live_field_query(task, route_plan, http_getter=http_getter)
                cache[cache_key] = _copy_jsonable(readback)
        else:
            readback = _plan_only_readback(route_plan)
        records.append(
            {
                "field_query_task_id": _stable_id(
                    "GD-LOCAL-FIELD",
                    task.get("query_task_id"),
                    task.get("project_id"),
                    task.get("candidate_group_id"),
                    task.get("responsible_person_name"),
                    task.get("source_profile_id"),
                ),
                "local_verification_query_task_id": str(task.get("query_task_id") or ""),
                "active_conflict_task_id": str(task.get("active_conflict_task_id") or ""),
                "project_id": str(task.get("project_id") or ""),
                "project_name": str(task.get("project_name") or ""),
                "candidate_group_id": str(task.get("candidate_group_id") or ""),
                "candidate_group_order": str(task.get("candidate_group_order") or ""),
                "responsible_person_name": str(task.get("responsible_person_name") or ""),
                "candidate_group_members": _list(task.get("candidate_group_members")),
                "matched_company_names": _list(task.get("matched_company_names")),
                "company_query_variants": _list(task.get("company_query_variants")),
                "certificate_no": str(task.get("certificate_no") or ""),
                "query_keywords": _list(task.get("query_keywords")),
                "source_profile_id": str(task.get("source_profile_id") or ""),
                "source_family": str(task.get("source_family") or ""),
                "source_url": str(task.get("source_url") or ""),
                "target_source_types": _list(task.get("target_source_types")),
                "query_params": query_params,
                "field_adapter_status": str(task.get("field_adapter_status") or ""),
                "execution_mode": (
                    "LIVE_PUBLIC_FIELD_QUERY_ATTEMPTED"
                    if enable_live_public_query
                    else "PLAN_ONLY_NOT_EXECUTED"
                ),
                **readback,
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _route_plan_for_task(task: Mapping[str, Any], query_params: Mapping[str, Any]) -> list[dict[str, Any]]:
    profile_id = str(task.get("source_profile_id") or "").upper()
    source_url = str(task.get("source_url") or "")
    keywords = _query_keywords(query_params)
    primary_keyword = _first_text(keywords)
    encoded = urllib.parse.quote(primary_keyword)
    routes: list[dict[str, Any]] = []
    if profile_id == "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY":
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route("city_double_publicity_keyword_url", f"https://zfcj.gz.gov.cn/zfcj/xyxx/index.html?keywords={encoded}", "city_double_publicity_keyword_probe", keywords),
                _route("city_construction_permit_category", f"https://zfcj.gz.gov.cn/zfcj/xyxx/index.html?subcategory=1&keywords={encoded}", "city_double_publicity_permit_probe", keywords),
            ]
        )
    elif profile_id == "GUANGDONG-ZFCXJST-PENALTY-PUBLICITY":
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route("province_site_search", f"https://search.gd.gov.cn/search/all/233?keywords={encoded}", "province_housing_site_search_probe", keywords),
            ]
        )
    elif profile_id == "GUANGDONG-CREDIT-GD-HOME":
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route("credit_gd_search_page", f"https://credit.gd.gov.cn/Search/index.html?keywords={encoded}", "credit_gd_subject_search_probe", keywords),
                _route("credit_gd_penalty_page", f"https://credit.gd.gov.cn/page/creditPublic/xzcf.html?keywords={encoded}", "credit_gd_penalty_page_probe", keywords),
            ]
        )
    elif profile_id == "GUANGDONG-TZXM-HOME":
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route("investment_project_home_keyword", f"https://tzxm.gd.gov.cn/?keywords={encoded}", "investment_project_home_keyword_probe", keywords),
            ]
        )
    elif profile_id == "GUANGDONG-GDCIC-HOME":
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route("gdcic_home_keyword", f"{source_url.rstrip('/')}?keywords={encoded}" if source_url else "", "gdcic_contract_performance_keyword_probe", keywords),
            ]
        )
    else:
        routes.append(_route("source_home", source_url, "source_home_probe", keywords))
    return [route for route in routes if route["url"]]


def _route(route_id: str, url: str, route_group: str, keywords: list[str]) -> dict[str, Any]:
    return {
        "route_id": route_id,
        "route_group": route_group,
        "url": url,
        "keyword_count": len(keywords),
        "query_keyword_probe": keywords[:5],
    }


def _query_keywords(query_params: Mapping[str, Any]) -> list[str]:
    values = [
        query_params.get("certificateNo"),
        query_params.get("personName"),
        query_params.get("companyName"),
        *_list(query_params.get("companyVariants")),
        _clean_project_title(query_params.get("projectName")),
        *_list(query_params.get("keywords")),
    ]
    return _dedupe(value for value in values if str(value or "").strip())


def _delegated_readback(profile_id: str, route_plan: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "field_query_probe_state": "DELEGATED_TO_SEPARATE_FIELD_ADAPTER",
        "field_readback_state": "NOT_EXECUTED_IN_THIS_PROBE",
        "readback_ready": False,
        "readback_status_code": None,
        "field_summary": {},
        "field_match_summary": {},
        "route_plan": list(route_plan),
        "route_attempts": [],
        "blocker_taxonomy": [],
        "delegated_adapter_id": DELEGATED_PROFILE_ADAPTERS[profile_id],
    }


def _plan_only_readback(route_plan: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "field_query_probe_state": "PLAN_ONLY_NOT_EXECUTED",
        "field_readback_state": "FIELD_READBACK_NOT_RUN",
        "readback_ready": False,
        "readback_status_code": None,
        "field_summary": {},
        "field_match_summary": {},
        "route_plan": list(route_plan),
        "route_attempts": [],
        "blocker_taxonomy": [],
    }


def _live_deferred_readback(max_live_tasks: int, route_plan: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "field_query_probe_state": "LIVE_FIELD_QUERY_DEFERRED_BY_LIMIT",
        "field_readback_state": "FIELD_READBACK_DEFERRED",
        "readback_ready": False,
        "readback_status_code": None,
        "field_summary": {},
        "field_match_summary": {},
        "route_plan": list(route_plan),
        "route_attempts": [],
        "blocker_taxonomy": ["guangdong_local_field_query_deferred_by_limit"],
        "diagnostic_message": f"max_live_tasks={max_live_tasks}",
    }


def _execute_live_field_query(
    task: Mapping[str, Any],
    route_plan: list[Mapping[str, Any]],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    getter = http_getter or _default_http_getter
    query_params = dict(task.get("query_params") or {})
    keywords = _query_keywords(query_params)
    attempts: list[dict[str, Any]] = []
    match_records: list[dict[str, Any]] = []
    for route in route_plan:
        response = _safe_get(route, getter=getter)
        attempt = _route_attempt(route, response, keywords)
        attempts.append(attempt)
        if attempt["keyword_hit_count"]:
            match_records.append(
                {
                    "route_id": attempt["route_id"],
                    "url": attempt["url"],
                    "matched_keywords": attempt["matched_keywords"],
                    "source_text_sha256": attempt["text_probe_sha256"],
                }
            )
    blockers = _dedupe(blocker for attempt in attempts for blocker in _list(attempt.get("blocker_taxonomy")))
    status_codes = [_int(attempt.get("http_status")) for attempt in attempts if _int(attempt.get("http_status"))]
    if match_records:
        return {
            "field_query_probe_state": "FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_KEYWORD_HIT_REVIEW_REQUIRED",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": {
                "keyword_hit_route_count": len(match_records),
                "matched_keyword_count": len(_dedupe(keyword for row in match_records for keyword in row["matched_keywords"])),
                "source_profile_keyword_hit": True,
            },
            "field_match_summary": {
                "match_records": match_records[:10],
                "query_miss_is_not_clearance": True,
            },
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers,
        }
    if attempts and all(str(attempt.get("route_state") or "").startswith("FAIL_CLOSED") for attempt in attempts):
        return {
            "field_query_probe_state": "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED",
            "field_readback_state": "FIELD_READBACK_BLOCKED",
            "readback_ready": False,
            "readback_status_code": status_codes[0] if status_codes else None,
            "field_summary": {},
            "field_match_summary": {"query_miss_is_not_clearance": True},
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers or ["guangdong_local_field_query_all_routes_blocked"],
        }
    return {
        "field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
        "field_readback_state": "PUBLIC_SOURCE_QUERIED_NO_KEYWORD_MATCH",
        "readback_ready": False,
        "readback_status_code": status_codes[0] if status_codes else None,
        "field_summary": {
            "keyword_hit_route_count": 0,
            "source_profile_keyword_hit": False,
        },
        "field_match_summary": {"query_miss_is_not_clearance": True},
        "route_plan": list(route_plan),
        "route_attempts": attempts,
        "blocker_taxonomy": blockers or ["guangdong_local_field_query_no_keyword_hit_review"],
    }


def _safe_get(route: Mapping[str, Any], *, getter: HttpGetter) -> Mapping[str, Any]:
    try:
        return dict(getter(str(route.get("url") or ""), {}))
    except Exception as exc:  # pragma: no cover - defensive guard for external routes.
        return {
            "http_status": None,
            "content_type": "",
            "text_probe": "",
            "transport_error": type(exc).__name__,
        }


def _default_http_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_http_timeout_seconds()) as response:  # noqa: S310
            body = response.read(80_000)
            content_type = response.headers.get("Content-Type", "")
            return {
                "http_status": response.getcode(),
                "content_type": content_type,
                "text_probe": _decode_probe(body, content_type),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(4096) if hasattr(exc, "read") else b""
        return {
            "http_status": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "text_probe": _decode_probe(body, exc.headers.get("Content-Type", "") if exc.headers else ""),
        }


def _route_attempt(route: Mapping[str, Any], response: Mapping[str, Any], keywords: list[str]) -> dict[str, Any]:
    text = str(response.get("text_probe") or response.get("body_probe") or "")
    matched = [keyword for keyword in keywords if keyword and keyword in text]
    blockers = _route_blockers(response)
    status = _int(response.get("http_status") or response.get("status_code"))
    if blockers:
        route_state = "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED"
    elif 200 <= status < 400:
        route_state = "PUBLIC_SOURCE_QUERIED"
    elif status:
        route_state = "REVIEW_REQUIRED_HTTP_STATUS"
    else:
        route_state = "FAIL_CLOSED_QUERY_TRANSPORT_ERROR"
        blockers = blockers or ["guangdong_local_field_query_transport_error"]
    return {
        "route_id": str(route.get("route_id") or ""),
        "route_group": str(route.get("route_group") or ""),
        "url": str(route.get("url") or ""),
        "route_state": route_state,
        "http_status": status or None,
        "content_type_probe": str(response.get("content_type") or ""),
        "keyword_hit_count": len(matched),
        "matched_keywords": matched[:10],
        "text_probe_sha256": _sha256_text(text),
        "text_probe_length": len(text),
        "blocker_taxonomy": blockers,
    }


def _route_blockers(response: Mapping[str, Any]) -> list[str]:
    status = _int(response.get("http_status") or response.get("status_code"))
    text = str(response.get("text_probe") or response.get("body_probe") or "")
    if response.get("transport_error"):
        return [f"guangdong_local_field_query_transport_error:{response.get('transport_error')}"]
    if status in {401, 403}:
        return ["guangdong_local_field_query_forbidden_or_login_required"]
    if status >= 500:
        return ["guangdong_local_field_query_source_server_error"]
    if _looks_like_captcha_or_login(text):
        return ["guangdong_local_field_query_captcha_or_login_required"]
    return []


def _looks_like_captcha_or_login(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in ("captcha", "验证码", "滑块", "请登录", "用户登录", "统一身份认证"))


def _project_task_records(field_task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for task in field_task_records:
        grouped.setdefault(str(task.get("project_id") or ""), []).append(task)
    records: list[dict[str, Any]] = []
    for project_id, tasks in grouped.items():
        records.append(
            {
                "project_id": project_id,
                "project_name": _first_text(task.get("project_name") for task in tasks),
                "field_query_task_ids": [str(task.get("field_query_task_id") or "") for task in tasks],
                "field_query_task_count": len(tasks),
                "source_profile_ids": _dedupe(task.get("source_profile_id") for task in tasks),
                "readback_ready_count": sum(1 for task in tasks if bool(task.get("readback_ready"))),
                "keyword_hit_count": sum(1 for task in tasks if str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE"),
                "blocker_taxonomy_counts": _counts(
                    blocker for task in tasks for blocker in _list(task.get("blocker_taxonomy"))
                ),
                "probe_state": "READY" if tasks else "NO_GUANGDONG_LOCAL_FIELD_TASKS",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _manual_check_table(field_task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "field_query_task_id": task.get("field_query_task_id"),
            "project_id": task.get("project_id"),
            "project_name": task.get("project_name"),
            "candidate_group_id": task.get("candidate_group_id"),
            "responsible_person_name": task.get("responsible_person_name"),
            "certificate_no": task.get("certificate_no"),
            "source_profile_id": task.get("source_profile_id"),
            "target_source_types": task.get("target_source_types"),
            "route_plan": task.get("route_plan"),
            "field_query_probe_state": task.get("field_query_probe_state"),
            "manual_check_state": "PENDING_FIELD_SOURCE_REVIEW",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for task in field_task_records
    ]


def _summary(
    *,
    field_task_records: list[Mapping[str, Any]],
    project_task_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "probe_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "execution_mode": execution_mode,
        "guangdong_local_field_query_task_count": len(field_task_records),
        "project_count": len(project_task_records),
        "source_profile_task_counts": _counts(task.get("source_profile_id") for task in field_task_records),
        "target_source_type_counts": _counts(
            source_type for task in field_task_records for source_type in _list(task.get("target_source_types"))
        ),
        "readback_ready_count": sum(1 for task in field_task_records if bool(task.get("readback_ready"))),
        "keyword_hit_task_count": sum(
            1 for task in field_task_records if str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE"
        ),
        "delegated_task_count": sum(
            1 for task in field_task_records if str(task.get("field_query_probe_state") or "") == "DELEGATED_TO_SEPARATE_FIELD_ADAPTER"
        ),
        "review_required_count": sum(
            1 for task in field_task_records if str(task.get("field_query_probe_state") or "") == "NO_FIELD_MATCH_REVIEW_REQUIRED"
        ),
        "fail_closed_count": sum(
            1 for task in field_task_records if str(task.get("field_query_probe_state") or "").startswith("FAIL_CLOSED")
        ),
        "field_query_probe_state_counts": _counts(task.get("field_query_probe_state") for task in field_task_records),
        "field_readback_state_counts": _counts(task.get("field_readback_state") for task in field_task_records),
        "blocker_taxonomy_counts": _counts(
            blocker for task in field_task_records for blocker in _list(task.get("blocker_taxonomy"))
        ),
        "delegated_adapter_counts": _counts(task.get("delegated_adapter_id") for task in field_task_records),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _cache_key(task: Mapping[str, Any], route_plan: list[Mapping[str, Any]]) -> str:
    return _fingerprint(
        {
            "profile": task.get("source_profile_id"),
            "source": task.get("source_url"),
            "query": task.get("query_params"),
            "routes": [route.get("url") for route in route_plan],
        }
    )


def _http_timeout_seconds() -> int:
    try:
        return max(3, min(30, int(os.environ.get("KAKA_GD_LOCAL_FIELD_HTTP_TIMEOUT_SECONDS", "8"))))
    except ValueError:
        return 8


def _decode_probe(body: bytes, content_type: str) -> str:
    if not body:
        return ""
    lowered = content_type.lower()
    encodings = ["gb18030", "utf-8"] if "charset=gb" in lowered else ["utf-8", "gb18030"]
    for encoding in encodings:
        try:
            return body.decode(encoding, errors="ignore")[:8000]
        except LookupError:
            continue
    return body.decode("utf-8", errors="ignore")[:8000]


def _clean_project_title(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in ("中标候选人公示", "中标结果公示", "中标结果公告", "招标公告", "招标文件", "资格审查结果公示"):
        text = text.replace(suffix, "")
    return " ".join(text.split()).strip(" -_，,。")


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            counts[text] = counts.get(text, 0) + 1
    return counts


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _normalize_filter(values: Iterable[str] | None) -> set[str]:
    return {str(value or "").strip().upper() for value in (values or []) if str(value or "").strip()}


def _first_text(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _copy_jsonable(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, default=str))


def _sha256_text(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint([str(part or '') for part in parts])[:16]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangdong Local FieldQueryProbe v1.")
    parser.add_argument("--local-verification-root", default=str(DEFAULT_LOCAL_VERIFICATION_ROOT))
    parser.add_argument("--local-verification-json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--source-profile-ids", nargs="*", default=[])
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--max-live-tasks", type=int)
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangdong_local_field_query_probe(
        local_verification_root=args.local_verification_root,
        local_verification_json=args.local_verification_json,
        output_root=args.output_root,
        source_profile_ids=args.source_profile_ids,
        enable_live_public_query=args.enable_live_public_query,
        max_live_tasks=args.max_live_tasks,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
