from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage3_parsing.ocr_text import OCR_REQUIRED, _extract_pdf_embedded_text
from stage3_parsing.real_parser import _extract_fields_from_text
from stage3_parsing.service import Stage3Service
from storage.db import DatabaseSession, PersistedRecord
from storage.legacy_object_triage import (
    LEGACY_OBJECT_TRIAGE_MANIFEST_OBJECT_TYPE,
    REVIEW_ONLY_ATTACHMENT_CANDIDATE,
)
from storage.object_storage import (
    LOCAL_OBJECT_STORAGE_BACKEND,
    LocalObjectStorage,
    ObjectStorageError,
)


LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE = "legacy_attachment_parse_manifest"
LEGACY_ATTACHMENT_PARSE_VERSION = 1
LEGACY_ATTACHMENT_PARSE_RULESET_ID = "legacy-attachment-parse-v1"
LEGACY_ATTACHMENT_PARSE_ADAPTER_ID = "legacy-attachment-parse"
LEGACY_ATTACHMENT_SNAPSHOT_KIND = "legacy_attachment_object"

PARSE_STATE_PARSED = "PARSED"
PARSE_STATE_PARSED_WITH_REVIEW = "PARSED_WITH_REVIEW"
PARSE_STATE_REVIEW_REQUIRED = "REVIEW_REQUIRED"

TARGET_ATTACHMENT_KINDS = frozenset({"pdf", "docx", "xlsx", "zip"})
ZIP_ENTRY_SAMPLE_LIMIT = 50
FIELD_VALUE_LIMIT = 500


@dataclass(frozen=True)
class LegacyAttachmentParseItem:
    object_key: str
    sha256: str
    content_kind: str
    content_type: str
    byte_size: int
    object_present: bool
    sha256_verified: bool
    byte_size_verified: bool
    hash_path_valid: bool
    parse_state: str
    stage3_parse_state_optional: str | None
    parser_family: str
    attachment_type: str
    parsed_field_count: int
    parsed_fields_summary: list[dict[str, Any]] = field(default_factory=list)
    parser_steps: list[str] = field(default_factory=list)
    fallback_steps: list[str] = field(default_factory=list)
    parser_error_taxonomy: list[str] = field(default_factory=list)
    review_required: bool = True
    review_reasons: list[str] = field(default_factory=list)
    source_url_optional: str | None = None
    source_family_optional: str | None = None
    zip_entry_count_optional: int | None = None
    zip_entry_samples: list[str] = field(default_factory=list)
    ocr_required: bool = False
    ocr_attempted: bool = False
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def build_legacy_attachment_parse(
    *,
    database_url: str,
    target_backend: str = "postgresql",
    object_storage_path: str | Path | None = None,
    execute: bool = False,
    limit: int | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    object_root = Path(object_storage_path) if object_storage_path is not None else default_object_storage_path()
    settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_root),
    )
    session = DatabaseSession(settings=settings)
    try:
        triage_record = _latest_record(session.list_records(LEGACY_OBJECT_TRIAGE_MANIFEST_OBJECT_TYPE))
        triage_payload = dict(triage_record.payload) if triage_record else {}
        blocking_reasons = _blocking_reasons(
            object_root=object_root,
            triage_record=triage_record,
        )
        object_store = LocalObjectStorage(root_path=object_root)
        attachment_items = _attachment_triage_items(triage_payload)
        if limit is not None and limit >= 0:
            attachment_items = attachment_items[:limit]
        parse_items = parse_legacy_attachments(
            triage_items=attachment_items,
            object_store=object_store,
            triage_manifest_id=str(triage_payload.get("manifest_id") or ""),
        )
        manifest = build_attachment_parse_manifest(
            items=parse_items,
            triage_manifest_id=str(triage_payload.get("manifest_id") or ""),
            database_url=database_url,
            target_backend=target_backend,
            object_storage_path=object_root,
            created_at=created,
        )
        result = {
            "parse_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "manifest": manifest,
            "summary": manifest["summary"],
            "execution": {
                "executed": False,
                "target_mutation_enabled": False,
                "database_write_enabled": False,
                "evidence_snapshot_manifest_generation_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_pass_generation_enabled": False,
                "large_object_blob_database_import_enabled": False,
            },
        }
        if execute and not blocking_reasons:
            with session.bulk_write():
                session.upsert_record(_attachment_parse_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_legacy_attachment_parse_manifest_count": 1,
                "evidence_snapshot_manifest_generation_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_pass_generation_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        return result
    finally:
        session.close()


def parse_legacy_attachments(
    *,
    triage_items: Iterable[Mapping[str, Any]],
    object_store: LocalObjectStorage,
    triage_manifest_id: str,
) -> list[LegacyAttachmentParseItem]:
    service = Stage3Service()
    parsed: list[LegacyAttachmentParseItem] = []
    for item in sorted(triage_items, key=lambda row: str(row.get("object_key") or "")):
        parsed.append(
            parse_legacy_attachment_item(
                triage_item=item,
                object_store=object_store,
                triage_manifest_id=triage_manifest_id,
                service=service,
            )
        )
    return parsed


def parse_legacy_attachment_item(
    *,
    triage_item: Mapping[str, Any],
    object_store: LocalObjectStorage,
    triage_manifest_id: str,
    service: Stage3Service | None = None,
) -> LegacyAttachmentParseItem:
    parser_service = service or Stage3Service()
    object_key = str(triage_item.get("object_key") or "")
    content_kind = _text(triage_item.get("content_kind")) or "unknown"
    content_type = _text(triage_item.get("content_type")) or _content_type_for_kind(content_kind)
    byte_size = _int(triage_item.get("byte_size"))
    sha256 = _text(triage_item.get("sha256")) or ""
    hash_path_valid = bool(triage_item.get("hash_path_valid"))
    source_url = _text(triage_item.get("source_url_optional"))
    source_family = _text(triage_item.get("source_family_optional"))
    review_reasons: list[str] = []

    try:
        path = object_store.object_path(object_key)
    except Exception as exc:
        return _review_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            hash_path_valid=False,
            object_present=False,
            sha256_verified=False,
            byte_size_verified=False,
            parser_family=_parser_family_for_kind(content_kind),
            attachment_type=_attachment_type_for_kind(content_kind),
            review_reasons=[f"object_key_invalid:{type(exc).__name__}"],
            source_url_optional=source_url,
            source_family_optional=source_family,
        )

    object_present = path.exists() and path.is_file()
    actual_byte_size = path.stat().st_size if object_present else -1
    actual_sha256 = _sha256_file(path) if object_present else ""
    sha256_verified = bool(sha256 and actual_sha256 == sha256)
    byte_size_verified = bool(byte_size >= 0 and actual_byte_size == byte_size)
    if not object_present:
        review_reasons.append("object_file_missing")
    if not sha256_verified:
        review_reasons.append("sha256_mismatch")
    if not byte_size_verified:
        review_reasons.append("byte_size_mismatch")
    if not hash_path_valid:
        review_reasons.append("hash_path_invalid")
    if content_kind not in TARGET_ATTACHMENT_KINDS:
        review_reasons.append("unsupported_legacy_attachment_kind")
    if review_reasons:
        return _review_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            hash_path_valid=hash_path_valid,
            object_present=object_present,
            sha256_verified=sha256_verified,
            byte_size_verified=byte_size_verified,
            parser_family=_parser_family_for_kind(content_kind),
            attachment_type=_attachment_type_for_kind(content_kind),
            review_reasons=review_reasons,
            source_url_optional=source_url,
            source_family_optional=source_family,
        )

    try:
        data = object_store.read_bytes(
            object_key,
            expected_sha256=sha256,
            expected_byte_size=byte_size,
        )
    except ObjectStorageError as exc:
        return _review_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            hash_path_valid=hash_path_valid,
            object_present=object_present,
            sha256_verified=False,
            byte_size_verified=byte_size_verified,
            parser_family=_parser_family_for_kind(content_kind),
            attachment_type=_attachment_type_for_kind(content_kind),
            review_reasons=[f"object_readback_failed:{type(exc).__name__}"],
            source_url_optional=source_url,
            source_family_optional=source_family,
        )

    if content_kind == "zip":
        zip_entry_count, zip_samples, zip_reasons = _inspect_zip(data)
        return _review_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            hash_path_valid=hash_path_valid,
            object_present=object_present,
            sha256_verified=sha256_verified,
            byte_size_verified=byte_size_verified,
            parser_family="zip",
            attachment_type="ZIP_ARCHIVE",
            review_reasons=["zip_directory_only_no_recursive_parse", *zip_reasons],
            source_url_optional=source_url,
            source_family_optional=source_family,
            zip_entry_count_optional=zip_entry_count,
            zip_entry_samples=zip_samples,
            parser_steps=["read_object_storage_object", "inspect_zip_directory"],
        )
    if content_kind == "pdf":
        return _parse_pdf_without_ocr(
            triage_item=triage_item,
            data=data,
            object_present=object_present,
            sha256_verified=sha256_verified,
            byte_size_verified=byte_size_verified,
            hash_path_valid=hash_path_valid,
            source_url_optional=source_url,
            source_family_optional=source_family,
        )

    readback = _stage3_readback(
        triage_item=triage_item,
        data=data,
        triage_manifest_id=triage_manifest_id,
        source_url_optional=source_url,
        source_family_optional=source_family,
    )
    try:
        carrier = dict(parser_service.parse_raw_snapshot_readback(readback))
    except Exception as exc:
        return _review_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            hash_path_valid=hash_path_valid,
            object_present=object_present,
            sha256_verified=sha256_verified,
            byte_size_verified=byte_size_verified,
            parser_family=_parser_family_for_kind(content_kind),
            attachment_type=_attachment_type_for_kind(content_kind),
            review_reasons=[f"stage3_parse_failed:{type(exc).__name__}"],
            source_url_optional=source_url,
            source_family_optional=source_family,
        )

    audit = dict(carrier.get("parser_audit") or {})
    parsed_fields = list(carrier.get("parsed_fields") or [])
    parser_steps = [str(step) for step in list(audit.get("parser_steps") or [])]
    fallback_steps = [str(step) for step in list(audit.get("fallback_steps") or [])]
    taxonomy = [str(code) for code in list(carrier.get("parse_error_taxonomy") or [])]
    reasons = _review_reasons(
        taxonomy=taxonomy,
        fallback_steps=fallback_steps,
        parsed_field_count=len(parsed_fields),
        source_url_optional=source_url,
    )
    stage3_parse_state = _text(carrier.get("parse_state")) or PARSE_STATE_REVIEW_REQUIRED
    parse_state = stage3_parse_state if parsed_fields else PARSE_STATE_REVIEW_REQUIRED
    return LegacyAttachmentParseItem(
        object_key=object_key,
        sha256=sha256,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        object_present=object_present,
        sha256_verified=sha256_verified,
        byte_size_verified=byte_size_verified,
        hash_path_valid=hash_path_valid,
        parse_state=parse_state,
        stage3_parse_state_optional=stage3_parse_state,
        parser_family=_text(carrier.get("parser_family")) or _parser_family_for_kind(content_kind),
        attachment_type=_text(carrier.get("attachment_type")) or _attachment_type_for_kind(content_kind),
        parsed_field_count=len(parsed_fields),
        parsed_fields_summary=_parsed_fields_summary(parsed_fields),
        parser_steps=parser_steps,
        fallback_steps=fallback_steps,
        parser_error_taxonomy=taxonomy,
        review_required=True,
        review_reasons=reasons,
        source_url_optional=source_url,
        source_family_optional=source_family,
        ocr_required=_contains_ocr_required(taxonomy, fallback_steps),
        ocr_attempted=any("ocr" in step.lower() for step in parser_steps),
        customer_visible_allowed=False,
        no_legal_conclusion=True,
    )


def _parse_pdf_without_ocr(
    *,
    triage_item: Mapping[str, Any],
    data: bytes,
    object_present: bool,
    sha256_verified: bool,
    byte_size_verified: bool,
    hash_path_valid: bool,
    source_url_optional: str | None,
    source_family_optional: str | None,
) -> LegacyAttachmentParseItem:
    object_key = str(triage_item.get("object_key") or "")
    sha256 = str(triage_item.get("sha256") or hashlib.sha256(data).hexdigest())
    content_type = _text(triage_item.get("content_type")) or "application/pdf"
    byte_size = _int(triage_item.get("byte_size"))
    parser_steps = ["read_object_storage_object", "detect_attachment_type:PDF", "extract_pdf_embedded_text_only"]
    pdf_result = _extract_pdf_embedded_text(data, max_pages=30)
    fields = []
    taxonomy: list[str] = []
    fallback_steps: list[str] = []
    if pdf_result.text:
        fields = [
            field.as_payload()
            for field in _extract_fields_from_text(
                pdf_result.text,
                source_file_ref=object_key,
                locator_type="pdf_text",
                base_locator={"source": "pdf_text", "extractor": pdf_result.extractor},
                confidence=pdf_result.confidence,
                review_required=pdf_result.review_required,
                parse_warnings=pdf_result.warnings,
            )
        ]
    else:
        taxonomy.append("PDF_TEXT_UNAVAILABLE")
        fallback_steps.append("degrade_to_review:pdf_embedded_text_unavailable")
        if OCR_REQUIRED in pdf_result.warnings or OCR_REQUIRED in pdf_result.state:
            taxonomy.append(OCR_REQUIRED)
            fallback_steps.append("degrade_to_review:ocr_required_but_disabled")
    if not fields:
        fallback_steps.append("degrade_to_review:no_field_candidates")
    parse_state = PARSE_STATE_PARSED if fields and not taxonomy else PARSE_STATE_REVIEW_REQUIRED
    if fields and taxonomy:
        parse_state = PARSE_STATE_PARSED_WITH_REVIEW
    reasons = _review_reasons(
        taxonomy=taxonomy,
        fallback_steps=fallback_steps,
        parsed_field_count=len(fields),
        source_url_optional=source_url_optional,
    )
    return LegacyAttachmentParseItem(
        object_key=object_key,
        sha256=sha256,
        content_kind="pdf",
        content_type=content_type,
        byte_size=byte_size,
        object_present=object_present,
        sha256_verified=sha256_verified,
        byte_size_verified=byte_size_verified,
        hash_path_valid=hash_path_valid,
        parse_state=parse_state,
        stage3_parse_state_optional=parse_state,
        parser_family="pdf",
        attachment_type="PDF",
        parsed_field_count=len(fields),
        parsed_fields_summary=_parsed_fields_summary(fields),
        parser_steps=parser_steps,
        fallback_steps=fallback_steps,
        parser_error_taxonomy=taxonomy,
        review_required=True,
        review_reasons=reasons,
        source_url_optional=source_url_optional,
        source_family_optional=source_family_optional,
        ocr_required=OCR_REQUIRED in taxonomy,
        ocr_attempted=False,
        customer_visible_allowed=False,
        no_legal_conclusion=True,
    )


def build_attachment_parse_manifest(
    *,
    items: list[LegacyAttachmentParseItem],
    triage_manifest_id: str,
    database_url: str,
    target_backend: str,
    object_storage_path: Path,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _parse_fingerprint(
        object_storage_path=object_storage_path,
        triage_manifest_id=triage_manifest_id,
        items=items,
    )
    manifest_id = f"LEGACY-ATTACHMENT-PARSE-{fingerprint[:16]}"
    payload = {
        "manifest_version": LEGACY_ATTACHMENT_PARSE_VERSION,
        "ruleset_id": LEGACY_ATTACHMENT_PARSE_RULESET_ID,
        "manifest_id": manifest_id,
        "parse_id": manifest_id,
        "created_at": created_at,
        "object_storage_path": str(object_storage_path),
        "object_storage_root_exists": object_storage_path.exists(),
        "source_object_storage_backend": LOCAL_OBJECT_STORAGE_BACKEND,
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "legacy_object_triage_manifest_id": triage_manifest_id,
        "parse_fingerprint": fingerprint,
        "summary": _summary(items),
        "items": [item.as_payload() for item in items],
        "sample_items": [item.as_payload() for item in sorted(items, key=lambda row: row.object_key)[:50]],
        "safety": _safety(),
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _stage3_readback(
    *,
    triage_item: Mapping[str, Any],
    data: bytes,
    triage_manifest_id: str,
    source_url_optional: str | None,
    source_family_optional: str | None,
) -> dict[str, Any]:
    object_key = str(triage_item.get("object_key") or "")
    sha256 = str(triage_item.get("sha256") or hashlib.sha256(data).hexdigest())
    content_type = _text(triage_item.get("content_type")) or _content_type_for_kind(
        _text(triage_item.get("content_kind")) or "unknown"
    )
    snapshot_id = f"LEGACY-ATTACHMENT-{sha256[:16]}"
    manifest = {
        "snapshot_id": snapshot_id,
        "object_key": object_key,
        "source_url_optional": source_url_optional,
        "source_family_optional": source_family_optional,
        "snapshot_kind": LEGACY_ATTACHMENT_SNAPSHOT_KIND,
        "content_type": content_type,
        "byte_size": int(triage_item.get("byte_size") or len(data)),
        "sha256": sha256,
        "lineage_refs": {
            "legacy_object_key": object_key,
            "legacy_object_triage_manifest_id": triage_manifest_id,
        },
        "raw_snapshot_metadata": {
            "legacy_review_required": True,
            "legacy_attachment_parse": True,
            "legacy_source_url_not_recovered": source_url_optional is None,
        },
    }
    return {
        "snapshot_id": snapshot_id,
        "readback_state": "READBACK_READY",
        "manifest_present": True,
        "object_present": True,
        "replayable": True,
        "fail_closed": False,
        "no_broad_fallback": True,
        "object_key": object_key,
        "content_type": content_type,
        "byte_size": int(triage_item.get("byte_size") or len(data)),
        "sha256": sha256,
        "snapshot_kind": LEGACY_ATTACHMENT_SNAPSHOT_KIND,
        "lineage_refs": dict(manifest["lineage_refs"]),
        "manifest": manifest,
        "bytes": data,
        "external_service_connection_enabled": False,
    }


def _review_item(
    *,
    object_key: str,
    sha256: str,
    content_kind: str,
    content_type: str,
    byte_size: int,
    hash_path_valid: bool,
    object_present: bool,
    sha256_verified: bool,
    byte_size_verified: bool,
    parser_family: str,
    attachment_type: str,
    review_reasons: list[str],
    source_url_optional: str | None,
    source_family_optional: str | None,
    zip_entry_count_optional: int | None = None,
    zip_entry_samples: list[str] | None = None,
    parser_steps: list[str] | None = None,
) -> LegacyAttachmentParseItem:
    reasons = [*review_reasons, "legacy_attachment_review_required"]
    if source_url_optional is None:
        reasons.append("legacy_source_url_not_recovered")
    return LegacyAttachmentParseItem(
        object_key=object_key,
        sha256=sha256,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        object_present=object_present,
        sha256_verified=sha256_verified,
        byte_size_verified=byte_size_verified,
        hash_path_valid=hash_path_valid,
        parse_state=PARSE_STATE_REVIEW_REQUIRED,
        stage3_parse_state_optional=None,
        parser_family=parser_family,
        attachment_type=attachment_type,
        parsed_field_count=0,
        parsed_fields_summary=[],
        parser_steps=list(parser_steps or []),
        fallback_steps=["degrade_to_review:legacy_attachment_review_required"],
        parser_error_taxonomy=list(dict.fromkeys(review_reasons)),
        review_required=True,
        review_reasons=list(dict.fromkeys(reasons)),
        source_url_optional=source_url_optional,
        source_family_optional=source_family_optional,
        zip_entry_count_optional=zip_entry_count_optional,
        zip_entry_samples=list(zip_entry_samples or []),
        ocr_required=any("ocr" in reason.lower() for reason in review_reasons),
        ocr_attempted=False,
        customer_visible_allowed=False,
        no_legal_conclusion=True,
    )


def _attachment_triage_items(triage_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = []
    for item in list(triage_payload.get("triage_items") or []):
        row = dict(item)
        if row.get("triage_state") == REVIEW_ONLY_ATTACHMENT_CANDIDATE:
            items.append(row)
    return items


def _parsed_fields_summary(parsed_fields: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in parsed_fields:
        payload = dict(field) if isinstance(field, Mapping) else {}
        locator = dict(payload.get("locator") or {})
        rows.append(
            {
                "field_name": _text(payload.get("field_name")),
                "field_value_optional": _limit_text(_text(payload.get("field_value_optional"))),
                "source_file_ref": _text(payload.get("source_file_ref")),
                "source_slice_sha256": _text(payload.get("source_slice_sha256")),
                "locator_type": _text(locator.get("type")),
                "confidence": payload.get("confidence"),
                "review_required": bool(payload.get("review_required")),
                "parse_warnings": list(payload.get("parse_warnings") or []),
            }
        )
    return rows[:50]


def _review_reasons(
    *,
    taxonomy: list[str],
    fallback_steps: list[str],
    parsed_field_count: int,
    source_url_optional: str | None,
) -> list[str]:
    reasons = [*taxonomy, *fallback_steps, "legacy_attachment_review_required"]
    if parsed_field_count <= 0:
        reasons.append("legacy_attachment_no_field_candidates")
    if source_url_optional is None:
        reasons.append("legacy_source_url_not_recovered")
    reasons.append("legacy_project_identity_not_resolved")
    reasons.append("legacy_customer_visibility_not_allowed")
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _inspect_zip(data: bytes) -> tuple[int | None, list[str], list[str]]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = sorted(archive.namelist())
    except zipfile.BadZipFile:
        return None, [], ["zip_directory_unreadable"]
    samples = [name for name in names[:ZIP_ENTRY_SAMPLE_LIMIT] if not _looks_like_path_escape(name)]
    blockers = []
    if len(samples) != min(len(names), ZIP_ENTRY_SAMPLE_LIMIT):
        blockers.append("zip_entry_path_escape_review")
    return len(names), samples, blockers


def _looks_like_path_escape(name: str) -> bool:
    parts = Path(name.replace("\\", "/")).parts
    return name.startswith("/") or ".." in parts


def _attachment_parse_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "legacy_object_triage_manifest_id": str(manifest["legacy_object_triage_manifest_id"]),
            "object_storage_path": str(manifest["object_storage_path"]),
        },
        decision_states={"legacy_attachment_parse_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_ATTACHMENT_PARSE_READY",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "evidence_snapshot_manifest_generation_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_pass_generation_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _summary(items: list[LegacyAttachmentParseItem]) -> dict[str, Any]:
    parsed_with_fields = sum(1 for item in items if item.parsed_field_count > 0)
    return {
        "attachment_candidate_count": len(items),
        "parsed_with_fields_count": parsed_with_fields,
        "review_required_count": len(items),
        "parse_state_counts": _counts(item.parse_state for item in items),
        "content_kind_counts": _counts(item.content_kind for item in items),
        "parser_family_counts": _counts(item.parser_family for item in items),
        "integrity_blocked_count": sum(
            1
            for item in items
            if not item.object_present
            or not item.sha256_verified
            or not item.byte_size_verified
            or not item.hash_path_valid
        ),
        "ocr_required_count": sum(1 for item in items if item.ocr_required),
        "ocr_attempted_count": sum(1 for item in items if item.ocr_attempted),
        "zip_review_count": sum(1 for item in items if item.content_kind == "zip"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_pass_generation_enabled": False,
        "large_object_blob_database_import_enabled": False,
    }


def _safety() -> dict[str, Any]:
    return {
        "external_service_connection_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "source_mutation_enabled": False,
        "object_delete_enabled": False,
        "object_move_enabled": False,
        "evidence_snapshot_manifest_generation_enabled": False,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_pass_generation_enabled": False,
        "large_object_blob_database_import_enabled": False,
        "pdf_ocr_bulk_enablement": False,
        "zip_recursive_parse_enabled": False,
    }


def _blocking_reasons(
    *,
    object_root: Path,
    triage_record: PersistedRecord | None,
) -> list[str]:
    reasons: list[str] = []
    if not object_root.exists():
        reasons.append("object_storage_root_missing")
    if triage_record is None:
        reasons.append("legacy_object_triage_manifest_missing")
    return reasons


def _latest_record(records: list[PersistedRecord]) -> PersistedRecord | None:
    if not records:
        return None
    return sorted(
        records,
        key=lambda row: (
            str(row.payload.get("created_at") or ""),
            row.persisted_at,
            row.record_id,
        ),
    )[-1]


def _parse_fingerprint(
    *,
    object_storage_path: Path,
    triage_manifest_id: str,
    items: list[LegacyAttachmentParseItem],
) -> str:
    payload = {
        "manifest_version": LEGACY_ATTACHMENT_PARSE_VERSION,
        "ruleset_id": LEGACY_ATTACHMENT_PARSE_RULESET_ID,
        "object_storage_path": str(object_storage_path),
        "legacy_object_triage_manifest_id": triage_manifest_id,
        "items": [
            {
                "object_key": item.object_key,
                "sha256": item.sha256,
                "content_kind": item.content_kind,
                "parse_state": item.parse_state,
                "parsed_field_count": item.parsed_field_count,
                "review_reasons": item.review_reasons,
            }
            for item in items
        ],
    }
    return _fingerprint(payload)


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contains_ocr_required(taxonomy: Iterable[str], fallback_steps: Iterable[str]) -> bool:
    return any("OCR_REQUIRED" in value or "ocr_required" in value.lower() for value in [*taxonomy, *fallback_steps])


def _parser_family_for_kind(content_kind: str) -> str:
    return {
        "pdf": "pdf",
        "docx": "word",
        "xlsx": "excel",
        "zip": "zip",
    }.get(content_kind, "attachment")


def _attachment_type_for_kind(content_kind: str) -> str:
    return {
        "pdf": "PDF",
        "docx": "WORD_DOCX",
        "xlsx": "EXCEL_XLSX",
        "zip": "ZIP_ARCHIVE",
    }.get(content_kind, "UNKNOWN_ATTACHMENT")


def _content_type_for_kind(content_kind: str) -> str:
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "zip": "application/zip",
    }.get(content_kind, "application/octet-stream")


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return str(value)


def _limit_text(value: str | None, *, limit: int = FIELD_VALUE_LIMIT) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:limit] + "..."


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse legacy attachment candidates into internal review manifests.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--object-storage-path", default=str(default_object_storage_path()))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_legacy_attachment_parse(
        database_url=args.database_url,
        target_backend=args.target_backend,
        object_storage_path=args.object_storage_path,
        execute=args.execute,
        limit=args.limit,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"legacy attachment parse {result['parse_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE",
    "PARSE_STATE_PARSED",
    "PARSE_STATE_PARSED_WITH_REVIEW",
    "PARSE_STATE_REVIEW_REQUIRED",
    "build_legacy_attachment_parse",
    "parse_legacy_attachment_item",
    "parse_legacy_attachments",
]
