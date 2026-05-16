from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGDONG_YGP_CITY_COVERAGE_CLOSEOUT_KIND = "guangdong_ygp_city_coverage_closeout_v1_manifest"
GUANGDONG_YGP_CITY_COVERAGE_CLOSEOUT_VERSION = 1
GUANGDONG_YGP_CITY_COVERAGE_CLOSEOUT_ADAPTER_ID = "guangdong-ygp-city-coverage-closeout-v1-builder"

DEFAULT_CITY_DISCOVERY_ROOT = Path("tmp/evaluation-real-samples/ygp-morecity-smoke-v1-city-discovery")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/ygp-morecity-smoke-v1-07-download")
DEFAULT_MINI_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/ygp-evidence-mini-closeout-v2")
DEFAULT_OVERSIZE_POLICY_ROOT = Path("tmp/evaluation-real-samples/ygp-oversize-policy-v1")
DEFAULT_P13B_YGP_EXPANSION_ROOT = Path("tmp/evaluation-real-samples/p13b-ygp-original-readback-expansion-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-ygp-city-coverage-closeout-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "确认本人", "是不是本人", "在建冲突成立", "违法成立", "造假成立")
P13B_READY_STATES = {
    "P13B_YGP_ORIGINAL_READBACK_READY",
    "P13B_YGP_BACKLOG_TRACKED_READY",
    "P13B_YGP_NO_PUBLIC_ATTACHMENT_BUT_DETAIL_READY",
}


def build_guangdong_ygp_city_coverage_closeout(
    city_discovery_root: str | Path = DEFAULT_CITY_DISCOVERY_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    mini_closeout_root: str | Path = DEFAULT_MINI_CLOSEOUT_ROOT,
    oversize_policy_root: str | Path = DEFAULT_OVERSIZE_POLICY_ROOT,
    p13b_ygp_expansion_root: str | Path = DEFAULT_P13B_YGP_EXPANSION_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    city_discovery_dir = Path(city_discovery_root)
    download_dir = Path(download_root)
    mini_dir = Path(mini_closeout_root)
    oversize_dir = Path(oversize_policy_root)
    p13b_dir = Path(p13b_ygp_expansion_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    mini_closeout = _load_first_json(
        [
            mini_dir / "ygp-evidence-mini-closeout-v2.json",
            mini_dir / "ygp-evidence-mini-closeout-v1.json",
        ],
        missing_inputs,
        "ygp_evidence_mini_closeout_missing",
    )
    mini_city_table = _load_json(mini_dir / "ygp-city-project-table.json", missing_inputs, "ygp_city_project_table_missing")
    oversize_policy = _load_json(oversize_dir / "ygp-oversize-policy-v1.json", missing_inputs, "ygp_oversize_policy_missing")
    p13b_expansion = _load_json(
        p13b_dir / "p13b-ygp-original-readback-expansion-v1.json",
        missing_inputs,
        "p13b_ygp_original_readback_expansion_missing",
    )
    city_discovery = _load_first_json(
        [
            city_discovery_dir / "guangdong-ygp-city-discovery-v1.json",
            download_dir / "city-discovery" / "guangdong-ygp-city-discovery-v1.json",
        ],
        missing_inputs,
        "ygp_city_discovery_manifest_missing",
    )
    full_chain = _load_json(download_dir / "ygp-full-chain-manifest.json", missing_inputs, "ygp_full_chain_manifest_missing")

    city_records = _mini_city_records(mini_closeout, mini_city_table)
    city_names = _city_names(_source_manifest(city_discovery), _source_manifest(full_chain))
    oversize_by_key, oversize_by_city = _oversize_counts(_source_manifest(oversize_policy))
    p13b_by_key, p13b_by_city = _p13b_task_counts(_source_manifest(p13b_expansion))
    p13b_overlap_by_key, p13b_overlap_by_city = _p13b_overlap_counts(_source_manifest(p13b_expansion))

    coverage_records = [
        _coverage_record(
            record=record,
            city_name=str(city_names.get(str(record.get("city_code") or "")) or ""),
            oversize_counts=_counts_for_record(record, oversize_by_key, oversize_by_city),
            p13b_counts=_counts_for_record(record, p13b_by_key, p13b_by_city),
            p13b_overlap_counts=_counts_for_record(record, p13b_overlap_by_key, p13b_overlap_by_city),
        )
        for record in city_records
    ]
    p13b_ready_records = [record for record in coverage_records if record.get("p13b_ready")]
    blocker_records = [_blocker_record(record) for record in coverage_records if _has_blocker(record)]
    recommendation_records = [_recommendation_record(record) for record in coverage_records]

    summary = _build_summary(
        coverage_records=coverage_records,
        p13b_ready_records=p13b_ready_records,
        missing_inputs=missing_inputs,
    )
    manifest = {
        "manifest_version": GUANGDONG_YGP_CITY_COVERAGE_CLOSEOUT_VERSION,
        "manifest_kind": GUANGDONG_YGP_CITY_COVERAGE_CLOSEOUT_KIND,
        "adapter_id": GUANGDONG_YGP_CITY_COVERAGE_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "GuangdongYgpCityCoverageCloseoutV1",
        "manifest_id": f"GUANGDONG-YGP-CITY-COVERAGE-{_fingerprint({'summary': summary, 'cities': coverage_records})[:16]}",
        "created_at": created,
        "source_city_discovery_root": str(city_discovery_dir),
        "source_download_root": str(download_dir),
        "source_mini_closeout_root": str(mini_dir),
        "source_oversize_policy_root": str(oversize_dir),
        "source_p13b_ygp_expansion_root": str(p13b_dir),
        "source_city_discovery_manifest_path": str(_loaded_path(city_discovery) or ""),
        "source_full_chain_manifest_path": str(download_dir / "ygp-full-chain-manifest.json"),
        "source_mini_closeout_manifest_path": str(_loaded_path(mini_closeout) or ""),
        "source_oversize_policy_manifest_path": str(oversize_dir / "ygp-oversize-policy-v1.json"),
        "source_p13b_ygp_expansion_manifest_path": str(p13b_dir / "p13b-ygp-original-readback-expansion-v1.json"),
        "city_coverage_records": coverage_records,
        "p13b_ready_project_records": p13b_ready_records,
        "city_blocker_records": blocker_records,
        "next_stage_recommendation_records": recommendation_records,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "flow_08_default_downloaded": False,
            "flow_08_default_downloaded_count": 0,
            "stage4_live_provider_enabled": False,
            "stage4_live_executed": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangdong_ygp_city_coverage_closeout_mode": "BUILT" if not missing_inputs else "INPUT_BLOCKED",
        "safe_to_execute": not missing_inputs,
        "blocking_reasons": missing_inputs,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, coverage_records, p13b_ready_records, blocker_records, recommendation_records)
    return result


def _mini_city_records(mini_closeout: Mapping[str, Any], city_table: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = _source_manifest(mini_closeout)
    by_city: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for source_records in (city_table.get("records"), manifest.get("city_project_records")):
        for record in _list(source_records):
            if not isinstance(record, Mapping):
                continue
            city_code = str(record.get("city_code") or "")
            if not city_code:
                continue
            if city_code not in by_city:
                order.append(city_code)
            by_city[city_code] = dict(record)
    return [by_city[city_code] for city_code in order]


def _coverage_record(
    *,
    record: Mapping[str, Any],
    city_name: str,
    oversize_counts: Mapping[str, int],
    p13b_counts: Mapping[str, int],
    p13b_overlap_counts: Mapping[str, int],
) -> dict[str, Any]:
    has_recent_07 = bool(record.get("has_recent_07"))
    oversize_queue_count = _first_int(record.get("oversize_queue_count"), oversize_counts.get("oversize_queue_count"))
    limit_deferred_queue_count = _first_int(record.get("limit_deferred_queue_count"), oversize_counts.get("limit_deferred_queue_count"))
    p13b_task_count = _int(p13b_counts.get("p13b_task_count"))
    p13b_ready_count = _int(p13b_counts.get("p13b_ready_count"))
    p13b_overlap_input_count = _int(p13b_overlap_counts.get("p13b_overlap_input_count"))
    p13b_ready = p13b_ready_count > 0
    p13b_input_ready = p13b_ready and p13b_overlap_input_count > 0
    no_public_attachment = (
        str(record.get("evidence_package_readiness_state") or "") == "YGP_EVIDENCE_MINI_NO_PUBLIC_ATTACHMENT_REVIEW"
        or str(record.get("city_closeout_state") or "") == "YGP_CITY_NO_PUBLIC_ATTACHMENT_REVIEW"
        or _int(record.get("listed_attachment_count")) <= 0 and has_recent_07
    )
    blocked = _is_blocked(record)
    state = _coverage_state(
        has_recent_07=has_recent_07,
        blocked=blocked,
        no_public_attachment=no_public_attachment,
        backlog_count=oversize_queue_count + limit_deferred_queue_count,
        p13b_input_ready=p13b_input_ready,
    )
    action = _recommended_next_action(state, backlog_count=oversize_queue_count + limit_deferred_queue_count)
    return {
        "city_code": str(record.get("city_code") or ""),
        "city_name_optional": city_name,
        "source_role": "YGP_GUANGDONG_NON_GZ_SZ_CITY",
        "has_recent_07": has_recent_07,
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "source_07_url": str(record.get("source_url") or ""),
        "source_url": str(record.get("source_url") or ""),
        "flow_bucket_count": _int(record.get("flow_bucket_count")),
        "present_flow_nos": _list(record.get("present_flow_nos")),
        "detail_readback_ready_count": _int(record.get("detail_readback_ready_count")),
        "attachment_listed_count": _int(record.get("listed_attachment_count")),
        "download_attempted_count": _int(record.get("download_attempted_count")),
        "attachment_snapshot_count": _int(record.get("attachment_snapshot_count")),
        "attachment_snapshot_success_rate": float(record.get("attachment_snapshot_success_rate") or 0.0),
        "fake_attachment_count": _int(record.get("fake_attachment_count")),
        "oversize_queue_count": oversize_queue_count,
        "limit_deferred_queue_count": limit_deferred_queue_count,
        "no_public_attachment": bool(no_public_attachment),
        "p13b_ready": bool(p13b_ready),
        "p13b_input_ready": bool(p13b_input_ready),
        "p13b_task_count": p13b_task_count,
        "p13b_ready_task_count": p13b_ready_count,
        "p13b_overlap_input_count": p13b_overlap_input_count,
        "city_coverage_state": state,
        "recommended_next_action": action,
        "failure_taxonomy_counts": dict(record.get("failure_taxonomy_counts") or {}),
        "real_download_failure_count": _int(record.get("real_download_failure_count")),
        "flow_08_default_downloaded": bool(record.get("flow_08_default_downloaded")),
        "stage4_live_executed": bool(record.get("stage4_live_executed")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _coverage_state(
    *,
    has_recent_07: bool,
    blocked: bool,
    no_public_attachment: bool,
    backlog_count: int,
    p13b_input_ready: bool,
) -> str:
    if not has_recent_07:
        return "YGP_CITY_COVERAGE_NO_RECENT_07"
    if blocked:
        return "YGP_CITY_COVERAGE_BLOCKED"
    if no_public_attachment:
        return "YGP_CITY_COVERAGE_NO_PUBLIC_ATTACHMENT_REVIEW"
    if backlog_count > 0:
        return "YGP_CITY_COVERAGE_READY_WITH_BACKLOG"
    if p13b_input_ready:
        return "YGP_CITY_COVERAGE_READY_FOR_P13B"
    return "YGP_CITY_COVERAGE_PARTIAL_REVIEW"


def _recommended_next_action(state: str, *, backlog_count: int) -> str:
    if state == "YGP_CITY_COVERAGE_READY_FOR_P13B":
        return "ENTER_P13B_COMPANY_HISTORY_OVERLAP_TRIAGE"
    if state == "YGP_CITY_COVERAGE_READY_WITH_BACKLOG":
        return "KEEP_BACKLOG_AND_ENTER_P13B"
    if state == "YGP_CITY_COVERAGE_NO_PUBLIC_ATTACHMENT_REVIEW":
        return "REVIEW_NO_PUBLIC_ATTACHMENT_PROJECT"
    if state == "YGP_CITY_COVERAGE_NO_RECENT_07":
        return "RETRY_CITY_DISCOVERY_WITH_WIDER_WINDOW"
    if state == "YGP_CITY_COVERAGE_BLOCKED":
        return "CITY_ADAPTER_REVIEW_REQUIRED"
    if backlog_count > 0:
        return "OVERSIZE_POLICY_FOLLOWUP"
    return "REVIEW_PARTIAL_P13B_INPUT"


def _is_blocked(record: Mapping[str, Any]) -> bool:
    if _int(record.get("real_download_failure_count")) > 0:
        return True
    if _int(record.get("fake_attachment_count")) > 0:
        return True
    if bool(record.get("flow_08_default_downloaded")) or bool(record.get("stage4_live_executed")):
        return True
    if bool(record.get("has_recent_07")) and (_int(record.get("flow_bucket_count")) != 12 or _int(record.get("detail_readback_ready_count")) <= 0):
        return True
    return False


def _has_blocker(record: Mapping[str, Any]) -> bool:
    return str(record.get("city_coverage_state") or "") == "YGP_CITY_COVERAGE_BLOCKED"


def _blocker_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "city_code": record.get("city_code"),
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "city_coverage_state": record.get("city_coverage_state"),
        "failure_taxonomy_counts": dict(record.get("failure_taxonomy_counts") or {}),
        "no_public_attachment": bool(record.get("no_public_attachment")),
        "real_download_failure_count": record.get("real_download_failure_count"),
        "fake_attachment_count": record.get("fake_attachment_count"),
        "flow_08_default_downloaded": bool(record.get("flow_08_default_downloaded")),
        "stage4_live_executed": bool(record.get("stage4_live_executed")),
        "recommended_next_action": record.get("recommended_next_action"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _recommendation_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "city_code": record.get("city_code"),
        "project_id": record.get("project_id"),
        "city_coverage_state": record.get("city_coverage_state"),
        "recommended_next_action": record.get("recommended_next_action"),
        "p13b_ready": bool(record.get("p13b_ready")),
        "p13b_overlap_input_count": record.get("p13b_overlap_input_count"),
        "oversize_queue_count": record.get("oversize_queue_count"),
        "limit_deferred_queue_count": record.get("limit_deferred_queue_count"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _build_summary(
    *,
    coverage_records: list[Mapping[str, Any]],
    p13b_ready_records: list[Mapping[str, Any]],
    missing_inputs: list[str],
) -> dict[str, Any]:
    state_counts = _counts(record.get("city_coverage_state") for record in coverage_records)
    real_download_failure_count = sum(_int(record.get("real_download_failure_count")) for record in coverage_records)
    total_oversize = sum(_int(record.get("oversize_queue_count")) for record in coverage_records)
    total_limit = sum(_int(record.get("limit_deferred_queue_count")) for record in coverage_records)
    blocked_count = state_counts.get("YGP_CITY_COVERAGE_BLOCKED", 0)
    total_p13b_tasks = sum(_int(record.get("p13b_task_count")) for record in coverage_records)
    total_p13b_overlap = sum(_int(record.get("p13b_overlap_input_count")) for record in coverage_records)
    recommended_global = _global_recommended_next_action(
        blocked_count=blocked_count,
        total_p13b_overlap=total_p13b_overlap,
        total_backlog=total_oversize + total_limit,
    )
    return {
        "city_coverage_closeout_state": "YGP_GUANGDONG_CITY_COVERAGE_CLOSEOUT_READY" if not missing_inputs else "YGP_GUANGDONG_CITY_COVERAGE_CLOSEOUT_INPUT_BLOCKED",
        "city_count": len(coverage_records),
        "city_with_recent_07_count": sum(1 for record in coverage_records if record.get("has_recent_07")),
        "city_no_recent_07_count": state_counts.get("YGP_CITY_COVERAGE_NO_RECENT_07", 0),
        "coverage_ready_for_p13b_count": state_counts.get("YGP_CITY_COVERAGE_READY_FOR_P13B", 0),
        "ready_for_p13b_count": state_counts.get("YGP_CITY_COVERAGE_READY_FOR_P13B", 0),
        "coverage_ready_with_backlog_count": state_counts.get("YGP_CITY_COVERAGE_READY_WITH_BACKLOG", 0),
        "ready_with_backlog_count": state_counts.get("YGP_CITY_COVERAGE_READY_WITH_BACKLOG", 0),
        "no_public_attachment_city_count": state_counts.get("YGP_CITY_COVERAGE_NO_PUBLIC_ATTACHMENT_REVIEW", 0),
        "no_recent_07_count": state_counts.get("YGP_CITY_COVERAGE_NO_RECENT_07", 0),
        "blocked_city_count": blocked_count,
        "total_project_count": sum(1 for record in coverage_records if record.get("project_id")),
        "total_p13b_task_count": total_p13b_tasks,
        "p13b_task_count": total_p13b_tasks,
        "total_p13b_ready_project_count": len(p13b_ready_records),
        "p13b_ready_project_count": len(p13b_ready_records),
        "total_p13b_overlap_input_count": total_p13b_overlap,
        "p13b_overlap_input_count": total_p13b_overlap,
        "total_oversize_queue_count": total_oversize,
        "total_limit_deferred_queue_count": total_limit,
        "real_download_failure_count": real_download_failure_count,
        "fake_attachment_count": sum(_int(record.get("fake_attachment_count")) for record in coverage_records),
        "stage4_live_executed": any(bool(record.get("stage4_live_executed")) for record in coverage_records),
        "flow_08_default_downloaded_count": sum(1 for record in coverage_records if record.get("flow_08_default_downloaded")),
        "city_coverage_state_counts": state_counts,
        "recommended_next_action": recommended_global,
        "recommended_parallel_action": "OVERSIZE_POLICY_FOLLOWUP" if total_oversize + total_limit > 0 else "",
        "missing_inputs": missing_inputs,
        "forbidden_term_scan_state": "PENDING",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _global_recommended_next_action(*, blocked_count: int, total_p13b_overlap: int, total_backlog: int) -> str:
    if blocked_count > 0:
        return "CITY_ADAPTER_REVIEW_REQUIRED"
    if total_p13b_overlap > 0 and total_backlog > 0:
        return "KEEP_BACKLOG_AND_ENTER_P13B"
    if total_p13b_overlap > 0:
        return "ENTER_P13B_COMPANY_HISTORY_OVERLAP_TRIAGE"
    if total_backlog > 0:
        return "OVERSIZE_POLICY_FOLLOWUP"
    return "SHENZHEN_INDEPENDENT_ADAPTER_NEXT"


def _city_names(city_discovery_manifest: Mapping[str, Any], full_manifest: Mapping[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for record in _list(city_discovery_manifest.get("ygp_city_search_records")):
        if isinstance(record, Mapping):
            city_code = str(record.get("city_code") or "")
            name = str(record.get("city_name") or record.get("city_name_optional") or "")
            if city_code and name:
                names[city_code] = name
    for item in _list(full_manifest.get("items")):
        if isinstance(item, Mapping):
            city_code = str(item.get("city_code") or "")
            name = str(item.get("city_name") or item.get("city_name_optional") or "")
            if city_code and name:
                names.setdefault(city_code, name)
    return names


def _oversize_counts(manifest: Mapping[str, Any]) -> tuple[dict[tuple[str, str], dict[str, int]], dict[str, dict[str, int]]]:
    by_key: dict[tuple[str, str], Counter[str]] = {}
    by_city: dict[str, Counter[str]] = {}
    for record in _list(manifest.get("oversize_attachment_queue")):
        if not isinstance(record, Mapping):
            continue
        state = str(record.get("policy_state") or "")
        city_code = str(record.get("city_code") or "")
        project_id = str(record.get("project_id") or "")
        if state not in {"OVERSIZE_QUEUE_READY", "LIMIT_DEFERRED_QUEUE_READY"}:
            continue
        key = "oversize_queue_count" if state == "OVERSIZE_QUEUE_READY" else "limit_deferred_queue_count"
        by_key.setdefault((city_code, project_id), Counter()).update([key])
        by_city.setdefault(city_code, Counter()).update([key])
    return (
        {key: dict(counter) for key, counter in by_key.items()},
        {key: dict(counter) for key, counter in by_city.items()},
    )


def _p13b_task_counts(manifest: Mapping[str, Any]) -> tuple[dict[tuple[str, str], dict[str, int]], dict[str, dict[str, int]]]:
    by_key: dict[tuple[str, str], Counter[str]] = {}
    by_city: dict[str, Counter[str]] = {}
    for record in _list(manifest.get("task_records")):
        if not isinstance(record, Mapping):
            continue
        city_code = str(record.get("city_code") or "")
        project_id = str(record.get("project_id") or "")
        state = str(record.get("p13b_ygp_original_readback_state") or "")
        counter_values = ["p13b_task_count"]
        if state in P13B_READY_STATES:
            counter_values.append("p13b_ready_count")
        by_key.setdefault((city_code, project_id), Counter()).update(counter_values)
        by_city.setdefault(city_code, Counter()).update(counter_values)
    return (
        {key: dict(counter) for key, counter in by_key.items()},
        {key: dict(counter) for key, counter in by_city.items()},
    )


def _p13b_overlap_counts(manifest: Mapping[str, Any]) -> tuple[dict[tuple[str, str], dict[str, int]], dict[str, dict[str, int]]]:
    by_key: dict[tuple[str, str], Counter[str]] = {}
    by_city: dict[str, Counter[str]] = {}
    for record in _list(manifest.get("overlap_triage_input_records")):
        if not isinstance(record, Mapping):
            continue
        city_code = str(record.get("city_code") or "")
        project_id = str(record.get("project_id") or "")
        by_key.setdefault((city_code, project_id), Counter()).update(["p13b_overlap_input_count"])
        by_city.setdefault(city_code, Counter()).update(["p13b_overlap_input_count"])
    return (
        {key: dict(counter) for key, counter in by_key.items()},
        {key: dict(counter) for key, counter in by_city.items()},
    )


def _counts_for_record(
    record: Mapping[str, Any],
    by_key: Mapping[tuple[str, str], Mapping[str, int]],
    by_city: Mapping[str, Mapping[str, int]],
) -> Mapping[str, int]:
    city_code = str(record.get("city_code") or "")
    project_id = str(record.get("project_id") or "")
    if (city_code, project_id) in by_key:
        return by_key[(city_code, project_id)]
    return by_city.get(city_code, {})


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    coverage_records: list[Mapping[str, Any]],
    p13b_ready_records: list[Mapping[str, Any]],
    blocker_records: list[Mapping[str, Any]],
    recommendation_records: list[Mapping[str, Any]],
) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *list(result.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    _write_json(out_dir / "ygp-city-coverage-table.json", {"summary": result["summary"], "records": coverage_records})
    _write_json(out_dir / "ygp-p13b-ready-project-table.json", {"summary": result["summary"], "records": p13b_ready_records})
    _write_json(out_dir / "ygp-city-blocker-table.json", {"summary": result["summary"], "records": blocker_records})
    _write_json(out_dir / "ygp-next-stage-recommendation-table.json", {"summary": result["summary"], "records": recommendation_records})
    _write_json(out_dir / "guangdong-ygp-city-coverage-closeout-v1.json", result)


def _load_first_json(paths: list[Path], missing: list[str], reason: str) -> dict[str, Any]:
    for path in paths:
        if path.exists():
            payload = _load_json(path, missing, reason)
            payload["_loaded_path"] = str(path)
            return payload
    missing.append(reason)
    return {}


def _loaded_path(payload: Mapping[str, Any]) -> str:
    return str(payload.get("_loaded_path") or "")


def _load_json(path: Path, missing: list[str], reason: str) -> dict[str, Any]:
    if not path.exists():
        missing.append(reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        missing.append(f"{reason}:invalid_json")
        return {}


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counter = Counter(str(value) for value in values if str(value or "").strip())
    return dict(sorted(counter.items()))


def _first_int(*values: Any) -> int:
    for value in values:
        if value is not None and value != "":
            return _int(value)
    return 0


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangdong YGP city coverage closeout v1.")
    parser.add_argument("--city-discovery-root", default=str(DEFAULT_CITY_DISCOVERY_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--mini-closeout-root", default=str(DEFAULT_MINI_CLOSEOUT_ROOT))
    parser.add_argument("--oversize-policy-root", default=str(DEFAULT_OVERSIZE_POLICY_ROOT))
    parser.add_argument("--p13b-ygp-expansion-root", default=str(DEFAULT_P13B_YGP_EXPANSION_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_guangdong_ygp_city_coverage_closeout(
        city_discovery_root=args.city_discovery_root,
        download_root=args.download_root,
        mini_closeout_root=args.mini_closeout_root,
        oversize_policy_root=args.oversize_policy_root,
        p13b_ygp_expansion_root=args.p13b_ygp_expansion_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            "guangdong ygp city coverage closeout built: "
            f"state={summary.get('city_coverage_closeout_state')} "
            f"cities={summary.get('city_count')} "
            f"with_07={summary.get('city_with_recent_07_count')} "
            f"p13b_ready={summary.get('p13b_ready_project_count')} "
            f"blocked={summary.get('blocked_city_count')}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
