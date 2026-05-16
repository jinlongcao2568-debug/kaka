from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGDONG_YGP_OVERSIZE_POLICY_KIND = "guangdong_ygp_oversize_policy_v1_manifest"
GUANGDONG_YGP_OVERSIZE_POLICY_VERSION = 1
GUANGDONG_YGP_OVERSIZE_POLICY_ADAPTER_ID = "guangdong-ygp-oversize-policy-v1-builder"

DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/ygp-morecity-smoke-v1-07-download")
DEFAULT_MINI_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/ygp-evidence-mini-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/ygp-oversize-policy-v1")

OVERSIZE_TAXONOMY = "OVERSIZE_DEFERRED_BY_POLICY"
LIMIT_DEFERRED_TAXONOMY = "DEFERRED_BY_YGP_DOWNLOAD_LIMIT"
FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
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


def build_guangdong_ygp_oversize_policy(
    *,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    mini_closeout_root: str | Path = DEFAULT_MINI_CLOSEOUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    download_dir = Path(download_root)
    mini_dir = Path(mini_closeout_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    full_chain = _load_json(download_dir / "ygp-full-chain-manifest.json", missing_inputs, "ygp_full_chain_manifest_missing")
    batch_closeout = _load_json(download_dir / "guangdong-ygp-batch-stability-closeout-v1.json", missing_inputs, "ygp_batch_closeout_missing")
    mini_closeout = _load_json(mini_dir / "ygp-evidence-mini-closeout-v1.json", missing_inputs, "ygp_evidence_mini_closeout_missing")
    city_project_table = _load_json(mini_dir / "ygp-city-project-table.json", missing_inputs, "ygp_city_project_table_missing")

    full_manifest = _source_manifest(full_chain)
    full_summary = _summary(full_chain)
    batch_summary = _summary(batch_closeout)
    mini_summary = _summary(mini_closeout)

    samples_by_project = {
        str(sample.get("project_id") or ""): dict(sample)
        for sample in _list(full_manifest.get("project_sample_items"))
        if isinstance(sample, Mapping)
    }
    items_by_project_flow = {
        (str(item.get("project_id") or ""), str(item.get("flow_no") or "")): dict(item)
        for item in _list(full_manifest.get("items"))
        if isinstance(item, Mapping)
    }
    attempts_by_url: dict[str, dict[str, Any]] = {}
    attempts_by_project: dict[str, list[dict[str, Any]]] = {}
    for attempt in _download_attempt_records(download_dir):
        url = str(attempt.get("download_url") or attempt.get("attachment_url") or "")
        if url:
            attempts_by_url[url] = attempt
        project_id = str(attempt.get("project_id") or "")
        if project_id:
            attempts_by_project.setdefault(project_id, []).append(attempt)

    queue_records: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for attempt in attempts_by_url.values():
        if _has_taxonomy(attempt, OVERSIZE_TAXONOMY):
            _append_record(
                queue_records,
                seen_keys,
                _record_from_attempt(attempt=attempt, samples_by_project=samples_by_project, defer_reason=OVERSIZE_TAXONOMY),
            )

    for (project_id, flow_no), item in items_by_project_flow.items():
        if not _has_taxonomy(item, LIMIT_DEFERRED_TAXONOMY):
            continue
        sample = samples_by_project.get(project_id, {})
        for attachment in _list(sample.get("attachment_link_items")):
            if not isinstance(attachment, Mapping):
                continue
            url = str(attachment.get("download_url") or "")
            existing_snapshot = _snapshot_for_url(sample, url)
            attempt = attempts_by_url.get(url)
            if attempt and _has_taxonomy(attempt, OVERSIZE_TAXONOMY):
                continue
            if attempt and not existing_snapshot:
                continue
            record = _record_from_attachment(
                attachment=attachment,
                sample=sample,
                item=item,
                defer_reason=LIMIT_DEFERRED_TAXONOMY,
                existing_snapshot_id=str(existing_snapshot.get("snapshot_id") or "") if existing_snapshot else "",
            )
            _append_record(queue_records, seen_keys, record)

    for sample in samples_by_project.values():
        if str(sample.get("guangdong_ygp_flow_no") or "") == "08":
            for attachment in _list(sample.get("attachment_link_items")):
                if isinstance(attachment, Mapping):
                    _append_record(
                        queue_records,
                        seen_keys,
                        _record_from_attachment(
                            attachment=attachment,
                            sample=sample,
                            item={},
                            defer_reason="FLOW_08_REGISTER_ONLY",
                            existing_snapshot_id="",
                            forced_policy_state="NOT_DOWNLOAD_REQUIRED",
                        ),
                    )

    summary = _build_summary(
        queue_records=queue_records,
        full_summary=full_summary,
        batch_summary=batch_summary,
        mini_summary=mini_summary,
        missing_inputs=missing_inputs,
    )
    manifest = {
        "manifest_version": GUANGDONG_YGP_OVERSIZE_POLICY_VERSION,
        "manifest_kind": GUANGDONG_YGP_OVERSIZE_POLICY_KIND,
        "adapter_id": GUANGDONG_YGP_OVERSIZE_POLICY_ADAPTER_ID,
        "pipeline_stage": "GuangdongYgpOversizePolicyV1",
        "manifest_id": f"GUANGDONG-YGP-OVERSIZE-POLICY-{_fingerprint({'summary': summary, 'queue': queue_records})[:16]}",
        "created_at": created,
        "source_download_root": str(download_dir),
        "source_mini_closeout_root": str(mini_dir),
        "source_full_chain_manifest_path": str(download_dir / "ygp-full-chain-manifest.json"),
        "source_batch_closeout_path": str(download_dir / "guangdong-ygp-batch-stability-closeout-v1.json"),
        "source_mini_closeout_path": str(mini_dir / "ygp-evidence-mini-closeout-v1.json"),
        "source_city_project_table_path": str(mini_dir / "ygp-city-project-table.json"),
        "city_project_table_loaded": bool(city_project_table),
        "summary": summary,
        "oversize_attachment_queue": queue_records,
        "oversize_next_action_records": [_next_action_record(record) for record in queue_records],
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "flow_08_register_only_unchanged": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangdong_ygp_oversize_policy_mode": "BUILT" if not missing_inputs else "INPUT_BLOCKED",
        "safe_to_execute": not missing_inputs,
        "blocking_reasons": missing_inputs,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, queue_records)
    return result


def _record_from_attempt(
    *,
    attempt: Mapping[str, Any],
    samples_by_project: Mapping[str, Mapping[str, Any]],
    defer_reason: str,
) -> dict[str, Any]:
    project_id = str(attempt.get("project_id") or "")
    sample = dict(samples_by_project.get(project_id) or {})
    attachment_url = str(attempt.get("attachment_url") or attempt.get("download_url") or "")
    existing_snapshot = _snapshot_for_url(sample, attachment_url)
    file_size = _file_size_bytes(attempt)
    size_source = _size_source(attempt)
    state = _policy_state(
        flow_no=str(attempt.get("flow_no") or sample.get("guangdong_ygp_flow_no") or ""),
        defer_reason=defer_reason,
        file_size_bytes=file_size,
        existing_snapshot_id=str(existing_snapshot.get("snapshot_id") or ""),
    )
    return _queue_record(
        city_code=str(attempt.get("city_code") or sample.get("city_code") or ""),
        project_id=project_id,
        project_name=str(sample.get("project_name") or attempt.get("project_name") or ""),
        flow_no=str(attempt.get("flow_no") or sample.get("guangdong_ygp_flow_no") or ""),
        flow_title=str(sample.get("guangdong_ygp_flow_title") or attempt.get("flow_title") or ""),
        source_url=str(sample.get("source_url") or ""),
        attachment_name=str(attempt.get("attachment_name") or attempt.get("attachment_link_text") or ""),
        attachment_url=attachment_url,
        file_size_bytes=file_size,
        size_source=size_source,
        defer_reason=defer_reason,
        existing_snapshot_id=str(existing_snapshot.get("snapshot_id") or ""),
        policy_state=state,
    )


def _record_from_attachment(
    *,
    attachment: Mapping[str, Any],
    sample: Mapping[str, Any],
    item: Mapping[str, Any],
    defer_reason: str,
    existing_snapshot_id: str,
    forced_policy_state: str | None = None,
) -> dict[str, Any]:
    file_size = _file_size_bytes(attachment)
    state = forced_policy_state or _policy_state(
        flow_no=str(attachment.get("flow_no") or sample.get("guangdong_ygp_flow_no") or ""),
        defer_reason=defer_reason,
        file_size_bytes=file_size,
        existing_snapshot_id=existing_snapshot_id,
    )
    return _queue_record(
        city_code=str(attachment.get("city_code") or sample.get("city_code") or ""),
        project_id=str(sample.get("project_id") or attachment.get("project_id") or ""),
        project_name=str(sample.get("project_name") or ""),
        flow_no=str(attachment.get("flow_no") or sample.get("guangdong_ygp_flow_no") or item.get("flow_no") or ""),
        flow_title=str(attachment.get("flow_title") or sample.get("guangdong_ygp_flow_title") or item.get("flow_title") or ""),
        source_url=str(sample.get("source_url") or attachment.get("detail_url") or ""),
        attachment_name=str(attachment.get("file_name") or attachment.get("link_text") or ""),
        attachment_url=str(attachment.get("download_url") or ""),
        file_size_bytes=file_size,
        size_source=_size_source(attachment),
        defer_reason=defer_reason,
        existing_snapshot_id=existing_snapshot_id,
        policy_state=state,
    )


def _queue_record(
    *,
    city_code: str,
    project_id: str,
    project_name: str,
    flow_no: str,
    flow_title: str,
    source_url: str,
    attachment_name: str,
    attachment_url: str,
    file_size_bytes: int | None,
    size_source: str,
    defer_reason: str,
    existing_snapshot_id: str,
    policy_state: str,
) -> dict[str, Any]:
    recommended_action = _recommended_action(policy_state)
    return {
        "queue_item_id": _stable_id("YGP-OVERSIZE-QUEUE", project_id, flow_no, attachment_url, defer_reason),
        "city_code": city_code,
        "project_id": project_id,
        "project_name": project_name,
        "flow_no": flow_no,
        "flow_title": flow_title,
        "source_url": source_url,
        "attachment_name": attachment_name,
        "attachment_url": attachment_url,
        "file_size_bytes": file_size_bytes,
        "size_source": size_source,
        "defer_reason": defer_reason,
        "existing_snapshot_id": existing_snapshot_id,
        "policy_state": policy_state,
        "recommended_action": recommended_action,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _policy_state(*, flow_no: str, defer_reason: str, file_size_bytes: int | None, existing_snapshot_id: str) -> str:
    if _flow_no(flow_no) == "08":
        return "NOT_DOWNLOAD_REQUIRED"
    if existing_snapshot_id:
        return "ALREADY_CAPTURED_NO_ACTION"
    if file_size_bytes is None and defer_reason in {OVERSIZE_TAXONOMY, LIMIT_DEFERRED_TAXONOMY}:
        return "SIZE_UNKNOWN_REVIEW" if defer_reason == OVERSIZE_TAXONOMY else "LIMIT_DEFERRED_QUEUE_READY"
    if defer_reason == OVERSIZE_TAXONOMY:
        return "OVERSIZE_QUEUE_READY"
    if defer_reason == LIMIT_DEFERRED_TAXONOMY:
        return "LIMIT_DEFERRED_QUEUE_READY"
    return "NOT_DOWNLOAD_REQUIRED"


def _recommended_action(policy_state: str) -> str:
    return {
        "OVERSIZE_QUEUE_READY": "MANUAL_DOWNLOAD_APPROVAL_REQUIRED",
        "LIMIT_DEFERRED_QUEUE_READY": "SCHEDULE_LIMITED_ATTACHMENT_BACKFILL",
        "SIZE_UNKNOWN_REVIEW": "REVIEW_SIZE_BEFORE_DOWNLOAD_DECISION",
        "ALREADY_CAPTURED_NO_ACTION": "NO_ACTION_EXISTING_SNAPSHOT_READY",
        "NOT_DOWNLOAD_REQUIRED": "KEEP_REGISTER_ONLY_OR_OUT_OF_SCOPE",
    }.get(policy_state, "REVIEW_POLICY_STATE")


def _download_attempt_records(download_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in download_dir.glob("projects/CN-GD/*/*/*/*/download-probe.json"):
        payload = _load_json(path, [], "download_probe_missing")
        sample = payload.get("project_sample") if isinstance(payload.get("project_sample"), Mapping) else {}
        for attempt in _list(payload.get("download_attempts")):
            if not isinstance(attempt, Mapping):
                continue
            row = dict(attempt)
            row.setdefault("project_id", sample.get("project_id"))
            row.setdefault("city_code", sample.get("city_code"))
            row.setdefault("flow_no", sample.get("guangdong_ygp_flow_no"))
            row.setdefault("flow_title", sample.get("guangdong_ygp_flow_title"))
            row.setdefault("project_name", sample.get("project_name"))
            records.append(row)
    return records


def _build_summary(
    *,
    queue_records: list[Mapping[str, Any]],
    full_summary: Mapping[str, Any],
    batch_summary: Mapping[str, Any],
    mini_summary: Mapping[str, Any],
    missing_inputs: list[str],
) -> dict[str, Any]:
    actionable_states = {"OVERSIZE_QUEUE_READY", "LIMIT_DEFERRED_QUEUE_READY", "SIZE_UNKNOWN_REVIEW"}
    state_counts = _counts(record.get("policy_state") for record in queue_records)
    largest = sorted(
        [dict(record) for record in queue_records if _int_or_none(record.get("file_size_bytes")) is not None],
        key=lambda record: _int_or_none(record.get("file_size_bytes")) or 0,
        reverse=True,
    )[:10]
    real_failure_count = _real_download_failure_count(full_summary=full_summary, batch_summary=batch_summary, mini_summary=mini_summary)
    fake_attachment_count = _int(full_summary.get("fake_attachment_count") or mini_summary.get("fake_attachment_count"))
    return {
        "oversize_policy_state": "YGP_OVERSIZE_POLICY_READY" if not missing_inputs else "YGP_OVERSIZE_POLICY_INPUT_BLOCKED",
        "queue_record_count": len(queue_records),
        "queued_attachment_count": sum(1 for record in queue_records if record.get("policy_state") in actionable_states),
        "oversize_queue_count": state_counts.get("OVERSIZE_QUEUE_READY", 0),
        "limit_deferred_queue_count": state_counts.get("LIMIT_DEFERRED_QUEUE_READY", 0),
        "size_unknown_count": state_counts.get("SIZE_UNKNOWN_REVIEW", 0),
        "already_captured_count": state_counts.get("ALREADY_CAPTURED_NO_ACTION", 0),
        "not_download_required_count": state_counts.get("NOT_DOWNLOAD_REQUIRED", 0),
        "manual_approval_required_count": sum(1 for record in queue_records if record.get("recommended_action") == "MANUAL_DOWNLOAD_APPROVAL_REQUIRED"),
        "by_city_counts": _counts(record.get("city_code") for record in queue_records if record.get("policy_state") in actionable_states),
        "by_flow_counts": _counts(record.get("flow_no") for record in queue_records if record.get("policy_state") in actionable_states),
        "policy_state_counts": state_counts,
        "largest_attachments_top10": [
            {
                "city_code": record.get("city_code"),
                "project_id": record.get("project_id"),
                "project_name": record.get("project_name"),
                "flow_no": record.get("flow_no"),
                "attachment_name": record.get("attachment_name"),
                "attachment_url": record.get("attachment_url"),
                "file_size_bytes": record.get("file_size_bytes"),
                "policy_state": record.get("policy_state"),
                "recommended_action": record.get("recommended_action"),
            }
            for record in largest
        ],
        "real_download_failure_count": real_failure_count,
        "fake_attachment_count": fake_attachment_count,
        "missing_inputs": missing_inputs,
        "forbidden_term_scan_state": "PENDING",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _real_download_failure_count(*, full_summary: Mapping[str, Any], batch_summary: Mapping[str, Any], mini_summary: Mapping[str, Any]) -> int:
    if "real_download_failure_count" in mini_summary:
        return _int(mini_summary.get("real_download_failure_count"))
    if "download_required_failed_attempt_count" in batch_summary:
        return _int(batch_summary.get("download_required_failed_attempt_count"))
    failure_counts = dict(full_summary.get("failure_taxonomy_counts") or {})
    return sum(_int(value) for key, value in failure_counts.items() if key in REAL_DOWNLOAD_FAILURE_TAXONOMIES)


def _next_action_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "queue_item_id": record.get("queue_item_id"),
        "city_code": record.get("city_code"),
        "project_id": record.get("project_id"),
        "flow_no": record.get("flow_no"),
        "attachment_name": record.get("attachment_name"),
        "policy_state": record.get("policy_state"),
        "recommended_action": record.get("recommended_action"),
        "defer_reason": record.get("defer_reason"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _has_taxonomy(record: Mapping[str, Any], taxonomy: str) -> bool:
    values = set(str(item) for item in _list(record.get("failure_taxonomy")))
    values.add(str(record.get("policy_deferred_reason") or ""))
    return taxonomy in values


def _snapshot_for_url(sample: Mapping[str, Any], url: str) -> Mapping[str, Any]:
    if not url:
        return {}
    for ref in _list(sample.get("attachment_snapshot_refs")):
        if not isinstance(ref, Mapping):
            continue
        if url in {str(ref.get("attachment_url") or ""), str(ref.get("source_url") or "")}:
            return ref
    return {}


def _file_size_bytes(record: Mapping[str, Any]) -> int | None:
    for value in (
        record.get("file_size_bytes"),
        record.get("file_size"),
        (record.get("download_diagnostics") or {}).get("file_size", {}).get("file_size_bytes")
        if isinstance(record.get("download_diagnostics"), Mapping)
        else None,
        record.get("head_content_length"),
    ):
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _size_source(record: Mapping[str, Any]) -> str:
    diagnostics = record.get("download_diagnostics") if isinstance(record.get("download_diagnostics"), Mapping) else {}
    file_size = diagnostics.get("file_size") if isinstance(diagnostics.get("file_size"), Mapping) else {}
    state = str(file_size.get("file_size_state") or record.get("file_size_state") or "")
    if state == "FILE_SIZE_READY" or record.get("file_size_url") or file_size.get("file_size_url"):
        return "file_size_url"
    if state == "HEAD_CONTENT_LENGTH_READY" or record.get("head_content_length") or file_size.get("head_content_length"):
        return "head_content_length"
    return "unknown"


def _append_record(records: list[dict[str, Any]], seen_keys: set[str], record: dict[str, Any]) -> None:
    key = "|".join(
        [
            str(record.get("project_id") or ""),
            str(record.get("flow_no") or ""),
            str(record.get("attachment_url") or ""),
            str(record.get("defer_reason") or ""),
        ]
    )
    if key in seen_keys:
        return
    seen_keys.add(key)
    records.append(record)


def _finalize_and_write(out_dir: Path, result: dict[str, Any], queue_records: list[Mapping[str, Any]]) -> None:
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
    _write_json(out_dir / "ygp-oversize-attachment-queue.json", {"summary": result["summary"], "records": queue_records})
    _write_json(out_dir / "ygp-oversize-next-action-table.json", {"summary": result["summary"], "records": result["manifest"]["oversize_next_action_records"]})
    _write_json(out_dir / "ygp-oversize-policy-v1.json", result)


def _load_json(path: Path, missing: list[str], reason: str) -> dict[str, Any]:
    if not path.exists():
        missing.append(reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        missing.append(f"{reason}:invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counter = Counter(str(value) for value in values if str(value or "").strip())
    return dict(sorted(counter.items()))


def _int(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return int(value)
        return int(float(str(value).strip()))
    except Exception:
        return None


def _flow_no(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.zfill(2)[-2:] if digits else ""


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint({'parts': [str(part or '') for part in parts]})[:16]}"


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangdong YGP oversize policy queue v1.")
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--mini-closeout-root", default=str(DEFAULT_MINI_CLOSEOUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_guangdong_ygp_oversize_policy(
        download_root=args.download_root,
        mini_closeout_root=args.mini_closeout_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            "guangdong ygp oversize policy built: "
            f"state={summary.get('oversize_policy_state')} "
            f"queued={summary.get('queued_attachment_count')} "
            f"oversize={summary.get('oversize_queue_count')} "
            f"limit_deferred={summary.get('limit_deferred_queue_count')}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
