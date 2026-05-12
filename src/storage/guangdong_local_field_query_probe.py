from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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

GUANGZHOU_ZFCJ_PROFILE_ID = "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"
GUANGZHOU_ZFCJ_XYXX_API_URL = "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/xyxxzhlb.ashx"
GUANGZHOU_ZFCJ_XYXX_DETAIL_API_URL = "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/xyxxxxxx.ashx"
GUANGZHOU_ZFCJ_XYXX_DETAIL_PAGE_URL = "https://zfcj.gz.gov.cn/zfcj/xyxx/xyxxDetails/index.html"
GUANGDONG_GDCIC_HOME_PROFILE_ID = "GUANGDONG-GDCIC-HOME"
GUANGDONG_GDCIC_HOME_BASE_URL = "http://210.76.80.152:8008"
GUANGDONG_GDCIC_PERFORMANCE_PUBLIC_URL = (
    f"{GUANGDONG_GDCIC_HOME_BASE_URL}/JG/Information/PerformanceEvaluationProject/Indexgs"
)
GUANGDONG_GDCIC_CONTRACT_SYSTEM_URL = (
    f"{GUANGDONG_GDCIC_HOME_BASE_URL}/JG/home/Indexht"
)
GUANGDONG_ZFCXJST_PENALTY_PROFILE_ID = "GUANGDONG-ZFCXJST-PENALTY-PUBLICITY"
GUANGDONG_ZFCXJST_GSGG_BASE_URL = "https://zfcxjst.gd.gov.cn/xxgk/gsgg/"
GUANGDONG_ZFCXJST_SITE_SEARCH_URL = "https://search.gd.gov.cn/search/all/233"
GUANGDONG_TZXM_PROFILE_ID = "GUANGDONG-TZXM-HOME"
GUANGDONG_TZXM_BASE_URL = "https://tzxm.gd.gov.cn"
GUANGDONG_TZXM_PUBLICITY_URL = f"{GUANGDONG_TZXM_BASE_URL}/PublicityInformation/PublicityHandlingResults.html"
GUANGDONG_TZXM_API_BASE_URL = f"{GUANGDONG_TZXM_BASE_URL}/tzxmspweb/api/publicityInformation"
GUANGDONG_CREDIT_GD_PROFILE_ID = "GUANGDONG-CREDIT-GD-HOME"
GUANGDONG_CREDIT_GD_BASE_URL = "https://credit.gd.gov.cn"
GUANGDONG_CREDIT_GD_QUERY_URL = (
    f"{GUANGDONG_CREDIT_GD_BASE_URL}/company/web/booleanQueryListByPageSimple"
)
GUANGDONG_CREDIT_GD_PENALTY_PAGE_URL = f"{GUANGDONG_CREDIT_GD_BASE_URL}/page/creditPublic/xzcf.html"
GUANGDONG_CREDIT_GD_LICENSE_PAGE_URL = f"{GUANGDONG_CREDIT_GD_BASE_URL}/page/creditPublic/xzxk.html"

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
    if profile_id == GUANGZHOU_ZFCJ_PROFILE_ID:
        company_keyword = str(query_params.get("companyName") or "").strip()
        project_keyword = _clean_project_title(query_params.get("projectName"))
        person_keyword = str(query_params.get("personName") or "").strip()
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route("city_double_publicity_keyword_url", f"https://zfcj.gz.gov.cn/zfcj/xyxx/index.html?keywords={encoded}", "city_double_publicity_keyword_probe", keywords),
                _route("city_construction_permit_category", f"https://zfcj.gz.gov.cn/zfcj/xyxx/index.html?subcategory=1&keywords={encoded}", "city_double_publicity_permit_probe", keywords),
            ]
        )
        for route in (
            _guangzhou_zfcj_api_route(
                "gz_zfcj_xyxx_api_company_construction_permit",
                "gz_zfcj_xyxx_api_construction_permit",
                company_keyword,
                keywords,
                subcategory=1,
            ),
            _guangzhou_zfcj_api_route(
                "gz_zfcj_xyxx_api_project_construction_permit",
                "gz_zfcj_xyxx_api_construction_permit",
                project_keyword,
                keywords,
                subcategory=1,
            ),
            _guangzhou_zfcj_api_route(
                "gz_zfcj_xyxx_api_person_all_categories",
                "gz_zfcj_xyxx_api_all_categories",
                person_keyword,
                keywords,
                subcategory=0,
            ),
        ):
            if route:
                routes.append(route)
    elif profile_id == GUANGDONG_ZFCXJST_PENALTY_PROFILE_ID:
        company_keyword = str(query_params.get("companyName") or "").strip()
        person_keyword = str(query_params.get("personName") or "").strip()
        project_keyword = _clean_project_title(query_params.get("projectName"))
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _guangdong_zfcxjst_penalty_list_route(1, keywords),
                _guangdong_zfcxjst_penalty_list_route(2, keywords),
                *[
                    route
                    for route in (
                        _guangdong_zfcxjst_penalty_search_route(company_keyword, keywords),
                        _guangdong_zfcxjst_penalty_search_route(person_keyword, keywords),
                        _guangdong_zfcxjst_penalty_search_route(project_keyword, keywords),
                    )
                    if route
                ],
            ]
        )
    elif profile_id == GUANGDONG_CREDIT_GD_PROFILE_ID:
        company_keyword = str(query_params.get("companyName") or "").strip()
        person_keyword = str(query_params.get("personName") or "").strip()
        project_keyword = _clean_project_title(query_params.get("projectName"))
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route(
                    "credit_gd_search_page",
                    f"https://credit.gd.gov.cn/Search/index.html?keywords={encoded}",
                    "credit_gd_subject_search_probe",
                    keywords,
                ),
                _route(
                    "credit_gd_penalty_page",
                    f"{GUANGDONG_CREDIT_GD_PENALTY_PAGE_URL}?keywords={encoded}",
                    "credit_gd_penalty_page_probe",
                    keywords,
                ),
                _route(
                    "credit_gd_license_page",
                    f"{GUANGDONG_CREDIT_GD_LICENSE_PAGE_URL}?keywords={encoded}",
                    "credit_gd_license_page_probe",
                    keywords,
                ),
                _guangdong_credit_gd_list_route("penalty_recent_public_list", "penalty", keywords),
                _guangdong_credit_gd_list_route("license_recent_public_list", "license", keywords),
                *[
                    route
                    for route in (
                        _guangdong_credit_gd_query_route("penalty_company_query", "penalty", company_keyword, keywords),
                        _guangdong_credit_gd_query_route("penalty_person_query", "penalty", person_keyword, keywords),
                        _guangdong_credit_gd_query_route("penalty_project_query", "penalty", project_keyword, keywords),
                        _guangdong_credit_gd_query_route("license_company_query", "license", company_keyword, keywords),
                        _guangdong_credit_gd_query_route("license_person_query", "license", person_keyword, keywords),
                        _guangdong_credit_gd_query_route("license_project_query", "license", project_keyword, keywords),
                    )
                    if route
                ],
            ]
        )
    elif profile_id == GUANGDONG_TZXM_PROFILE_ID:
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route(
                    "investment_project_publicity_page",
                    GUANGDONG_TZXM_PUBLICITY_URL,
                    "investment_project_publicity_page_probe",
                    keywords,
                ),
                _route(
                    "investment_project_home_keyword",
                    f"https://tzxm.gd.gov.cn/?keywords={encoded}",
                    "investment_project_home_keyword_probe",
                    keywords,
                ),
                _guangdong_tzxm_publicity_list_route("ba", "1", "project_filing_publicity", keywords),
                _guangdong_tzxm_publicity_list_route("hz", "9", "project_approval_pre_publicity", keywords),
                _guangdong_tzxm_publicity_list_route("hz", "10", "project_approval_notice", keywords),
                _guangdong_tzxm_publicity_list_route("sp", "6", "project_review_pre_publicity", keywords),
                _guangdong_tzxm_publicity_list_route("sp", "7", "project_review_notice", keywords),
                _guangdong_tzxm_publicity_list_route("jn", "13", "energy_saving_review_notice", keywords),
            ]
        )
    elif profile_id == GUANGDONG_GDCIC_HOME_PROFILE_ID:
        company_keyword = str(query_params.get("companyName") or "").strip()
        project_keyword = _clean_project_title(query_params.get("projectName"))
        routes.extend(
            [
                _route("source_home", source_url, "source_home_probe", keywords),
                _route("gdcic_home_keyword", f"{source_url.rstrip('/')}?keywords={encoded}" if source_url else "", "gdcic_contract_performance_keyword_probe", keywords),
            ]
        )
        for route in (
            _guangdong_gdcic_home_performance_route(
                "gd_gdcic_performance_public_project",
                project_keyword,
                keywords,
            ),
            _guangdong_gdcic_home_performance_route(
                "gd_gdcic_performance_public_company",
                company_keyword,
                keywords,
            ),
            _guangdong_gdcic_home_contract_sso_route(keywords),
        ):
            if route:
                routes.append(route)
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


def _guangzhou_zfcj_api_route(
    route_id: str,
    route_group: str,
    keyword: str,
    query_keywords: list[str],
    *,
    subcategory: int,
) -> dict[str, Any] | None:
    keyword = str(keyword or "").strip()
    if not keyword:
        return None
    params = {
        "subcategory": subcategory,
        "keywords": keyword,
        "page": 1,
        "pageSize": 10,
    }
    return {
        "route_id": route_id,
        "route_group": route_group,
        "url": GUANGZHOU_ZFCJ_XYXX_API_URL,
        "method": "POST",
        "params": params,
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangzhou_zfcj_xyxx_api_query_v1",
    }


def _guangdong_gdcic_home_performance_route(
    route_id: str,
    keyword: str,
    query_keywords: list[str],
) -> dict[str, Any] | None:
    keyword = str(keyword or "").strip()
    if not keyword:
        return None
    params = {
        "pageCurrent": 1,
        "pageTotal": 5,
        "search_name": keyword,
    }
    return {
        "route_id": route_id,
        "route_group": "gd_gdcic_contract_performance_public_page",
        "url": GUANGDONG_GDCIC_PERFORMANCE_PUBLIC_URL,
        "method": "GET",
        "params": params,
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangdong_gdcic_contract_performance_public_page_v1",
    }


def _guangdong_gdcic_home_contract_sso_route(query_keywords: list[str]) -> dict[str, Any]:
    return {
        "route_id": "gd_gdcic_contract_system_sso_check",
        "route_group": "gd_gdcic_contract_system_login_check",
        "url": GUANGDONG_GDCIC_CONTRACT_SYSTEM_URL,
        "method": "GET",
        "params": {"RequestMethod": 1, "SysType": 2},
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangdong_gdcic_contract_performance_public_page_v1",
    }


def _guangdong_zfcxjst_penalty_list_route(page: int, query_keywords: list[str]) -> dict[str, Any]:
    suffix = "index.html" if page <= 1 else f"index_{page}.html"
    return {
        "route_id": f"gd_zfcxjst_penalty_list_page_{page}",
        "route_group": "gd_zfcxjst_penalty_publicity_list",
        "url": urllib.parse.urljoin(GUANGDONG_ZFCXJST_GSGG_BASE_URL, suffix),
        "method": "GET",
        "params": {},
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangdong_zfcxjst_penalty_publicity_page_v1",
    }


def _guangdong_zfcxjst_penalty_search_route(
    keyword: str,
    query_keywords: list[str],
) -> dict[str, Any] | None:
    keyword = str(keyword or "").strip()
    if not keyword:
        return None
    return {
        "route_id": f"gd_zfcxjst_penalty_site_search_{_sha256_text(keyword)[:8]}",
        "route_group": "gd_zfcxjst_penalty_site_search",
        "url": GUANGDONG_ZFCXJST_SITE_SEARCH_URL,
        "method": "GET",
        "params": {
            "keywords": keyword,
            "sort": "time",
            "position": "all",
            "time": "5year",
        },
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangdong_zfcxjst_penalty_publicity_page_v1",
    }


def _guangdong_tzxm_publicity_list_route(
    audit: str,
    flag: str,
    route_kind: str,
    query_keywords: list[str],
) -> dict[str, Any]:
    endpoint_by_audit = {
        "ba": "selectByPageBA",
        "hz": "selectHzByPage",
        "sp": "selectByPageSP",
        "jn": "selectJnscByPage",
    }
    endpoint = endpoint_by_audit[audit]
    return {
        "route_id": f"gd_tzxm_{route_kind}_page_1",
        "route_group": "gd_tzxm_publicity_list",
        "url": f"{GUANGDONG_TZXM_API_BASE_URL}/{endpoint}",
        "method": "POST",
        "json_body": True,
        "params": {
            "flag": flag,
            "pageSize": 20,
            "pageNumber": 1,
        },
        "tzxm_audit": audit,
        "tzxm_flag": flag,
        "tzxm_route_kind": route_kind,
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangdong_tzxm_project_approval_publicity_api_v1",
    }


def _guangdong_credit_gd_list_route(
    route_id: str,
    record_type: str,
    query_keywords: list[str],
) -> dict[str, Any]:
    table_name, order_args, referer = _guangdong_credit_gd_table_config(record_type)
    return {
        "route_id": f"gd_credit_gd_{route_id}",
        "route_group": "gd_credit_gd_public_credit_list",
        "url": GUANGDONG_CREDIT_GD_QUERY_URL,
        "method": "POST",
        "form_body": True,
        "referer": referer,
        "params": {
            "tableName": table_name,
            "page": 1,
            "rows": 20,
            "orderArgs": json.dumps(order_args, ensure_ascii=False),
        },
        "credit_gd_record_type": record_type,
        "targeted_query": False,
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangdong_credit_gd_public_credit_query_v1",
    }


def _guangdong_credit_gd_query_route(
    route_id: str,
    record_type: str,
    keyword: str,
    query_keywords: list[str],
) -> dict[str, Any] | None:
    keyword = str(keyword or "").strip()
    if not keyword:
        return None
    table_name, order_args, referer = _guangdong_credit_gd_table_config(record_type)
    query_key = "cf_xdr_mc_qkh" if record_type == "penalty" else "xk_xdr_mc_qkh"
    if route_id.endswith("_person_query") or route_id.endswith("_project_query"):
        query_key = "cf_wsh_qkh" if record_type == "penalty" else "xk_wsh_qkh"
    return {
        "route_id": f"gd_credit_gd_{route_id}_{_sha256_text(keyword)[:8]}",
        "route_group": "gd_credit_gd_public_credit_targeted_query",
        "url": GUANGDONG_CREDIT_GD_QUERY_URL,
        "method": "POST",
        "form_body": True,
        "referer": referer,
        "params": {
            "tableName": table_name,
            "page": 1,
            "rows": 20,
            "orderArgs": json.dumps(order_args, ensure_ascii=False),
            "jsonArgs": json.dumps({query_key: f"like;{keyword}"}, ensure_ascii=False),
        },
        "credit_gd_record_type": record_type,
        "targeted_query": True,
        "targeted_query_keyword": keyword,
        "keyword_count": len(query_keywords),
        "query_keyword_probe": query_keywords[:5],
        "source_specific_adapter_id": "guangdong_credit_gd_public_credit_query_v1",
    }


def _guangdong_credit_gd_table_config(record_type: str) -> tuple[str, list[dict[str, str]], str]:
    if record_type == "license":
        return (
            "v_ztk_03_sgs_xzxk,V_XYDAK_SGS_2018XZXKXX",
            [{"xk_jdrq_sort": "desc"}],
            GUANGDONG_CREDIT_GD_LICENSE_PAGE_URL,
        )
    return (
        "v_ztk_03_sgs_xzcf",
        [{"cf_jdrq_sort": "desc"}],
        GUANGDONG_CREDIT_GD_PENALTY_PAGE_URL,
    )


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
    if any(
        str(route.get("source_specific_adapter_id") or "") == "guangzhou_zfcj_xyxx_api_query_v1"
        for route in route_plan
    ):
        return _execute_guangzhou_zfcj_field_query(task, route_plan, http_getter=http_getter)
    if any(
        str(route.get("source_specific_adapter_id") or "")
        == "guangdong_gdcic_contract_performance_public_page_v1"
        for route in route_plan
    ):
        return _execute_guangdong_gdcic_home_field_query(task, route_plan, http_getter=http_getter)
    if any(
        str(route.get("source_specific_adapter_id") or "")
        == "guangdong_zfcxjst_penalty_publicity_page_v1"
        for route in route_plan
    ):
        return _execute_guangdong_zfcxjst_penalty_field_query(task, route_plan, http_getter=http_getter)
    if any(
        str(route.get("source_specific_adapter_id") or "")
        == "guangdong_tzxm_project_approval_publicity_api_v1"
        for route in route_plan
    ):
        return _execute_guangdong_tzxm_field_query(task, route_plan, http_getter=http_getter)
    if any(
        str(route.get("source_specific_adapter_id") or "")
        == "guangdong_credit_gd_public_credit_query_v1"
        for route in route_plan
    ):
        return _execute_guangdong_credit_gd_field_query(task, route_plan, http_getter=http_getter)
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
        return dict(getter(str(route.get("url") or ""), _request_params_for_route(route)))
    except Exception as exc:  # pragma: no cover - defensive guard for external routes.
        return {
            "http_status": None,
            "content_type": "",
            "text_probe": "",
            "transport_error": type(exc).__name__,
        }


def _request_params_for_route(route: Mapping[str, Any]) -> dict[str, Any]:
    params = dict(route.get("params") or {})
    if route.get("method"):
        params["_method"] = str(route.get("method") or "GET").upper()
    if route.get("json_body"):
        params["_json_body"] = True
    if route.get("form_body"):
        params["_form_body"] = True
    if route.get("referer"):
        params["_referer"] = str(route.get("referer") or "")
    if route.get("route_id"):
        params["_route_id"] = str(route.get("route_id") or "")
    if route.get("route_group"):
        params["_route_group"] = str(route.get("route_group") or "")
    return params


def _default_http_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
    request_params = {key: value for key, value in dict(params or {}).items() if not str(key).startswith("_")}
    method = str((params or {}).get("_method") or "GET").upper()
    json_body = bool((params or {}).get("_json_body"))
    form_body = bool((params or {}).get("_form_body"))
    request_url = url
    data = None
    if method == "POST" and json_body:
        data = json.dumps(request_params, ensure_ascii=False).encode("utf-8")
    elif method == "POST" and form_body:
        data = urllib.parse.urlencode(request_params).encode("utf-8")
    elif request_params:
        request_url = f"{url}?{urllib.parse.urlencode(request_params)}"
    if method == "POST" and data is None:
        data = b""
    request = urllib.request.Request(
        request_url,
        data=data,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": str((params or {}).get("_referer") or "https://zfcj.gz.gov.cn/zfcj/xyxx/"),
            "X-Requested-With": "XMLHttpRequest",
            **({"Content-Type": "application/json;charset=utf-8"} if method == "POST" and json_body else {}),
            **(
                {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
                if method == "POST" and form_body
                else {}
            ),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=_http_timeout_seconds()) as response:  # noqa: S310
            body = response.read(80_000)
            content_type = response.headers.get("Content-Type", "")
            text = _decode_probe(body, content_type)
            return {
                "http_status": response.getcode(),
                "content_type": content_type,
                "text_probe": text,
                "json_payload": _loads_json_or_empty(text),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(4096) if hasattr(exc, "read") else b""
        text = _decode_probe(body, exc.headers.get("Content-Type", "") if exc.headers else "")
        return {
            "http_status": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "text_probe": text,
            "json_payload": _loads_json_or_empty(text),
        }


def _execute_guangzhou_zfcj_field_query(
    task: Mapping[str, Any],
    route_plan: list[Mapping[str, Any]],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    getter = http_getter or _default_http_getter
    query_params = dict(task.get("query_params") or {})
    keywords = _query_keywords(query_params)
    attempts: list[dict[str, Any]] = []
    field_records: list[dict[str, Any]] = []
    generic_match_records: list[dict[str, Any]] = []
    detail_ready_count = 0
    for route in route_plan:
        response = _safe_get(route, getter=getter)
        attempt = _route_attempt(route, response, keywords)
        if attempt["keyword_hit_count"]:
            generic_match_records.append(
                {
                    "route_id": attempt["route_id"],
                    "url": attempt["url"],
                    "matched_keywords": attempt["matched_keywords"],
                    "source_text_sha256": attempt["text_probe_sha256"],
                }
            )
        records = _guangzhou_zfcj_records_from_response(response)
        if records:
            attempt["json_record_count"] = len(records)
        attempts.append(attempt)
        if not records:
            continue
        for record in records[:5]:
            compact = _compact_guangzhou_zfcj_record(record, keywords)
            detail_route = _guangzhou_zfcj_detail_route(record, keywords)
            if detail_route:
                detail_response = _safe_get(detail_route, getter=getter)
                detail_attempt = _route_attempt(detail_route, detail_response, keywords)
                detail_records = _guangzhou_zfcj_records_from_response(detail_response)
                detail_attempt["json_record_count"] = len(detail_records)
                attempts.append(detail_attempt)
                detail = _compact_guangzhou_zfcj_detail(_first_mapping(detail_records))
                if detail:
                    detail_ready_count += 1
                    compact["detail_readback"] = detail
                    compact["detail_text_sha256"] = _sha256_text(json.dumps(detail, ensure_ascii=False, sort_keys=True))
            field_records.append(compact)

    blockers = _dedupe(blocker for attempt in attempts for blocker in _list(attempt.get("blocker_taxonomy")))
    status_codes = [_int(attempt.get("http_status")) for attempt in attempts if _int(attempt.get("http_status"))]
    matched_keyword_count = len(
        _dedupe(keyword for record in field_records for keyword in _list(record.get("matched_keywords")))
    )
    if field_records:
        return {
            "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": {
                "source_specific_adapter_id": "guangzhou_zfcj_xyxx_api_query_v1",
                "record_count": len(field_records),
                "detail_readback_count": detail_ready_count,
                "matched_keyword_count": matched_keyword_count,
                "source_profile_keyword_hit": bool(matched_keyword_count),
                "source_profile_id": GUANGZHOU_ZFCJ_PROFILE_ID,
            },
            "field_match_summary": {
                "source_specific_records": field_records[:10],
                "query_miss_is_not_clearance": True,
                "readback_is_line_clue_not_final_conclusion": True,
            },
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers,
        }
    if generic_match_records:
        return {
            "field_query_probe_state": "FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_KEYWORD_HIT_REVIEW_REQUIRED",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": {
                "source_specific_adapter_id": "guangzhou_zfcj_xyxx_api_query_v1",
                "record_count": 0,
                "keyword_hit_route_count": len(generic_match_records),
                "matched_keyword_count": len(
                    _dedupe(keyword for row in generic_match_records for keyword in row["matched_keywords"])
                ),
                "source_profile_keyword_hit": True,
            },
            "field_match_summary": {
                "match_records": generic_match_records[:10],
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
            "field_summary": {"source_specific_adapter_id": "guangzhou_zfcj_xyxx_api_query_v1"},
            "field_match_summary": {"query_miss_is_not_clearance": True},
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers or ["guangzhou_zfcj_xyxx_api_all_routes_blocked"],
        }
    return {
        "field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
        "field_readback_state": "PUBLIC_SOURCE_QUERIED_NO_FIELD_RECORD",
        "readback_ready": False,
        "readback_status_code": status_codes[0] if status_codes else None,
        "field_summary": {
            "source_specific_adapter_id": "guangzhou_zfcj_xyxx_api_query_v1",
            "record_count": 0,
            "source_profile_keyword_hit": False,
        },
        "field_match_summary": {
            "query_miss_is_not_clearance": True,
            "readback_is_line_clue_not_final_conclusion": True,
        },
        "route_plan": list(route_plan),
        "route_attempts": attempts,
        "blocker_taxonomy": blockers or ["guangzhou_zfcj_xyxx_api_no_record_review"],
    }


def _execute_guangdong_gdcic_home_field_query(
    task: Mapping[str, Any],
    route_plan: list[Mapping[str, Any]],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    getter = http_getter or _default_http_getter
    query_params = dict(task.get("query_params") or {})
    keywords = _query_keywords(query_params)
    attempts: list[dict[str, Any]] = []
    performance_records: list[dict[str, Any]] = []
    sso_route_seen = False
    for route in route_plan:
        response = _safe_get(route, getter=getter)
        attempt = _route_attempt(route, response, keywords)
        route_group = str(route.get("route_group") or "")
        text = str(response.get("text_probe") or response.get("body_probe") or "")
        if route_group == "gd_gdcic_contract_system_login_check":
            sso_route_seen = True
            if "SSO/jrsso/auth" in text or "UniteLogin" in text:
                attempt["route_state"] = "FAIL_CLOSED_LOGIN_OR_SSO_REQUIRED"
                attempt["blocker_taxonomy"] = _dedupe(
                    [
                        *attempt.get("blocker_taxonomy", []),
                        "gd_gdcic_contract_system_sso_login_required",
                    ]
                )
        records = _guangdong_gdcic_performance_records_from_html(text, keywords)
        if records:
            attempt["html_record_count"] = len(records)
            performance_records.extend(records[:5])
        attempts.append(attempt)

    blockers = _dedupe(blocker for attempt in attempts for blocker in _list(attempt.get("blocker_taxonomy")))
    status_codes = [_int(attempt.get("http_status")) for attempt in attempts if _int(attempt.get("http_status"))]
    matched_keyword_count = len(
        _dedupe(keyword for record in performance_records for keyword in _list(record.get("matched_keywords")))
    )
    if performance_records:
        return {
            "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": {
                "source_specific_adapter_id": "guangdong_gdcic_contract_performance_public_page_v1",
                "record_count": len(performance_records),
                "matched_keyword_count": matched_keyword_count,
                "source_profile_keyword_hit": bool(matched_keyword_count),
                "source_profile_id": GUANGDONG_GDCIC_HOME_PROFILE_ID,
                "contract_system_sso_route_seen": sso_route_seen,
            },
            "field_match_summary": {
                "source_specific_records": performance_records[:10],
                "query_miss_is_not_clearance": True,
                "readback_is_line_clue_not_final_conclusion": True,
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
            "field_summary": {
                "source_specific_adapter_id": "guangdong_gdcic_contract_performance_public_page_v1",
                "contract_system_sso_route_seen": sso_route_seen,
            },
            "field_match_summary": {"query_miss_is_not_clearance": True},
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers or ["gd_gdcic_contract_performance_all_routes_blocked"],
        }
    return {
        "field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
        "field_readback_state": "PUBLIC_SOURCE_QUERIED_NO_FIELD_RECORD",
        "readback_ready": False,
        "readback_status_code": status_codes[0] if status_codes else None,
        "field_summary": {
            "source_specific_adapter_id": "guangdong_gdcic_contract_performance_public_page_v1",
            "record_count": 0,
            "source_profile_keyword_hit": False,
            "contract_system_sso_route_seen": sso_route_seen,
        },
        "field_match_summary": {
            "query_miss_is_not_clearance": True,
            "readback_is_line_clue_not_final_conclusion": True,
        },
        "route_plan": list(route_plan),
        "route_attempts": attempts,
        "blocker_taxonomy": blockers or ["gd_gdcic_contract_performance_public_no_record_review"],
    }


def _execute_guangdong_zfcxjst_penalty_field_query(
    task: Mapping[str, Any],
    route_plan: list[Mapping[str, Any]],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    getter = http_getter or _default_http_getter
    query_params = dict(task.get("query_params") or {})
    keywords = _query_keywords(query_params)
    attempts: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for route in route_plan:
        response = _safe_get(route, getter=getter)
        attempt = _route_attempt(route, response, keywords)
        text = str(response.get("text_probe") or response.get("body_probe") or "")
        candidate_links = _guangdong_zfcxjst_penalty_links_from_html(text, str(route.get("url") or ""))
        if candidate_links:
            attempt["html_candidate_link_count"] = len(candidate_links)
        attempts.append(attempt)
        for link in candidate_links[:8]:
            detail_url = str(link.get("url") or "")
            if not detail_url or detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)
            title = str(link.get("title") or "")
            title_match = [keyword for keyword in keywords if keyword and keyword in title]
            if not title_match and not _looks_like_penalty_title(title):
                continue
            detail_route = {
                "route_id": f"gd_zfcxjst_penalty_detail_{_sha256_text(detail_url)[:8]}",
                "route_group": "gd_zfcxjst_penalty_detail_page",
                "url": detail_url,
                "method": "GET",
                "params": {},
                "keyword_count": len(keywords),
                "query_keyword_probe": keywords[:5],
                "source_specific_adapter_id": "guangdong_zfcxjst_penalty_publicity_page_v1",
            }
            detail_response = _safe_get(detail_route, getter=getter)
            detail_attempt = _route_attempt(detail_route, detail_response, keywords)
            detail_text = str(detail_response.get("text_probe") or detail_response.get("body_probe") or "")
            detail_record = _guangdong_zfcxjst_penalty_record_from_detail(
                detail_text,
                detail_url=detail_url,
                fallback_title=title,
                keywords=keywords,
            )
            if detail_record:
                detail_attempt["penalty_record_ready"] = True
                source_records.append(detail_record)
            attempts.append(detail_attempt)

    blockers = _dedupe(blocker for attempt in attempts for blocker in _list(attempt.get("blocker_taxonomy")))
    status_codes = [_int(attempt.get("http_status")) for attempt in attempts if _int(attempt.get("http_status"))]
    matched_keyword_count = len(
        _dedupe(keyword for record in source_records for keyword in _list(record.get("matched_keywords")))
    )
    if source_records:
        return {
            "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": {
                "source_specific_adapter_id": "guangdong_zfcxjst_penalty_publicity_page_v1",
                "record_count": len(source_records),
                "matched_keyword_count": matched_keyword_count,
                "source_profile_keyword_hit": bool(matched_keyword_count),
                "source_profile_id": GUANGDONG_ZFCXJST_PENALTY_PROFILE_ID,
                "record_type": "administrative_penalty_or_supervision_notice",
            },
            "field_match_summary": {
                "source_specific_records": source_records[:10],
                "query_miss_is_not_clearance": True,
                "readback_is_line_clue_not_final_conclusion": True,
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
            "field_summary": {
                "source_specific_adapter_id": "guangdong_zfcxjst_penalty_publicity_page_v1",
            },
            "field_match_summary": {"query_miss_is_not_clearance": True},
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers or ["gd_zfcxjst_penalty_publicity_all_routes_blocked"],
        }
    return {
        "field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
        "field_readback_state": "PUBLIC_SOURCE_QUERIED_NO_FIELD_RECORD",
        "readback_ready": False,
        "readback_status_code": status_codes[0] if status_codes else None,
        "field_summary": {
            "source_specific_adapter_id": "guangdong_zfcxjst_penalty_publicity_page_v1",
            "record_count": 0,
            "source_profile_keyword_hit": False,
        },
        "field_match_summary": {
            "query_miss_is_not_clearance": True,
            "readback_is_line_clue_not_final_conclusion": True,
        },
        "route_plan": list(route_plan),
        "route_attempts": attempts,
        "blocker_taxonomy": blockers or ["gd_zfcxjst_penalty_publicity_no_record_review"],
    }


def _execute_guangdong_tzxm_field_query(
    task: Mapping[str, Any],
    route_plan: list[Mapping[str, Any]],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    getter = http_getter or _default_http_getter
    query_params = dict(task.get("query_params") or {})
    keywords = _query_keywords(query_params)
    attempts: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []

    for route in route_plan:
        response = _safe_get(route, getter=getter)
        attempt = _route_attempt(route, response, keywords)
        route_group = str(route.get("route_group") or "")
        if route_group != "gd_tzxm_publicity_list":
            _suppress_tzxm_navigation_login_noise(attempt)
            attempts.append(attempt)
            continue
        records = _guangdong_tzxm_records_from_response(response)
        attempt["json_record_count"] = len(records)
        attempts.append(attempt)
        for record in records[:20]:
            compact = _compact_guangdong_tzxm_record(record, route, keywords)
            if not compact.get("matched_keywords"):
                continue
            detail_route = _guangdong_tzxm_detail_route(record, route, keywords)
            if detail_route:
                detail_response = _safe_get(detail_route, getter=getter)
                detail_attempt = _route_attempt(detail_route, detail_response, keywords)
                detail_records = _guangdong_tzxm_records_from_response(detail_response)
                detail_attempt["json_record_count"] = len(detail_records)
                detail = _compact_guangdong_tzxm_detail(
                    _first_mapping(detail_records),
                    route,
                    keywords,
                )
                if detail:
                    compact["detail_readback"] = detail
                    compact["detail_text_sha256"] = _sha256_text(json.dumps(detail, ensure_ascii=False, sort_keys=True))
                    detail_attempt["tzxm_detail_readback_ready"] = True
                attempts.append(detail_attempt)
            source_records.append(compact)

    blockers = _dedupe(blocker for attempt in attempts for blocker in _list(attempt.get("blocker_taxonomy")))
    status_codes = [_int(attempt.get("http_status")) for attempt in attempts if _int(attempt.get("http_status"))]
    matched_keyword_count = len(
        _dedupe(keyword for record in source_records for keyword in _list(record.get("matched_keywords")))
    )
    if source_records:
        return {
            "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": {
                "source_specific_adapter_id": "guangdong_tzxm_project_approval_publicity_api_v1",
                "record_count": len(source_records),
                "matched_keyword_count": matched_keyword_count,
                "source_profile_keyword_hit": bool(matched_keyword_count),
                "source_profile_id": GUANGDONG_TZXM_PROFILE_ID,
                "record_type": "investment_project_approval_or_filing_publicity",
            },
            "field_match_summary": {
                "source_specific_records": source_records[:10],
                "query_miss_is_not_clearance": True,
                "readback_is_line_clue_not_final_conclusion": True,
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
            "field_summary": {
                "source_specific_adapter_id": "guangdong_tzxm_project_approval_publicity_api_v1",
            },
            "field_match_summary": {"query_miss_is_not_clearance": True},
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers or ["gd_tzxm_project_approval_all_routes_blocked"],
        }
    return {
        "field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
        "field_readback_state": "PUBLIC_SOURCE_QUERIED_NO_FIELD_RECORD",
        "readback_ready": False,
        "readback_status_code": status_codes[0] if status_codes else None,
        "field_summary": {
            "source_specific_adapter_id": "guangdong_tzxm_project_approval_publicity_api_v1",
            "record_count": 0,
            "source_profile_keyword_hit": False,
        },
        "field_match_summary": {
            "query_miss_is_not_clearance": True,
            "readback_is_line_clue_not_final_conclusion": True,
        },
        "route_plan": list(route_plan),
        "route_attempts": attempts,
        "blocker_taxonomy": blockers or ["gd_tzxm_project_approval_no_record_review"],
    }


def _execute_guangdong_credit_gd_field_query(
    task: Mapping[str, Any],
    route_plan: list[Mapping[str, Any]],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    getter = http_getter or _default_http_getter
    query_params = dict(task.get("query_params") or {})
    keywords = _query_keywords(query_params)
    attempts: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []

    for route in route_plan:
        response = _safe_get(route, getter=getter)
        attempt = _route_attempt(route, response, keywords)
        if str(route.get("source_specific_adapter_id") or "") != "guangdong_credit_gd_public_credit_query_v1":
            attempts.append(attempt)
            continue
        if _int(response.get("http_status")) == 404:
            blockers = _list(attempt.get("blocker_taxonomy"))
            blockers.append("gd_credit_gd_interface_endpoint_not_found_or_stale")
            attempt["blocker_taxonomy"] = _dedupe(blockers)
            attempt["route_state"] = "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED"
        if _int(response.get("http_status")) in {401, 403} or _looks_like_captcha_or_login(
            str(response.get("text_probe") or response.get("body_probe") or "")
        ):
            blockers = _list(attempt.get("blocker_taxonomy"))
            blockers.append("gd_credit_gd_waf_or_captcha_required")
            attempt["blocker_taxonomy"] = _dedupe(blockers)
            attempt["route_state"] = "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED"
        records = _guangdong_credit_gd_records_from_response(response)
        attempt["json_record_count"] = len(records)
        attempts.append(attempt)
        for record in records[:20]:
            compact = _compact_guangdong_credit_gd_record(record, route, keywords)
            if not compact.get("matched_keywords"):
                continue
            source_records.append(compact)

    blockers = _dedupe(blocker for attempt in attempts for blocker in _list(attempt.get("blocker_taxonomy")))
    status_codes = [_int(attempt.get("http_status")) for attempt in attempts if _int(attempt.get("http_status"))]
    matched_keyword_count = len(
        _dedupe(keyword for record in source_records for keyword in _list(record.get("matched_keywords")))
    )
    if source_records:
        return {
            "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": {
                "source_specific_adapter_id": "guangdong_credit_gd_public_credit_query_v1",
                "record_count": len(source_records),
                "matched_keyword_count": matched_keyword_count,
                "source_profile_keyword_hit": bool(matched_keyword_count),
                "source_profile_id": GUANGDONG_CREDIT_GD_PROFILE_ID,
                "record_type": "credit_public_penalty_or_license_record",
            },
            "field_match_summary": {
                "source_specific_records": source_records[:10],
                "query_miss_is_not_clearance": True,
                "readback_is_line_clue_not_final_conclusion": True,
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
            "field_summary": {
                "source_specific_adapter_id": "guangdong_credit_gd_public_credit_query_v1",
            },
            "field_match_summary": {"query_miss_is_not_clearance": True},
            "route_plan": list(route_plan),
            "route_attempts": attempts,
            "blocker_taxonomy": blockers or ["gd_credit_gd_public_credit_all_routes_blocked"],
        }
    return {
        "field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
        "field_readback_state": "PUBLIC_SOURCE_QUERIED_NO_FIELD_RECORD",
        "readback_ready": False,
        "readback_status_code": status_codes[0] if status_codes else None,
        "field_summary": {
            "source_specific_adapter_id": "guangdong_credit_gd_public_credit_query_v1",
            "record_count": 0,
            "source_profile_keyword_hit": False,
        },
        "field_match_summary": {
            "query_miss_is_not_clearance": True,
            "readback_is_line_clue_not_final_conclusion": True,
        },
        "route_plan": list(route_plan),
        "route_attempts": attempts,
        "blocker_taxonomy": blockers or ["gd_credit_gd_public_credit_no_record_review"],
    }


def _suppress_tzxm_navigation_login_noise(attempt: dict[str, Any]) -> None:
    if _int(attempt.get("http_status")) != 200:
        return
    route_group = str(attempt.get("route_group") or "")
    if route_group not in {
        "source_home_probe",
        "investment_project_publicity_page_probe",
        "investment_project_home_keyword_probe",
    }:
        return
    blockers = _list(attempt.get("blocker_taxonomy"))
    if blockers == ["guangdong_local_field_query_captcha_or_login_required"]:
        attempt["route_state"] = "PUBLIC_SOURCE_QUERIED"
        attempt["blocker_taxonomy"] = []
        attempt["navigation_login_text_suppressed"] = True


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


def _loads_json_or_empty(text: str) -> Any:
    probe = str(text or "").strip()
    if not probe or probe[0] not in "[{":
        return {}
    try:
        return json.loads(probe)
    except json.JSONDecodeError:
        return {}


def _json_payload(response: Mapping[str, Any]) -> Any:
    payload = response.get("json_payload")
    if isinstance(payload, (Mapping, list)):
        return payload
    return _loads_json_or_empty(str(response.get("text_probe") or response.get("body_probe") or ""))


def _guangzhou_zfcj_records_from_response(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payload = _json_payload(response)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if isinstance(data, Mapping):
        return [data]
    for key in ("rows", "items", "list", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
    return []


def _compact_guangzhou_zfcj_record(record: Mapping[str, Any], keywords: list[str]) -> dict[str, Any]:
    info_id = str(record.get("infoId") or record.get("infoid") or "").strip()
    subcategory = str(record.get("subCategory") or record.get("subcategory") or "").strip()
    info_name = str(record.get("infoName") or record.get("infoname") or record.get("xmmc") or "").strip()
    info_date = str(record.get("infoDate") or record.get("jdrq") or "").strip()
    return {
        "info_id": info_id,
        "subcategory": subcategory,
        "info_name_probe": info_name[:500],
        "info_date": info_date,
        "row_num": str(record.get("rowNum") or ""),
        "detail_url": _guangzhou_zfcj_detail_page_url(info_id, subcategory),
        "matched_keywords": [keyword for keyword in keywords if keyword and keyword in info_name][:10],
        "record_sha256": _sha256_text(json.dumps(dict(record), ensure_ascii=False, sort_keys=True, default=str)),
    }


def _compact_guangzhou_zfcj_detail(record: Mapping[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    fields = {
        "document_no": record.get("wsh"),
        "project_name": record.get("xmmc"),
        "approval_category": record.get("splb"),
        "license_content": record.get("xknr"),
        "administrative_counterparty": record.get("xdrmc"),
        "decision_date": record.get("jdrq"),
        "licensing_authority": record.get("xkjg"),
        "current_status": record.get("dqzt"),
        "credit_code": record.get("xydm"),
    }
    return {
        key: str(value or "").strip()[:500]
        for key, value in fields.items()
        if str(value or "").strip()
    }


def _guangzhou_zfcj_detail_route(record: Mapping[str, Any], keywords: list[str]) -> dict[str, Any] | None:
    info_id = str(record.get("infoId") or record.get("infoid") or "").strip()
    subcategory = str(record.get("subCategory") or record.get("subcategory") or "").strip()
    if not info_id or not subcategory:
        return None
    return {
        "route_id": f"gz_zfcj_xyxx_detail_api_{info_id[:8]}",
        "route_group": "gz_zfcj_xyxx_detail_api",
        "url": GUANGZHOU_ZFCJ_XYXX_DETAIL_API_URL,
        "method": "POST",
        "params": {"infoid": info_id, "subcategory": subcategory},
        "keyword_count": len(keywords),
        "query_keyword_probe": keywords[:5],
        "source_specific_adapter_id": "guangzhou_zfcj_xyxx_api_query_v1",
    }


def _guangzhou_zfcj_detail_page_url(info_id: str, subcategory: str) -> str:
    if not info_id or not subcategory:
        return ""
    return f"{GUANGZHOU_ZFCJ_XYXX_DETAIL_PAGE_URL}?{urllib.parse.urlencode({'infoid': info_id, 'subcategory': subcategory})}"


def _guangdong_gdcic_performance_records_from_html(text: str, keywords: list[str]) -> list[dict[str, Any]]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", str(text or ""), flags=re.I | re.S)
    records: list[dict[str, Any]] = []
    for row in rows:
        cells = [
            _strip_html(cell)
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        ]
        if len(cells) < 6:
            continue
        row_text = " ".join(cells)
        data_guid = ""
        guid_match = re.search(r"ppDetaill\(['\"]?([^'\")]+)", row, flags=re.I)
        if guid_match:
            data_guid = guid_match.group(1).strip()
        records.append(
            {
                "row_index": len(records) + 1,
                "project_name_probe": cells[1][:500] if len(cells) > 1 else "",
                "construction_unit_probe": cells[2][:200] if len(cells) > 2 else "",
                "construction_company_probe": cells[3][:200] if len(cells) > 3 else "",
                "survey_company_probe": cells[4][:200] if len(cells) > 4 else "",
                "design_company_probe": cells[5][:200] if len(cells) > 5 else "",
                "supervision_company_probe": cells[6][:200] if len(cells) > 6 else "",
                "detail_url": (
                    f"{GUANGDONG_GDCIC_HOME_BASE_URL}/JG/Information/PerformanceEvaluationProject/Detailgs?DataGuid={urllib.parse.quote(data_guid)}"
                    if data_guid
                    else ""
                ),
                "matched_keywords": [keyword for keyword in keywords if keyword and keyword in row_text][:10],
                "record_sha256": _sha256_text(row_text),
            }
        )
    return records


def _guangdong_tzxm_records_from_response(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payload = _json_payload(response)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if isinstance(data, Mapping):
        for key in ("list", "rows", "items", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
        return [data]
    for key in ("list", "rows", "items", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
    return []


def _compact_guangdong_tzxm_record(
    record: Mapping[str, Any],
    route: Mapping[str, Any],
    keywords: list[str],
) -> dict[str, Any]:
    project_name = _first_text(
        (
            record.get("projectName"),
            record.get("pname"),
            record.get("title"),
            record.get("xmmc"),
        )
    )
    project_code = _first_text(
        (
            record.get("projectCode"),
            record.get("proofCode"),
            record.get("proofOrSerialCode"),
            record.get("projectNo"),
        )
    )
    unit = _first_text(
        (
            record.get("applyOrgan"),
            record.get("buildOrgan"),
            record.get("projectDept"),
            record.get("legalDeptName"),
            record.get("approvalOrgan"),
            record.get("lxUnit"),
        )
    )
    record_text = _compact_mapping_text(record)
    return {
        "source_profile_id": GUANGDONG_TZXM_PROFILE_ID,
        "source_specific_adapter_id": "guangdong_tzxm_project_approval_publicity_api_v1",
        "route_kind": str(route.get("tzxm_route_kind") or ""),
        "audit": str(route.get("tzxm_audit") or ""),
        "flag": str(route.get("tzxm_flag") or ""),
        "project_code": project_code[:100],
        "project_name_probe": project_name[:500],
        "project_unit_probe": unit[:300],
        "approval_unit_probe": _first_text((record.get("approveUnitName"), record.get("department"), record.get("fullName")))[:300],
        "project_location_probe": _first_text((record.get("projectAddress"), record.get("place"), record.get("areaDetailName")))[:300],
        "status_probe": _first_text((record.get("stateFlagName"), record.get("stateName"), record.get("isValidity")))[:120],
        "finish_date": _first_text((record.get("finishDate"), record.get("operateDate"), record.get("beginDate"), record.get("endDate")))[:80],
        "detail_url": _guangdong_tzxm_detail_page_url(record, route),
        "matched_keywords": [keyword for keyword in keywords if keyword and keyword in record_text][:10],
        "record_sha256": _sha256_text(record_text),
        "query_miss_is_not_clearance": True,
        "readback_is_line_clue_not_final_conclusion": True,
    }


def _compact_guangdong_tzxm_detail(
    record: Mapping[str, Any],
    route: Mapping[str, Any],
    keywords: list[str],
) -> dict[str, Any]:
    if not record:
        return {}
    record_text = _compact_mapping_text(record)
    fields = {
        "route_kind": str(route.get("tzxm_route_kind") or ""),
        "audit": str(route.get("tzxm_audit") or ""),
        "flag": str(route.get("tzxm_flag") or ""),
        "project_code": _first_text((record.get("proofOrSerialCode"), record.get("projectCode"), record.get("proofCode"))),
        "project_name": _first_text((record.get("projectName"), record.get("pname"), record.get("title"))),
        "project_unit": _first_text((record.get("applyOrgan"), record.get("buildOrgan"), record.get("approvalOrgan"))),
        "project_location": _first_text((record.get("place"), record.get("projectAddress"), record.get("areaDetailName"))),
        "project_scope_probe": _strip_html(str(record.get("scope") or record.get("scaleContent") or ""))[:700],
        "total_invest": str(record.get("totalInvest") or record.get("totalMoney") or "").strip(),
        "approval_unit": _first_text((record.get("fullName"), record.get("department"), record.get("handleDeptName"))),
        "finish_date": _first_text((record.get("finishDate"), record.get("finishDateString"), record.get("submitDate"))),
        "project_period": _first_text(
            (
                f"{record.get('beginDate') or ''}至{record.get('overDate') or record.get('fixed') or ''}".strip("至"),
                record.get("fixed"),
            )
        ),
        "state": _first_text((record.get("stateFlagName"), record.get("isValidity"), record.get("openType"))),
        "tender_scope_probe": _strip_html(str(record.get("tenderJson") or ""))[:700],
        "matched_keywords": [keyword for keyword in keywords if keyword and keyword in record_text][:10],
        "record_sha256": _sha256_text(record_text),
    }
    return {
        key: value
        for key, value in fields.items()
        if value not in ("", [], None)
    }


def _guangdong_tzxm_detail_route(
    record: Mapping[str, Any],
    route: Mapping[str, Any],
    keywords: list[str],
) -> dict[str, Any] | None:
    audit = str(route.get("tzxm_audit") or "")
    flag = str(route.get("tzxm_flag") or "")
    if audit == "ba":
        ba_id = _first_text((record.get("baId"), record.get("id")))
        if not ba_id:
            return None
        endpoint = "selectBaProjectInfo"
        params = {"baId": ba_id}
        suffix = f"id={urllib.parse.quote(ba_id)}&audit=ba&flag={urllib.parse.quote(flag)}"
    elif audit == "hz":
        row_id = _first_text((record.get("id"), record.get("projectId")))
        if not row_id:
            return None
        endpoint = "getHzggInfoById" if flag == "10" else "getHzgsInfoById"
        params = {"id": row_id}
        suffix = f"id={urllib.parse.quote(row_id)}&audit=hz&flag={urllib.parse.quote(flag)}"
    elif audit == "sp":
        row_id = _first_text((record.get("id"), record.get("projectId")))
        if not row_id:
            return None
        endpoint = "getSpggInfoById" if flag == "7" else "getSpgsInfoById"
        params = {"id": row_id}
        pid = _first_text((record.get("pid"), record.get("projectId")))
        if flag == "7" and pid:
            params["pid"] = pid
        suffix = f"id={urllib.parse.quote(row_id)}&pid={urllib.parse.quote(pid)}&audit=sp&flag={urllib.parse.quote(flag)}"
    elif audit == "jn":
        row_id = _first_text((record.get("id"), record.get("projectId")))
        if not row_id:
            return None
        endpoint = "getJnscggInfoById"
        params = {"id": row_id}
        suffix = f"id={urllib.parse.quote(row_id)}&audit=jn&flag={urllib.parse.quote(flag)}"
    else:
        return None
    return {
        "route_id": f"gd_tzxm_detail_{audit}_{flag}_{_sha256_text(json.dumps(params, sort_keys=True))[:8]}",
        "route_group": "gd_tzxm_publicity_detail",
        "url": f"{GUANGDONG_TZXM_API_BASE_URL}/{endpoint}",
        "method": "POST",
        "json_body": True,
        "params": params,
        "human_detail_url": f"{GUANGDONG_TZXM_BASE_URL}/PublicityInformation/resultDetail2.html?{suffix}",
        "tzxm_audit": audit,
        "tzxm_flag": flag,
        "tzxm_route_kind": str(route.get("tzxm_route_kind") or ""),
        "keyword_count": len(keywords),
        "query_keyword_probe": keywords[:5],
        "source_specific_adapter_id": "guangdong_tzxm_project_approval_publicity_api_v1",
    }


def _guangdong_tzxm_detail_page_url(record: Mapping[str, Any], route: Mapping[str, Any]) -> str:
    detail_route = _guangdong_tzxm_detail_route(record, route, [])
    return str((detail_route or {}).get("human_detail_url") or "")


def _guangdong_credit_gd_records_from_response(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payload = _json_payload(response)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if isinstance(data, Mapping):
        for key in ("rows", "list", "items", "result", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
        return [data] if any(data.values()) else []
    for key in ("rows", "list", "items", "result", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
    return []


def _compact_guangdong_credit_gd_record(
    record: Mapping[str, Any],
    route: Mapping[str, Any],
    keywords: list[str],
) -> dict[str, Any]:
    record_type = str(route.get("credit_gd_record_type") or "penalty")
    record_text = _compact_mapping_text(record)
    record_id = _record_text(record, "ID", "id", "uuid", "ROW_ID", "row_id")
    if record_type == "license":
        counterparty = _record_text(record, "XK_XDR_MC", "xk_xdr_mc", "xkXdrMc", "xdrmc", "xdrMc")
        document_no = _record_text(record, "XK_WSH", "xk_wsh", "xkWsh", "wsh")
        item_name = _record_text(record, "XK_XMMC", "xk_xmmc", "xkXmmc", "xmmc")
        authority = _record_text(record, "XK_XKJG", "xk_xkjg", "xkXkjg", "xkjg")
        decision_date = _record_text(record, "XK_JDRQ", "xk_jdrq", "xkJdrq", "jdrq")
        content = _record_text(record, "XK_NR", "xk_nr", "xkNr", "xknr")
        detail_url = _guangdong_credit_gd_detail_url(record_id, "license", record)
        source_type = "administrative_license_public_record"
    else:
        counterparty = _record_text(record, "CF_XDR_MC", "cf_xdr_mc", "cfXdrMc", "xdrmc", "xdrMc")
        document_no = _record_text(record, "CF_WSH", "cf_wsh", "cfWsh", "wsh")
        item_name = _record_text(record, "CF_SY", "cf_sy", "cfSy", "ajmc", "xmmc")
        authority = _record_text(record, "CF_CFJG", "cf_cfjg", "cfCfjg", "cfjg")
        decision_date = _record_text(record, "CF_JDRQ", "cf_jdrq", "cfJdrq", "jdrq")
        content = _record_text(record, "CF_NR", "cf_nr", "cfNr", "cfnr")
        detail_url = _guangdong_credit_gd_detail_url(record_id, "penalty", record)
        source_type = "administrative_penalty_public_record"
    return {
        "source_profile_id": GUANGDONG_CREDIT_GD_PROFILE_ID,
        "source_specific_adapter_id": "guangdong_credit_gd_public_credit_query_v1",
        "record_type": source_type,
        "record_id": record_id,
        "administrative_counterparty": counterparty[:300],
        "document_no": document_no[:200],
        "project_or_item_name_probe": item_name[:500],
        "decision_authority": authority[:300],
        "decision_date": decision_date[:100],
        "content_probe": content[:800],
        "detail_url": detail_url,
        "matched_keywords": [keyword for keyword in keywords if keyword and keyword in record_text][:10],
        "targeted_query": bool(route.get("targeted_query")),
        "record_sha256": _sha256_text(record_text),
    }


def _guangdong_credit_gd_detail_url(record_id: str, record_type: str, record: Mapping[str, Any]) -> str:
    if not record_id:
        return ""
    if record_type == "license":
        detail_page = "xzxkOlddet.html" if _record_text(record, "TABLE_NAME", "tableName", "const_0") else "xzxkdet.html"
        return f"{GUANGDONG_CREDIT_GD_BASE_URL}/page/creditPublic/{detail_page}?id={urllib.parse.quote(record_id)}"
    return f"{GUANGDONG_CREDIT_GD_BASE_URL}/page/creditPublic/xzcfdet.html?id={urllib.parse.quote(record_id)}"


def _record_text(record: Mapping[str, Any], *keys: str) -> str:
    lowered = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        if key in record and str(record.get(key) or "").strip():
            return str(record.get(key) or "").strip()
        value = lowered.get(str(key).lower())
        if str(value or "").strip():
            return str(value or "").strip()
    return ""


def _guangdong_zfcxjst_penalty_links_from_html(text: str, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in re.finditer(r"<a\b([^>]*?)>(.*?)</a>", str(text or ""), flags=re.I | re.S):
        attrs = match.group(1)
        body = match.group(2)
        href_match = re.search(r"\bhref=['\"]([^'\"]+)['\"]", attrs, flags=re.I)
        if not href_match:
            continue
        href = href_match.group(1).strip()
        if not href or href.startswith("javascript:"):
            continue
        title_match = re.search(r"\btitle=['\"]([^'\"]+)['\"]", attrs, flags=re.I)
        title = _strip_html(title_match.group(1) if title_match else body)
        url = urllib.parse.urljoin(base_url or GUANGDONG_ZFCXJST_GSGG_BASE_URL, href)
        if "zfcxjst.gd.gov.cn" not in url or "/content/post_" not in url:
            continue
        if not _looks_like_penalty_title(title) and "行政处罚" not in _strip_html(body):
            continue
        links.append({"title": title[:500], "url": url})
    return _dedupe_links(links)


def _guangdong_zfcxjst_penalty_record_from_detail(
    text: str,
    *,
    detail_url: str,
    fallback_title: str,
    keywords: list[str],
) -> dict[str, Any]:
    plain = _strip_html(text)
    title = _first_text(
        (
            _meta_content(text, "ArticleTitle"),
            _match_text(r"<div[^>]+class=['\"][^'\"]*news-title[^'\"]*['\"][^>]*>(.*?)</div>", text),
            fallback_title,
        )
    )
    if not _looks_like_penalty_title(title) and "行政处罚" not in plain:
        return {}
    matched = [keyword for keyword in keywords if keyword and (keyword in title or keyword in plain)]
    # Source-specific records are only useful when at least one query term appears in title/body.
    if not matched:
        return {}
    party = _first_text(
        (
            _match_text(r"（法人）名称[:：]\s*(.+?)(?=统一社会信用代码|文号|成文日期|发布机构|$)", plain),
            _match_text(r"名称[:：]\s*(.+?)(?=统一社会信用代码|文号|成文日期|发布机构|$)", plain),
            _match_text(r"关于(.+?)的行政处罚决定书", title),
        )
    )
    document_no = _first_text(
        (
            _meta_content(text, "DocumentNumber"),
            _match_text(r"([\u4e00-\u9fa5]{1,8}罚〔\d{4}〕\d+号)", plain),
            _match_text(r"([\u4e00-\u9fa5]{1,8}告〔\d{4}〕\d+号)", plain),
            _match_text(r"文号[:：]\s*(.+?)(?=本机关|你单位|若你|$)", plain),
        )
    )
    record = {
        "title_probe": title[:500],
        "detail_url": detail_url,
        "publication_date": _first_text((_meta_content(text, "PubDate"), _match_text(r"(\d{4}[-年]\d{1,2}[-月]\d{1,2})", plain))),
        "document_no": document_no[:200],
        "administrative_counterparty": party[:300],
        "credit_code": _match_text(r"统一社会信用代码[:：]\s*([0-9A-Z]{15,20})", plain),
        "project_name_probe": _match_text(r"承建的(.{2,120}?项目)", plain)[:300],
        "punishment_summary_probe": _penalty_summary_probe(plain),
        "matched_keywords": matched[:10],
        "record_sha256": _sha256_text(plain),
        "source_profile_id": GUANGDONG_ZFCXJST_PENALTY_PROFILE_ID,
        "source_specific_adapter_id": "guangdong_zfcxjst_penalty_publicity_page_v1",
        "query_miss_is_not_clearance": True,
        "readback_is_line_clue_not_final_conclusion": True,
    }
    return {key: value for key, value in record.items() if value not in ("", [], None)}


def _looks_like_penalty_title(title: str) -> bool:
    text = str(title or "")
    return any(pattern in text for pattern in ("行政处罚", "处罚决定书", "处罚意见告知", "暂扣", "撤销", "监管决定"))


def _penalty_summary_probe(text: str) -> str:
    for pattern in (
        r"(决定给予.{2,120}?行政处罚[^。]*。)",
        r"(决定对你.{0,80}?作出如下行政处罚[:：]?.{0,160})",
        r"(暂扣建筑施工企业安全生产许可证[^。]*。)",
        r"(罚款人民币[^。]*。)",
    ):
        matched = _match_text(pattern, text)
        if matched:
            return matched[:500]
    start = text.find("本机关决定")
    if start >= 0:
        return text[start : start + 300]
    return ""


def _meta_content(text: str, name: str) -> str:
    pattern = rf"<meta[^>]+(?:name|property)=['\"]{re.escape(name)}['\"][^>]+content=['\"]([^'\"]*)['\"]"
    return _match_text(pattern, text)


def _match_text(pattern: str, text: str) -> str:
    match = re.search(pattern, str(text or ""), flags=re.I | re.S)
    if not match:
        return ""
    return _strip_html(match.group(1)).strip()


def _dedupe_links(links: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in links:
        url = str(link.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"title": str(link.get("title") or "").strip(), "url": url})
    return out


def _strip_html(value: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.replace("&nbsp;", " ").split())


def _compact_mapping_text(record: Mapping[str, Any]) -> str:
    return " ".join(json.dumps(dict(record), ensure_ascii=False, default=str).split())


def _first_mapping(records: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    for record in records:
        if isinstance(record, Mapping):
            return record
    return {}


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
                "keyword_hit_count": sum(
                    1
                    for task in tasks
                    if str(task.get("field_query_probe_state") or "")
                    in {"FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE", "FIELD_READBACK_READY_PUBLIC_SOURCE"}
                    and _int((task.get("field_summary") or {}).get("matched_keyword_count"))
                ),
                "source_specific_readback_ready_count": sum(
                    1 for task in tasks if str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_READY_PUBLIC_SOURCE"
                ),
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
            1
            for task in field_task_records
            if str(task.get("field_query_probe_state") or "")
            in {"FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE", "FIELD_READBACK_READY_PUBLIC_SOURCE"}
            and _int((task.get("field_summary") or {}).get("matched_keyword_count"))
        ),
        "source_specific_readback_ready_count": sum(
            1
            for task in field_task_records
            if str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_READY_PUBLIC_SOURCE"
        ),
        "guangzhou_zfcj_api_readback_ready_count": sum(
            1
            for task in field_task_records
            if str(task.get("source_profile_id") or "").upper() == GUANGZHOU_ZFCJ_PROFILE_ID
            and str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_READY_PUBLIC_SOURCE"
        ),
        "guangdong_gdcic_contract_performance_readback_ready_count": sum(
            1
            for task in field_task_records
            if str(task.get("source_profile_id") or "").upper() == GUANGDONG_GDCIC_HOME_PROFILE_ID
            and str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_READY_PUBLIC_SOURCE"
        ),
        "guangdong_zfcxjst_penalty_readback_ready_count": sum(
            1
            for task in field_task_records
            if str(task.get("source_profile_id") or "").upper() == GUANGDONG_ZFCXJST_PENALTY_PROFILE_ID
            and str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_READY_PUBLIC_SOURCE"
        ),
        "guangdong_tzxm_readback_ready_count": sum(
            1
            for task in field_task_records
            if str(task.get("source_profile_id") or "").upper() == GUANGDONG_TZXM_PROFILE_ID
            and str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_READY_PUBLIC_SOURCE"
        ),
        "guangdong_credit_gd_readback_ready_count": sum(
            1
            for task in field_task_records
            if str(task.get("source_profile_id") or "").upper() == GUANGDONG_CREDIT_GD_PROFILE_ID
            and str(task.get("field_query_probe_state") or "") == "FIELD_READBACK_READY_PUBLIC_SOURCE"
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
    probe_limit = _http_probe_char_limit()
    lowered = content_type.lower()
    encodings = ["gb18030", "utf-8"] if "charset=gb" in lowered else ["utf-8", "gb18030"]
    for encoding in encodings:
        try:
            return body.decode(encoding, errors="ignore")[:probe_limit]
        except LookupError:
            continue
    return body.decode("utf-8", errors="ignore")[:probe_limit]


def _http_probe_char_limit() -> int:
    try:
        return max(8_000, min(80_000, int(os.environ.get("KAKA_GD_LOCAL_FIELD_HTTP_PROBE_CHARS", "50000"))))
    except ValueError:
        return 50_000


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
