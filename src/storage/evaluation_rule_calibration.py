from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


EVALUATION_RULE_CALIBRATION_MANIFEST_OBJECT_TYPE = "evaluation_rule_calibration_manifest"
EVALUATION_RULE_CALIBRATION_MANIFEST_VERSION = 1
EVALUATION_RULE_CALIBRATION_RULESET_ID = "evaluation-rule-calibration-file-review-v1"
EVALUATION_RULE_CALIBRATION_ADAPTER_ID = "evaluation-rule-calibration-builder"
FILE_REVIEW_RULE_CODE = "FILE-REVIEW-001"

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
    items = [
        _calibrate_file_review_item(item)
        for item in list(source_manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]
    manifest = _build_manifest(
        items=items,
        source_manifest=source_manifest,
        execution_path=execution_path,
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


def _target_requires_attachment(item: Mapping[str, Any]) -> bool:
    value = item.get("attachment_required")
    if value is None:
        value = item.get("requires_attachment")
    return bool(value)


def _build_manifest(
    *,
    items: list[dict[str, Any]],
    source_manifest: Mapping[str, Any],
    execution_path: Path,
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    summary = _summary(items)
    fingerprint = _fingerprint(
        {
            "source_manifest_id": source_manifest.get("manifest_id"),
            "source_manifest_sha256": source_manifest.get("manifest_sha256"),
            "items": items,
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
        "database_url_redacted": _redact_database_url(database_url),
        "target_storage_backend": target_backend,
        "calibrated_rule_codes": [FILE_REVIEW_RULE_CODE],
        "non_calibrated_rule_codes": [
            "TAILORED-REVIEW-001",
            "FATAL-REVIEW-001",
            "PRICE-REVIEW-001",
            "REMEDY-REVIEW-001",
        ],
        "items": items,
        "sample_items": items[:80],
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


def _summary(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    review_count = sum(1 for item in items if item.get("expected_file_review_state") == "REVIEW_REQUIRED")
    pass_count = sum(1 for item in items if item.get("expected_file_review_state") == "PASS")
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
    parser = argparse.ArgumentParser(description="Build internal evaluation FILE/OCR rule calibration manifest.")
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
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
    "build_evaluation_rule_calibration_manifest",
]
