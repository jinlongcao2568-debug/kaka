from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


P13B_ORIGINAL_BACKTRACE_CONTINUATION_KIND = "p13b_original_backtrace_continuation_controller_v2_manifest"
P13B_ORIGINAL_BACKTRACE_CONTINUATION_VERSION = 2
P13B_ORIGINAL_BACKTRACE_CONTINUATION_ADAPTER_ID = "p13b-original-backtrace-continuation-controller-v2"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-original-backtrace-continuation-controller-v2")


def build_p13b_original_backtrace_continuation_controller(
    *,
    original_notice_backtrace_json: str | Path | None = None,
    original_notice_backtrace_root: str | Path | None = None,
    targeted_person_readback_json: str | Path | None = None,
    targeted_person_readback_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    continuation_input_root = out_dir / "continuation-input"
    out_dir.mkdir(parents=True, exist_ok=True)
    continuation_input_root.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    original_manifest = _load_original_manifest(
        original_notice_backtrace_json=original_notice_backtrace_json,
        original_notice_backtrace_root=original_notice_backtrace_root,
        blocking_reasons=blocking_reasons,
    )
    targeted_person_lookup = _load_targeted_person_readback_lookup(
        targeted_person_readback_json=targeted_person_readback_json,
        targeted_person_readback_root=targeted_person_readback_root,
    )
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    plan_records = _continuation_plan_records(
        original_manifest,
        targeted_person_lookup=targeted_person_lookup,
        selected_projects=selected_projects,
        created_at=created,
    )
    continuation_input_rows = [
        _continuation_input_row(record)
        for record in plan_records
        if str(record.get("continuation_state") or "") == "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT"
    ]
    continuation_input = {
        "manifest": {
            "manifest_kind": "p13b_original_backtrace_continuation_input_v1",
            "created_at": created,
            "manual_original_url_backtrace_table": continuation_input_rows,
            "bid_show_records": [_bid_show_row(record) for record in plan_records if record.get("bid_show_record_id")],
            "source_original_notice_backtrace_json": str(original_notice_backtrace_json or ""),
            "source_original_notice_backtrace_root": str(original_notice_backtrace_root or ""),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "summary": {
            "manual_original_url_backtrace_count": len(continuation_input_rows),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    summary = _summary(plan_records, continuation_input_rows, blocking_reasons)
    manifest = {
        "manifest_version": P13B_ORIGINAL_BACKTRACE_CONTINUATION_VERSION,
        "manifest_kind": P13B_ORIGINAL_BACKTRACE_CONTINUATION_KIND,
        "adapter_id": P13B_ORIGINAL_BACKTRACE_CONTINUATION_ADAPTER_ID,
        "pipeline_stage": "P13BOriginalBacktraceContinuationControllerV2",
        "manifest_id": f"P13B-ORIGINAL-BACKTRACE-CONT-{_fingerprint({'records': plan_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_original_notice_backtrace_json": str(original_notice_backtrace_json or ""),
        "source_original_notice_backtrace_root": str(original_notice_backtrace_root or ""),
        "source_targeted_person_readback_json": str(targeted_person_readback_json or ""),
        "source_targeted_person_readback_root": str(targeted_person_readback_root or ""),
        "targeted_person_readback_record_count": len(targeted_person_lookup),
        "project_ids": list(project_ids),
        "continuation_company_history_triage_root": str(continuation_input_root),
        "continuation_company_history_triage_json": str(continuation_input_root / "company-history-overlap-triage-v1.json"),
        "continuation_plan_records": plan_records,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "p13b_original_backtrace_continuation_controller_mode": "BUILT"
        if not blocking_reasons
        else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "p13b-original-backtrace-continuation-controller-v2.json", result)
    _write_json(out_dir / "original-backtrace-continuation-plan-v2.json", {"summary": summary, "records": plan_records})
    _write_json(continuation_input_root / "company-history-overlap-triage-v1.json", continuation_input)
    return result


def _continuation_plan_records(
    original_manifest: Mapping[str, Any],
    *,
    targeted_person_lookup: Mapping[str, Mapping[str, Any]],
    selected_projects: set[str],
    created_at: str,
) -> list[dict[str, Any]]:
    task_by_id = {
        str(record.get("original_notice_task_id") or ""): record
        for record in _list(original_manifest.get("original_notice_task_records"))
        if isinstance(record, Mapping) and record.get("original_notice_task_id")
    }
    extraction_by_id = {
        str(record.get("original_notice_task_id") or ""): record
        for record in _list(original_manifest.get("original_notice_extraction_records"))
        if isinstance(record, Mapping) and record.get("original_notice_task_id")
    }
    overlap_by_id = {
        str(record.get("original_notice_task_id") or ""): record
        for record in _list(original_manifest.get("original_notice_overlap_signal_records"))
        if isinstance(record, Mapping) and record.get("original_notice_task_id")
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fetch in _list(original_manifest.get("original_notice_fetch_records")):
        if not isinstance(fetch, Mapping):
            continue
        task_id = str(fetch.get("original_notice_task_id") or "")
        if not task_id:
            continue
        record = _plan_record(
            base={**dict(task_by_id.get(task_id, {})), **dict(fetch)},
            extraction=extraction_by_id.get(task_id, {}),
            overlap=overlap_by_id.get(task_id, {}),
            targeted_person_readback=targeted_person_lookup.get(task_id, {}),
            created_at=created_at,
        )
        if selected_projects and _project_key(record.get("project_id")) not in selected_projects:
            continue
        rows.append(record)
        seen.add(task_id)
    for task_id, task in task_by_id.items():
        if task_id in seen:
            continue
        record = _plan_record(
            base=task,
            extraction=extraction_by_id.get(task_id, {}),
            overlap=overlap_by_id.get(task_id, {}),
            targeted_person_readback=targeted_person_lookup.get(task_id, {}),
            created_at=created_at,
        )
        if selected_projects and _project_key(record.get("project_id")) not in selected_projects:
            continue
        rows.append(record)
    rows.sort(
        key=lambda row: (
            _continuation_sort_rank(str(row.get("continuation_state") or "")),
            -int(row.get("original_notice_live_priority_score") or 0),
            int(row.get("original_notice_live_priority_rank") or 999999),
            int(row.get("original_notice_source_order") or 999999),
            str(row.get("original_notice_task_id") or ""),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["continuation_priority_rank"] = index
    return rows


def _plan_record(
    *,
    base: Mapping[str, Any],
    extraction: Mapping[str, Any],
    overlap: Mapping[str, Any],
    targeted_person_readback: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    blockers = _dedupe([*_list(base.get("blocker_taxonomy")), *_list(extraction.get("blocker_taxonomy"))])
    match_state = str(overlap.get("original_notice_backtrace_match_state") or "")
    state, action, reasons = _continuation_decision(
        fetch_state=str(base.get("fetch_state") or ""),
        execution_mode=str(base.get("execution_mode") or ""),
        blockers=blockers,
        route_class=str(base.get("original_notice_route_class") or ""),
        live_budget_eligible=base.get("original_notice_live_budget_eligible") is not False,
        match_state=match_state,
        overlap_state=str(overlap.get("original_notice_overlap_signal_state") or ""),
        targeted_person_readback_state=str(targeted_person_readback.get("targeted_person_readback_state") or ""),
        targeted_person_signal_ready=bool(targeted_person_readback.get("same_person_company_period_signal_ready")),
        targeted_person_blockers=[
            *[str(item) for item in _list(targeted_person_readback.get("blocker_taxonomy"))],
            *[str(item) for item in _list(targeted_person_readback.get("review_reasons"))],
        ],
    )
    return {
        "original_notice_task_id": str(base.get("original_notice_task_id") or ""),
        "project_id": str(base.get("project_id") or ""),
        "project_name": str(base.get("project_name") or ""),
        "candidate_company_name": str(base.get("candidate_company_name") or ""),
        "responsible_person_names": _list(base.get("responsible_person_names") or overlap.get("responsible_person_names")),
        "bid_project_name": str(base.get("bid_project_name") or ""),
        "historical_project_area_code": str(base.get("historical_project_area_code") or base.get("bid_area_code") or ""),
        "bid_area_code": str(base.get("bid_area_code") or base.get("historical_project_area_code") or ""),
        "original_notice_url": str(base.get("original_notice_url") or ""),
        "bid_show_record_id": str(base.get("bid_show_record_id") or ""),
        "bid_show_url": str(base.get("bid_show_url") or ""),
        "original_notice_route_class": str(base.get("original_notice_route_class") or ""),
        "original_notice_route_strategy": str(base.get("original_notice_route_strategy") or ""),
        "original_notice_live_priority_score": int(base.get("original_notice_live_priority_score") or 0),
        "original_notice_live_priority_rank": int(base.get("original_notice_live_priority_rank") or 0),
        "original_notice_source_order": int(base.get("original_notice_source_order") or 0),
        "fetch_state": str(base.get("fetch_state") or ""),
        "execution_mode": str(base.get("execution_mode") or ""),
        "original_notice_backtrace_match_state": match_state,
        "original_notice_overlap_signal_state": str(overlap.get("original_notice_overlap_signal_state") or ""),
        "extracted_responsible_person_names": _list(overlap.get("extracted_responsible_person_names") or extraction.get("extracted_responsible_person_names")),
        "different_person_names": _list(overlap.get("different_person_names")),
        "matched_person_names": _list(overlap.get("matched_person_names")),
        "extracted_period_text": str(overlap.get("extracted_period_text") or extraction.get("extracted_period_text") or ""),
        "candidate_company_matched": bool(overlap.get("candidate_company_matched")),
        "performance_period_present": bool(overlap.get("performance_period_present")),
        "targeted_person_readback_state": str(targeted_person_readback.get("targeted_person_readback_state") or ""),
        "targeted_person_signal_ready": bool(targeted_person_readback.get("same_person_company_period_signal_ready")),
        "continuation_state": state,
        "recommended_next_action": action,
        "review_reasons": reasons,
        "blocker_taxonomy": blockers,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _continuation_decision(
    *,
    fetch_state: str,
    execution_mode: str,
    blockers: list[str],
    route_class: str,
    live_budget_eligible: bool,
    match_state: str,
    overlap_state: str,
    targeted_person_readback_state: str,
    targeted_person_signal_ready: bool,
    targeted_person_blockers: list[str],
) -> tuple[str, str, list[str]]:
    route_readback_consumed = execution_mode in {"LOCAL_YGP_READBACK_CONSUMED", "LOCAL_BROWSER_READBACK_CONSUMED"}
    if overlap_state == "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED" or match_state == "SAME_PERSON_COMPANY_PERIOD_SIGNAL":
        return (
            "RELEASE_EVIDENCE_READY",
            "build_release_evidence_regional_adapter_plan",
            ["same_person_company_performance_period_signal_already_found"],
        )
    if targeted_person_signal_ready:
        return (
            "RELEASE_EVIDENCE_READY",
            "build_release_evidence_regional_adapter_plan",
            ["targeted_person_readback_found_same_person_company_period_signal"],
        )
    if targeted_person_readback_state in {
        "TARGETED_PERSON_NOT_FOUND_IN_TARGETED_READBACK",
        "TARGETED_PERSON_NOT_FOUND_NO_ATTACHMENT_LINKS",
    }:
        return (
            "PARK_TARGETED_PERSON_NOT_FOUND",
            "park_without_clearance_claim",
            targeted_person_blockers or ["targeted_person_readback_executed_without_same_person_signal"],
        )
    if targeted_person_readback_state in {"TARGETED_PERSON_PAGE_FETCH_BLOCKED", "TARGETED_PERSON_READBACK_DEFERRED_BY_LIMIT"}:
        return (
            "BLOCKED_OR_SOURCE_UNSUPPORTED",
            "manual_review_or_retry_targeted_person_readback_without_clearance_claim",
            targeted_person_blockers or ["targeted_person_readback_blocked_or_deferred"],
        )
    if route_class == "YGP_MAPPING_POINTER" and not route_readback_consumed:
        return (
            "TARGETED_YGP_READBACK_REQUIRED",
            "run_ygp_original_readback_before_original_backtrace",
            ["ygp_mapping_pointer_should_not_consume_direct_live_budget"],
        )
    if route_class == "INVALID_OR_MISSING_URL":
        return (
            "BLOCKED_OR_SOURCE_UNSUPPORTED",
            "manual_review_missing_or_invalid_original_notice_url_without_clearance_claim",
            blockers or ["original_notice_url_missing_or_invalid"],
        )
    if not live_budget_eligible and not route_readback_consumed:
        return (
            "ROUTE_SPECIFIC_READBACK_REQUIRED",
            "run_route_specific_readback_before_direct_live_retry",
            ["original_notice_route_not_live_budget_eligible"],
        )
    if execution_mode == "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT" or "max_live_original_notices_deferred" in blockers:
        return (
            "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT",
            "run_next_live_original_notice_backtrace_batch",
            ["original_notice_backtrace_budget_deferred_or_incomplete"],
        )
    if match_state == "PERIOD_AND_COMPANY_NO_PERSON":
        return (
            "TARGETED_PERSON_READBACK_REQUIRED",
            "run_browser_or_attachment_ocr_readback_for_responsible_person",
            ["candidate_company_and_performance_period_present_but_responsible_person_missing"],
        )
    if match_state == "EXTRACTED_DIFFERENT_PERSON_WITH_PERIOD":
        return (
            "PARK_DIFFERENT_PERSON_WITH_PERIOD",
            "park_or_manual_review_without_release_probe",
            ["extracted_responsible_person_differs_from_candidate_with_period"],
        )
    if match_state == "EXTRACTED_DIFFERENT_PERSON_NO_PERIOD":
        return (
            "PARK_DIFFERENT_PERSON_NO_PERIOD",
            "park_low_priority_or_manual_review_without_clearance_claim",
            ["extracted_responsible_person_differs_from_candidate_without_period"],
        )
    if match_state == "COMPANY_ONLY_NO_PERSON_PERIOD":
        return (
            "LOW_VALUE_COMPANY_ONLY_REVIEW",
            "park_or_targeted_readback_if_value_justifies",
            ["candidate_company_present_but_person_and_period_missing"],
        )
    if match_state == "NO_COMPANY_PERSON_PERIOD_MATCH":
        return (
            "PARK_NO_EXTRACTED_MATCH_FIELDS",
            "park_without_clearance_claim",
            ["original_notice_no_company_person_period_match"],
        )
    if fetch_state in {"ORIGINAL_NOTICE_FETCH_BLOCKED", "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"}:
        return (
            "BLOCKED_OR_SOURCE_UNSUPPORTED",
            "manual_review_or_route_specific_readback_without_clearance_claim",
            blockers or ["original_notice_fetch_blocked_or_source_unsupported"],
        )
    if not fetch_state:
        return (
            "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT",
            "run_live_original_notice_backtrace_for_unattempted_task",
            ["original_notice_task_not_attempted"],
        )
    return (
        "PARK_LOW_VALUE_REVIEW",
        "park_without_clearance_claim",
        ["original_notice_backtrace_no_a_signal"],
    )


def _continuation_input_row(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "candidate_company_name": str(record.get("candidate_company_name") or ""),
        "responsible_person_names": _list(record.get("responsible_person_names")),
        "bid_project_name": str(record.get("bid_project_name") or ""),
        "historical_project_area_code": str(record.get("historical_project_area_code") or record.get("bid_area_code") or ""),
        "bid_area_code": str(record.get("bid_area_code") or record.get("historical_project_area_code") or ""),
        "original_notice_url": str(record.get("original_notice_url") or ""),
        "bid_show_record_id": str(record.get("bid_show_record_id") or ""),
        "bid_show_url": str(record.get("bid_show_url") or ""),
        "backtrace_reason": "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT",
        "suggested_next_step": "run_next_live_original_notice_backtrace_batch",
        "source_original_notice_task_id": str(record.get("original_notice_task_id") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _bid_show_row(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(record.get("project_id") or ""),
        "candidate_company_name": str(record.get("candidate_company_name") or ""),
        "bid_show_record_id": str(record.get("bid_show_record_id") or ""),
        "bid_show_url": str(record.get("bid_show_url") or ""),
        "bid_project_name": str(record.get("bid_project_name") or ""),
        "historical_project_area_code": str(record.get("historical_project_area_code") or record.get("bid_area_code") or ""),
        "bid_area_code": str(record.get("bid_area_code") or record.get("historical_project_area_code") or ""),
        "original_notice_url": str(record.get("original_notice_url") or ""),
    }


def _summary(
    plan_records: list[Mapping[str, Any]],
    continuation_input_rows: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    state_counts = _counts(record.get("continuation_state") for record in plan_records)
    next_action = "NO_CONTINUATION_ACTION"
    if continuation_input_rows:
        next_action = "RUN_NEXT_ORIGINAL_BACKTRACE_BATCH"
    elif int(state_counts.get("RELEASE_EVIDENCE_READY", 0)):
        next_action = "BUILD_RELEASE_EVIDENCE_REGIONAL_ADAPTER_PLAN"
    elif int(state_counts.get("TARGETED_PERSON_READBACK_REQUIRED", 0)):
        next_action = "RUN_TARGETED_BROWSER_OR_ATTACHMENT_READBACK"
    elif plan_records:
        next_action = "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM"
    return {
        "continuation_plan_record_count": len(plan_records),
        "continuation_run_task_count": len(continuation_input_rows),
        "deferred_task_count": int(state_counts.get("CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT", 0)),
        "release_evidence_ready_count": int(state_counts.get("RELEASE_EVIDENCE_READY", 0)),
        "targeted_person_readback_required_count": int(state_counts.get("TARGETED_PERSON_READBACK_REQUIRED", 0)),
        "parked_or_low_value_count": sum(
            count
            for state, count in state_counts.items()
            if state.startswith("PARK_") or state.startswith("LOW_VALUE_")
        ),
        "continuation_state_counts": state_counts,
        "recommended_next_action": next_action,
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _load_original_manifest(
    *,
    original_notice_backtrace_json: str | Path | None,
    original_notice_backtrace_root: str | Path | None,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    manifests: list[Mapping[str, Any]] = []
    source_paths: list[Path] = []
    for path in _split_paths(original_notice_backtrace_json):
        source_paths.append(Path(path))
    for root in _split_paths(original_notice_backtrace_root):
        source_paths.append(Path(root) / "original-notice-backtrace-v1.json")
    if not source_paths:
        blocking_reasons.append("original_notice_backtrace_input_missing")
        return {}
    for path in source_paths:
        payload = _load_json(path)
        if not payload:
            continue
        manifests.append(_source_manifest(payload))
    if not manifests:
        blocking_reasons.append("original_notice_backtrace_input_missing_or_invalid")
        return {}
    return _merge_manifests(manifests)


def _load_targeted_person_readback_lookup(
    *,
    targeted_person_readback_json: str | Path | None,
    targeted_person_readback_root: str | Path | None,
) -> dict[str, Mapping[str, Any]]:
    source_paths: list[Path] = []
    for path in _split_paths(targeted_person_readback_json):
        source_paths.append(Path(path))
    for root in _split_paths(targeted_person_readback_root):
        source_paths.append(Path(root) / "p13b-targeted-person-readback-v1.json")
    lookup: dict[str, Mapping[str, Any]] = {}
    for path in source_paths:
        payload = _load_json(path)
        if not payload:
            continue
        manifest = _source_manifest(payload)
        for record in _list(manifest.get("targeted_person_readback_records")):
            if not isinstance(record, Mapping):
                continue
            task_id = str(record.get("original_notice_task_id") or "").strip()
            if task_id:
                lookup[task_id] = record
    return lookup


def _merge_manifests(manifests: list[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for manifest in manifests:
        for key, value in manifest.items():
            if isinstance(value, list):
                existing = merged.setdefault(key, [])
                if isinstance(existing, list):
                    existing.extend(value)
                continue
            if isinstance(value, Mapping):
                existing = merged.get(key)
                merged[key] = {**(existing if isinstance(existing, Mapping) else {}), **dict(value)}
                continue
            if value not in ("", None, [], {}) or key not in merged:
                merged[key] = value
    for key, value in list(merged.items()):
        if isinstance(value, list):
            merged[key] = _dedupe_records(value)
    return merged


def _dedupe_records(records: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    indexes_by_key: dict[str, int] = {}
    for record in records:
        key = _record_identity(record)
        if key in indexes_by_key:
            out[indexes_by_key[key]] = record
            continue
        indexes_by_key[key] = len(out)
        out.append(record)
    return out


def _record_identity(record: Any) -> str:
    if isinstance(record, Mapping):
        task_id = str(record.get("original_notice_task_id") or "").strip()
        if task_id:
            return f"original_notice_task_id:{task_id}"
        project_id = str(record.get("project_id") or "").strip()
        company = str(record.get("candidate_company_name") or "").strip()
        url = str(record.get("original_notice_url") or record.get("source_url") or "").strip()
        if project_id and url:
            return f"project_url:{project_id}|{company}|{url}"
    return f"fingerprint:{_fingerprint(record)}"


def _split_paths(value: str | Path | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("PROJ-"):
        return text.rsplit("-", 1)[-1]
    return text


def _continuation_sort_rank(state: str) -> int:
    ranks = {
        "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT": 0,
        "RELEASE_EVIDENCE_READY": 10,
        "TARGETED_PERSON_READBACK_REQUIRED": 20,
        "BLOCKED_OR_SOURCE_UNSUPPORTED": 30,
    }
    return ranks.get(state, 50)


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build P13B original backtrace continuation controller v2 outputs.")
    parser.add_argument("--original-notice-backtrace-json", default="")
    parser.add_argument("--original-notice-backtrace-root", default="")
    parser.add_argument("--targeted-person-readback-json", default="")
    parser.add_argument("--targeted-person-readback-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_p13b_original_backtrace_continuation_controller(
        original_notice_backtrace_json=args.original_notice_backtrace_json or None,
        original_notice_backtrace_root=args.original_notice_backtrace_root or None,
        targeted_person_readback_json=args.targeted_person_readback_json or None,
        targeted_person_readback_root=args.targeted_person_readback_root or None,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "P13B_ORIGINAL_BACKTRACE_CONTINUATION_KIND",
    "build_p13b_original_backtrace_continuation_controller",
]
