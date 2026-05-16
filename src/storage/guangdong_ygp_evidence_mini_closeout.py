from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGDONG_YGP_EVIDENCE_MINI_CLOSEOUT_KIND = "guangdong_ygp_evidence_mini_closeout_v1_manifest"
GUANGDONG_YGP_EVIDENCE_MINI_CLOSEOUT_VERSION = 1
GUANGDONG_YGP_EVIDENCE_MINI_CLOSEOUT_ADAPTER_ID = "guangdong-ygp-evidence-mini-closeout-v1-builder"

DEFAULT_CITY_DISCOVERY_ROOT = Path("tmp/evaluation-real-samples/ygp-morecity-smoke-v1-city-discovery")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/ygp-morecity-smoke-v1-07-download")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/ygp-evidence-mini-closeout-v1")
DEFAULT_CITY_CODES = (
    "440200",
    "440700",
    "440800",
    "440900",
    "441200",
    "441300",
    "441400",
    "441500",
    "441600",
    "441700",
    "441800",
    "441900",
    "442000",
    "445100",
    "445200",
    "445300",
)

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
STRATEGY_DEFERRED_TAXONOMIES = {"DEFERRED_BY_YGP_DOWNLOAD_LIMIT", "OVERSIZE_DEFERRED_BY_POLICY"}
NO_PUBLIC_ATTACHMENT_TAXONOMIES = {"ygp_no_public_attachment_link_found"}
REAL_DOWNLOAD_FAILURE_TAXONOMIES = {
    "ygp_attachment_empty_response_review",
    "ygp_attachment_interface_error",
    "ygp_attachment_not_file_like_response",
    "ygp_attachment_transport_error_retry_required",
    "ygp_attachment_temporary_unavailable_retry_required",
    "ygp_attachment_incomplete_read_retry_required",
    "ygp_attachment_login_or_permission_required",
    "ygp_attachment_captcha_or_challenge_required",
    "ygp_attachment_interface_expired_or_stale",
    "ygp_attachment_file_not_found_or_expired",
    "ygp_attachment_snapshot_readback_missing",
    "ygp_attachment_snapshot_captured_human_write_failed",
}


def build_guangdong_ygp_evidence_mini_closeout(
    *,
    city_discovery_root: str | Path = DEFAULT_CITY_DISCOVERY_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    city_codes: list[str] | tuple[str, ...] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    city_discovery_dir = Path(city_discovery_root)
    download_dir = Path(download_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    full_chain = _load_json(download_dir / "ygp-full-chain-manifest.json", missing_inputs, "ygp_full_chain_manifest_missing")
    batch_closeout = _load_json(download_dir / "guangdong-ygp-batch-stability-closeout-v1.json", missing_inputs, "ygp_batch_closeout_missing")
    discovery = _load_first_json(
        [
            download_dir / "city-discovery" / "guangdong-ygp-city-discovery-v1.json",
            city_discovery_dir / "guangdong-ygp-city-discovery-v1.json",
        ],
        missing_inputs,
        "ygp_city_discovery_manifest_missing",
    )
    flow_matrix = _load_first_json(
        [
            download_dir / "city-discovery" / "flow-matrix" / "guangdong-ygp-flow-matrix-v1.json",
            city_discovery_dir / "flow-matrix" / "guangdong-ygp-flow-matrix-v1.json",
        ],
        missing_inputs,
        "ygp_flow_matrix_manifest_missing",
    )

    full_manifest = _source_manifest(full_chain)
    full_summary = _summary(full_chain)
    closeout_summary = _summary(batch_closeout)
    discovery_manifest = _source_manifest(discovery)
    flow_manifest = _source_manifest(flow_matrix)

    cities = _city_codes(city_codes, full_manifest, discovery_manifest)
    items_by_city = {
        str(item.get("city_code") or ""): dict(item)
        for item in _list(full_manifest.get("items"))
        if isinstance(item, Mapping) and str(item.get("flow_no") or "") == "07"
    }
    samples_by_project = {
        str(sample.get("project_id") or ""): dict(sample)
        for sample in _list(full_manifest.get("project_sample_items"))
        if isinstance(sample, Mapping)
    }
    project_records_by_key = _project_records_by_key(flow_manifest)
    flow_buckets_by_key = _flow_buckets_by_key(flow_manifest)
    city_search_blockers = _city_search_blockers(discovery_manifest)
    flow08_downloaded_by_city = _flow08_default_downloaded_by_city(full_manifest)
    stage4_live_executed = _stage4_live_executed(full_chain, batch_closeout)

    city_project_records = [
        _city_project_record(
            city_code=city_code,
            item=items_by_city.get(city_code),
            samples_by_project=samples_by_project,
            project_records_by_key=project_records_by_key,
            flow_buckets_by_key=flow_buckets_by_key,
            city_search_blockers=city_search_blockers,
            flow08_default_downloaded=flow08_downloaded_by_city.get(city_code, False),
            stage4_live_executed=stage4_live_executed,
        )
        for city_code in cities
    ]
    download_stability_records = [_download_stability_record(record) for record in city_project_records]
    next_action_records = [_next_action_record(record) for record in city_project_records]

    summary = _build_summary(
        city_project_records=city_project_records,
        full_summary=full_summary,
        closeout_summary=closeout_summary,
        missing_inputs=missing_inputs,
        stage4_live_executed=stage4_live_executed,
    )
    manifest = {
        "manifest_version": GUANGDONG_YGP_EVIDENCE_MINI_CLOSEOUT_VERSION,
        "manifest_kind": GUANGDONG_YGP_EVIDENCE_MINI_CLOSEOUT_KIND,
        "adapter_id": GUANGDONG_YGP_EVIDENCE_MINI_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "GuangdongYgpEvidenceMiniCloseoutV1",
        "manifest_id": f"GUANGDONG-YGP-EVIDENCE-MINI-{_fingerprint({'summary': summary, 'cities': city_project_records})[:16]}",
        "created_at": created,
        "source_city_discovery_root": str(city_discovery_dir),
        "source_download_root": str(download_dir),
        "source_full_chain_manifest_path": str(download_dir / "ygp-full-chain-manifest.json"),
        "source_city_discovery_manifest_path": str(_loaded_path(discovery) or ""),
        "source_flow_matrix_manifest_path": str(_loaded_path(flow_matrix) or ""),
        "city_codes": cities,
        "summary": summary,
        "city_project_records": city_project_records,
        "download_stability_records": download_stability_records,
        "next_action_records": next_action_records,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "flow_08_default_downloaded": any(record["flow_08_default_downloaded"] for record in city_project_records),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangdong_ygp_evidence_mini_closeout_mode": "BUILT" if not missing_inputs else "INPUT_BLOCKED",
        "safe_to_execute": not missing_inputs,
        "blocking_reasons": missing_inputs,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, city_project_records, download_stability_records, next_action_records)
    return result


def _city_project_record(
    *,
    city_code: str,
    item: Mapping[str, Any] | None,
    samples_by_project: Mapping[str, Mapping[str, Any]],
    project_records_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    flow_buckets_by_key: Mapping[tuple[str, str], list[Mapping[str, Any]]],
    city_search_blockers: Mapping[str, Counter[str]],
    flow08_default_downloaded: bool,
    stage4_live_executed: bool,
) -> dict[str, Any]:
    if not item:
        failure_counts = dict(city_search_blockers.get(city_code) or {})
        if not failure_counts:
            failure_counts = {"no_supported_07_candidate": 1}
        return {
            "city_code": city_code,
            "has_recent_07": False,
            "project_id": "",
            "project_name": "",
            "source_url": "",
            "flow_bucket_count": 0,
            "flow_bucket_count_is_12": False,
            "present_flow_nos": [],
            "detail_readback_ready_count": 0,
            "listed_attachment_count": 0,
            "download_attempted_count": 0,
            "attachment_snapshot_count": 0,
            "attachment_snapshot_success_rate": 0.0,
            "fake_attachment_count": 0,
            "flow_08_default_downloaded": False,
            "stage4_live_executed": bool(stage4_live_executed),
            "failure_taxonomy_counts": failure_counts,
            "strategy_deferred_counts": {},
            "real_download_failure_taxonomy_counts": {},
            "real_download_failure_count": 0,
            "city_closeout_state": "YGP_CITY_NO_RECENT_07_REVIEW",
            "recommended_next_action": _recommended_next_action("YGP_CITY_NO_RECENT_07_REVIEW"),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    project_id = str(item.get("project_id") or "")
    sample = dict(samples_by_project.get(project_id) or {})
    project_code = str(sample.get("project_code") or "")
    project_key = (city_code, project_code)
    buckets = list(flow_buckets_by_key.get(project_key) or [])
    project_record = dict(project_records_by_key.get(project_key) or {})
    failure_counts = _counts(_list(item.get("failure_taxonomy")))
    strategy_deferred_counts = {key: value for key, value in failure_counts.items() if key in STRATEGY_DEFERRED_TAXONOMIES}
    real_failure_counts = {key: value for key, value in failure_counts.items() if key in REAL_DOWNLOAD_FAILURE_TAXONOMIES}
    fake_count = _fake_attachment_count(sample)
    attempted = _int(item.get("download_attempted_count"))
    snapshots = _int(item.get("attachment_snapshot_count"))
    listed = _int(item.get("listed_attachment_count"))
    success_rate = snapshots / attempted if attempted else 0.0
    present_flow_nos = sorted(
        {
            str(bucket.get("flow_no") or "")
            for bucket in buckets
            if str(bucket.get("flow_item_state") or "") == "YGP_FLOW_ITEM_PRESENT"
        }
    )
    detail_ready = _int(project_record.get("detail_readback_ready_count"))
    state = _city_closeout_state(
        flow_bucket_count=len(buckets),
        detail_readback_ready_count=detail_ready,
        listed_attachment_count=listed,
        failure_counts=failure_counts,
        strategy_deferred_counts=strategy_deferred_counts,
        real_failure_counts=real_failure_counts,
        fake_attachment_count=fake_count,
        flow08_default_downloaded=flow08_default_downloaded,
        stage4_live_executed=stage4_live_executed,
    )
    return {
        "city_code": city_code,
        "has_recent_07": True,
        "project_id": project_id,
        "project_name": str(item.get("project_name") or sample.get("project_name") or ""),
        "source_url": str(item.get("source_url") or sample.get("source_url") or ""),
        "flow_bucket_count": len(buckets),
        "flow_bucket_count_is_12": len(buckets) == 12,
        "present_flow_nos": present_flow_nos,
        "detail_readback_ready_count": detail_ready,
        "listed_attachment_count": listed,
        "download_attempted_count": attempted,
        "attachment_snapshot_count": snapshots,
        "attachment_snapshot_success_rate": success_rate,
        "fake_attachment_count": fake_count,
        "flow_08_default_downloaded": bool(flow08_default_downloaded),
        "stage4_live_executed": bool(stage4_live_executed),
        "failure_taxonomy_counts": failure_counts,
        "strategy_deferred_counts": strategy_deferred_counts,
        "real_download_failure_taxonomy_counts": real_failure_counts,
        "real_download_failure_count": sum(real_failure_counts.values()),
        "city_closeout_state": state,
        "recommended_next_action": _recommended_next_action(state),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _city_closeout_state(
    *,
    flow_bucket_count: int,
    detail_readback_ready_count: int,
    listed_attachment_count: int,
    failure_counts: Mapping[str, int],
    strategy_deferred_counts: Mapping[str, int],
    real_failure_counts: Mapping[str, int],
    fake_attachment_count: int,
    flow08_default_downloaded: bool,
    stage4_live_executed: bool,
) -> str:
    if flow_bucket_count != 12 or detail_readback_ready_count <= 0:
        return "YGP_CITY_SOURCE_OR_DOWNLOAD_BLOCKED"
    if real_failure_counts or fake_attachment_count > 0 or flow08_default_downloaded or stage4_live_executed:
        return "YGP_CITY_SOURCE_OR_DOWNLOAD_BLOCKED"
    if listed_attachment_count <= 0 or any(key in failure_counts for key in NO_PUBLIC_ATTACHMENT_TAXONOMIES):
        return "YGP_CITY_NO_PUBLIC_ATTACHMENT_REVIEW"
    if strategy_deferred_counts:
        other = {
            key: value
            for key, value in failure_counts.items()
            if key not in STRATEGY_DEFERRED_TAXONOMIES and key not in NO_PUBLIC_ATTACHMENT_TAXONOMIES
        }
        if not other:
            return "YGP_CITY_ATTACHMENT_POLICY_DEFERRED"
    if failure_counts and not set(failure_counts).issubset(STRATEGY_DEFERRED_TAXONOMIES | NO_PUBLIC_ATTACHMENT_TAXONOMIES):
        return "YGP_CITY_REVIEW_REQUIRED"
    return "YGP_CITY_EVIDENCE_MINI_READY"


def _download_stability_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "city_code": record.get("city_code"),
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "listed_attachment_count": record.get("listed_attachment_count"),
        "download_attempted_count": record.get("download_attempted_count"),
        "attachment_snapshot_count": record.get("attachment_snapshot_count"),
        "attachment_snapshot_success_rate": record.get("attachment_snapshot_success_rate"),
        "strategy_deferred_counts": dict(record.get("strategy_deferred_counts") or {}),
        "real_download_failure_taxonomy_counts": dict(record.get("real_download_failure_taxonomy_counts") or {}),
        "fake_attachment_count": record.get("fake_attachment_count"),
        "city_closeout_state": record.get("city_closeout_state"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _next_action_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "city_code": record.get("city_code"),
        "project_id": record.get("project_id"),
        "city_closeout_state": record.get("city_closeout_state"),
        "recommended_next_action": record.get("recommended_next_action"),
        "reason_taxonomy_counts": dict(record.get("failure_taxonomy_counts") or {}),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _build_summary(
    *,
    city_project_records: list[Mapping[str, Any]],
    full_summary: Mapping[str, Any],
    closeout_summary: Mapping[str, Any],
    missing_inputs: list[str],
    stage4_live_executed: bool,
) -> dict[str, Any]:
    state_counts = _counts(record.get("city_closeout_state") for record in city_project_records)
    strategy_deferred = Counter[str]()
    real_failures = Counter[str]()
    failure_counts = Counter[str]()
    for record in city_project_records:
        strategy_deferred.update(dict(record.get("strategy_deferred_counts") or {}))
        real_failures.update(dict(record.get("real_download_failure_taxonomy_counts") or {}))
        failure_counts.update(dict(record.get("failure_taxonomy_counts") or {}))
    return {
        "evidence_mini_closeout_state": "YGP_EVIDENCE_MINI_CLOSEOUT_READY" if not missing_inputs else "YGP_EVIDENCE_MINI_CLOSEOUT_INPUT_BLOCKED",
        "city_count": len(city_project_records),
        "city_with_recent_07_count": sum(1 for record in city_project_records if record.get("has_recent_07")),
        "city_no_recent_07_count": state_counts.get("YGP_CITY_NO_RECENT_07_REVIEW", 0),
        "city_source_or_download_blocked_count": state_counts.get("YGP_CITY_SOURCE_OR_DOWNLOAD_BLOCKED", 0),
        "city_attachment_policy_deferred_count": state_counts.get("YGP_CITY_ATTACHMENT_POLICY_DEFERRED", 0),
        "city_no_public_attachment_review_count": state_counts.get("YGP_CITY_NO_PUBLIC_ATTACHMENT_REVIEW", 0),
        "city_evidence_mini_ready_count": state_counts.get("YGP_CITY_EVIDENCE_MINI_READY", 0),
        "city_closeout_state_counts": state_counts,
        "listed_attachment_count": sum(_int(record.get("listed_attachment_count")) for record in city_project_records),
        "download_attempted_count": sum(_int(record.get("download_attempted_count")) for record in city_project_records),
        "attachment_snapshot_count": sum(_int(record.get("attachment_snapshot_count")) for record in city_project_records),
        "real_download_failure_count": sum(real_failures.values()),
        "real_download_failure_taxonomy_counts": dict(sorted(real_failures.items())),
        "strategy_deferred_counts": dict(sorted(strategy_deferred.items())),
        "failure_taxonomy_counts": dict(sorted(failure_counts.items())),
        "fake_attachment_count": sum(_int(record.get("fake_attachment_count")) for record in city_project_records),
        "flow_08_default_downloaded_count": sum(1 for record in city_project_records if record.get("flow_08_default_downloaded")),
        "stage4_live_executed": bool(stage4_live_executed),
        "source_full_chain_batch_closeout_state": full_summary.get("batch_closeout_state") or closeout_summary.get("batch_closeout_state"),
        "source_full_chain_attachment_snapshot_success_rate": full_summary.get("attachment_snapshot_success_rate"),
        "missing_inputs": missing_inputs,
        "forbidden_term_scan_state": "PENDING",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _recommended_next_action(state: str) -> str:
    return {
        "YGP_CITY_EVIDENCE_MINI_READY": "ENTER_YGP_EVIDENCE_PACKAGE_CHAIN",
        "YGP_CITY_NO_RECENT_07_REVIEW": "REVIEW_CITY_SEARCH_WINDOW_OR_KEEP_MONITORING",
        "YGP_CITY_ATTACHMENT_POLICY_DEFERRED": "RUN_YGP_OVERSIZE_POLICY_OR_LIMITED_ATTACHMENT_QUEUE",
        "YGP_CITY_NO_PUBLIC_ATTACHMENT_REVIEW": "MANUAL_REVIEW_07_PAGE_AND_KEEP_DETAIL_ONLY",
        "YGP_CITY_SOURCE_OR_DOWNLOAD_BLOCKED": "RUN_YGP_DOWNLOAD_REPAIR_V2",
        "YGP_CITY_REVIEW_REQUIRED": "MANUAL_REVIEW_TAXONOMY",
    }.get(state, "MANUAL_REVIEW_TAXONOMY")


def _flow08_default_downloaded_by_city(full_manifest: Mapping[str, Any]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for item in _list(full_manifest.get("items")):
        if not isinstance(item, Mapping) or str(item.get("flow_no") or "") != "08":
            continue
        city = str(item.get("city_code") or "")
        downloaded = _int(item.get("download_attempted_count")) > 0 or _int(item.get("attachment_snapshot_count")) > 0
        out[city] = out.get(city, False) or downloaded
    return out


def _stage4_live_executed(full_chain: Mapping[str, Any], batch_closeout: Mapping[str, Any]) -> bool:
    execution = full_chain.get("execution") if isinstance(full_chain.get("execution"), Mapping) else {}
    if bool(execution.get("stage4_live_provider_enabled")):
        return True
    full_summary = _summary(full_chain)
    closeout_summary = _summary(batch_closeout)
    return _int(full_summary.get("stage4_execution_item_count")) > 0 or _int(closeout_summary.get("stage4_execution_item_count")) > 0


def _project_records_by_key(flow_manifest: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    out: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in _list(flow_manifest.get("ygp_project_records")):
        if not isinstance(record, Mapping):
            continue
        route = record.get("resolved_project_route") if isinstance(record.get("resolved_project_route"), Mapping) else {}
        key = (str(route.get("siteCode") or ""), str(route.get("projectCode") or ""))
        if key[0] and key[1]:
            out[key] = record
    return out


def _flow_buckets_by_key(flow_manifest: Mapping[str, Any]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    out: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for bucket in _list(flow_manifest.get("ygp_flow_bucket_records")):
        if not isinstance(bucket, Mapping):
            continue
        key = (str(bucket.get("site_code") or ""), str(bucket.get("project_code") or ""))
        if key[0] and key[1]:
            out.setdefault(key, []).append(bucket)
    return out


def _city_search_blockers(discovery_manifest: Mapping[str, Any]) -> dict[str, Counter[str]]:
    out: dict[str, Counter[str]] = {}
    for record in _list(discovery_manifest.get("ygp_city_search_records")):
        if not isinstance(record, Mapping):
            continue
        city = str(record.get("city_code") or "")
        if not city:
            continue
        out.setdefault(city, Counter()).update(str(item) for item in _list(record.get("blocker_taxonomy")) if item)
    return out


def _fake_attachment_count(sample: Mapping[str, Any]) -> int:
    count = 0
    for item in _list(sample.get("attachment_link_items")):
        if not isinstance(item, Mapping):
            continue
        source_field = str(item.get("source_field") or "")
        if source_field != "richtext_link":
            continue
        url = str(item.get("download_url") or "").lower()
        file_name = str(item.get("file_name") or "").lower()
        file_like = (
            "/base/sys-file/download/" in url
            or any(file_name.endswith(ext) for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"))
        )
        shell_like = any(token in url for token in ("gdcic.net", "#/index", "/plain/page"))
        if shell_like or not file_like:
            count += 1
    return count


def _city_codes(
    requested: list[str] | tuple[str, ...] | None,
    full_manifest: Mapping[str, Any],
    discovery_manifest: Mapping[str, Any],
) -> list[str]:
    values = list(requested or [])
    if not values:
        values = [str(item) for item in _list(full_manifest.get("city_codes")) if str(item).strip()]
    if not values:
        values = [str(item) for item in _list(discovery_manifest.get("city_codes")) if str(item).strip()]
    if not values:
        values = list(DEFAULT_CITY_CODES)
    return _dedupe(values)


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    city_project_records: list[Mapping[str, Any]],
    download_stability_records: list[Mapping[str, Any]],
    next_action_records: list[Mapping[str, Any]],
) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*list(result.get("blocking_reasons") or []), *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    _write_json(out_dir / "ygp-city-project-table.json", {"summary": result["summary"], "records": city_project_records})
    _write_json(out_dir / "ygp-download-stability-table.json", {"summary": result["summary"], "records": download_stability_records})
    _write_json(out_dir / "ygp-next-action-table.json", {"summary": result["summary"], "records": next_action_records})
    _write_json(out_dir / "ygp-evidence-mini-closeout-v1.json", result)


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


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = payload.get("summary") if isinstance(payload, Mapping) else {}
    if isinstance(summary, Mapping):
        return summary
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping) and isinstance(manifest.get("summary"), Mapping):
        return manifest["summary"]  # type: ignore[return-value]
    return {}


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


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counter = Counter(str(value) for value in values if str(value or "").strip())
    return dict(sorted(counter.items()))


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangdong YGP evidence mini closeout v1.")
    parser.add_argument("--city-discovery-root", default=str(DEFAULT_CITY_DISCOVERY_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--city-code", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_guangdong_ygp_evidence_mini_closeout(
        city_discovery_root=args.city_discovery_root,
        download_root=args.download_root,
        output_root=args.output_root,
        city_codes=args.city_code or None,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            "guangdong ygp evidence mini closeout built: "
            f"state={summary.get('evidence_mini_closeout_state')} "
            f"cities={summary.get('city_count')} "
            f"with_07={summary.get('city_with_recent_07_count')} "
            f"real_failures={summary.get('real_download_failure_count')}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
