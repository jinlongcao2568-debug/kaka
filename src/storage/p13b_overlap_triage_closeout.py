from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


P13B_OVERLAP_TRIAGE_CLOSEOUT_KIND = "p13b_overlap_triage_closeout_v1_manifest"
P13B_OVERLAP_TRIAGE_CLOSEOUT_VERSION = 1
P13B_OVERLAP_TRIAGE_CLOSEOUT_ADAPTER_ID = "p13b-overlap-triage-closeout-v1-builder"

DEFAULT_COMPANY_HISTORY_TRIAGE_ROOT = Path("tmp/evaluation-real-samples/p13b-company-history-overlap-triage-ygp-v1")
DEFAULT_ORIGINAL_NOTICE_BACKTRACE_ROOT = Path("tmp/evaluation-real-samples/p13b-original-notice-backtrace-ygp-v1-ygpreadback")
DEFAULT_YGP_READBACK_ROOT = Path("tmp/evaluation-real-samples/p13b-ygp-original-readback-p13b-v1")
DEFAULT_YGP_COVERAGE_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-ygp-city-coverage-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-overlap-triage-closeout-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")


def build_p13b_overlap_triage_closeout(
    *,
    company_history_triage_root: str | Path = DEFAULT_COMPANY_HISTORY_TRIAGE_ROOT,
    original_notice_backtrace_root: str | Path = DEFAULT_ORIGINAL_NOTICE_BACKTRACE_ROOT,
    ygp_readback_root: str | Path = DEFAULT_YGP_READBACK_ROOT,
    ygp_coverage_closeout_root: str | Path | None = DEFAULT_YGP_COVERAGE_CLOSEOUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    company_dir = Path(company_history_triage_root)
    original_dir = Path(original_notice_backtrace_root)
    ygp_dir = Path(ygp_readback_root)
    coverage_dir = Path(ygp_coverage_closeout_root) if ygp_coverage_closeout_root else None
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    company_history = _load_json(
        company_dir / "company-history-overlap-triage-v1.json",
        missing_inputs,
        "p13b_company_history_overlap_triage_missing",
    )
    original_notice = _load_json(
        original_dir / "original-notice-backtrace-v1.json",
        missing_inputs,
        "p13b_original_notice_backtrace_missing",
    )
    ygp_readback = _load_json(
        ygp_dir / "ygp-original-readback-v1.json",
        missing_inputs,
        "p13b_ygp_original_readback_missing",
    )
    ygp_coverage = (
        _load_json(
            coverage_dir / "guangdong-ygp-city-coverage-closeout-v1.json",
            missing_inputs,
            "guangdong_ygp_city_coverage_closeout_missing",
        )
        if coverage_dir
        else {}
    )

    company_manifest = _source_manifest(company_history)
    original_manifest = _source_manifest(original_notice)
    ygp_manifest = _source_manifest(ygp_readback)
    coverage_manifest = _source_manifest(ygp_coverage)

    company_table = _company_history_readback_table(company_manifest, created_at=created)
    original_table = _original_notice_readback_table(original_manifest, ygp_manifest, created_at=created)
    release_table = _release_evidence_trigger_table(company_manifest, original_manifest, created_at=created)
    project_table = _project_overlap_triage_table(
        company_manifest=company_manifest,
        original_table=original_table,
        company_table=company_table,
        release_table=release_table,
        coverage_manifest=coverage_manifest,
        created_at=created,
    )
    summary = _summary(
        project_records=project_table,
        company_records=company_table,
        original_records=original_table,
        release_records=release_table,
        company_manifest=company_manifest,
        original_manifest=original_manifest,
        ygp_manifest=ygp_manifest,
        missing_inputs=missing_inputs,
    )
    manifest = {
        "manifest_version": P13B_OVERLAP_TRIAGE_CLOSEOUT_VERSION,
        "manifest_kind": P13B_OVERLAP_TRIAGE_CLOSEOUT_KIND,
        "adapter_id": P13B_OVERLAP_TRIAGE_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "P13BOverlapTriageCloseoutV1",
        "manifest_id": f"P13B-OVERLAP-TRIAGE-CLOSEOUT-{_fingerprint({'summary': summary, 'projects': project_table})[:16]}",
        "created_at": created,
        "source_company_history_triage_root": str(company_dir),
        "source_original_notice_backtrace_root": str(original_dir),
        "source_ygp_readback_root": str(ygp_dir),
        "source_ygp_coverage_closeout_root": str(coverage_dir or ""),
        "project_overlap_triage_records": project_table,
        "company_history_readback_records": company_table,
        "original_notice_readback_records": original_table,
        "release_evidence_trigger_records": release_table,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "flow_08_parse_enabled": False,
            "llm_execution_enabled": False,
            "manifest_stores_raw_html_or_blob": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "p13b_overlap_triage_closeout_mode": "BUILT" if not missing_inputs else "INPUT_BLOCKED",
        "safe_to_execute": not missing_inputs,
        "blocking_reasons": missing_inputs,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, project_table, company_table, original_table, release_table)
    return result


def _company_history_readback_table(company_manifest: Mapping[str, Any], *, created_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in _list(company_manifest.get("company_history_query_records")):
        if not isinstance(record, Mapping):
            continue
        blockers = _list(record.get("blocker_taxonomy"))
        query_state = str(record.get("query_state") or "")
        if "max_live_companies_deferred" in blockers:
            closeout_state = "SOURCE_LIMIT_DEFERRED"
        elif query_state == "COMPANY_HISTORY_RECORD_FOUND":
            closeout_state = "COMPANY_HISTORY_RECORD_FOUND"
        elif query_state == "SOURCE_BLOCKED_RETRY_REQUIRED":
            closeout_state = "ORIGINAL_NOTICE_READBACK_REQUIRED"
        else:
            closeout_state = "NO_OVERLAP_SIGNAL_REVIEW"
        rows.append(
            {
                "project_id": str(record.get("project_id") or ""),
                "project_name": str(record.get("project_name") or ""),
                "candidate_company_name": str(record.get("candidate_company_name") or ""),
                "responsible_person_names": _list(record.get("responsible_person_names")),
                "company_history_query_task_id": str(record.get("company_history_query_task_id") or ""),
                "query_state": query_state,
                "triage_closeout_state": closeout_state,
                "uniscid": str(record.get("uniscid") or ""),
                "search_url": str(record.get("search_url") or ""),
                "search_total": _int(record.get("search_total")),
                "bid_list_total": _int(record.get("bid_list_total")),
                "selected_bid_record_count": _int(record.get("selected_bid_record_count")),
                "blocker_taxonomy": blockers,
                "query_miss_is_not_clearance": True,
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _original_notice_readback_table(
    original_manifest: Mapping[str, Any],
    ygp_manifest: Mapping[str, Any],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    extraction_by_key = {
        _notice_key(record): record
        for record in _list(original_manifest.get("original_notice_extraction_records"))
        if isinstance(record, Mapping)
    }
    overlap_by_key = {
        _notice_key(record): record
        for record in _list(original_manifest.get("original_notice_overlap_signal_records"))
        if isinstance(record, Mapping)
    }
    ygp_by_key = {
        _notice_key(record): record
        for record in _list(ygp_manifest.get("ygp_original_readback_records"))
        if isinstance(record, Mapping)
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fetch in _list(original_manifest.get("original_notice_fetch_records")):
        if not isinstance(fetch, Mapping):
            continue
        key = _notice_key(fetch)
        seen.add(key)
        extraction = extraction_by_key.get(key, {})
        overlap = overlap_by_key.get(key, {})
        ygp = ygp_by_key.get(key, {})
        rows.append(_original_notice_row(fetch, extraction, overlap, ygp, created_at=created_at))
    for key, extraction in extraction_by_key.items():
        if key in seen:
            continue
        seen.add(key)
        overlap = overlap_by_key.get(key, {})
        ygp = ygp_by_key.get(key, {})
        rows.append(_original_notice_row(extraction, extraction, overlap, ygp, created_at=created_at))
    for key, ygp in ygp_by_key.items():
        if key in seen:
            continue
        rows.append(_original_notice_row(ygp, {}, {}, ygp, created_at=created_at))
    return rows


def _original_notice_row(
    base: Mapping[str, Any],
    extraction: Mapping[str, Any],
    overlap: Mapping[str, Any],
    ygp: Mapping[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    blockers = _dedupe([*_list(base.get("blocker_taxonomy")), *_list(extraction.get("blocker_taxonomy")), *_list(ygp.get("blocker_taxonomy"))])
    fetch_state = str(base.get("fetch_state") or "")
    extraction_state = str(extraction.get("original_notice_extraction_state") or "")
    overlap_state = str(overlap.get("original_notice_overlap_signal_state") or "")
    ygp_state = str(ygp.get("ygp_readback_state") or "")
    if overlap_state == "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED":
        closeout_state = "OVERLAP_SIGNAL_REVIEW_REQUIRED"
    elif any(str(item).startswith("max_live_") for item in blockers):
        closeout_state = "SOURCE_LIMIT_DEFERRED"
    elif ygp_state in {"YGP_ORIGINAL_URL_UNSUPPORTED", "YGP_ORIGINAL_URL_BLOCKED"} or (
        extraction_state == "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED" and "ygp.gdzwfw.gov.cn" in str(base.get("original_notice_url") or base.get("source_url") or "").lower()
    ):
        closeout_state = "YGP_READBACK_BLOCKED_OR_UNSUPPORTED"
    elif fetch_state == "ORIGINAL_NOTICE_FETCH_BLOCKED" or extraction_state == "ORIGINAL_NOTICE_FETCH_BLOCKED":
        closeout_state = "ORIGINAL_NOTICE_READBACK_REQUIRED"
    elif extraction_state in {"ORIGINAL_NOTICE_NO_MATCH_REVIEW", "ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED"} or ygp_state in {
        "YGP_ORIGINAL_URL_READBACK_READY",
        "YGP_BROWSER_NETWORK_READBACK_READY",
    }:
        closeout_state = "NO_OVERLAP_SIGNAL_REVIEW"
    else:
        closeout_state = "ORIGINAL_NOTICE_READBACK_REQUIRED"
    return {
        "project_id": str(base.get("project_id") or extraction.get("project_id") or ygp.get("project_id") or ""),
        "project_name": str(base.get("project_name") or extraction.get("project_name") or ygp.get("project_name") or ""),
        "candidate_company_name": str(base.get("candidate_company_name") or extraction.get("candidate_company_name") or ygp.get("candidate_company_name") or ""),
        "responsible_person_names": _list(base.get("responsible_person_names") or extraction.get("responsible_person_names") or ygp.get("responsible_person_names")),
        "original_notice_task_id": str(base.get("original_notice_task_id") or extraction.get("original_notice_task_id") or ygp.get("original_notice_task_id") or ""),
        "original_notice_url": str(base.get("original_notice_url") or extraction.get("original_notice_url") or ygp.get("original_notice_url") or ""),
        "source_url": str(base.get("source_url") or extraction.get("source_url") or ygp.get("source_url") or ""),
        "fetch_state": fetch_state,
        "original_notice_extraction_state": extraction_state,
        "original_notice_overlap_signal_state": overlap_state,
        "ygp_readback_state": ygp_state,
        "extracted_responsible_person_names": _list(extraction.get("extracted_responsible_person_names") or ygp.get("extracted_responsible_person_names")),
        "extracted_period_text": str(extraction.get("extracted_period_text") or ygp.get("extracted_period_text") or ""),
        "extracted_award_date": str(extraction.get("extracted_award_date") or ygp.get("extracted_award_date") or ""),
        "matched_person_names": _list(overlap.get("matched_person_names")),
        "triage_closeout_state": closeout_state,
        "release_evidence_probe_triggered": bool(overlap.get("release_evidence_probe_triggered")),
        "blocker_taxonomy": blockers,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _release_evidence_trigger_table(
    company_manifest: Mapping[str, Any],
    original_manifest: Mapping[str, Any],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    for record in _list(company_manifest.get("overlap_signal_records")):
        if isinstance(record, Mapping) and str(record.get("overlap_signal_state") or "") == "OVERLAP_SIGNAL_REVIEW_REQUIRED":
            rows_by_key.setdefault(
                _release_key(record),
                _release_row(record, source_stage="DATA_GGZY_BID_SHOW", created_at=created_at),
            )
    for record in _list(original_manifest.get("original_notice_overlap_signal_records")):
        if isinstance(record, Mapping) and str(record.get("original_notice_overlap_signal_state") or "") == "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED":
            # The original notice is closer to the source document than the
            # data.ggzy bid_show summary, so it wins when both describe the
            # same company/person overlap candidate.
            rows_by_key[_release_key(record)] = _release_row(record, source_stage="ORIGINAL_NOTICE_BACKTRACE", created_at=created_at)
    return list(rows_by_key.values())


def _release_key(record: Mapping[str, Any]) -> str:
    people = _list(record.get("matched_person_names")) or _list(record.get("responsible_person_names"))
    normalized_people = ",".join(sorted(str(item) for item in people if str(item)))
    if not normalized_people:
        normalized_people = str(record.get("source_url") or record.get("bid_show_url") or record.get("original_notice_url") or "")
    return "|".join(
        (
            str(record.get("project_id") or ""),
            str(record.get("candidate_company_name") or ""),
            normalized_people,
        )
    )


def _release_row(record: Mapping[str, Any], *, source_stage: str, created_at: str) -> dict[str, Any]:
    return {
        "release_evidence_trigger_id": _stable_id("P13B-RELEASE-TRIGGER", source_stage, record.get("project_id"), record.get("candidate_company_name"), record.get("source_url") or record.get("bid_show_url")),
        "source_stage": source_stage,
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "candidate_company_name": str(record.get("candidate_company_name") or ""),
        "matched_person_names": _list(record.get("matched_person_names")),
        "responsible_person_names": _list(record.get("responsible_person_names")),
        "source_url": str(record.get("source_url") or record.get("bid_show_url") or record.get("original_notice_url") or ""),
        "extracted_period_text": str(record.get("extracted_period_text") or ""),
        "extracted_award_date": str(record.get("extracted_award_date") or ""),
        "release_evidence_probe_triggered": True,
        "suggested_next_step": "targeted_release_evidence_probe",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_overlap_triage_table(
    *,
    company_manifest: Mapping[str, Any],
    original_table: list[Mapping[str, Any]],
    company_table: list[Mapping[str, Any]],
    release_table: list[Mapping[str, Any]],
    coverage_manifest: Mapping[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    projects: dict[str, dict[str, Any]] = {}
    for record in _list(company_manifest.get("project_task_records")):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "")
        if not project_id:
            continue
        projects.setdefault(project_id, {}).update(
            {
                "project_id": project_id,
                "project_name": str(record.get("project_name") or ""),
                "city_code": str(record.get("city_code") or ""),
                "candidate_notice_source_urls": _list(record.get("candidate_notice_source_urls")),
                "candidate_companies": _list(record.get("candidate_companies")),
                "responsible_person_names": _list(record.get("responsible_person_names")),
            }
        )
    for record in _list(coverage_manifest.get("city_coverage_records")):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "")
        if project_id and project_id in projects:
            projects[project_id].setdefault("city_code", str(record.get("city_code") or ""))
            projects[project_id]["ygp_coverage_state"] = str(record.get("city_coverage_state") or "")
            projects[project_id]["ygp_source_07_url"] = str(record.get("source_07_url") or record.get("source_url") or "")
    rows: list[dict[str, Any]] = []
    for project_id in sorted(projects):
        project = projects[project_id]
        company_rows = [row for row in company_table if str(row.get("project_id") or "") == project_id]
        original_rows = [row for row in original_table if str(row.get("project_id") or "") == project_id]
        release_rows = [row for row in release_table if str(row.get("project_id") or "") == project_id]
        state = _project_state(company_rows, original_rows, release_rows)
        rows.append(
            {
                **project,
                "project_overlap_triage_state": state,
                "company_history_query_count": len(company_rows),
                "queried_company_count": sum(1 for row in company_rows if str(row.get("query_state") or "") != "PLAN_ONLY_NOT_EXECUTED"),
                "company_history_record_found_count": sum(1 for row in company_rows if str(row.get("query_state") or "") == "COMPANY_HISTORY_RECORD_FOUND"),
                "original_notice_readback_count": len(original_rows),
                "original_notice_state_counts": _counts(row.get("triage_closeout_state") for row in original_rows),
                "release_evidence_trigger_count": len(release_rows),
                "source_limit_deferred_count": sum(1 for row in [*company_rows, *original_rows] if row.get("triage_closeout_state") == "SOURCE_LIMIT_DEFERRED"),
                "ygp_readback_blocked_or_unsupported_count": sum(1 for row in original_rows if row.get("triage_closeout_state") == "YGP_READBACK_BLOCKED_OR_UNSUPPORTED"),
                "query_miss_is_not_clearance": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "created_at": created_at,
            }
        )
    return rows


def _project_state(company_rows: list[Mapping[str, Any]], original_rows: list[Mapping[str, Any]], release_rows: list[Mapping[str, Any]]) -> str:
    if release_rows:
        return "OVERLAP_SIGNAL_REVIEW_REQUIRED"
    states = {str(row.get("triage_closeout_state") or "") for row in [*company_rows, *original_rows]}
    if "YGP_READBACK_BLOCKED_OR_UNSUPPORTED" in states:
        return "YGP_READBACK_BLOCKED_OR_UNSUPPORTED"
    if "ORIGINAL_NOTICE_READBACK_REQUIRED" in states:
        return "ORIGINAL_NOTICE_READBACK_REQUIRED"
    if "SOURCE_LIMIT_DEFERRED" in states:
        return "SOURCE_LIMIT_DEFERRED"
    return "NO_OVERLAP_SIGNAL_REVIEW"


def _summary(
    *,
    project_records: list[Mapping[str, Any]],
    company_records: list[Mapping[str, Any]],
    original_records: list[Mapping[str, Any]],
    release_records: list[Mapping[str, Any]],
    company_manifest: Mapping[str, Any],
    original_manifest: Mapping[str, Any],
    ygp_manifest: Mapping[str, Any],
    missing_inputs: list[str],
) -> dict[str, Any]:
    return {
        "p13b_overlap_triage_closeout_state": "P13B_OVERLAP_TRIAGE_CLOSEOUT_READY" if not missing_inputs else "P13B_OVERLAP_TRIAGE_CLOSEOUT_INPUT_BLOCKED",
        "project_count": len(project_records),
        "company_history_query_count": len(company_records),
        "queried_company_count": sum(1 for row in company_records if str(row.get("query_state") or "") != "PLAN_ONLY_NOT_EXECUTED"),
        "company_history_record_found_count": sum(1 for row in company_records if str(row.get("query_state") or "") == "COMPANY_HISTORY_RECORD_FOUND"),
        "bid_show_record_count": len(_list(company_manifest.get("bid_show_records"))),
        "original_notice_readback_count": len(original_records),
        "original_notice_fetch_count": _int(_summary_field(original_manifest, "original_notice_fetch_count")),
        "original_notice_extraction_count": _int(_summary_field(original_manifest, "original_notice_extraction_count")),
        "ygp_original_readback_count": _int(_summary_field(ygp_manifest, "ygp_original_readback_count")),
        "ygp_readback_ready_count": _int(_summary_field(ygp_manifest, "ygp_readback_ready_count")),
        "overlap_signal_review_required_count": len(release_records),
        "release_evidence_trigger_count": len(release_records),
        "manual_release_evidence_probe_count": len(release_records),
        "source_limit_deferred_count": sum(1 for row in [*company_records, *original_records] if row.get("triage_closeout_state") == "SOURCE_LIMIT_DEFERRED"),
        "original_notice_readback_required_count": sum(1 for row in original_records if row.get("triage_closeout_state") == "ORIGINAL_NOTICE_READBACK_REQUIRED"),
        "ygp_readback_blocked_or_unsupported_count": sum(1 for row in original_records if row.get("triage_closeout_state") == "YGP_READBACK_BLOCKED_OR_UNSUPPORTED"),
        "project_state_counts": _counts(row.get("project_overlap_triage_state") for row in project_records),
        "company_state_counts": _counts(row.get("triage_closeout_state") for row in company_records),
        "original_notice_state_counts": _counts(row.get("triage_closeout_state") for row in original_records),
        "blocking_reasons": missing_inputs,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PASS",
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    project_records: list[Mapping[str, Any]],
    company_records: list[Mapping[str, Any]],
    original_records: list[Mapping[str, Any]],
    release_records: list[Mapping[str, Any]],
) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*result.get("blocking_reasons", []), *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"] = result["summary"]
        text = json.dumps(result, ensure_ascii=False, indent=2)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "p13b-overlap-triage-closeout-v1.json").write_text(text, encoding="utf-8")
    _write_json(out_dir / "project-overlap-triage-table.json", {"summary": result["summary"], "records": project_records})
    _write_json(out_dir / "company-history-readback-table.json", {"summary": result["summary"], "records": company_records})
    _write_json(out_dir / "original-notice-readback-table.json", {"summary": result["summary"], "records": original_records})
    _write_json(out_dir / "release-evidence-trigger-table.json", {"summary": result["summary"], "records": release_records})


def _load_json(path: Path, missing_inputs: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        missing_inputs.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        missing_inputs.append(f"{missing_reason}_invalid_json")
        return {}
    if isinstance(payload, dict):
        return payload
    missing_inputs.append(f"{missing_reason}_not_object")
    return {}


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    return manifest if isinstance(manifest, Mapping) else {}


def _summary_field(manifest: Mapping[str, Any], key: str) -> Any:
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), Mapping) else {}
    return summary.get(key)


def _notice_key(record: Mapping[str, Any]) -> str:
    task_id = str(record.get("original_notice_task_id") or "")
    url = str(record.get("original_notice_url") or record.get("source_url") or "")
    if task_id:
        return f"task:{task_id}"
    return f"url:{url}"


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for value in values:
        key = str(value or "")
        if key:
            counter[key] += 1
    return dict(sorted(counter.items()))


def _dedupe(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint(parts)[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B overlap triage closeout v1.")
    parser.add_argument("--company-history-triage-root", default=str(DEFAULT_COMPANY_HISTORY_TRIAGE_ROOT))
    parser.add_argument("--original-notice-backtrace-root", default=str(DEFAULT_ORIGINAL_NOTICE_BACKTRACE_ROOT))
    parser.add_argument("--ygp-readback-root", default=str(DEFAULT_YGP_READBACK_ROOT))
    parser.add_argument("--ygp-coverage-closeout-root", default=str(DEFAULT_YGP_COVERAGE_CLOSEOUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_overlap_triage_closeout(
        company_history_triage_root=args.company_history_triage_root,
        original_notice_backtrace_root=args.original_notice_backtrace_root,
        ygp_readback_root=args.ygp_readback_root,
        ygp_coverage_closeout_root=args.ygp_coverage_closeout_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        summary = result["summary"]
        print(
            "p13b overlap triage closeout built: "
            f"state={summary.get('p13b_overlap_triage_closeout_state')} "
            f"projects={summary.get('project_count')} "
            f"release_triggers={summary.get('release_evidence_trigger_count')}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
