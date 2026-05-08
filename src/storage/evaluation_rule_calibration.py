from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage3_parsing.tailored_bid_signals import (
    DEFAULT_SEED_PATH as DEFAULT_TAILORED_SIGNAL_SEED_PATH,
    build_tailored_bid_signal_profile,
    load_tailored_bid_signal_seed,
)
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


EVALUATION_RULE_CALIBRATION_MANIFEST_OBJECT_TYPE = "evaluation_rule_calibration_manifest"
EVALUATION_RULE_CALIBRATION_MANIFEST_VERSION = 1
EVALUATION_RULE_CALIBRATION_RULESET_ID = "evaluation-rule-calibration-file-tailored-v1"
EVALUATION_RULE_CALIBRATION_ADAPTER_ID = "evaluation-rule-calibration-builder"
FILE_REVIEW_RULE_CODE = "FILE-REVIEW-001"
TAILORED_REVIEW_RULE_CODE = "TAILORED-REVIEW-001"

FILE_REVIEW_DOCUMENT_STATES = {
    "DETAIL_SNAPSHOT_MISSING_REVIEW",
    "ATTACHMENTS_NOT_CAPTURED_REVIEW",
    "PARTIAL_REVIEW_REQUIRED",
}
FILE_VERSION_REVIEW_STATES = {"VERSION_REVIEW_REQUIRED", "CLARIFICATION_OR_ADDENDUM_PRESENT"}
OCR_REVIEW_STATES = {"OCR_REQUIRED", "OCR_ENGINE_UNAVAILABLE"}


def build_evaluation_rule_calibration_manifest(
    *,
    real_sample_execution_manifest_json: str | Path,
    tailored_signal_seed_json: str | Path | None = None,
    database_url: str | None = None,
    target_backend: str = "postgresql",
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    execution_path = Path(real_sample_execution_manifest_json)
    blocking_reasons: list[str] = []
    source_payload: dict[str, Any] = {}
    if not execution_path.exists():
        blocking_reasons.append("real_sample_execution_manifest_missing")
    else:
        try:
            source_payload = json.loads(execution_path.read_text(encoding="utf-8"))
        except Exception as exc:
            blocking_reasons.append(f"real_sample_execution_manifest_load_failed:{exc}")
    source_manifest = _source_manifest(source_payload)
    tailored_seed_path = Path(tailored_signal_seed_json or DEFAULT_TAILORED_SIGNAL_SEED_PATH)
    tailored_seed_load_ok = True
    try:
        load_tailored_bid_signal_seed(tailored_seed_path)
    except Exception as exc:
        tailored_seed_load_ok = False
        blocking_reasons.append(f"tailored_signal_seed_load_failed:{exc}")
    items = [
        _calibrate_file_review_item(item)
        for item in list(source_manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]
    tailored_items = (
        [
            _calibrate_tailored_review_item(item, seed_path=tailored_seed_path)
            for item in list(source_manifest.get("items") or [])
            if isinstance(item, Mapping)
        ]
        if tailored_seed_load_ok
        else []
    )
    manifest = _build_manifest(
        items=items,
        tailored_items=tailored_items,
        source_manifest=source_manifest,
        execution_path=execution_path,
        tailored_seed_path=tailored_seed_path,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created,
    )
    result = {
        "rule_calibration_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": manifest["summary"],
        "execution": {
            "executed": False,
            "target_mutation_enabled": False,
            "database_write_enabled": False,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
        },
    }
    if execute:
        if blocking_reasons:
            raise RuntimeError(
                "evaluation rule calibration is not safe to execute: " + ", ".join(blocking_reasons)
            )
        settings = Settings(
            storage_backend=target_backend,
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
        )
        session = DatabaseSession(settings=settings)
        try:
            with session.bulk_write():
                session.upsert_record(_calibration_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                **result["execution"],
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_evaluation_rule_calibration_manifest_count": 1,
            }
        finally:
            session.close()
    return result


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _calibrate_file_review_item(item: Mapping[str, Any]) -> dict[str, Any]:
    parse_summary = dict(item.get("parse_summary") or {})
    document_counts = _mapping_counts(parse_summary.get("document_completeness_state_counts"))
    version_counts = _mapping_counts(parse_summary.get("notice_version_chain_state_counts"))
    document_quality_reasons = _string_list(parse_summary.get("document_quality_reasons"))
    download_quality_reasons = _string_list(parse_summary.get("download_archive_quality_reasons"))
    target_execution_state = str(item.get("target_execution_state") or "")
    detail_refs = [dict(ref) for ref in list(item.get("detail_snapshot_refs") or []) if isinstance(ref, Mapping)]
    attachment_refs = [
        dict(ref) for ref in list(item.get("attachment_snapshot_refs") or []) if isinstance(ref, Mapping)
    ]
    detail_document_states = [
        str(ref.get("document_completeness_state") or "")
        for ref in detail_refs
        if str(ref.get("document_completeness_state") or "")
    ]
    detail_version_states = [
        str(ref.get("notice_version_chain_state") or "")
        for ref in detail_refs
        if str(ref.get("notice_version_chain_state") or "")
    ]
    all_document_states = set(document_counts) | set(detail_document_states)
    all_version_states = set(version_counts) | set(detail_version_states)
    ocr_count = _int_value(parse_summary.get("ocr_required_count"), default=0) + _int_value(
        parse_summary.get("attachment_ocr_required_count"),
        default=0,
    )
    attachment_missing_count = _int_value(parse_summary.get("attachment_missing_review_count"), default=0)
    version_review_count = _int_value(parse_summary.get("clarification_version_review_count"), default=0)
    unknown_attachment_count = _int_value(parse_summary.get("unknown_attachment_count"), default=0)
    reasons: list[str] = []

    if target_execution_state in {"DISCOVERY_FAILED_CLOSED", "DISCOVERY_NO_MATCH_REVIEW", "CAPTURE_PARTIAL_REVIEW"}:
        reasons.append(f"target_execution_state={target_execution_state}")
    if all_document_states.intersection(FILE_REVIEW_DOCUMENT_STATES):
        reasons.extend(f"document_completeness_state={state}" for state in sorted(all_document_states.intersection(FILE_REVIEW_DOCUMENT_STATES)))
    if all_version_states.intersection(FILE_VERSION_REVIEW_STATES):
        reasons.extend(f"notice_version_chain_state={state}" for state in sorted(all_version_states.intersection(FILE_VERSION_REVIEW_STATES)))
    if version_review_count:
        reasons.append("clarification_or_addendum_version_review_required")
    if attachment_missing_count:
        reasons.append("attachment_missing_or_partial_review_required")
    if ocr_count:
        reasons.append("ocr_required_or_engine_unavailable")
    if unknown_attachment_count:
        reasons.append("unknown_attachment_format_or_role")
    for reason in document_quality_reasons + download_quality_reasons:
        if reason in {
            "unknown_attachment_format",
            "unknown_attachment_role",
            "attachment_capture_failed",
            "detail_capture_failed",
            "ocr_required",
            "ocr_engine_unavailable",
        }:
            reasons.append(reason)
    expected_state = "REVIEW_REQUIRED" if _dedupe_strings(reasons) else "PASS"
    if (
        not reasons
        and "DETAIL_ONLY_NO_ATTACHMENTS" in all_document_states
        and not _target_requires_attachment(item)
    ):
        expected_state = "PASS"
    if (
        not reasons
        and "COMPLETE_WITH_ATTACHMENTS" in all_document_states
        and not document_quality_reasons
        and not download_quality_reasons
    ):
        expected_state = "PASS"
    return {
        "target_id": str(item.get("target_id") or ""),
        "document_kind": str(item.get("document_kind") or ""),
        "jurisdiction": str(item.get("jurisdiction") or ""),
        "source_profile_id": str(item.get("source_profile_id") or ""),
        "target_execution_state": target_execution_state,
        "detail_snapshot_count": len(detail_refs),
        "attachment_snapshot_count": len(attachment_refs),
        "document_completeness_state_counts": document_counts,
        "notice_version_chain_state_counts": version_counts,
        "ocr_required_count": ocr_count,
        "attachment_missing_review_count": attachment_missing_count,
        "clarification_version_review_count": version_review_count,
        "unknown_attachment_count": unknown_attachment_count,
        "file_review_rule_code": FILE_REVIEW_RULE_CODE,
        "expected_file_review_state": expected_state,
        "expected_file_review_reasons": _dedupe_strings(reasons),
        "calibration_scope": "FILE_OCR_ONLY",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _calibrate_tailored_review_item(item: Mapping[str, Any], *, seed_path: Path) -> dict[str, Any]:
    profile_inputs = _tailored_profile_inputs(item)
    profile = build_tailored_bid_signal_profile(
        profile_inputs,
        text=_tailored_calibration_text(profile_inputs),
        seed_path=seed_path,
    )
    expected_state = (
        "REVIEW_REQUIRED"
        if profile.get("tailored_bid_stage5_review_required")
        or profile.get("evidence_state") == "INSUFFICIENT_EVIDENCE"
        else "PASS"
    )
    return {
        "target_id": str(item.get("target_id") or ""),
        "document_kind": str(item.get("document_kind") or ""),
        "jurisdiction": str(item.get("jurisdiction") or ""),
        "source_profile_id": str(item.get("source_profile_id") or ""),
        "target_execution_state": str(item.get("target_execution_state") or ""),
        "tailored_review_rule_code": TAILORED_REVIEW_RULE_CODE,
        "tailored_signal_seed_id": profile.get("seed_id"),
        "tailored_bid_index": profile.get("tailored_bid_index"),
        "tailored_bid_risk_level": profile.get("tailored_bid_risk_level"),
        "tailored_bid_sub_indices": profile.get("tailored_bid_sub_indices") or {},
        "tailored_bid_signal_count": profile.get("tailored_bid_signal_count"),
        "tailored_bid_counter_reason_count": profile.get("counter_reason_count"),
        "tailored_bid_ai_review_required": bool(profile.get("tailored_bid_ai_review_required")),
        "tailored_bid_stage5_review_required": bool(
            profile.get("tailored_bid_stage5_review_required")
        ),
        "tailored_bid_evidence_state": profile.get("evidence_state"),
        "tailored_bid_ai_review_reasons": profile.get("ai_review_reasons") or [],
        "tailored_bid_signal_families": profile.get("tailored_bid_signal_families") or {},
        "source_class_counts": profile.get("source_class_counts") or {},
        "expected_tailored_review_state": expected_state,
        "expected_tailored_review_reasons": _dedupe_strings(
            [
                f"tailored_bid_index={profile.get('tailored_bid_index')}",
                f"tailored_bid_risk_level={profile.get('tailored_bid_risk_level')}",
            ]
            + list(profile.get("ai_review_reasons") or [])
            + list(profile.get("evidence_reasons") or [])
        ),
        "calibration_scope": "TAILORED_BID_SIGNAL_INDEX_ONLY",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _tailored_calibration_text(item: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "source_text",
        "detail_text",
        "document_text",
        "parsed_text",
        "attachment_text",
        "source_title",
        "project_name",
        "notice_title",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    parse_summary = item.get("parse_summary")
    if isinstance(parse_summary, Mapping):
        for key in (
            "text_probe",
            "sample_text",
            "extracted_text",
            "ocr_text",
            "source_text",
            "detail_text",
        ):
            value = parse_summary.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        for key in (
            "document_quality_reasons",
            "download_archive_quality_reasons",
            "target_execution_reasons",
        ):
            parts.extend(_string_list(parse_summary.get(key)))
    return "\n".join(dict.fromkeys(parts))


def _tailored_profile_inputs(item: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(item)
    parse_summary = item.get("parse_summary")
    if not isinstance(parse_summary, Mapping):
        return result
    document_counts = _mapping_counts(parse_summary.get("document_completeness_state_counts"))
    version_counts = _mapping_counts(parse_summary.get("notice_version_chain_state_counts"))
    if not result.get("document_completeness_state") and document_counts:
        result["document_completeness_state"] = next(iter(document_counts))
    if not result.get("notice_version_chain_state") and version_counts:
        result["notice_version_chain_state"] = next(iter(version_counts))
    result["attachment_ocr_required_count"] = _int_value(
        result.get("attachment_ocr_required_count"),
        default=_int_value(parse_summary.get("attachment_ocr_required_count"), default=0)
        + _int_value(parse_summary.get("ocr_required_count"), default=0),
    )
    result["attachment_missing_review_count"] = _int_value(
        result.get("attachment_missing_review_count"),
        default=_int_value(parse_summary.get("attachment_missing_review_count"), default=0),
    )
    return result


def _target_requires_attachment(item: Mapping[str, Any]) -> bool:
    value = item.get("attachment_required")
    if value is None:
        value = item.get("requires_attachment")
    return bool(value)


def _build_manifest(
    *,
    items: list[dict[str, Any]],
    tailored_items: list[dict[str, Any]],
    source_manifest: Mapping[str, Any],
    execution_path: Path,
    tailored_seed_path: Path,
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    summary = _summary(items, tailored_items)
    fingerprint = _fingerprint(
        {
            "source_manifest_id": source_manifest.get("manifest_id"),
            "source_manifest_sha256": source_manifest.get("manifest_sha256"),
            "items": items,
            "tailored_items": tailored_items,
            "tailored_seed_path": str(tailored_seed_path),
        }
    )
    manifest = {
        "manifest_version": EVALUATION_RULE_CALIBRATION_MANIFEST_VERSION,
        "manifest_kind": EVALUATION_RULE_CALIBRATION_MANIFEST_OBJECT_TYPE,
        "ruleset_id": EVALUATION_RULE_CALIBRATION_RULESET_ID,
        "adapter_id": EVALUATION_RULE_CALIBRATION_ADAPTER_ID,
        "manifest_id": f"EVALUATION-RULE-CALIBRATION-{fingerprint[:16]}",
        "created_at": created_at,
        "source_real_sample_execution_manifest_id": str(source_manifest.get("manifest_id") or ""),
        "source_real_sample_execution_manifest_path": str(execution_path),
        "tailored_signal_seed_path": str(tailored_seed_path),
        "database_url_redacted": _redact_database_url(database_url),
        "target_storage_backend": target_backend,
        "calibrated_rule_codes": [FILE_REVIEW_RULE_CODE, TAILORED_REVIEW_RULE_CODE],
        "non_calibrated_rule_codes": [
            "FATAL-REVIEW-001",
            "PRICE-REVIEW-001",
            "REMEDY-REVIEW-001",
        ],
        "items": items,
        "sample_items": items[:80],
        "tailored_items": tailored_items,
        "tailored_sample_items": tailored_items[:80],
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "formal_rule_threshold_mutation_enabled": False,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return manifest


def _summary(
    items: list[Mapping[str, Any]],
    tailored_items: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    tailored_items = list(tailored_items or [])
    review_count = sum(1 for item in items if item.get("expected_file_review_state") == "REVIEW_REQUIRED")
    pass_count = sum(1 for item in items if item.get("expected_file_review_state") == "PASS")
    tailored_review_count = sum(
        1 for item in tailored_items if item.get("expected_tailored_review_state") == "REVIEW_REQUIRED"
    )
    tailored_pass_count = sum(
        1 for item in tailored_items if item.get("expected_tailored_review_state") == "PASS"
    )
    tailored_sample_state = "SAMPLE_READY" if len(tailored_items) >= 50 else "INSUFFICIENT_SAMPLE"
    return {
        "target_count": len(items),
        "target_bucket_coverage": _counts(str(item.get("document_kind") or "") for item in items),
        "site_coverage": _counts(str(item.get("source_profile_id") or "") for item in items),
        "target_execution_state_counts": _counts(str(item.get("target_execution_state") or "") for item in items),
        "document_completeness_state_distribution": _aggregate_mapping_counts(
            item.get("document_completeness_state_counts") for item in items
        ),
        "notice_version_chain_state_distribution": _aggregate_mapping_counts(
            item.get("notice_version_chain_state_counts") for item in items
        ),
        "ocr_blocked_count": sum(_int_value(item.get("ocr_required_count"), default=0) for item in items),
        "attachment_missing_count": sum(
            _int_value(item.get("attachment_missing_review_count"), default=0) for item in items
        ),
        "clarification_version_review_count": sum(
            _int_value(item.get("clarification_version_review_count"), default=0) for item in items
        ),
        "unknown_format_count": sum(_int_value(item.get("unknown_attachment_count"), default=0) for item in items),
        "file_review_rule_code": FILE_REVIEW_RULE_CODE,
        "file_review_expected_counts": {
            "PASS": pass_count,
            "REVIEW_REQUIRED": review_count,
        },
        "tailored_review_rule_code": TAILORED_REVIEW_RULE_CODE,
        "tailored_sample_count": len(tailored_items),
        "tailored_insufficient_sample_state": tailored_sample_state,
        "tailored_expected_counts": {
            "PASS": tailored_pass_count,
            "REVIEW_REQUIRED": tailored_review_count,
        },
        "tailored_risk_level_counts": _counts(
            str(item.get("tailored_bid_risk_level") or "") for item in tailored_items
        ),
        "tailored_index_distribution": _tailored_index_distribution(tailored_items),
        "tailored_sub_index_distribution": _aggregate_tailored_sub_indices(tailored_items),
        "tailored_ai_review_required_count": sum(
            1 for item in tailored_items if item.get("tailored_bid_ai_review_required")
        ),
        "tailored_stage5_review_required_count": sum(
            1 for item in tailored_items if item.get("tailored_bid_stage5_review_required")
        ),
        "tailored_counter_reason_count": sum(
            _int_value(item.get("tailored_bid_counter_reason_count"), default=0)
            for item in tailored_items
        ),
        "tailored_threshold_recommendation": {
            "recommendation_state": tailored_sample_state,
            "current_policy": {
                "NO_SIGNAL": 0,
                "LOW": "1-20",
                "WEAK_CLUE_REVIEW": "21-40",
                "MEDIUM_CLUE_REVIEW": "41-60",
                "HIGH_CLUE_REVIEW": "61-80",
                "STRONG_CLUE_REVIEW": "81-100",
            },
            "suggested_action": (
                "DO_NOT_MUTATE_FORMAL_THRESHOLDS_UNTIL_50_PLUS_REVIEWED_SAMPLES"
                if tailored_sample_state == "INSUFFICIENT_SAMPLE"
                else "MANUAL_REVIEW_THRESHOLD_DISTRIBUTION_BEFORE_MUTATION"
            ),
            "formal_rule_threshold_mutation_enabled": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _calibration_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    manifest_id = str(manifest["manifest_id"])
    return PersistedRecord(
        object_type=EVALUATION_RULE_CALIBRATION_MANIFEST_OBJECT_TYPE,
        record_id=manifest_id,
        stage_scope=0,
        project_id=None,
        object_refs={"manifest_id": manifest_id},
        decision_states={"evaluation_rule_calibration_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest.get("manifest_sha256") or "")},
        governed_state={
            "primary_status": "EVALUATION_RULE_CALIBRATION_READY",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "formal_rule_threshold_mutation_enabled": False,
        },
        writeback_state={
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at or build_persisted_at(),
    )


def _mapping_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        text = str(key or "")
        if not text:
            continue
        result[text] = _int_value(raw_count, default=0)
    return result


def _aggregate_mapping_counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        for key, count in _mapping_counts(value).items():
            result[key] = result.get(key, 0) + count
    return dict(sorted(result.items()))


def _tailored_index_distribution(items: list[Mapping[str, Any]]) -> dict[str, int]:
    buckets = {
        "0": 0,
        "1-20": 0,
        "21-40": 0,
        "41-60": 0,
        "61-80": 0,
        "81-100": 0,
    }
    for item in items:
        value = _int_value(item.get("tailored_bid_index"), default=0)
        if value <= 0:
            buckets["0"] += 1
        elif value <= 20:
            buckets["1-20"] += 1
        elif value <= 40:
            buckets["21-40"] += 1
        elif value <= 60:
            buckets["41-60"] += 1
        elif value <= 80:
            buckets["61-80"] += 1
        else:
            buckets["81-100"] += 1
    return buckets


def _aggregate_tailored_sub_indices(items: list[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    aggregate: dict[str, dict[str, int]] = {}
    for item in items:
        sub_indices = item.get("tailored_bid_sub_indices")
        if not isinstance(sub_indices, Mapping):
            continue
        for key, raw_value in sub_indices.items():
            value = _int_value(raw_value, default=0)
            if value <= 0:
                continue
            bucket = "1-20"
            if value > 80:
                bucket = "81-100"
            elif value > 60:
                bucket = "61-80"
            elif value > 40:
                bucket = "41-60"
            elif value > 20:
                bucket = "21-40"
            family = str(key or "")
            if not family:
                continue
            aggregate.setdefault(family, {"sample_count": 0, "score_sum": 0})
            aggregate[family]["sample_count"] += 1
            aggregate[family]["score_sum"] += value
            aggregate[family][bucket] = aggregate[family].get(bucket, 0) + 1
    return dict(sorted(aggregate.items()))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _redact_database_url(database_url: str | None) -> str:
    if not database_url or "://" not in database_url or "@" not in database_url:
        return database_url or ""
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build internal evaluation FILE/OCR and TAILORED rule calibration manifest."
    )
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
    parser.add_argument("--tailored-signal-seed-json")
    parser.add_argument("--database-url")
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--output-json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evaluation_rule_calibration_manifest(
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
        tailored_signal_seed_json=args.tailored_signal_seed_json,
        database_url=args.database_url,
        target_backend=args.target_backend,
        execute=args.execute,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "evaluation rule calibration "
            f"{result['rule_calibration_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVALUATION_RULE_CALIBRATION_MANIFEST_OBJECT_TYPE",
    "FILE_REVIEW_RULE_CODE",
    "TAILORED_REVIEW_RULE_CODE",
    "build_evaluation_rule_calibration_manifest",
]
