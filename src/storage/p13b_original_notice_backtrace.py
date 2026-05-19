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


P13B_ORIGINAL_NOTICE_BACKTRACE_KIND = "p13b_original_notice_backtrace_v1_manifest"
P13B_ORIGINAL_NOTICE_BACKTRACE_VERSION = 1
P13B_ORIGINAL_NOTICE_BACKTRACE_ADAPTER_ID = "p13b-original-notice-backtrace-v1-builder"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-company-history-overlap-triage-v1-smoke")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-original-notice-backtrace-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
RELEASE_EVIDENCE_SOURCE_TARGETS = [
    "construction_permit",
    "contract_filing_or_contract_credit_info",
    "completion_or_acceptance_filing",
    "project_manager_change_notice",
    "construction_permit_change",
    "owner_approved_non_contractor_shutdown_over_120_days",
    "same_project_adjacent_section_or_phase_exception",
    "administrative_penalty_or_complaint_decision",
]
HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
MISSING_ORIGINAL_NOTICE_URL_MARKERS = {
    "",
    "-",
    "--",
    "null",
    "none",
    "nan",
    "n/a",
    "na",
    "无",
    "暂无",
    "无链接",
    "公告地址为空",
    "原文地址为空",
    "原文链接为空",
}
MISSING_ORIGINAL_NOTICE_URL_PHRASES = ("公告地址为空", "原文地址为空", "原文链接为空")


def build_p13b_original_notice_backtrace(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    input_json: str | Path | None = None,
    company_history_triage_root: str | Path | None = None,
    ygp_readback_root: str | Path | None = None,
    ygp_readback_json: str | Path | None = None,
    browser_readback_root: str | Path | None = None,
    browser_readback_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_public_query: bool = False,
    max_live_original_notices: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_dir = Path(company_history_triage_root) if company_history_triage_root else Path(input_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(input_json) if input_json else in_dir / "company-history-overlap-triage-v1.json"
    blocking_reasons: list[str] = []
    p13b_payload = _load_json(source_path, blocking_reasons, "p13b_company_history_overlap_triage_missing")
    source_manifest = _source_manifest(p13b_payload)
    ygp_readback_lookup = _load_ygp_readback_lookup(
        ygp_readback_root=ygp_readback_root,
        ygp_readback_json=ygp_readback_json,
    )
    browser_readback_lookup = _load_browser_readback_lookup(
        browser_readback_root=browser_readback_root,
        browser_readback_json=browser_readback_json,
    )
    execution_mode = "LIVE_PUBLIC_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED"
    original_notice_task_records = _prioritize_original_notice_tasks(
        _task_records_from_p13b(
            source_manifest,
            created_at=created,
            project_ids=project_ids,
        )
    )
    original_notice_task_triage_table = _original_notice_task_triage_table(original_notice_task_records)
    fetch_records, extraction_records, overlap_records = _execute_original_notice_tasks(
        original_notice_task_records,
        created_at=created,
        enable_live_public_query=enable_live_public_query,
        max_live_original_notices=max_live_original_notices,
        http_getter=http_getter,
        ygp_readback_lookup=ygp_readback_lookup,
        browser_readback_lookup=browser_readback_lookup,
    )
    manual_release_evidence_probe_table = _manual_release_evidence_probe_table(overlap_records)
    summary = _summary(
        original_notice_task_records=original_notice_task_records,
        fetch_records=fetch_records,
        extraction_records=extraction_records,
        overlap_records=overlap_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": P13B_ORIGINAL_NOTICE_BACKTRACE_VERSION,
        "manifest_kind": P13B_ORIGINAL_NOTICE_BACKTRACE_KIND,
        "adapter_id": P13B_ORIGINAL_NOTICE_BACKTRACE_ADAPTER_ID,
        "pipeline_stage": "P13BOriginalNoticeBacktraceV1",
        "manifest_id": f"P13B-ORIGINAL-NOTICE-BACKTRACE-{_fingerprint({'summary': summary, 'tasks': original_notice_task_records})[:16]}",
        "created_at": created,
        "source_input_root": str(in_dir),
        "source_input_json": str(source_path),
        "source_company_history_triage_root": str(company_history_triage_root or ""),
        "ygp_readback_root": str(ygp_readback_root or ""),
        "ygp_readback_json": str(ygp_readback_json or ""),
        "ygp_readback_record_count": _ygp_readback_record_count(ygp_readback_lookup),
        "browser_readback_root": str(browser_readback_root or ""),
        "browser_readback_json": str(browser_readback_json or ""),
        "browser_readback_record_count": _browser_readback_record_count(browser_readback_lookup),
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "max_live_original_notices": max_live_original_notices,
        "project_ids": list(project_ids),
        "original_notice_task_records": original_notice_task_records,
        "original_notice_task_triage_table": original_notice_task_triage_table,
        "original_notice_fetch_records": fetch_records,
        "original_notice_extraction_records": extraction_records,
        "original_notice_overlap_signal_records": overlap_records,
        "manual_release_evidence_probe_table": manual_release_evidence_probe_table,
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
            "ygp_original_url_pointer_only": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "p13b_original_notice_backtrace_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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
    _write_outputs(out_dir, result, fetch_records, extraction_records, overlap_records, manual_release_evidence_probe_table)
    return result


def _task_records_from_p13b(
    source_manifest: Mapping[str, Any],
    *,
    created_at: str,
    project_ids: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    rows = _list(source_manifest.get("manual_original_url_backtrace_table"))
    bid_show_by_key = _bid_show_lookup(source_manifest)
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        original_url = str(row.get("original_notice_url") or "").strip()
        if not original_url:
            continue
        project_id = str(row.get("project_id") or "")
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue
        company = str(row.get("candidate_company_name") or "")
        key = f"{project_id}|{company}|{original_url}"
        if key in seen:
            continue
        seen.add(key)
        bid_show = bid_show_by_key.get(key, {})
        tasks.append(
            {
                "original_notice_task_id": _stable_id("P13B-ORIGINAL-NOTICE", project_id, company, original_url),
                "project_id": project_id,
                "candidate_company_name": company,
                "responsible_person_names": _list(row.get("responsible_person_names")),
                "bid_project_name": str(row.get("bid_project_name") or bid_show.get("bid_project_name") or ""),
                "historical_project_area_code": str(
                    row.get("historical_project_area_code")
                    or row.get("bid_area_code")
                    or bid_show.get("historical_project_area_code")
                    or bid_show.get("bid_area_code")
                    or ""
                ),
                "bid_area_code": str(row.get("bid_area_code") or bid_show.get("bid_area_code") or ""),
                "original_notice_url": original_url,
                "bid_show_record_id": str(bid_show.get("bid_show_record_id") or ""),
                "bid_show_url": str(bid_show.get("bid_show_url") or ""),
                "backtrace_reason": str(row.get("backtrace_reason") or ""),
                "source_profile_note": "original_notice_pointer_from_data_ggzy_bid_show",
                "ygp_original_url_pointer_only": "ygp.gdzwfw.gov.cn" in original_url.lower(),
                "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                "original_notice_state": "PLAN_ONLY_NOT_EXECUTED",
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return tasks


def _prioritize_original_notice_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        triage = _triage_original_notice_task(task, source_order=index)
        enriched.append({**task, **triage})
    enriched.sort(
        key=lambda task: (
            -int(task.get("original_notice_live_priority_score") or 0),
            int(task.get("original_notice_source_order") or 0),
        )
    )
    for rank, task in enumerate(enriched, start=1):
        task["original_notice_live_priority_rank"] = rank
    return enriched


def _triage_original_notice_task(task: Mapping[str, Any], *, source_order: int) -> dict[str, Any]:
    raw_url = str(task.get("original_notice_url") or "").strip()
    normalized_url, url_blockers = _canonical_original_notice_url(raw_url)
    parsed = urllib.parse.urlsplit(normalized_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    lowered_url = normalized_url.lower()
    title = str(task.get("bid_project_name") or "")
    title_score, title_reasons = _original_notice_title_priority(title)
    score = 0
    route_class = "PUBLIC_PAGE_REVIEW"
    route_strategy = "direct_public_fetch"
    budget_eligible = True
    reasons: list[str] = []

    if url_blockers:
        score = -100 + title_score
        route_class = "INVALID_OR_MISSING_URL"
        route_strategy = "blocked_review"
        budget_eligible = False
        reasons.extend(url_blockers)
    elif "ygp.gdzwfw.gov.cn" in lowered_url:
        score = 20 + title_score
        route_class = "YGP_MAPPING_POINTER"
        route_strategy = "ygp_readback_required"
        budget_eligible = False
        reasons.append("ygp_original_pointer_should_use_ygp_readback_not_direct_fetch")
    elif _looks_like_original_notice_jump_page(host, path, lowered_url):
        score = 35 + title_score
        route_class = "REDIRECT_OR_JUMP_PAGE"
        route_strategy = "browser_or_platform_api_readback_preferred"
        reasons.append("jump_or_redirect_shell_needs_route_specific_readback")
    elif raw_url and not raw_url.lower().startswith(("http://", "https://")):
        score = 50 + title_score
        route_class = "SCHEME_LESS_PUBLIC_URL"
        route_strategy = "normalize_then_direct_fetch"
        reasons.append("scheme_less_public_url_normalized_before_live")
    elif _looks_like_official_direct_html(host, path):
        score = 90 + title_score
        route_class = "OFFICIAL_DIRECT_HTML"
        route_strategy = "direct_public_fetch_first"
        reasons.append("official_direct_html_high_budget_value")
    elif _looks_like_official_public_page(host):
        score = 60 + title_score
        route_class = "OFFICIAL_PUBLIC_PAGE"
        route_strategy = "direct_public_fetch"
        reasons.append("official_public_page")
    else:
        score = 40 + title_score
        reasons.append("public_url_needs_live_quality_check")

    if title_reasons:
        reasons.extend(title_reasons)
    band = _priority_band(score=score, route_class=route_class, budget_eligible=budget_eligible)
    return {
        "original_notice_source_order": source_order,
        "original_notice_url_normalized_for_triage": normalized_url,
        "original_notice_route_class": route_class,
        "original_notice_route_strategy": route_strategy,
        "original_notice_live_budget_eligible": budget_eligible,
        "original_notice_live_priority_score": score,
        "original_notice_live_priority_band": band,
        "original_notice_priority_reasons": _dedupe(reasons),
    }


def _original_notice_task_triage_table(tasks: list[Mapping[str, Any]]) -> dict[str, Any]:
    records = []
    for task in tasks:
        records.append(
            {
                "project_id": str(task.get("project_id") or ""),
                "candidate_company_name": str(task.get("candidate_company_name") or ""),
                "bid_project_name": str(task.get("bid_project_name") or ""),
                "responsible_person_names": _list(task.get("responsible_person_names")),
                "original_notice_task_id": str(task.get("original_notice_task_id") or ""),
                "original_notice_url": str(task.get("original_notice_url") or ""),
                "original_notice_url_normalized_for_triage": str(
                    task.get("original_notice_url_normalized_for_triage") or ""
                ),
                "original_notice_route_class": str(task.get("original_notice_route_class") or ""),
                "original_notice_route_strategy": str(task.get("original_notice_route_strategy") or ""),
                "original_notice_live_budget_eligible": bool(task.get("original_notice_live_budget_eligible")),
                "original_notice_live_priority_score": int(task.get("original_notice_live_priority_score") or 0),
                "original_notice_live_priority_rank": int(task.get("original_notice_live_priority_rank") or 0),
                "original_notice_live_priority_band": str(task.get("original_notice_live_priority_band") or ""),
                "original_notice_priority_reasons": _list(task.get("original_notice_priority_reasons")),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return {
        "summary": {
            "task_count": len(records),
            "budget_eligible_count": sum(1 for record in records if bool(record.get("original_notice_live_budget_eligible"))),
            "route_class_counts": _counts(record.get("original_notice_route_class") for record in records),
            "priority_band_counts": _counts(record.get("original_notice_live_priority_band") for record in records),
        },
        "records": records,
    }


def _original_notice_title_priority(title: str) -> tuple[int, list[str]]:
    text = str(title or "")
    score = 0
    reasons: list[str] = []
    if re.search(r"(施工|工程总承包|EPC|建设项目|改造|道路|桥梁|隧道|管网|码头|厂房|基础设施)", text, flags=re.I):
        score += 12
        reasons.append("title_suggests_construction_or_long_cycle_project")
    if re.search(r"(中标结果|中标公告|中标结果公告|中标结果公示)", text):
        score += 5
        reasons.append("title_suggests_award_result_notice")
    if re.search(r"(设计|勘察|咨询|服务|采购结果)", text) and not re.search(r"(施工|工程总承包|EPC)", text, flags=re.I):
        score -= 6
        reasons.append("title_suggests_design_survey_or_service_notice_lower_direct_budget")
    return score, reasons


def _looks_like_original_notice_jump_page(host: str, path: str, url: str) -> bool:
    return any(marker in path or marker in url for marker in ("jump.html", "tiaozhuan", "redirectpage", "redirect"))


def _looks_like_official_direct_html(host: str, path: str) -> bool:
    if not path.endswith((".html", ".htm")) and "detailhtml" not in path:
        return False
    return _looks_like_official_public_page(host)


def _looks_like_official_public_page(host: str) -> bool:
    return (
        host.endswith(".gov.cn")
        or "ggzy" in host
        or "ccgp" in host
        or host.endswith(".cn") and any(token in host for token in ("zfcg", "bid", "jyzx", "jyxx"))
    )


def _priority_band(*, score: int, route_class: str, budget_eligible: bool) -> str:
    if not budget_eligible:
        return "P3_ROUTE_SPECIFIC_OR_BLOCKED"
    if route_class == "OFFICIAL_DIRECT_HTML" and score >= 90:
        return "P0_DIRECT_OFFICIAL_HTML"
    if score >= 60:
        return "P1_OFFICIAL_OR_NORMALIZED_PUBLIC_PAGE"
    if score >= 35:
        return "P2_REDIRECT_OR_LOWER_CONFIDENCE_PAGE"
    return "P3_ROUTE_SPECIFIC_OR_BLOCKED"


def _bid_show_lookup(source_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    lookup: dict[str, Mapping[str, Any]] = {}
    for record in _list(source_manifest.get("bid_show_records")):
        if not isinstance(record, Mapping):
            continue
        key = f"{record.get('project_id') or ''}|{record.get('candidate_company_name') or ''}|{record.get('original_notice_url') or ''}"
        lookup[key] = record
    return lookup


def _execute_original_notice_tasks(
    tasks: list[dict[str, Any]],
    *,
    created_at: str,
    enable_live_public_query: bool,
    max_live_original_notices: int | None,
    http_getter: HttpGetter | None,
    ygp_readback_lookup: Mapping[str, Mapping[str, Any]],
    browser_readback_lookup: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not enable_live_public_query and not ygp_readback_lookup and not browser_readback_lookup:
        return [], [], []
    getter = http_getter or _default_http_getter
    fetch_records: list[dict[str, Any]] = []
    extraction_records: list[dict[str, Any]] = []
    overlap_records: list[dict[str, Any]] = []
    attempted = 0
    for task in tasks:
        ygp_readback = _match_ygp_readback(task, ygp_readback_lookup)
        if ygp_readback:
            fetch = _fetch_record_from_ygp_readback(task, ygp_readback, created_at=created_at)
            fetch_records.append(fetch)
            extraction = _extract_record_from_ygp_readback(task, ygp_readback, created_at=created_at)
            extraction_records.append(extraction)
            overlap_records.append(_overlap_record(task, extraction, created_at=created_at))
            continue
        browser_readback = _match_browser_readback(task, browser_readback_lookup)
        if browser_readback:
            fetch = _fetch_record_from_browser_readback(task, browser_readback, created_at=created_at)
            fetch_records.append(fetch)
            extraction = _extract_record_from_browser_readback(task, browser_readback, created_at=created_at)
            extraction_records.append(extraction)
            overlap_records.append(_overlap_record(task, extraction, created_at=created_at))
            continue
        if not enable_live_public_query:
            if ygp_readback_lookup and bool(task.get("ygp_original_url_pointer_only")):
                fetch = _ygp_readback_missing_fetch_record(task, created_at=created_at)
                fetch_records.append(fetch)
                extraction = _extract_original_notice(task, fetch, created_at=created_at)
                extraction_records.append(extraction)
                overlap_records.append(_overlap_record(task, extraction, created_at=created_at))
            continue
        if max_live_original_notices is not None and attempted >= max_live_original_notices:
            fetch = {
                **task,
                "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                "fetch_state": "ORIGINAL_NOTICE_FETCH_BLOCKED",
                "blocker_taxonomy": ["max_live_original_notices_deferred"],
                "max_live_original_notices": max_live_original_notices,
            }
            fetch_records.append(fetch)
            continue
        attempted += 1
        fetch = _fetch_original_notice(task, getter=getter, created_at=created_at)
        fetch_records.append(fetch)
        extraction = _extract_original_notice(task, fetch, created_at=created_at)
        extraction_records.append(extraction)
        overlap_records.append(_overlap_record(task, extraction, created_at=created_at))
    return fetch_records, extraction_records, overlap_records


def _load_ygp_readback_lookup(
    *,
    ygp_readback_root: str | Path | None,
    ygp_readback_json: str | Path | None,
) -> dict[str, Mapping[str, Any]]:
    if not ygp_readback_root and not ygp_readback_json:
        return {}
    source_path = Path(ygp_readback_json) if ygp_readback_json else Path(ygp_readback_root or "") / "ygp-original-readback-v1.json"
    if not source_path.exists():
        return {}
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    manifest = _source_manifest(payload)
    lookup: dict[str, Mapping[str, Any]] = {}
    for record in _list(manifest.get("ygp_original_readback_records")):
        if not isinstance(record, Mapping):
            continue
        state = str(record.get("ygp_readback_state") or "")
        extraction_state = str(record.get("ygp_extraction_state") or "")
        if state not in {"YGP_ORIGINAL_URL_READBACK_READY", "YGP_BROWSER_NETWORK_READBACK_READY"} and extraction_state != "YGP_ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED":
            continue
        for key in _ygp_readback_lookup_keys(record):
            lookup.setdefault(key, record)
    return lookup


def _load_browser_readback_lookup(
    *,
    browser_readback_root: str | Path | None,
    browser_readback_json: str | Path | None,
) -> dict[str, Mapping[str, Any]]:
    if not browser_readback_root and not browser_readback_json:
        return {}
    lookup: dict[str, Mapping[str, Any]] = {}
    source_paths = [
        *[Path(path) for path in _split_path_values(browser_readback_json)],
        *[Path(path) / "browser-original-readback-v1.json" for path in _split_path_values(browser_readback_root)],
    ]
    for source_path in source_paths:
        if not source_path.exists():
            continue
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        manifest = _source_manifest(payload)
        for record in _list(manifest.get("browser_original_readback_records")):
            if not isinstance(record, Mapping):
                continue
            if str(record.get("browser_readback_state") or "") != "BROWSER_ORIGINAL_READBACK_READY":
                continue
            for key in _browser_readback_lookup_keys(record):
                lookup.setdefault(key, record)
    return lookup


def _match_ygp_readback(task: Mapping[str, Any], lookup: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any] | None:
    task_id = str(task.get("original_notice_task_id") or "")
    url = str(task.get("original_notice_url") or "")
    if task_id and f"task:{task_id}" in lookup:
        return lookup[f"task:{task_id}"]
    for key in _url_lookup_keys(url):
        if key in lookup:
            return lookup[key]
    return None


def _match_browser_readback(task: Mapping[str, Any], lookup: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any] | None:
    task_id = str(task.get("original_notice_task_id") or "")
    url = str(task.get("original_notice_url") or "")
    if task_id and f"task:{task_id}" in lookup:
        return lookup[f"task:{task_id}"]
    for key in _url_lookup_keys(url):
        if key in lookup:
            return lookup[key]
    return None


def _ygp_readback_lookup_keys(record: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    task_id = str(record.get("original_notice_task_id") or "")
    if task_id:
        keys.append(f"task:{task_id}")
    for url in (
        record.get("original_notice_url"),
        record.get("source_url"),
        _route_attempt_url(record),
    ):
        keys.extend(_url_lookup_keys(str(url or "")))
    return _dedupe(keys)


def _browser_readback_lookup_keys(record: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    task_id = str(record.get("original_notice_task_id") or "")
    if task_id:
        keys.append(f"task:{task_id}")
    for url in (
        record.get("original_notice_url"),
        record.get("source_url"),
        _route_attempt_url(record),
    ):
        keys.extend(_url_lookup_keys(str(url or "")))
    return _dedupe(keys)


def _url_lookup_keys(url: str) -> list[str]:
    raw = str(url or "").strip()
    if not raw:
        return []
    keys = [f"url:{raw}"]
    unquoted = urllib.parse.unquote(raw)
    if unquoted != raw:
        keys.append(f"url:{unquoted}")
    match = re.search(r"/url-mapping/([^/?#]+)", unquoted)
    if match:
        keys.append(f"ygp-url-mapping:{match.group(1)}")
    parsed = urllib.parse.urlsplit(unquoted)
    query_texts = [parsed.query]
    if "?" in parsed.fragment:
        query_texts.append(parsed.fragment.split("?", 1)[1])
    for query_text in query_texts:
        query = urllib.parse.parse_qs(query_text)
        for name in ("noticeId", "projectCode", "bizCode"):
            for value in query.get(name, []):
                if value:
                    keys.append(f"ygp-query:{name}:{value}")
    return _dedupe(keys)


def _route_attempt_url(record: Mapping[str, Any]) -> str:
    route_attempt = record.get("route_attempt")
    if isinstance(route_attempt, Mapping):
        return str(route_attempt.get("url") or route_attempt.get("source_url") or "")
    route_attempts = record.get("route_attempts")
    if isinstance(route_attempts, list):
        for item in route_attempts:
            if isinstance(item, Mapping) and (item.get("url") or item.get("source_url")):
                return str(item.get("url") or item.get("source_url") or "")
    return ""


def _ygp_readback_record_count(lookup: Mapping[str, Mapping[str, Any]]) -> int:
    return len({_fingerprint(record) for record in lookup.values()})


def _browser_readback_record_count(lookup: Mapping[str, Mapping[str, Any]]) -> int:
    return len({_fingerprint(record) for record in lookup.values()})


def _ygp_readback_text(record: Mapping[str, Any]) -> str:
    for key in ("text_extractable", "text_probe", "body_text", "body_probe", "body"):
        value = str(record.get(key) or "")
        if value.strip():
            return value
    return ""


def _browser_readback_text(record: Mapping[str, Any]) -> str:
    for key in ("text_extractable", "text_probe", "body_text", "body_probe", "body"):
        value = str(record.get(key) or "")
        if value.strip():
            return value
    return ""


def _fetch_record_from_ygp_readback(task: Mapping[str, Any], ygp_readback: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    text = _ygp_readback_text(ygp_readback)
    return {
        **dict(task),
        "execution_mode": "LOCAL_YGP_READBACK_CONSUMED",
        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
        "fetch_source": "YGP_ORIGINAL_READBACK",
        "source_url": str(ygp_readback.get("source_url") or task.get("original_notice_url") or ""),
        "status_code": int(ygp_readback.get("status_code") or 200),
        "content_type": str(ygp_readback.get("content_type") or "application/json"),
        "body_sha256": str(ygp_readback.get("readback_payload_sha256") or ygp_readback.get("record_payload_sha256") or ""),
        "body_probe": text[:300],
        "text_probe": text[:600],
        "text_probe_sha256": _sha256(text[:600]) if text else "",
        "route_attempt": {
            "route": "ygp_original_readback_consumed",
            "url": str(ygp_readback.get("source_url") or task.get("original_notice_url") or ""),
            "status_code": int(ygp_readback.get("status_code") or 200),
            "content_type": str(ygp_readback.get("content_type") or "application/json"),
            "body_sha256": str(ygp_readback.get("readback_payload_sha256") or ygp_readback.get("record_payload_sha256") or ""),
            "error": "",
        },
        "blocker_taxonomy": [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fetch_record_from_browser_readback(
    task: Mapping[str, Any],
    browser_readback: Mapping[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    text = _browser_readback_text(browser_readback)
    return {
        **dict(task),
        "execution_mode": "LOCAL_BROWSER_READBACK_CONSUMED",
        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
        "fetch_source": "BROWSER_ORIGINAL_READBACK",
        "source_url": str(browser_readback.get("source_url") or task.get("original_notice_url") or ""),
        "status_code": int(browser_readback.get("status_code") or 200),
        "content_type": str(browser_readback.get("content_type") or "text/plain"),
        "body_sha256": str(browser_readback.get("readback_payload_sha256") or browser_readback.get("record_payload_sha256") or ""),
        "body_probe": text[:300],
        "text_probe": text[:600],
        "text_probe_sha256": _sha256(text[:600]) if text else "",
        "route_attempt": {
            "route": "browser_original_readback_consumed",
            "url": str(browser_readback.get("source_url") or task.get("original_notice_url") or ""),
            "status_code": int(browser_readback.get("status_code") or 200),
            "content_type": str(browser_readback.get("content_type") or "text/plain"),
            "body_sha256": str(browser_readback.get("readback_payload_sha256") or browser_readback.get("record_payload_sha256") or ""),
            "error": "",
        },
        "blocker_taxonomy": [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _ygp_readback_missing_fetch_record(task: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    url = str(task.get("original_notice_url") or "")
    return {
        **dict(task),
        "execution_mode": "LOCAL_YGP_READBACK_REQUIRED",
        "fetch_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
        "source_url": url,
        "status_code": 0,
        "content_type": "",
        "body_sha256": "",
        "body_probe": "",
        "text_probe": "",
        "text_probe_sha256": "",
        "route_attempt": {
            "route": "ygp_original_readback_missing",
            "url": url,
            "status_code": 0,
            "content_type": "",
            "body_sha256": "",
            "error": "ygp_local_readback_missing",
        },
        "blocker_taxonomy": ["ygp_local_readback_missing"],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _extract_record_from_browser_readback(
    task: Mapping[str, Any],
    browser_readback: Mapping[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    people = _list(browser_readback.get("extracted_responsible_person_names"))
    period = str(browser_readback.get("extracted_period_text") or "")
    award_date = str(browser_readback.get("extracted_award_date") or "")
    companies = _list(browser_readback.get("extracted_company_names"))
    text_probe = _browser_readback_text(browser_readback)
    if text_probe:
        if not people:
            people = _extract_responsible_people(text_probe)
        if not period:
            period = _extract_period_text(text_probe)
        if not award_date:
            award_date = _extract_award_date(text_probe)
        if not companies:
            companies = _extract_company_names(text_probe)
    if people and period:
        state = "ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED"
    elif people or period or companies or text_probe:
        state = "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
    else:
        state = "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"
    blockers: list[str] = []
    if state == "ORIGINAL_NOTICE_NO_MATCH_REVIEW" and not (people and period):
        blockers = ["original_notice_person_period_not_extracted_review"]
    return {
        **dict(task),
        "original_notice_extraction_state": state,
        "extraction_source": "BROWSER_ORIGINAL_READBACK",
        "source_url": str(browser_readback.get("source_url") or task.get("original_notice_url") or ""),
        "extracted_responsible_person_names": people,
        "extracted_period_text": period,
        "extracted_award_date": award_date,
        "extracted_company_names": companies,
        "text_probe": text_probe[:600],
        "text_probe_sha256": str(browser_readback.get("text_probe_sha256") or (_sha256(text_probe[:600]) if text_probe else "")),
        "record_payload_sha256": str(browser_readback.get("record_payload_sha256") or ""),
        "blocker_taxonomy": blockers,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _extract_record_from_ygp_readback(task: Mapping[str, Any], ygp_readback: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    people = _list(ygp_readback.get("extracted_responsible_person_names"))
    period = str(ygp_readback.get("extracted_period_text") or "")
    award_date = str(ygp_readback.get("extracted_award_date") or "")
    companies = _list(ygp_readback.get("extracted_company_names"))
    text_probe = _ygp_readback_text(ygp_readback)
    if text_probe:
        if not people:
            people = _extract_responsible_people(text_probe)
        if not period:
            period = _extract_period_text(text_probe)
        if not award_date:
            award_date = _extract_award_date(text_probe)
        if not companies:
            companies = _extract_company_names(text_probe)
    if people and period:
        state = "ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED"
    elif people or period or companies or text_probe:
        state = "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
    else:
        state = "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"
    return {
        **dict(task),
        "original_notice_extraction_state": state,
        "extraction_source": "YGP_ORIGINAL_READBACK",
        "source_url": str(ygp_readback.get("source_url") or task.get("original_notice_url") or ""),
        "extracted_responsible_person_names": people,
        "extracted_period_text": period,
        "extracted_award_date": award_date,
        "extracted_company_names": companies,
        "text_probe": text_probe[:600],
        "text_probe_sha256": str(ygp_readback.get("text_probe_sha256") or (_sha256(text_probe[:600]) if text_probe else "")),
        "record_payload_sha256": str(ygp_readback.get("record_payload_sha256") or ""),
        "blocker_taxonomy": [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fetch_original_notice(task: Mapping[str, Any], *, getter: HttpGetter, created_at: str) -> dict[str, Any]:
    raw_url = str(task.get("original_notice_url") or "").strip()
    url, url_blockers = _canonical_original_notice_url(raw_url)
    if url_blockers:
        return {
            **dict(task),
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "fetch_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
            "source_url": url,
            "original_notice_url_raw": raw_url,
            "original_notice_url_normalized": url,
            "original_notice_url_was_normalized": raw_url != url,
            "status_code": 0,
            "content_type": "",
            "body_sha256": "",
            "body_probe": "",
            "text_probe": "",
            "text_probe_sha256": "",
            "route_attempt": {"url": raw_url, "normalized_url": url, "status_code": 0, "error": ",".join(url_blockers)},
            "blocker_taxonomy": url_blockers,
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    if "ygp.gdzwfw.gov.cn" in url.lower():
        return {
            **dict(task),
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "fetch_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
            "source_url": url,
            "original_notice_url_raw": raw_url,
            "original_notice_url_normalized": url,
            "original_notice_url_was_normalized": raw_url != url,
            "status_code": 0,
            "content_type": "",
            "body_sha256": "",
            "body_probe": "",
            "text_probe": "",
            "text_probe_sha256": "",
            "route_attempt": {
                "url": url,
                "status_code": 0,
                "content_type": "",
                "body_sha256": "",
                "error": "ygp_original_readback_required",
            },
            "blocker_taxonomy": ["ygp_original_readback_required"],
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    response = dict(getter(url, {"route": "original_notice_fetch", "task": dict(task)}))
    route_attempts = [_route_attempt_from_fetch_response(response, requested_url=url)]
    status, content_type, body = _fetch_response_parts(response)
    blockers = _blockers_from_response(status=status, body_probe=body[:300], error=str(response.get("error") or ""))
    fallback_url = _http_fallback_url_for_scheme_less_https(raw_url=raw_url, normalized_url=url, blockers=blockers)
    if fallback_url:
        response = dict(
            getter(
                fallback_url,
                {
                    "route": "original_notice_fetch_http_fallback",
                    "task": dict(task),
                    "previous_attempt": route_attempts[-1],
                },
            )
        )
        route_attempts.append(_route_attempt_from_fetch_response(response, requested_url=fallback_url))
        status, content_type, body = _fetch_response_parts(response)
        blockers = _blockers_from_response(status=status, body_probe=body[:300], error=str(response.get("error") or ""))
    full_text = _html_to_text(body) if body else ""
    fetch_state = "ORIGINAL_NOTICE_FETCH_BLOCKED" if blockers else "ORIGINAL_NOTICE_FETCHED"
    return {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "fetch_state": fetch_state,
        "source_url": str(response.get("url") or url),
        "original_notice_url_raw": raw_url,
        "original_notice_url_normalized": url,
        "original_notice_url_effective": str(response.get("url") or route_attempts[-1].get("url") or url),
        "original_notice_http_fallback_attempted": bool(fallback_url),
        "original_notice_url_was_normalized": raw_url != url,
        "status_code": status,
        "content_type": content_type,
        "body_sha256": _sha256(body) if body else "",
        "body_probe": body[:300],
        "text_probe": full_text[:1200] if full_text else "",
        "text_probe_sha256": _sha256(full_text[:1200]) if full_text else "",
        "text_extractable": full_text[:50000] if full_text else "",
        "route_attempt": route_attempts[-1],
        "route_attempts": route_attempts,
        "blocker_taxonomy": blockers,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _extract_original_notice(task: Mapping[str, Any], fetch: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    if str(fetch.get("fetch_state") or "") == "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED":
        return {
            **dict(task),
            "original_notice_extraction_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
            "source_url": str(fetch.get("source_url") or task.get("original_notice_url") or ""),
            "blocker_taxonomy": _list(fetch.get("blocker_taxonomy")),
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    if str(fetch.get("fetch_state") or "") != "ORIGINAL_NOTICE_FETCHED":
        return {
            **dict(task),
            "original_notice_extraction_state": "ORIGINAL_NOTICE_FETCH_BLOCKED",
            "source_url": str(fetch.get("source_url") or task.get("original_notice_url") or ""),
            "blocker_taxonomy": _list(fetch.get("blocker_taxonomy")),
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    text = str(fetch.get("text_extractable") or fetch.get("text_probe") or "")
    people = _extract_responsible_people(text)
    period = _extract_period_text(text)
    award_date = _extract_award_date(text)
    companies = _extract_company_names(text)
    if people and period:
        state = "ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED"
    elif people or period or companies:
        state = "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
    elif text.strip():
        state = "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
    else:
        state = "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"
    blockers: list[str] = []
    if state == "ORIGINAL_NOTICE_NO_MATCH_REVIEW" and not (people and period):
        blockers = ["original_notice_person_period_not_extracted_review"]
        if _looks_like_browser_readback_required(text, str(fetch.get("source_url") or "")):
            blockers.append("original_notice_browser_readback_required")
    elif state == "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED":
        blockers = ["original_notice_body_not_extractable_review"]
    return {
        **dict(task),
        "original_notice_extraction_state": state,
        "source_url": str(fetch.get("source_url") or task.get("original_notice_url") or ""),
        "extracted_responsible_person_names": people,
        "extracted_period_text": period,
        "extracted_award_date": award_date,
        "extracted_company_names": companies,
        "text_probe": text[:600],
        "text_probe_sha256": _sha256(text[:600]) if text else "",
        "record_payload_sha256": _fingerprint(
            {"source_url": fetch.get("source_url"), "people": people, "period": period, "award_date": award_date, "companies": companies}
        ),
        "blocker_taxonomy": blockers,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _overlap_record(task: Mapping[str, Any], extraction: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    candidate_people = {str(item).strip() for item in _list(task.get("responsible_person_names")) if str(item).strip()}
    extracted_people = {str(item).strip() for item in _list(extraction.get("extracted_responsible_person_names")) if str(item).strip()}
    matched_people = sorted(candidate_people & extracted_people)
    company_match = _contains_company(extraction.get("extracted_company_names"), str(task.get("candidate_company_name") or ""))
    period_present = bool(str(extraction.get("extracted_period_text") or "").strip() or str(extraction.get("extracted_award_date") or "").strip())
    if str(extraction.get("original_notice_extraction_state") or "") == "ORIGINAL_NOTICE_FETCH_BLOCKED":
        state = "ORIGINAL_NOTICE_FETCH_BLOCKED"
        reasons = _list(extraction.get("blocker_taxonomy")) or ["original_notice_fetch_blocked"]
    elif matched_people and company_match and period_present:
        state = "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED"
        reasons = ["same_responsible_person", "candidate_company_matched", "period_or_award_date_present"]
    else:
        state = "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
        reasons = ["original_notice_no_same_person_company_time_window_signal"]
    return {
        "original_notice_overlap_signal_id": _stable_id("P13B-ORIGINAL-OVERLAP", task.get("original_notice_task_id"), state),
        "original_notice_task_id": str(task.get("original_notice_task_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "candidate_company_name": str(task.get("candidate_company_name") or ""),
        "responsible_person_names": sorted(candidate_people),
        "matched_person_names": matched_people,
        "historical_project_area_code": str(task.get("historical_project_area_code") or task.get("bid_area_code") or ""),
        "bid_area_code": str(task.get("bid_area_code") or task.get("historical_project_area_code") or ""),
        "original_notice_url": str(task.get("original_notice_url") or ""),
        "source_url": str(extraction.get("source_url") or task.get("original_notice_url") or ""),
        "extracted_company_names": _list(extraction.get("extracted_company_names")),
        "extracted_period_text": str(extraction.get("extracted_period_text") or ""),
        "extracted_award_date": str(extraction.get("extracted_award_date") or ""),
        "original_notice_overlap_signal_state": state,
        "review_reasons": reasons,
        "release_evidence_probe_triggered": state == "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED",
        "release_evidence_source_targets": RELEASE_EVIDENCE_SOURCE_TARGETS
        if state == "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED"
        else [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _manual_release_evidence_probe_table(overlap_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in overlap_records:
        if str(record.get("original_notice_overlap_signal_state") or "") != "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED":
            continue
        rows.append(
            {
                "project_id": str(record.get("project_id") or ""),
                "candidate_company_name": str(record.get("candidate_company_name") or ""),
                "matched_person_names": _list(record.get("matched_person_names")),
                "historical_project_area_code": str(record.get("historical_project_area_code") or record.get("bid_area_code") or ""),
                "bid_area_code": str(record.get("bid_area_code") or record.get("historical_project_area_code") or ""),
                "original_notice_url": str(record.get("original_notice_url") or ""),
                "source_url": str(record.get("source_url") or ""),
                "extracted_period_text": str(record.get("extracted_period_text") or ""),
                "extracted_award_date": str(record.get("extracted_award_date") or ""),
                "extracted_company_names": _list(record.get("extracted_company_names")),
                "release_evidence_source_targets": RELEASE_EVIDENCE_SOURCE_TARGETS,
                "release_evidence_probe_reason": "same_person_company_time_window_signal_from_original_notice",
                "suggested_next_step": "targeted_release_evidence_probe",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _write_outputs(
    out_dir: Path,
    result: Mapping[str, Any],
    fetch_records: list[Mapping[str, Any]],
    extraction_records: list[Mapping[str, Any]],
    overlap_records: list[Mapping[str, Any]],
    manual_release_evidence_probe_table: list[Mapping[str, Any]],
) -> None:
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    manifest = result.get("manifest") if isinstance(result.get("manifest"), Mapping) else {}
    triage_table = manifest.get("original_notice_task_triage_table") if isinstance(manifest, Mapping) else {}
    _write_json(out_dir / "original-notice-backtrace-v1.json", result)
    _write_json(out_dir / "original-notice-task-triage-table.json", triage_table if isinstance(triage_table, Mapping) else {})
    _write_json(out_dir / "original-notice-fetch-records.json", {"summary": summary, "records": fetch_records})
    _write_json(out_dir / "original-notice-extraction-records.json", {"summary": summary, "records": extraction_records})
    _write_json(out_dir / "original-notice-overlap-signal-records.json", {"summary": summary, "records": overlap_records})
    _write_json(out_dir / "manual-release-evidence-probe-table.json", {"summary": summary, "records": manual_release_evidence_probe_table})


def _summary(
    *,
    original_notice_task_records: list[Mapping[str, Any]],
    fetch_records: list[Mapping[str, Any]],
    extraction_records: list[Mapping[str, Any]],
    overlap_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    live_processed_count = sum(
        1
        for record in fetch_records
        if str(record.get("execution_mode") or "")
        in {"LIVE_PUBLIC_QUERY_ATTEMPTED", "LOCAL_YGP_READBACK_CONSUMED", "LOCAL_BROWSER_READBACK_CONSUMED"}
    )
    fetched_count = sum(1 for record in fetch_records if str(record.get("fetch_state") or "") == "ORIGINAL_NOTICE_FETCHED")
    person_period_extracted_count = sum(
        1 for record in extraction_records if str(record.get("original_notice_extraction_state") or "") == "ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED"
    )
    overlap_signal_count = sum(
        1 for record in overlap_records if str(record.get("original_notice_overlap_signal_state") or "") == "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED"
    )
    no_match_review_count = sum(
        1 for record in overlap_records if str(record.get("original_notice_overlap_signal_state") or "") == "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
    )
    source_unsupported_count = sum(
        1 for record in extraction_records if str(record.get("original_notice_extraction_state") or "") == "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"
    )
    fetch_blocked_count = sum(1 for record in fetch_records if str(record.get("fetch_state") or "") == "ORIGINAL_NOTICE_FETCH_BLOCKED")
    ygp_readback_ready_count = sum(
        1 for record in extraction_records if str(record.get("extraction_source") or "") == "YGP_ORIGINAL_READBACK"
    )
    browser_readback_ready_count = sum(
        1 for record in extraction_records if str(record.get("extraction_source") or "") == "BROWSER_ORIGINAL_READBACK"
    )
    return {
        "p13b_original_notice_backtrace_state": "P13B_ORIGINAL_NOTICE_BACKTRACE_READY" if not blocking_reasons else "P13B_ORIGINAL_NOTICE_INPUT_BLOCKED",
        "execution_mode": execution_mode,
        "original_notice_task_count": len(original_notice_task_records),
        "live_processed_count": live_processed_count,
        "fetched_count": fetched_count,
        "original_notice_fetch_count": len(fetch_records),
        "original_notice_extraction_count": len(extraction_records),
        "original_notice_overlap_signal_count": len(overlap_records),
        "original_notice_person_period_extracted_count": person_period_extracted_count,
        "person_period_extracted_count": person_period_extracted_count,
        "original_notice_overlap_signal_review_required_count": overlap_signal_count,
        "overlap_signal_count": overlap_signal_count,
        "no_match_review_count": no_match_review_count,
        "source_unsupported_count": source_unsupported_count,
        "fetch_blocked_count": fetch_blocked_count,
        "ygp_readback_ready_count": ygp_readback_ready_count,
        "browser_readback_ready_count": browser_readback_ready_count,
        "manual_release_evidence_probe_count": sum(
            1 for record in overlap_records if bool(record.get("release_evidence_probe_triggered"))
        ),
        "fetch_state_counts": _counts(record.get("fetch_state") for record in fetch_records),
        "extraction_state_counts": _counts(record.get("original_notice_extraction_state") for record in extraction_records),
        "overlap_signal_state_counts": _counts(record.get("original_notice_overlap_signal_state") for record in overlap_records),
        "original_notice_route_class_counts": _counts(
            record.get("original_notice_route_class") for record in original_notice_task_records
        ),
        "original_notice_live_priority_band_counts": _counts(
            record.get("original_notice_live_priority_band") for record in original_notice_task_records
        ),
        "original_notice_budget_eligible_count": sum(
            1 for record in original_notice_task_records if bool(record.get("original_notice_live_budget_eligible"))
        ),
        "blocker_taxonomy_counts": _counts(
            blocker
            for record in [*fetch_records, *extraction_records]
            for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _default_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    request_url = _request_safe_url(url)
    request = urllib.request.Request(
        request_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaP13B/1.0",
            "Accept": "text/html,application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": response.headers.get("Content-Type", ""),
                "body": body,
                "url": response.geturl(),
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
    except (UnicodeEncodeError, ValueError, OSError) as exc:
        return {"status_code": 0, "content_type": "", "body": "", "url": url, "error": f"{type(exc).__name__}:{exc}"}


def _fetch_response_parts(response: Mapping[str, Any]) -> tuple[int, str, str]:
    status = int(response.get("status_code") or response.get("status") or 0)
    content_type = str(response.get("content_type") or "")
    body = str(response.get("body") or response.get("content") or response.get("text") or "")
    return status, content_type, body


def _route_attempt_from_fetch_response(response: Mapping[str, Any], *, requested_url: str) -> dict[str, Any]:
    status, content_type, body = _fetch_response_parts(response)
    return {
        "url": str(response.get("url") or requested_url),
        "requested_url": requested_url,
        "status_code": status,
        "content_type": content_type,
        "body_sha256": _sha256(body) if body else "",
        "error": str(response.get("error") or ""),
    }


def _http_fallback_url_for_scheme_less_https(*, raw_url: str, normalized_url: str, blockers: list[str]) -> str:
    if not blockers or "original_notice_transport_error_retry_required" not in blockers:
        return ""
    if str(raw_url or "").strip().lower().startswith(("http://", "https://")):
        return ""
    if not str(normalized_url or "").lower().startswith("https://"):
        return ""
    return "http://" + str(normalized_url)[len("https://") :]


def _canonical_original_notice_url(raw_url: str) -> tuple[str, list[str]]:
    text = str(raw_url or "").strip()
    lowered = text.lower()
    if lowered in MISSING_ORIGINAL_NOTICE_URL_MARKERS or any(phrase in text for phrase in MISSING_ORIGINAL_NOTICE_URL_PHRASES):
        return text, ["original_notice_url_missing_review"]
    if text.startswith("//"):
        return f"https:{text}", []
    parts = urllib.parse.urlsplit(text)
    if parts.scheme in {"http", "https"} and parts.netloc:
        return text, []
    if parts.scheme:
        return text, ["original_notice_unsupported_url_scheme"]
    if _looks_like_scheme_less_public_url(text):
        return f"https://{text.lstrip('/')}", []
    return text, ["original_notice_unsupported_url_scheme"]


def _looks_like_scheme_less_public_url(value: str) -> bool:
    return bool(
        re.match(
            r"^(?:www\.|[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+)(?::[0-9]{1,5})?(?:[/?#]|$)",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _request_safe_url(url: str) -> str:
    parts = urllib.parse.urlsplit(str(url or ""))
    if not parts.scheme or not parts.netloc:
        return str(url or "")
    try:
        netloc = parts.netloc.encode("idna").decode("ascii")
    except UnicodeError:
        netloc = parts.netloc
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%")
    query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe="=&?/%:+,;@")
    return urllib.parse.urlunsplit((parts.scheme, netloc, path, query, parts.fragment))


def _blockers_from_response(*, status: int, body_probe: str, error: str) -> list[str]:
    blockers: list[str] = []
    if status in {403, 429}:
        blockers.append("original_notice_forbidden_or_rate_limited_review")
    if status in {500, 502, 503, 504}:
        blockers.append("original_notice_temporary_unavailable_retry_required")
    if status == 0 and error:
        blockers.append("original_notice_transport_error_retry_required")
    if "验证码" in body_probe or "captcha" in body_probe.lower():
        blockers.append("original_notice_captcha_or_challenge_review")
    if status == 200 and not body_probe.strip():
        blockers.append("original_notice_empty_body_review")
    return _dedupe(blockers)


def _looks_like_browser_readback_required(text: str, source_url: str) -> bool:
    lowered = str(text or "").lower()
    url = str(source_url or "").lower()
    return any(
        marker in lowered
        for marker in (
            "loading",
            "doesn't work properly without javascript enabled",
            "please enable it to continue",
            "window._amapsecurityconfig",
            "whebd-vue",
            "交易平台 doesn't work",
        )
    ) or "jump.html" in url


def _extract_responsible_people(text: str) -> list[str]:
    patterns = [
        r"(?:建筑师[/／]总监[/／]负责人)\s*[:：]\s*([\u4e00-\u9fa5·]{2,8})",
        r"(?:项目负责人|项目经理|施工项目负责人|设计负责人|勘察负责人|总监理工程师|工程总承包项目经理)\s*[:：]\s*([\u4e00-\u9fa5·]{2,8})",
        r"(?:项目负责人|项目经理|施工项目负责人|设计负责人|勘察负责人|总监理工程师|工程总承包项目经理)\s+([\u4e00-\u9fa5·]{2,8})",
        r"(?:负责人姓名|姓名)\s*[:：]\s*([\u4e00-\u9fa5·]{2,8})",
    ]
    people: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if _looks_like_person_name(name):
                people.append(name)
    people.extend(_extract_people_from_role_table_windows(text))
    return _dedupe(people)


def _extract_people_from_role_table_windows(text: str) -> list[str]:
    people: list[str] = []
    role_pattern = r"(?:项目负责人|项目经理|施工项目负责人|设计负责人|勘察负责人|总监理工程师|工程总承包项目经理)"
    for match in re.finditer(role_pattern, text):
        window = str(text[match.end() : match.end() + 520])
        for candidate in re.findall(r"[\u4e00-\u9fa5·]{2,8}", window):
            if _looks_like_person_name(candidate):
                people.append(candidate)
                break
    return people


def _looks_like_person_name(value: str) -> bool:
    name = str(value or "").strip()
    if not name:
        return False
    if name in {
        "姓名",
        "负责人",
        "项目负责人",
        "项目经理",
        "执业",
        "职业资格",
        "执业或职业",
        "职称",
        "证书名称",
        "证书编号",
        "职称专业",
        "职称级别",
        "质量",
        "质量承诺",
        "工期",
        "服务期",
        "中标内容",
        "行政监督",
        "定标时间",
        "定标方法",
    }:
        return False
    if any(
        token in name
        for token in (
            "公司",
            "集团",
            "工程",
            "建设",
            "中标",
            "单位",
            "中国",
            "质量",
            "标准",
            "合格",
            "现行",
            "国家",
            "有关",
            "职称",
            "证书",
            "注册",
            "专业",
            "资格",
            "编号",
            "名称",
            "电话",
            "日期",
            "机构",
            "监督",
        )
    ):
        return False
    if "·" in name:
        return 2 <= len(name) <= 8
    return 2 <= len(name) <= 4


def _extract_period_text(text: str) -> str:
    duration_match = re.search(
        r"(?:中标工期|工期)\s*[（(]\s*日历天\s*[）)]\s*[:：]\s*([0-9]{1,5})",
        text,
    )
    if duration_match:
        return f"{duration_match.group(1).strip()}日历天"
    patterns = [
        r"(?:中标工期|工期（交货期）|工期\(交货期\)|工期|服务期|服务时间|合同履行期限|履行期限|服务期限)\s*[:：]\s*([^。；;\n]{2,80})",
        r"(?:中标工期|工期（交货期）|工期\(交货期\)|工期（或服务期、交货期）|工期\(或服务期、交货期\)|工期|服务期|服务时间|合同履行期限|履行期限|服务期限)\s+([0-9]{1,5}\s*(?:天|日历天|个日历天|个月|月|年))",
        r"(?:计划工期)\s*[:：]\s*([^。；;\n]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    table_period = _extract_period_from_table_windows(text)
    if table_period:
        return table_period
    return ""


def _extract_period_from_table_windows(text: str) -> str:
    period_label = r"(?:工期（或服务期、交货期）|工期\(或服务期、交货期\)|工期（交货期）|工期\(交货期\)|工期|服务期|合同履行期限)"
    for match in re.finditer(period_label, text):
        window = str(text[match.end() : match.end() + 420])
        duration_match = re.search(r"([0-9]{1,5}\s*(?:天|日历天|个日历天|个月|月|年))", window)
        if duration_match:
            return duration_match.group(1).strip()
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
        r"(?:中标人名称|中标人|成交供应商名称|成交供应商|中标单位|中标候选人名称|中标候选人|第一中标候选人)\s*[:：]\s*([^。；;\n]{4,100})",
        r"(?:联合体成员|联合体\(成\)|联合体（成）)\s*[:：]\s*([^。；;\n]{4,100})",
    ]
    names: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            segment = match.group(1)
            for part in re.split(r"[;,，、；]|(?:联合体)|(?:\\(成\\))|(?:（成）)|(?:\\(主\\))|(?:（主）)", segment):
                if not isinstance(part, str):
                    continue
                part = part.strip()
                if "公司" in part or "集团" in part or "院" in part:
                    names.append(part)
    for match in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,80}(?:有限公司|集团有限公司|设计研究院|工程院|研究院)", text):
        names.append(match.group(0).strip())
    return _dedupe(names)


def _contains_company(company_names: Any, candidate_company: str) -> bool:
    candidate = _norm(candidate_company)
    if not candidate:
        return False
    for name in _list(company_names):
        normalized = _norm(str(name or ""))
        if normalized and (candidate in normalized or normalized in candidate):
            return True
    return False


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _html_to_text(content: str) -> str:
    text = re.sub(r"<\s*br\s*/?>", "\n", content, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


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


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"JG\d{4}-\d+(?:-\d+)?", text)
    if match:
        return match.group(0)
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _split_path_values(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[;,]", text) if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B original notice backtrace manifest.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--input-json", default=None)
    parser.add_argument("--company-history-triage-root", default=None)
    parser.add_argument("--ygp-readback-root", default=None)
    parser.add_argument("--ygp-readback-json", default=None)
    parser.add_argument("--browser-readback-root", default=None)
    parser.add_argument("--browser-readback-json", default=None)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--max-live-original-notices", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_original_notice_backtrace(
        input_root=args.input_root,
        input_json=args.input_json,
        company_history_triage_root=args.company_history_triage_root,
        ygp_readback_root=args.ygp_readback_root,
        ygp_readback_json=args.ygp_readback_json,
        browser_readback_root=args.browser_readback_root,
        browser_readback_json=args.browser_readback_json,
        output_root=args.output_root,
        enable_live_public_query=args.enable_live_public_query,
        max_live_original_notices=args.max_live_original_notices,
        project_ids=_parse_csv(args.project_ids),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
