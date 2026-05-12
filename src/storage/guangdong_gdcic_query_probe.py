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


GUANGDONG_GDCIC_QUERY_PROBE_KIND = "guangdong_gdcic_query_probe_v1_manifest"
GUANGDONG_GDCIC_QUERY_PROBE_VERSION = 1
GUANGDONG_GDCIC_QUERY_PROBE_ADAPTER_ID = "guangdong-gdcic-query-probe-v1-builder"

SOURCE_PROFILE_ID = "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"
GDCIC_OPENPLATFORM_PAGE_URL = "https://skypt.gdcic.net/openplatform/"
GDCIC_API_BASE_URL = "https://skypt.gdcic.net/api"
DEFAULT_ACTIVE_CONFLICT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-active-conflict-probe-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-gdcic-query-probe-v1")
DEFAULT_PAGE_SIZE = 5
MAX_COMPANY_ROUTE_VARIANTS = 4
MAX_ID_CARD_FOLLOWUPS = 3

FORBIDDEN_TERMS = ("在建冲突成立", "无在建", "无冲突", "造假成立", "违法成立", "确认本人")

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_guangdong_gdcic_query_probe(
    *,
    active_conflict_root: str | Path = DEFAULT_ACTIVE_CONFLICT_ROOT,
    active_conflict_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_public_query: bool = False,
    max_live_tasks: int | None = None,
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    active_dir = Path(active_conflict_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    active_path = (
        Path(active_conflict_json)
        if active_conflict_json
        else active_dir / "guangzhou-active-conflict-probe-v1.json"
    )
    blocking_reasons: list[str] = []
    active_manifest = _source_manifest(
        _load_json(active_path, blocking_reasons, "active_conflict_probe_missing")
    )
    execution_mode = "LIVE_PUBLIC_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED"
    query_task_records = _query_task_records_from_active_conflict(
        active_manifest,
        created_at=created,
        enable_live_public_query=enable_live_public_query,
        max_live_tasks=max_live_tasks,
        http_getter=http_getter,
    )
    project_task_records = _project_task_records(query_task_records)
    manual_check_table = _manual_check_table(query_task_records)
    summary = _summary(
        query_task_records=query_task_records,
        project_task_records=project_task_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GUANGDONG_GDCIC_QUERY_PROBE_VERSION,
        "manifest_kind": GUANGDONG_GDCIC_QUERY_PROBE_KIND,
        "adapter_id": GUANGDONG_GDCIC_QUERY_PROBE_ADAPTER_ID,
        "pipeline_stage": "GuangdongGdcicQueryProbeV1",
        "manifest_id": f"GUANGDONG-GDCIC-QUERY-PROBE-{_fingerprint({'tasks': query_task_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_active_conflict_root": str(active_dir),
        "source_active_conflict_json": str(active_path),
        "source_profile_id": SOURCE_PROFILE_ID,
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "max_live_tasks": max_live_tasks,
        "project_task_records": project_task_records,
        "query_task_records": query_task_records,
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
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "guangdong_gdcic_query_probe_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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
    (out_dir / "guangdong-gdcic-query-probe-v1.json").write_text(text, encoding="utf-8")
    return result


def _query_task_records_from_active_conflict(
    active_manifest: Mapping[str, Any],
    *,
    created_at: str,
    enable_live_public_query: bool,
    max_live_tasks: int | None,
    http_getter: HttpGetter | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    live_attempted = 0
    for task in _list(active_manifest.get("task_records")):
        if not isinstance(task, Mapping):
            continue
        source_entry = _gdcic_source_entry(task)
        if not source_entry:
            continue
        query_url = str(source_entry.get("source_url") or GDCIC_OPENPLATFORM_PAGE_URL)
        query_params = _query_params(task)
        if enable_live_public_query:
            if max_live_tasks is not None and live_attempted >= max_live_tasks:
                readback = _live_deferred_readback(max_live_tasks)
            else:
                live_attempted += 1
                readback = _execute_live_query(query_url, query_params, http_getter=http_getter)
        else:
            readback = _plan_only_readback()
        records.append(
            {
                "query_task_id": _stable_id(
                    "GD-GDCIC-QUERY",
                    task.get("task_id"),
                    task.get("project_id"),
                    task.get("candidate_group_id"),
                    task.get("responsible_person_name"),
                    task.get("certificate_no"),
                ),
                "active_conflict_task_id": str(task.get("task_id") or ""),
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
                "source_profile_id": SOURCE_PROFILE_ID,
                "source_entry": source_entry,
                "source_url": query_url,
                "api_base_url": GDCIC_API_BASE_URL,
                "target_source_types": _list(source_entry.get("target_source_types")),
                "query_params": query_params,
                "execution_mode": (
                    "LIVE_PUBLIC_QUERY_ATTEMPTED"
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


def _gdcic_source_entry(task: Mapping[str, Any]) -> dict[str, Any]:
    for entry in _list(task.get("source_entries")):
        if isinstance(entry, Mapping) and str(entry.get("source_profile_id") or "") == SOURCE_PROFILE_ID:
            return dict(entry)
    return {}


def _query_params(task: Mapping[str, Any]) -> dict[str, Any]:
    project_name = str(task.get("project_name") or "").strip()
    person = str(task.get("responsible_person_name") or "").strip()
    certificate_no = str(task.get("certificate_no") or "").strip()
    companies = _list(task.get("company_query_variants"))
    company_variants = _dedupe([*companies, *_list(task.get("candidate_group_members")), *_list(task.get("matched_company_names"))])
    return {
        "projectId": str(task.get("project_id") or ""),
        "projectName": project_name,
        "companyName": _first_text(companies),
        "companyVariants": company_variants,
        "personName": person,
        "certificateNo": certificate_no,
        "keywords": _dedupe([project_name, *company_variants, person, certificate_no]),
    }


def _plan_only_readback() -> dict[str, Any]:
    return {
        "query_probe_state": "PLAN_ONLY_NOT_EXECUTED",
        "reachability_diagnostic_state": "REACHABILITY_DIAGNOSTIC_NOT_RUN",
        "readback_ready": False,
        "readback_status_code": None,
        "field_summary": {},
        "api_route_plan": _route_plan_preview(),
        "route_attempts": [],
        "blocker_taxonomy": [],
    }


def _live_deferred_readback(max_live_tasks: int) -> dict[str, Any]:
    return {
        "query_probe_state": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
        "reachability_diagnostic_state": "REACHABILITY_DIAGNOSTIC_DEFERRED",
        "readback_ready": False,
        "readback_status_code": None,
        "field_summary": {},
        "api_route_plan": _route_plan_preview(),
        "route_attempts": [],
        "blocker_taxonomy": ["gdcic_live_query_deferred_by_limit"],
        "diagnostic_message": f"max_live_tasks={max_live_tasks}",
    }


def _execute_live_query(
    query_url: str,
    query_params: Mapping[str, Any],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    getter = http_getter or _default_http_getter
    route_attempts: list[dict[str, Any]] = []
    aggregate_records: list[Mapping[str, Any]] = []
    seen_route_keys: set[str] = set()

    def run_route(route: Mapping[str, Any]) -> None:
        key = _route_key(route)
        if key in seen_route_keys:
            return
        seen_route_keys.add(key)
        attempt, records = _execute_gdcic_route(route, getter=getter)
        route_attempts.append(attempt)
        aggregate_records.extend(records)

    for route in _initial_route_specs(query_params):
        run_route(route)

    for id_card in _id_card_values(aggregate_records)[:MAX_ID_CARD_FOLLOWUPS]:
        for route in _id_card_followup_route_specs(id_card):
            run_route(route)

    summary = _field_summary(aggregate_records)
    blockers = _dedupe(
        blocker for attempt in route_attempts for blocker in _list(attempt.get("blocker_taxonomy"))
    )
    status_codes = [_int(attempt.get("http_status")) for attempt in route_attempts if _int(attempt.get("http_status"))]
    readback_routes = [
        str(attempt.get("route_id") or "")
        for attempt in route_attempts
        if str(attempt.get("route_state") or "") == "READBACK_READY_PUBLIC_SOURCE"
    ]
    if summary.get("record_count") and _field_summary_has_useful_fields(summary):
        return {
            "query_probe_state": "READBACK_READY_PUBLIC_SOURCE",
            "reachability_diagnostic_state": "PUBLIC_SOURCE_READBACK_READY",
            "readback_ready": True,
            "readback_status_code": status_codes[0] if status_codes else 200,
            "field_summary": summary,
            "limited_readback": {
                "record_count": summary["record_count"],
                "route_attempt_count": len(route_attempts),
                "readback_route_ids": readback_routes,
                "sample_project_names": summary["sample_project_names"],
                "sample_company_names": summary["sample_company_names"],
                "sample_person_names": summary["sample_person_names"],
                "sample_certificate_nos": summary["sample_certificate_nos"],
            },
            "route_attempts": route_attempts,
            "blocker_taxonomy": blockers,
        }
    if route_attempts and all(str(attempt.get("route_state") or "").startswith("FAIL_CLOSED") for attempt in route_attempts):
        fail_states = _dedupe(str(attempt.get("route_state") or "") for attempt in route_attempts)
        return _fail_closed(
            state=fail_states[0] if len(fail_states) == 1 else "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED",
            taxonomy=blockers[0] if blockers else "gdcic_all_routes_blocked",
            status=status_codes[0] if status_codes else None,
            message="all_gdcic_api_routes_failed_closed",
            extra={"route_attempts": route_attempts, "blocker_taxonomy": blockers or ["gdcic_all_routes_blocked"]},
        )
    return _review_required(
        taxonomy="gdcic_public_query_empty_review",
        status=status_codes[0] if status_codes else None,
        extra={"route_attempts": route_attempts, "blocker_taxonomy": blockers or ["gdcic_public_query_empty_review"]},
    )


def _default_http_getter(query_url: str, query_params: Mapping[str, Any]) -> Mapping[str, Any]:
    params = {str(key): value for key, value in dict(query_params).items() if str(value or "").strip()}
    url = query_url
    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 KakaGdcicQueryProbe/1.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=_http_timeout_seconds()) as response:
            body = response.read(1_000_000)
            content_type = response.headers.get("Content-Type", "")
            text = body.decode("utf-8", errors="ignore")
            payload: Any = {}
            if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {}
            return {
                "http_status": int(response.status),
                "content_type": content_type,
                "payload": payload,
                "text_probe": text[:500],
            }
    except urllib.error.HTTPError as exc:
        probe = exc.read(2000).decode("utf-8", errors="ignore")
        return {
            "http_status": int(exc.code),
            "content_type": exc.headers.get("Content-Type", ""),
            "payload": {},
            "text_probe": probe[:500],
        }


def _http_timeout_seconds() -> int:
    try:
        return max(3, min(30, int(os.environ.get("KAKA_GDCIC_HTTP_TIMEOUT_SECONDS", "8"))))
    except ValueError:
        return 8


def _records_from_response(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payload = response.get("payload", response)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("records", "items", "rows", "data", "result", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            nested = _records_from_response({"payload": value})
            if nested:
                return nested
            if _looks_like_record(value):
                return [value]
    if _looks_like_record(payload):
        return [payload]
    return []


def _field_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len(records),
        "sample_project_names": _dedupe(
            _first_field(record, ("projectName", "project_name", "prjName", "工程名称", "项目名称"))
            for record in records[:5]
        )[:5],
        "sample_company_names": _dedupe(
            _first_field(
                record,
                (
                    "companyName",
                    "corpName",
                    "企业名称",
                    "单位名称",
                    "contractorName",
                    "contractOrgName",
                    "biddingOrgName",
                    "orgName",
                    "entName",
                    "biddingUnit.orgName",
                ),
            )
            for record in records[:5]
        )[:5],
        "sample_person_names": _dedupe(
            _first_field(record, ("personName", "managerName", "memberName", "项目经理", "负责人", "name"))
            for record in records[:5]
        )[:5],
        "sample_certificate_nos": _dedupe(
            _first_field(record, ("certificateNo", "certNo", "certNum", "regCertNo", "注册证书号", "证书编号"))
            for record in records[:5]
        )[:5],
        "sample_id_card_hashes": _dedupe(
            _first_field(record, ("idCard", "idNum", "idCardHash", "personId"))
            for record in records[:5]
        )[:5],
    }


def _first_field(record: Mapping[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        text = _nested_text(record, name)
        if text:
            return text
    return ""


def _field_summary_has_useful_fields(summary: Mapping[str, Any]) -> bool:
    return any(
        summary.get(key)
        for key in (
            "sample_project_names",
            "sample_company_names",
            "sample_person_names",
            "sample_certificate_nos",
            "sample_id_card_hashes",
        )
    )


def _route_plan_preview() -> list[dict[str, str]]:
    return [
        {"route_id": "person_in_gd_by_name", "endpoint": "/openplatform/personInGd/list"},
        {"route_id": "person_into_gd_by_name_company", "endpoint": "/openplatform/personIntoGd/list"},
        {"route_id": "project_bidding_by_company", "endpoint": "/openplatform/projectBidding/list"},
        {"route_id": "member_involved_project_by_company", "endpoint": "/openplatform/memberInvolvedProject/list"},
        {"route_id": "project_lookup_by_title", "endpoint": "/openplatform/project/list"},
        {"route_id": "person_cert_reg_by_id_card", "endpoint": "/openplatform/personCertReg/list"},
        {"route_id": "person_cert_spec_by_id_card", "endpoint": "/openplatform/personCertSpec/list"},
        {"route_id": "project_member_by_id_card", "endpoint": "/openplatform/projectMember/list"},
    ]


def _initial_route_specs(query_params: Mapping[str, Any]) -> list[dict[str, Any]]:
    person = str(query_params.get("personName") or "").strip()
    project_name = str(query_params.get("projectName") or "").strip()
    companies = _dedupe(_list(query_params.get("companyVariants")) or [query_params.get("companyName")])
    routes: list[dict[str, Any]] = []
    if person:
        routes.append(
            _route_spec(
                "person_in_gd_by_name",
                "/openplatform/personInGd/list",
                {"name": person},
                route_group="person_directory",
            )
        )
        for company in companies[:MAX_COMPANY_ROUTE_VARIANTS]:
            routes.append(
                _route_spec(
                    "person_into_gd_by_name_company",
                    "/openplatform/personIntoGd/list",
                    {"name": person, "entName": company},
                    route_group="person_directory",
                )
            )
    for company in companies[:MAX_COMPANY_ROUTE_VARIANTS]:
        routes.extend(
            [
                _route_spec(
                    "project_bidding_by_company",
                    "/openplatform/projectBidding/list",
                    {"biddingOrgName": company},
                    route_group="company_project_evidence",
                ),
                _route_spec(
                    "member_involved_project_by_company",
                    "/openplatform/memberInvolvedProject/list",
                    {"orgName": company},
                    route_group="company_project_evidence",
                ),
                _route_spec(
                    "project_contract_by_company",
                    "/openplatform/projectContract/list",
                    {"contractOrgName": company},
                    route_group="company_project_evidence",
                ),
            ]
        )
    if project_name:
        routes.extend(
            [
                _route_spec(
                    "project_lookup_by_title",
                    "/openplatform/project/list",
                    {"projectName": _clean_project_title(project_name)},
                    route_group="project_public_record",
                ),
                _route_spec(
                    "construction_permit_by_project_title",
                    "/openplatform/constructionPermit/list",
                    {"projectName": _clean_project_title(project_name)},
                    route_group="project_public_record",
                ),
            ]
        )
    return routes


def _id_card_followup_route_specs(id_card: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(id_card, safe="")
    return [
        _route_spec(
            "person_in_gd_detail_by_id_card",
            f"/openplatform/personInGd/getByIdNum/{encoded}",
            {},
            route_group="person_directory_followup",
        ),
        _route_spec(
            "person_into_gd_detail_by_id_card",
            f"/openplatform/personIntoGd/getByIdNum/{encoded}",
            {},
            route_group="person_directory_followup",
        ),
        _route_spec(
            "person_cert_reg_by_id_card",
            "/openplatform/personCertReg/list",
            {"idCard": id_card},
            route_group="person_certificate_followup",
        ),
        _route_spec(
            "person_cert_spec_by_id_card",
            "/openplatform/personCertSpec/list",
            {"idCard": id_card},
            route_group="person_certificate_followup",
        ),
        _route_spec(
            "project_member_by_id_card",
            "/openplatform/projectMember/list",
            {"idCard": id_card},
            route_group="person_project_followup",
        ),
    ]


def _route_spec(route_id: str, endpoint: str, params: Mapping[str, Any], *, route_group: str) -> dict[str, Any]:
    clean_params = {
        "pageNum": "1",
        "pageSize": str(DEFAULT_PAGE_SIZE),
        **{str(key): str(value) for key, value in params.items() if str(value or "").strip()},
    }
    if "getByIdNum" in endpoint:
        clean_params.pop("pageNum", None)
        clean_params.pop("pageSize", None)
    return {
        "route_id": route_id,
        "route_group": route_group,
        "endpoint": endpoint,
        "url": f"{GDCIC_API_BASE_URL}{endpoint}",
        "params": clean_params,
    }


def _route_key(route: Mapping[str, Any]) -> str:
    return _fingerprint(
        {
            "route_id": route.get("route_id"),
            "endpoint": route.get("endpoint"),
            "params": route.get("params"),
        }
    )


def _execute_gdcic_route(
    route: Mapping[str, Any],
    *,
    getter: HttpGetter,
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    url = str(route.get("url") or "")
    params = dict(route.get("params") or {})
    try:
        response = dict(getter(url, params))
    except Exception as exc:  # pragma: no cover - defensive guard for external routes.
        return (
            _route_attempt(
                route,
                route_state="FAIL_CLOSED_QUERY_TRANSPORT_ERROR",
                taxonomy=["gdcic_query_transport_error"],
                message=type(exc).__name__,
            ),
            [],
        )
    status = _int(response.get("http_status") or response.get("status_code") or 200)
    content_type = str(response.get("content_type") or "")
    text_probe = str(response.get("text_probe") or response.get("body_probe") or "")
    if status == 403:
        return (
            _route_attempt(
                route,
                route_state="FAIL_CLOSED_FORBIDDEN",
                status=status,
                content_type=content_type,
                taxonomy=["gdcic_http_403"],
            ),
            [],
        )
    if _looks_like_captcha(text_probe) or str(response.get("captcha_required") or "").lower() == "true":
        return (
            _route_attempt(
                route,
                route_state="FAIL_CLOSED_CAPTCHA_REQUIRED",
                status=status,
                content_type=content_type,
                taxonomy=["gdcic_captcha_required"],
            ),
            [],
        )
    if status and status >= 500:
        return (
            _route_attempt(
                route,
                route_state="FAIL_CLOSED_SOURCE_SERVER_ERROR",
                status=status,
                content_type=content_type,
                taxonomy=["gdcic_source_server_error"],
            ),
            [],
        )
    records = _records_from_response(response)
    summary = _field_summary(records)
    if records and _field_summary_has_useful_fields(summary):
        return (
            _route_attempt(
                route,
                route_state="READBACK_READY_PUBLIC_SOURCE",
                status=status,
                content_type=content_type,
                record_count=len(records),
                field_summary=summary,
                sample_records=[_record_probe(record) for record in records[:2]],
            ),
            records,
        )
    if records:
        return (
            _route_attempt(
                route,
                route_state="REVIEW_REQUIRED",
                status=status,
                content_type=content_type,
                record_count=len(records),
                field_summary=summary,
                taxonomy=["gdcic_field_summary_missing"],
                sample_records=[_record_probe(record) for record in records[:2]],
            ),
            records,
        )
    return (
        _route_attempt(
            route,
            route_state="REVIEW_REQUIRED",
            status=status,
            content_type=content_type,
            taxonomy=["gdcic_public_query_empty_review"],
        ),
        [],
    )


def _route_attempt(
    route: Mapping[str, Any],
    *,
    route_state: str,
    status: int | None = None,
    content_type: str = "",
    taxonomy: list[str] | None = None,
    message: str = "",
    record_count: int = 0,
    field_summary: Mapping[str, Any] | None = None,
    sample_records: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "route_id": str(route.get("route_id") or ""),
        "route_group": str(route.get("route_group") or ""),
        "endpoint": str(route.get("endpoint") or ""),
        "api_url": _url_with_query(str(route.get("url") or ""), dict(route.get("params") or {})),
        "params": dict(route.get("params") or {}),
        "route_state": route_state,
        "http_status": status,
        "content_type_probe": content_type,
        "record_count": int(record_count),
        "field_summary": dict(field_summary or {}),
        "sample_records": list(sample_records or []),
        "blocker_taxonomy": list(taxonomy or []),
        "diagnostic_message": message,
    }


def _id_card_values(records: list[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        for key in ("idCard", "idNum", "idCardHash", "personId"):
            text = str(record.get(key) or "").strip()
            if text:
                values.append(text)
    return _dedupe(values)


def _record_probe(record: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "projectName",
        "projectCode",
        "prjNum",
        "entName",
        "orgName",
        "companyName",
        "corpName",
        "biddingOrgName",
        "contractOrgName",
        "name",
        "personName",
        "memberName",
        "certificateNo",
        "certNo",
        "certNum",
        "idCard",
        "idNum",
        "position",
        "role",
    )
    return {key: str(record.get(key) or "")[:120] for key in allowed if str(record.get(key) or "").strip()}


def _looks_like_record(value: Any) -> bool:
    return isinstance(value, Mapping) and any(
        str(key) in value
        for key in (
            "projectName",
            "projectCode",
            "entName",
            "orgName",
            "name",
            "idCard",
            "idNum",
            "certificateNo",
            "certNo",
        )
    )


def _nested_text(record: Mapping[str, Any], name: str) -> str:
    if "." not in name:
        return str(record.get(name) or "").strip()
    head, tail = name.split(".", 1)
    value = record.get(head)
    if isinstance(value, Mapping):
        return _nested_text(value, tail)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                text = _nested_text(item, tail)
                if text:
                    return text
    return ""


def _clean_project_title(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in (
        "中标候选人公示",
        "中标结果公示",
        "中标结果公告",
        "招标公告",
        "招标文件",
        "资格审查结果公示",
    ):
        text = text.replace(suffix, "")
    text = re.sub(r"\s+", " ", text).strip(" -_，,。")
    return text


def _url_with_query(url: str, params: Mapping[str, Any]) -> str:
    clean = {str(key): str(value) for key, value in dict(params).items() if str(value or "").strip()}
    return f"{url}?{urllib.parse.urlencode(clean)}" if clean else url


def _looks_like_captcha(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("captcha", "verify", "验证码", "滑块", "请完成验证"))


def _fail_closed(
    *,
    state: str,
    taxonomy: str,
    status: int | None = None,
    content_type: str = "",
    message: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "query_probe_state": state,
        "reachability_diagnostic_state": "PUBLIC_SOURCE_BLOCKED",
        "readback_ready": False,
        "readback_status_code": status,
        "field_summary": {},
        "blocker_taxonomy": [taxonomy],
        "diagnostic_message": message,
        "content_type_probe": content_type,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _review_required(
    *,
    taxonomy: str,
    status: int | None = None,
    content_type: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "query_probe_state": "REVIEW_REQUIRED",
        "reachability_diagnostic_state": "PUBLIC_SOURCE_REVIEW_REQUIRED",
        "readback_ready": False,
        "readback_status_code": status,
        "field_summary": {},
        "blocker_taxonomy": [taxonomy],
        "content_type_probe": content_type,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _project_task_records(query_task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for task in query_task_records:
        grouped.setdefault(str(task.get("project_id") or ""), []).append(task)
    rows: list[dict[str, Any]] = []
    for project_id, tasks in grouped.items():
        rows.append(
            {
                "project_id": project_id,
                "project_name": _first_text(task.get("project_name") for task in tasks),
                "query_task_ids": [str(task.get("query_task_id") or "") for task in tasks],
                "query_task_count": len(tasks),
                "readback_ready_count": sum(1 for task in tasks if bool(task.get("readback_ready"))),
                "blocker_taxonomy_counts": _counts(
                    blocker for task in tasks for blocker in _list(task.get("blocker_taxonomy"))
                ),
                "probe_state": "READY" if tasks else "NO_GDCIC_TASKS",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _manual_check_table(query_task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in query_task_records:
        rows.append(
            {
                "query_task_id": task.get("query_task_id"),
                "project_id": task.get("project_id"),
                "project_name": task.get("project_name"),
                "candidate_group_id": task.get("candidate_group_id"),
                "responsible_person_name": task.get("responsible_person_name"),
                "certificate_no": task.get("certificate_no"),
                "company_query_variants": _list(task.get("company_query_variants")),
                "source_url": task.get("source_url"),
                "query_params": task.get("query_params"),
                "query_probe_state": task.get("query_probe_state"),
                "manual_check_state": "PENDING_PUBLIC_SOURCE_REVIEW",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _summary(
    *,
    query_task_records: list[Mapping[str, Any]],
    project_task_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    states = _counts(task.get("query_probe_state") for task in query_task_records)
    blockers = _counts(
        blocker for task in query_task_records for blocker in _list(task.get("blocker_taxonomy"))
    )
    route_state_counts = _counts(
        route.get("route_state")
        for task in query_task_records
        for route in _list(task.get("route_attempts"))
        if isinstance(route, Mapping)
    )
    return {
        "probe_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "execution_mode": execution_mode,
        "source_profile_id": SOURCE_PROFILE_ID,
        "gdcic_query_probe_task_count": len(query_task_records),
        "project_count": len(project_task_records),
        "gdcic_readback_ready_count": sum(1 for task in query_task_records if bool(task.get("readback_ready"))),
        "gdcic_person_directory_readback_ready_count": sum(
            1 for task in query_task_records if _task_has_ready_route_group(task, {"person_directory", "person_directory_followup"})
        ),
        "gdcic_company_project_readback_ready_count": sum(
            1 for task in query_task_records if _task_has_ready_route_group(task, {"company_project_evidence", "project_public_record"})
        ),
        "gdcic_certificate_route_readback_ready_count": sum(
            1 for task in query_task_records if _task_has_ready_route_group(task, {"person_certificate_followup"})
        ),
        "gdcic_certificate_field_candidate_count": sum(
            1 for task in query_task_records if _list((task.get("field_summary") or {}).get("sample_certificate_nos"))
        ),
        "gdcic_captcha_blocked_task_count": sum(
            1 for task in query_task_records if "gdcic_captcha_required" in _list(task.get("blocker_taxonomy"))
        ),
        "review_required_count": sum(1 for task in query_task_records if str(task.get("query_probe_state") or "") == "REVIEW_REQUIRED"),
        "fail_closed_count": sum(1 for task in query_task_records if str(task.get("query_probe_state") or "").startswith("FAIL_CLOSED")),
        "query_probe_state_counts": states,
        "gdcic_route_state_counts": route_state_counts,
        "gdcic_blocker_taxonomy_counts": blockers,
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _task_has_ready_route_group(task: Mapping[str, Any], groups: set[str]) -> bool:
    for route in _list(task.get("route_attempts")):
        if not isinstance(route, Mapping):
            continue
        if (
            str(route.get("route_state") or "") == "READBACK_READY_PUBLIC_SOURCE"
            and str(route.get("route_group") or "") in groups
        ):
            return True
    return False


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


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


def _first_text(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint([str(part or '') for part in parts])[:16]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangdong GDCIC QueryProbe v1.")
    parser.add_argument("--active-conflict-root", default=str(DEFAULT_ACTIVE_CONFLICT_ROOT))
    parser.add_argument("--active-conflict-json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--max-live-tasks", type=int)
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangdong_gdcic_query_probe(
        active_conflict_root=args.active_conflict_root,
        active_conflict_json=args.active_conflict_json,
        output_root=args.output_root,
        enable_live_public_query=args.enable_live_public_query,
        max_live_tasks=args.max_live_tasks,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
