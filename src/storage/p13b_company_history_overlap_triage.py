from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


P13B_COMPANY_HISTORY_OVERLAP_TRIAGE_KIND = "p13b_company_history_overlap_triage_v1_manifest"
P13B_COMPANY_HISTORY_OVERLAP_TRIAGE_VERSION = 1
P13B_COMPANY_HISTORY_OVERLAP_TRIAGE_ADAPTER_ID = "p13b-company-history-overlap-triage-v1-builder"

DATA_GGZY_BASE_URL = "https://data.ggzy.gov.cn"
DATA_GGZY_COMPANY_SEARCH_URL = f"{DATA_GGZY_BASE_URL}/yjcx/index/search"
DATA_GGZY_BID_LIST_URL = f"{DATA_GGZY_BASE_URL}/yjcx/index/bid_list"
DATA_GGZY_BID_SHOW_URL = f"{DATA_GGZY_BASE_URL}/yjcx/index/bid_show"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-value-closeout-p12-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-company-history-overlap-triage-v1")
DEFAULT_YGP_EXPANSION_ROOT = Path("tmp/evaluation-real-samples/p13b-ygp-original-readback-expansion-v1")
DEFAULT_YGP_COVERAGE_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-ygp-city-coverage-closeout-v1")
DEFAULT_HISTORY_WINDOW_YEARS = (1, 2, 3)
DEFAULT_MAX_BID_RECORDS_PER_COMPANY = 10

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_p13b_company_history_overlap_triage(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    ygp_expansion_root: str | Path | None = None,
    ygp_coverage_closeout_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_public_query: bool = False,
    max_live_companies: int | None = None,
    max_bid_records_per_company: int = DEFAULT_MAX_BID_RECORDS_PER_COMPANY,
    history_window_years: list[int] | tuple[int, ...] = DEFAULT_HISTORY_WINDOW_YEARS,
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_dir = Path(input_root)
    ygp_expansion_dir = Path(ygp_expansion_root) if ygp_expansion_root else None
    ygp_coverage_dir = Path(ygp_coverage_closeout_root) if ygp_coverage_closeout_root else None
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    input_mode = "YGP_ORIGINAL_READBACK_EXPANSION" if ygp_expansion_dir else "P12_VALUE_CLOSEOUT"
    ygp_input_count = 0
    if ygp_expansion_dir:
        ygp_input_table = _load_json(
            ygp_expansion_dir / "p13b-ygp-overlap-triage-input-table.json",
            blocking_reasons,
            "p13b_ygp_overlap_triage_input_table_missing",
        )
        ygp_expansion = _load_json(
            ygp_expansion_dir / "p13b-ygp-original-readback-expansion-v1.json",
            blocking_reasons,
            "p13b_ygp_original_readback_expansion_missing",
        )
        ygp_coverage = (
            _load_json(
                ygp_coverage_dir / "guangdong-ygp-city-coverage-closeout-v1.json",
                blocking_reasons,
                "guangdong_ygp_city_coverage_closeout_missing",
            )
            if ygp_coverage_dir
            else {}
        )
        ygp_inputs = _ygp_overlap_inputs(ygp_input_table, ygp_expansion)
        ygp_input_count = len(ygp_inputs)
        project_task_records = _ygp_project_task_records(ygp_inputs, _coverage_by_project(_source_manifest(ygp_coverage)))
        company_query_tasks = _company_query_tasks(project_task_records, created_at=created, dedupe_by_company=True)
    else:
        project_table = _load_json(in_dir / "project-value-table.json", blocking_reasons, "project_value_table_missing")
        candidate_table = _load_json(
            in_dir / "candidate-group-verification-table.json",
            blocking_reasons,
            "candidate_group_verification_table_missing",
        )
        selected_projects = [
            dict(record)
            for record in _list(project_table.get("records"))
            if isinstance(record, Mapping)
            and str(record.get("value_closeout_state") or "") == "EXTERNAL_CONFLICT_SOURCE_REQUIRED"
        ]
        candidate_records = [
            dict(record)
            for record in _list(candidate_table.get("records"))
            if isinstance(record, Mapping)
        ]
        selected_project_ids = {str(record.get("project_id") or "") for record in selected_projects}
        candidates_by_project: dict[str, list[dict[str, Any]]] = {}
        for record in candidate_records:
            project_id = str(record.get("project_id") or "")
            if project_id in selected_project_ids:
                candidates_by_project.setdefault(project_id, []).append(record)
        project_task_records = _project_task_records(selected_projects, candidates_by_project)
        company_query_tasks = _company_query_tasks(project_task_records, created_at=created)

    execution_mode = "LIVE_PUBLIC_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED"
    company_history_query_records, bid_show_records, overlap_signal_records = _execute_company_history_tasks(
        company_query_tasks,
        created_at=created,
        enable_live_public_query=enable_live_public_query,
        max_live_companies=max_live_companies,
        max_bid_records_per_company=max_bid_records_per_company,
        history_window_years=tuple(sorted({int(item) for item in history_window_years if int(item) > 0})),
        http_getter=http_getter,
    )
    manual_original_url_backtrace_table = _manual_original_url_backtrace_table(bid_show_records, overlap_signal_records)
    summary = _summary(
        project_task_records=project_task_records,
        company_history_query_records=company_history_query_records,
        bid_show_records=bid_show_records,
        overlap_signal_records=overlap_signal_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
        input_mode=input_mode,
        ygp_input_count=ygp_input_count,
    )
    manifest = {
        "manifest_version": P13B_COMPANY_HISTORY_OVERLAP_TRIAGE_VERSION,
        "manifest_kind": P13B_COMPANY_HISTORY_OVERLAP_TRIAGE_KIND,
        "adapter_id": P13B_COMPANY_HISTORY_OVERLAP_TRIAGE_ADAPTER_ID,
        "pipeline_stage": "P13BCompanyHistoryOverlapTriageV1",
        "manifest_id": f"P13B-COMPANY-HISTORY-OVERLAP-{_fingerprint({'summary': summary, 'tasks': company_history_query_records})[:16]}",
        "created_at": created,
        "source_input_root": str(in_dir),
        "source_ygp_expansion_root": str(ygp_expansion_dir or ""),
        "source_ygp_coverage_closeout_root": str(ygp_coverage_dir or ""),
        "source_project_value_table": str(in_dir / "project-value-table.json"),
        "source_candidate_group_verification_table": str(in_dir / "candidate-group-verification-table.json"),
        "source_profile_id": "NATIONAL-GGZY-DATA-SERVICE-COMPANY-AWARD-HISTORY",
        "input_mode": input_mode,
        "source_base_url": DATA_GGZY_BASE_URL,
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "max_live_companies": max_live_companies,
        "max_bid_records_per_company": max_bid_records_per_company,
        "history_window_years": list(history_window_years),
        "project_task_records": project_task_records,
        "company_history_query_records": company_history_query_records,
        "bid_show_records": bid_show_records,
        "overlap_signal_records": overlap_signal_records,
        "manual_original_url_backtrace_table": manual_original_url_backtrace_table,
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
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "p13b_company_history_overlap_triage_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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

    (out_dir / "company-history-overlap-triage-v1.json").write_text(text, encoding="utf-8")
    return result


def _project_task_records(
    selected_projects: list[dict[str, Any]],
    candidates_by_project: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for project in selected_projects:
        project_id = str(project.get("project_id") or "")
        candidates = candidates_by_project.get(project_id, [])
        companies = _dedupe(
            company
            for candidate in candidates
            for company in _list(candidate.get("candidate_group_members"))
            if str(company or "").strip()
        )
        people = _dedupe(
            str(candidate.get("responsible_person_name") or "").strip()
            for candidate in candidates
            if str(candidate.get("responsible_person_name") or "").strip()
        )
        records.append(
            {
                "project_task_id": _stable_id("P13B-PROJECT", project_id),
                "project_id": project_id,
                "project_name": str(project.get("project_name") or ""),
                "candidate_group_count": len(candidates),
                "candidate_group_ids": _dedupe(str(candidate.get("candidate_group_id") or "") for candidate in candidates),
                "candidate_companies": companies,
                "responsible_person_names": people,
                "candidate_notice_source_urls": _list(project.get("candidate_notice_source_urls")),
                "project_source_urls": _list(project.get("project_source_urls")),
                "value_closeout_state": str(project.get("value_closeout_state") or ""),
                "p13b_triage_state": "P13B_COMPANY_HISTORY_TRIAGE_REQUIRED",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _ygp_overlap_inputs(input_table: Mapping[str, Any], expansion: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = [
        dict(record)
        for record in _list(input_table.get("records"))
        if isinstance(record, Mapping)
    ]
    if records:
        return records
    manifest = _source_manifest(expansion)
    return [
        dict(record)
        for record in _list(manifest.get("overlap_triage_input_records"))
        if isinstance(record, Mapping)
    ]


def _coverage_by_project(coverage_manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for record in _list(coverage_manifest.get("city_coverage_records")):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "")
        if project_id:
            out[project_id] = dict(record)
    return out


def _ygp_project_task_records(
    ygp_inputs: list[dict[str, Any]],
    coverage_by_project: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in ygp_inputs:
        project_id = str(item.get("project_id") or "")
        if not project_id:
            continue
        coverage = dict(coverage_by_project.get(project_id) or {})
        project = grouped.setdefault(
            project_id,
            {
                "project_task_id": _stable_id("P13B-YGP-PROJECT", project_id),
                "project_id": project_id,
                "project_name": str(item.get("project_name") or coverage.get("project_name") or ""),
                "city_code": str(item.get("city_code") or coverage.get("city_code") or ""),
                "candidate_group_count": 0,
                "candidate_group_ids": [],
                "candidate_companies": [],
                "candidate_company_input_counts": {},
                "responsible_person_names": [],
                "candidate_notice_source_urls": [],
                "project_source_urls": [],
                "value_closeout_state": "YGP_COVERAGE_READY_FOR_P13B",
                "p13b_triage_state": "P13B_COMPANY_HISTORY_TRIAGE_REQUIRED",
                "ygp_city_coverage_state": str(coverage.get("city_coverage_state") or ""),
                "ygp_recommended_next_action": str(coverage.get("recommended_next_action") or ""),
                "backlog_tracked": _int(coverage.get("oversize_queue_count")) + _int(coverage.get("limit_deferred_queue_count")) > 0
                or bool(item.get("backlog_tracked")),
                "ygp_overlap_input_count": 0,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
        )
        company = str(item.get("candidate_company_name") or "").strip()
        if company:
            project["candidate_companies"] = _dedupe([*project["candidate_companies"], company])
            counts = dict(project.get("candidate_company_input_counts") or {})
            counts[company] = _int(counts.get(company)) + 1
            project["candidate_company_input_counts"] = counts
        project["responsible_person_names"] = _dedupe(
            [*project["responsible_person_names"], *_list(item.get("responsible_person_candidates"))]
        )
        urls = _dedupe([*project["candidate_notice_source_urls"], item.get("source_07_url"), item.get("source_url")])
        project["candidate_notice_source_urls"] = urls
        project["project_source_urls"] = urls
        project["ygp_overlap_input_count"] = _int(project.get("ygp_overlap_input_count")) + 1
    return list(grouped.values())


def _company_query_tasks(
    project_task_records: list[dict[str, Any]],
    *,
    created_at: str,
    dedupe_by_company: bool = False,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    by_company: dict[str, dict[str, Any]] = {}
    for project in project_task_records:
        for company in _list(project.get("candidate_companies")):
            company_name = str(company or "").strip()
            if not company_name:
                continue
            normalized_company = _norm(company_name)
            key = normalized_company if dedupe_by_company else f"{project.get('project_id')}|{normalized_company}"
            if key in seen:
                if dedupe_by_company:
                    existing = by_company[key]
                    existing["responsible_person_names"] = _dedupe(
                        [*existing.get("responsible_person_names", []), *_list(project.get("responsible_person_names"))]
                    )
                    existing["candidate_notice_source_urls"] = _dedupe(
                        [*existing.get("candidate_notice_source_urls", []), *_list(project.get("candidate_notice_source_urls"))]
                    )
                    existing["related_project_refs"] = _dedupe_project_refs(
                        [
                            *existing.get("related_project_refs", []),
                            _project_ref_for_company(project, company_name),
                        ]
                    )
                    existing["ygp_input_count"] = _int(existing.get("ygp_input_count")) + _int(
                        dict(project.get("candidate_company_input_counts") or {}).get(company_name, 1)
                    )
                continue
            seen.add(key)
            search_url = _company_search_url(company_name)
            task = {
                "company_history_query_task_id": _stable_id(
                    "P13B-COMPANY-HISTORY",
                    "YGP" if dedupe_by_company else project.get("project_id"),
                    company_name,
                ),
                "project_id": str(project.get("project_id") or ""),
                "project_name": str(project.get("project_name") or ""),
                "candidate_company_name": company_name,
                "candidate_company_variants": _company_search_variants(company_name),
                "responsible_person_names": _list(project.get("responsible_person_names")),
                "candidate_notice_source_urls": _list(project.get("candidate_notice_source_urls")),
                "search_url": search_url,
                "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                "query_state": "PLAN_ONLY_NOT_EXECUTED",
                "related_project_refs": [_project_ref_for_company(project, company_name)] if dedupe_by_company else [],
                "ygp_input_count": _int(dict(project.get("candidate_company_input_counts") or {}).get(company_name, 1))
                if dedupe_by_company
                else 0,
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            if dedupe_by_company:
                by_company[key] = task
            tasks.append(task)
    return tasks


def _project_ref_for_company(project: Mapping[str, Any], company_name: str) -> dict[str, Any]:
    return {
        "project_id": str(project.get("project_id") or ""),
        "project_name": str(project.get("project_name") or ""),
        "city_code": str(project.get("city_code") or ""),
        "candidate_company_name": company_name,
        "responsible_person_names": _list(project.get("responsible_person_names")),
        "candidate_notice_source_urls": _list(project.get("candidate_notice_source_urls")),
        "ygp_city_coverage_state": str(project.get("ygp_city_coverage_state") or ""),
        "backlog_tracked": bool(project.get("backlog_tracked")),
    }


def _dedupe_project_refs(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = f"{value.get('project_id')}|{value.get('candidate_company_name')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(value))
    return out


def _execute_company_history_tasks(
    tasks: list[dict[str, Any]],
    *,
    created_at: str,
    enable_live_public_query: bool,
    max_live_companies: int | None,
    max_bid_records_per_company: int,
    history_window_years: tuple[int, ...],
    http_getter: HttpGetter | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not enable_live_public_query:
        return tasks, [], []
    getter = http_getter or _default_http_getter
    company_records: list[dict[str, Any]] = []
    bid_show_records: list[dict[str, Any]] = []
    overlap_records: list[dict[str, Any]] = []
    attempted = 0
    cutoff_year = _created_year(created_at) - max(history_window_years or DEFAULT_HISTORY_WINDOW_YEARS)
    for task in tasks:
        if max_live_companies is not None and attempted >= max_live_companies:
            company_records.append(
                {
                    **task,
                    "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                    "query_state": "SOURCE_BLOCKED_RETRY_REQUIRED",
                    "blocker_taxonomy": ["max_live_companies_deferred"],
                    "max_live_companies": max_live_companies,
                }
            )
            continue
        attempted += 1
        company_record, bid_records = _execute_company_task(
            task,
            getter=getter,
            max_bid_records_per_company=max_bid_records_per_company,
            cutoff_year=cutoff_year,
            created_at=created_at,
        )
        company_records.append(company_record)
        bid_show_records.extend(bid_records)
        overlap_records.extend(_overlap_records_for_company(company_record, bid_records, created_at=created_at))
    return company_records, bid_show_records, overlap_records


def _execute_company_task(
    task: Mapping[str, Any],
    *,
    getter: HttpGetter,
    max_bid_records_per_company: int,
    cutoff_year: int,
    created_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    company_name = str(task.get("candidate_company_name") or "")
    company_variants = [
        str(item).strip()
        for item in _list(task.get("candidate_company_variants"))
        if str(item).strip()
    ] or _company_search_variants(company_name)
    search_attempts: list[dict[str, Any]] = []
    search_attempt: dict[str, Any] = {}
    search_records: list[dict[str, Any]] = []
    matched: dict[str, Any] = {}
    matched_search_keyword = ""
    for keyword in company_variants:
        search_url = _company_search_url(keyword)
        current_attempt = _http_json(
            search_url,
            getter,
            route="company_search",
            task={**dict(task), "search_keyword": keyword},
        )
        current_attempt["search_keyword"] = keyword
        search_attempts.append(current_attempt)
        blocker = _blockers_from_attempt(current_attempt)
        if blocker:
            return (
                {
                    **dict(task),
                    "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                    "query_state": "SOURCE_BLOCKED_RETRY_REQUIRED",
                    "search_attempt": current_attempt,
                    "search_attempts": search_attempts,
                    "matched_search_keyword": matched_search_keyword,
                    "blocker_taxonomy": blocker,
                },
                [],
            )
        current_records = _extract_records(
            current_attempt.get("json_payload"),
            preferred_paths=(("result", "records"), ("result", "data", "records")),
        )
        current_matched = _match_company(
            current_records,
            company_name,
            company_variants=company_variants,
        )
        if current_matched:
            search_attempt = current_attempt
            search_records = current_records
            matched = current_matched
            matched_search_keyword = keyword
            break
        if not search_attempt:
            search_attempt = current_attempt
            search_records = current_records
    if not matched:
        return (
            {
                **dict(task),
                "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                "query_state": "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW",
                "search_attempt": search_attempt,
                "search_attempts": search_attempts,
                "search_total": _extract_total(search_attempt.get("json_payload")),
                "matched_search_keyword": matched_search_keyword,
                "matched_company_name": "",
                "uniscid": "",
                "blocker_taxonomy": ["company_search_no_exact_or_alias_match_review"],
                "query_miss_is_not_clearance": True,
            },
            [],
        )
    uniscid = str(matched.get("uniscid") or "").strip()
    bid_list_url = _bid_list_url(uniscid, page_size=max_bid_records_per_company)
    bid_list_attempt = _http_json(bid_list_url, getter, route="bid_list", task=task)
    bid_blocker = _blockers_from_attempt(bid_list_attempt)
    if bid_blocker:
        return (
            {
                **dict(task),
                "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                "query_state": "SOURCE_BLOCKED_RETRY_REQUIRED",
                "search_attempt": search_attempt,
                "search_attempts": search_attempts,
                "bid_list_attempt": bid_list_attempt,
                "matched_search_keyword": matched_search_keyword,
                "matched_company_name": str(matched.get("entname") or matched.get("name") or company_name),
                "uniscid": uniscid,
                "blocker_taxonomy": bid_blocker,
            },
            [],
        )
    bid_records_raw = _extract_records(
        bid_list_attempt.get("json_payload"),
        preferred_paths=(("result", "data", "records"), ("result", "records")),
    )
    selected_bid_records = [
        record
        for record in bid_records_raw[:max_bid_records_per_company]
        if _within_history_window(str(record.get("createTime") or ""), cutoff_year)
    ]
    bid_show_records: list[dict[str, Any]] = []
    for bid in selected_bid_records:
        bid_id = str(bid.get("id") or "").strip()
        if not bid_id:
            continue
        bid_show_url = _bid_show_url(bid_id)
        show_attempt = _http_json(bid_show_url, getter, route="bid_show", task={**dict(task), "bid_record_id": bid_id})
        bid_show_records.append(
            _bid_show_record(
                task,
                bid_record=bid,
                show_attempt=show_attempt,
                bid_show_url=bid_show_url,
                matched_company=matched,
                created_at=created_at,
            )
        )
    query_state = "COMPANY_HISTORY_RECORD_FOUND" if selected_bid_records else "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"
    return (
        {
            **dict(task),
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "query_state": query_state,
            "search_attempt": search_attempt,
            "search_attempts": search_attempts,
            "bid_list_attempt": bid_list_attempt,
            "matched_search_keyword": matched_search_keyword,
            "matched_company_name": str(matched.get("entname") or matched.get("name") or company_name),
            "uniscid": uniscid,
            "search_total": _extract_total(search_attempt.get("json_payload")),
            "bid_list_total": _extract_total(bid_list_attempt.get("json_payload")),
            "selected_bid_record_count": len(selected_bid_records),
            "max_bid_records_per_company": max_bid_records_per_company,
            "query_miss_is_not_clearance": True,
            "blocker_taxonomy": [] if selected_bid_records else ["bid_list_no_recent_record_review"],
        },
        bid_show_records,
    )


def _bid_show_record(
    task: Mapping[str, Any],
    *,
    bid_record: Mapping[str, Any],
    show_attempt: Mapping[str, Any],
    bid_show_url: str,
    matched_company: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    blockers = _blockers_from_attempt(show_attempt)
    result = _result_payload(show_attempt.get("json_payload"))
    content_html = str(result.get("content") or "")
    content_text = _html_to_text(content_html)
    extracted_people = _extract_responsible_people(content_text)
    period_text = _extract_period_text(content_text)
    award_date = _extract_award_date(content_text) or str(bid_record.get("createTime") or "")
    original_url = str(result.get("url") or bid_record.get("url") or "")
    time_window = _time_window_review_fields(
        period_text,
        award_date,
        reference_date_text=created_at,
    )
    company_names = _dedupe(
        [
            str(matched_company.get("entname") or ""),
            str(task.get("candidate_company_name") or ""),
            str(bid_record.get("bidOrgName") or ""),
        ]
    )
    if blockers:
        state = "SOURCE_BLOCKED_RETRY_REQUIRED"
    elif extracted_people and period_text:
        state = "BID_SHOW_PERSON_AND_PERIOD_EXTRACTED"
    elif original_url:
        state = "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
    else:
        state = "BID_SHOW_PERSON_OR_PERIOD_MISSING_REVIEW"
    text_probe = content_text[:600]
    return {
        "bid_show_record_id": _stable_id("P13B-BID-SHOW", task.get("project_id"), task.get("candidate_company_name"), bid_record.get("id")),
        "company_history_query_task_id": str(task.get("company_history_query_task_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "project_name": str(task.get("project_name") or ""),
        "candidate_company_name": str(task.get("candidate_company_name") or ""),
        "matched_company_names": company_names,
        "responsible_person_names": _list(task.get("responsible_person_names")),
        "uniscid": str(matched_company.get("uniscid") or ""),
        "bid_record_id": str(bid_record.get("id") or ""),
        "bid_project_name": str(result.get("title") or bid_record.get("projectName") or ""),
        "bid_area_code": str(result.get("areaCode") or bid_record.get("areaCode") or ""),
        "bid_create_time": str(bid_record.get("createTime") or ""),
        "bid_price": str(result.get("bidPrice") or bid_record.get("bidPrice") or ""),
        "bid_show_url": bid_show_url,
        "original_notice_url": original_url,
        "extracted_responsible_person_names": extracted_people,
        "extracted_period_text": period_text,
        "extracted_award_date": award_date,
        "time_window_review_state": time_window["time_window_review_state"],
        "time_window_reference_date": time_window["time_window_reference_date"],
        "estimated_performance_end_date": time_window["estimated_performance_end_date"],
        "time_window_review_basis": time_window["time_window_review_basis"],
        "bid_show_state": state,
        "original_notice_backtrace_required": state == "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
        "text_probe": text_probe,
        "text_probe_sha256": _sha256(text_probe),
        "record_payload_sha256": _fingerprint({"bid_record": bid_record, "field_probe": text_probe, "original_url": original_url}),
        "route_attempt": show_attempt,
        "blocker_taxonomy": blockers,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _overlap_records_for_company(
    company_record: Mapping[str, Any],
    bid_show_records: list[dict[str, Any]],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    candidate_people = {str(item).strip() for item in _list(company_record.get("responsible_person_names")) if str(item).strip()}
    candidate_company = str(company_record.get("candidate_company_name") or "")
    for show in bid_show_records:
        extracted_people = {str(item).strip() for item in _list(show.get("extracted_responsible_person_names")) if str(item).strip()}
        person_matches = sorted(candidate_people & extracted_people)
        company_match = _contains_company(show.get("matched_company_names"), candidate_company)
        time_window_state = str(show.get("time_window_review_state") or "")
        if person_matches and company_match and time_window_state == "TIME_WINDOW_OVERLAP_REVIEW":
            state = "OVERLAP_SIGNAL_REVIEW_REQUIRED"
            reasons = ["same_responsible_person", "candidate_company_matched", "contract_or_delivery_time_present_in_bid_show"]
        elif (
            person_matches
            and company_match
            and str(show.get("original_notice_url") or "")
            and str(show.get("extracted_period_text") or "").strip()
            and time_window_state == "TIME_WINDOW_REVIEW_REQUIRED"
        ):
            state = "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
            reasons = ["original_notice_url_available", "bid_show_time_window_needs_review"]
        elif (
            str(show.get("original_notice_url") or "")
            and (person_matches or not extracted_people)
            and time_window_state != "TIME_WINDOW_NO_OVERLAP_REVIEW"
        ):
            state = "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
            reasons = ["original_notice_url_available", "bid_show_person_or_period_needs_review"]
        else:
            state = "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"
            reasons = ["no_same_person_company_time_window_signal_in_bid_show"]
        records.append(
            {
                "overlap_signal_id": _stable_id("P13B-OVERLAP", show.get("bid_show_record_id"), state),
                "project_id": str(show.get("project_id") or ""),
                "project_name": str(show.get("project_name") or ""),
                "candidate_company_name": candidate_company,
                "responsible_person_names": sorted(candidate_people),
                "matched_person_names": person_matches,
                "bid_show_record_id": str(show.get("bid_show_record_id") or ""),
                "bid_project_name": str(show.get("bid_project_name") or ""),
                "historical_project_area_code": str(show.get("bid_area_code") or ""),
                "bid_area_code": str(show.get("bid_area_code") or ""),
                "bid_show_url": str(show.get("bid_show_url") or ""),
                "original_notice_url": str(show.get("original_notice_url") or ""),
                "extracted_period_text": str(show.get("extracted_period_text") or ""),
                "extracted_award_date": str(show.get("extracted_award_date") or ""),
                "time_window_review_state": time_window_state,
                "time_window_reference_date": str(show.get("time_window_reference_date") or ""),
                "estimated_performance_end_date": str(show.get("estimated_performance_end_date") or ""),
                "time_window_review_basis": str(show.get("time_window_review_basis") or ""),
                "overlap_signal_state": state,
                "review_reasons": reasons,
                "overlap_source_stage": "DATA_GGZY_BID_SHOW_DIRECT"
                if state == "OVERLAP_SIGNAL_REVIEW_REQUIRED"
                else "ORIGINAL_NOTICE_BACKTRACE_NEEDED"
                if state == "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
                else "DATA_GGZY_BID_SHOW_REVIEW",
                "original_notice_backtrace_required": state == "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                "release_evidence_probe_triggered": state == "OVERLAP_SIGNAL_REVIEW_REQUIRED",
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _manual_original_url_backtrace_table(
    bid_show_records: list[dict[str, Any]],
    overlap_signal_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signal_by_show = {str(record.get("bid_show_record_id") or ""): record for record in overlap_signal_records}
    rows: list[dict[str, Any]] = []
    for show in bid_show_records:
        original_url = str(show.get("original_notice_url") or "")
        if not original_url:
            continue
        signal = signal_by_show.get(str(show.get("bid_show_record_id") or ""), {})
        state = str(signal.get("overlap_signal_state") or show.get("bid_show_state") or "")
        if state != "ORIGINAL_NOTICE_BACKTRACE_REQUIRED":
            continue
        rows.append(
            {
                "project_id": str(show.get("project_id") or ""),
                "candidate_company_name": str(show.get("candidate_company_name") or ""),
                "responsible_person_names": _list(show.get("responsible_person_names")),
                "bid_project_name": str(show.get("bid_project_name") or ""),
                "historical_project_area_code": str(show.get("bid_area_code") or ""),
                "bid_area_code": str(show.get("bid_area_code") or ""),
                "original_notice_url": original_url,
                "backtrace_reason": state,
                "suggested_next_step": "targeted_original_notice_01_to_12_backtrace",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _summary(
    *,
    project_task_records: list[Mapping[str, Any]],
    company_history_query_records: list[Mapping[str, Any]],
    bid_show_records: list[Mapping[str, Any]],
    overlap_signal_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
    input_mode: str = "P12_VALUE_CLOSEOUT",
    ygp_input_count: int = 0,
) -> dict[str, Any]:
    queried_company_count = sum(
        1
        for record in company_history_query_records
        if str(record.get("execution_mode") or "") == "LIVE_PUBLIC_QUERY_ATTEMPTED"
    )
    source_blocked_count = sum(
        1
        for record in company_history_query_records
        if str(record.get("query_state") or "") == "SOURCE_BLOCKED_RETRY_REQUIRED"
        and "max_live_companies_deferred" not in set(str(item) for item in _list(record.get("blocker_taxonomy")))
    )
    company_search_hit_count = sum(1 for record in company_history_query_records if str(record.get("uniscid") or ""))
    bid_list_hit_count = sum(1 for record in company_history_query_records if _int(record.get("bid_list_total")) > 0)
    return {
        "p13b_triage_state": "P13B_COMPANY_HISTORY_OVERLAP_TRIAGE_READY" if not blocking_reasons else "P13B_INPUT_BLOCKED",
        "input_mode": input_mode,
        "execution_mode": execution_mode,
        "ygp_input_count": ygp_input_count,
        "unique_company_count": len(company_history_query_records),
        "queried_company_count": queried_company_count,
        "company_search_hit_count": company_search_hit_count,
        "bid_list_hit_count": bid_list_hit_count,
        "project_task_count": len(project_task_records),
        "company_history_query_task_count": len(company_history_query_records),
        "company_history_record_found_count": sum(
            1 for record in company_history_query_records if str(record.get("query_state") or "") == "COMPANY_HISTORY_RECORD_FOUND"
        ),
        "bid_show_record_count": len(bid_show_records),
        "bid_show_person_and_period_extracted_count": sum(
            1 for record in bid_show_records if str(record.get("bid_show_state") or "") == "BID_SHOW_PERSON_AND_PERIOD_EXTRACTED"
        ),
        "overlap_signal_review_required_count": sum(
            1 for record in overlap_signal_records if str(record.get("overlap_signal_state") or "") == "OVERLAP_SIGNAL_REVIEW_REQUIRED"
        ),
        "overlap_signal_count": sum(
            1 for record in overlap_signal_records if str(record.get("overlap_signal_state") or "") == "OVERLAP_SIGNAL_REVIEW_REQUIRED"
        ),
        "original_notice_backtrace_required_count": sum(
            1 for record in overlap_signal_records if str(record.get("overlap_signal_state") or "") == "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
        ),
        "source_blocked_count": source_blocked_count,
        "company_query_state_counts": _counts(record.get("query_state") for record in company_history_query_records),
        "bid_show_state_counts": _counts(record.get("bid_show_state") for record in bid_show_records),
        "overlap_signal_state_counts": _counts(record.get("overlap_signal_state") for record in overlap_signal_records),
        "blocker_taxonomy_counts": _counts(
            blocker
            for record in [*company_history_query_records, *bid_show_records]
            for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _default_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaP13B/1.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": DATA_GGZY_BASE_URL + "/",
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
        return {
            "status_code": 0,
            "content_type": "",
            "body": "",
            "url": url,
            "error": str(exc.reason),
        }


def _http_json(url: str, getter: HttpGetter, *, route: str, task: Mapping[str, Any]) -> dict[str, Any]:
    response = dict(getter(url, {"route": route, "task": dict(task)}))
    status = int(response.get("status_code") or response.get("status") or 0)
    body = str(response.get("body") or response.get("content") or response.get("text") or "")
    parsed: Any = {}
    parse_error = ""
    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    return {
        "route": route,
        "url": str(response.get("url") or url),
        "status_code": status,
        "content_type": str(response.get("content_type") or ""),
        "body_sha256": _sha256(body) if body else "",
        "body_probe": body[:300],
        "json_payload": parsed if isinstance(parsed, Mapping) else {},
        "json_parse_error": parse_error,
        "error": str(response.get("error") or ""),
    }


def _blockers_from_attempt(attempt: Mapping[str, Any]) -> list[str]:
    status = int(attempt.get("status_code") or 0)
    body_probe = str(attempt.get("body_probe") or "")
    error = str(attempt.get("error") or "")
    blockers: list[str] = []
    if status in {403, 429}:
        blockers.append("data_ggzy_forbidden_or_rate_limited_review")
    if status in {500, 502, 503, 504}:
        blockers.append("data_ggzy_temporary_unavailable_retry_required")
    if status == 0 and error:
        blockers.append("data_ggzy_transport_error_retry_required")
    if "验证码" in body_probe or "captcha" in body_probe.lower():
        blockers.append("data_ggzy_captcha_or_challenge_review")
    if attempt.get("json_parse_error") and status == 200:
        blockers.append("data_ggzy_json_parse_failed_review")
    payload = attempt.get("json_payload")
    if isinstance(payload, Mapping) and payload.get("success") is False and status == 200:
        blockers.append("data_ggzy_api_success_false_review")
    return _dedupe(blockers)


def _extract_records(payload: Any, *, preferred_paths: tuple[tuple[str, ...], ...]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    for path in preferred_paths:
        value: Any = payload
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _extract_total(payload: Any) -> int:
    if not isinstance(payload, Mapping):
        return 0
    candidates: list[Any] = [
        payload.get("total"),
        (payload.get("result") or {}).get("total") if isinstance(payload.get("result"), Mapping) else None,
    ]
    result = payload.get("result")
    if isinstance(result, Mapping):
        data = result.get("data")
        if isinstance(data, Mapping):
            candidates.append(data.get("total"))
    for item in candidates:
        try:
            return int(item)
        except (TypeError, ValueError):
            continue
    return 0


def _result_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping) and isinstance(payload.get("result"), Mapping):
        return dict(payload.get("result") or {})
    return {}


def _match_company(
    records: Iterable[Mapping[str, Any]],
    company_name: str,
    *,
    company_variants: Iterable[str] | None = None,
) -> dict[str, Any]:
    normalized_targets = _dedupe(
        [
            _norm(company_name),
            *[_norm(item) for item in (company_variants or []) if _norm(item)],
        ]
    )
    fallback: dict[str, Any] = {}
    cached_records = [dict(record) for record in records if isinstance(record, Mapping)]
    for record in cached_records:
        entname = str(record.get("entname") or record.get("name") or "")
        if not fallback:
            fallback = dict(record)
        normalized_entname = _norm(entname)
        if normalized_entname and normalized_entname in normalized_targets:
            return dict(record)
    for record in cached_records:
        entname = str(record.get("entname") or record.get("name") or "")
        normalized_entname = _norm(entname)
        if any(
            target and normalized_entname and (target in normalized_entname or normalized_entname in target)
            for target in normalized_targets
        ):
            return dict(record)
    return fallback if len(cached_records) == 1 else {}


def _company_search_variants(company_name: str) -> list[str]:
    base = str(company_name or "").strip()
    if not base:
        return []
    variants: list[str] = [base]
    current = base
    for suffix in (
        "集团股份有限公司",
        "股份有限公司",
        "有限责任公司",
        "集团有限公司",
        "有限公司",
        "股份公司",
        "公司",
    ):
        if current.endswith(suffix):
            current = current[: -len(suffix)].strip()
            if len(current) >= 6:
                variants.append(current)
    return _dedupe(variants)


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
        r"(?:工期（交货期）|工期\(交货期\)|工期|计划工期|交付期|交货期|供货期|完工期|完成期限|服务期|服务期限|服务时间|合同履行期限|合同履约期限|合同期限|合同周期|履行期限|履约期限|履约期|履约周期)\s*[:：]\s*([^。；;\n]{2,100})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _time_window_review_fields(period_text: str, award_date: str, *, reference_date_text: str) -> dict[str, str]:
    reference_date = _parse_date(reference_date_text) or datetime.utcnow()
    estimated_end, basis = _estimate_performance_end_date(period_text, award_date)
    if not str(period_text or "").strip():
        state = "TIME_WINDOW_NOT_AVAILABLE"
    elif estimated_end is None:
        state = "TIME_WINDOW_REVIEW_REQUIRED"
    elif estimated_end.date() >= reference_date.date():
        state = "TIME_WINDOW_OVERLAP_REVIEW"
    else:
        state = "TIME_WINDOW_NO_OVERLAP_REVIEW"
    return {
        "time_window_review_state": state,
        "time_window_reference_date": reference_date.date().isoformat(),
        "estimated_performance_end_date": estimated_end.date().isoformat() if estimated_end else "",
        "time_window_review_basis": basis,
    }


def _estimate_performance_end_date(period_text: str, award_date: str) -> tuple[datetime | None, str]:
    period = str(period_text or "")
    explicit_dates = _parse_dates(period)
    if explicit_dates:
        return max(explicit_dates), "period_text_explicit_end_date"
    start = _parse_date(award_date)
    if not start:
        return None, "award_date_missing_for_duration_estimate"
    days_match = re.search(r"([0-9]{1,5})\s*(?:日历天|天|日)", period)
    if days_match:
        return start + timedelta(days=int(days_match.group(1))), "award_date_plus_duration_days"
    months_match = re.search(r"([0-9]{1,3})\s*(?:个月|月)", period)
    if months_match:
        return start + timedelta(days=int(months_match.group(1)) * 30), "award_date_plus_duration_months_approx"
    years_match = re.search(r"([0-9]{1,2})\s*年", period)
    if years_match:
        return start + timedelta(days=int(years_match.group(1)) * 365), "award_date_plus_duration_years_approx"
    return None, "period_text_not_machine_estimable"


def _parse_dates(text: str) -> list[datetime]:
    dates: list[datetime] = []
    for match in re.finditer(r"(20[0-9]{2})年([0-9]{1,2})月([0-9]{1,2})日", str(text or "")):
        try:
            dates.append(datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    for match in re.finditer(r"(20[0-9]{2})[-/]([0-9]{1,2})[-/]([0-9]{1,2})", str(text or "")):
        try:
            dates.append(datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    return dates


def _parse_date(text: str) -> datetime | None:
    dates = _parse_dates(text)
    return dates[0] if dates else None


def _extract_award_date(text: str) -> str:
    patterns = [
        r"(?:中标日期|成交日期|公告日期|发布日期)\s*[:：]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _html_to_text(content: str) -> str:
    text = re.sub(r"<\s*br\s*/?>", "\n", content, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _within_history_window(date_text: str, cutoff_year: int) -> bool:
    year = _extract_year(date_text)
    return year == 0 or year >= cutoff_year


def _extract_year(date_text: str) -> int:
    match = re.search(r"(20[0-9]{2})", date_text)
    return int(match.group(1)) if match else 0


def _created_year(created_at: str) -> int:
    match = re.search(r"(20[0-9]{2})", created_at)
    if match:
        return int(match.group(1))
    return datetime.utcnow().year


def _contains_company(company_names: Any, candidate_company: str) -> bool:
    candidate = _norm(candidate_company)
    if not candidate:
        return False
    for name in _list(company_names):
        normalized = _norm(str(name or ""))
        if normalized and (candidate in normalized or normalized in candidate):
            return True
    return False


def _company_search_url(company_name: str) -> str:
    return DATA_GGZY_COMPANY_SEARCH_URL + "?" + urllib.parse.urlencode(
        {"keyword": company_name, "pageNo": 1, "pageSize": 10}
    )


def _bid_list_url(uniscid: str, *, page_size: int) -> str:
    return DATA_GGZY_BID_LIST_URL + "?" + urllib.parse.urlencode(
        {"uniscid": uniscid, "tos": "", "pageNo": 1, "pageSize": page_size}
    )


def _bid_show_url(record_id: str) -> str:
    return DATA_GGZY_BID_SHOW_URL + "?" + urllib.parse.urlencode({"id": record_id})


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


def _norm(value: str) -> str:
    return re.sub(r"[\s（）()；;，,、·\-—_]+", "", value or "").lower()


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _parse_history_window_years(value: str) -> list[int]:
    years: list[int] = []
    for part in re.split(r"[,，\s]+", value):
        if not part:
            continue
        try:
            years.append(int(part))
        except ValueError:
            continue
    return years or list(DEFAULT_HISTORY_WINDOW_YEARS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B company history overlap triage manifest.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--ygp-expansion-root", default="")
    parser.add_argument("--ygp-coverage-closeout-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--max-live-companies", type=int, default=None)
    parser.add_argument("--max-bid-records-per-company", type=int, default=DEFAULT_MAX_BID_RECORDS_PER_COMPANY)
    parser.add_argument("--history-window-years", default="1,2,3")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_company_history_overlap_triage(
        input_root=args.input_root,
        ygp_expansion_root=args.ygp_expansion_root or None,
        ygp_coverage_closeout_root=args.ygp_coverage_closeout_root or None,
        output_root=args.output_root,
        enable_live_public_query=args.enable_live_public_query,
        max_live_companies=args.max_live_companies,
        max_bid_records_per_company=args.max_bid_records_per_company,
        history_window_years=_parse_history_window_years(args.history_window_years),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
