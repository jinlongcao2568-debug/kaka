from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.object_storage import (
    EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE,
    LOCAL_OBJECT_STORAGE_BACKEND,
    OBJECT_STORAGE_OBJECT_TYPE,
    EvidenceSnapshotManifest,
    LocalObjectStorage,
    StoredObjectMetadata,
    build_replay_metadata,
)
from storage.object_storage_inventory import OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE
from storage.repositories.object_storage_repo import ObjectStorageRepository


LEGACY_OBJECT_TRIAGE_MANIFEST_OBJECT_TYPE = "legacy_object_triage_manifest"
LEGACY_OBJECT_TRIAGE_VERSION = 1
LEGACY_OBJECT_TRIAGE_RULESET_ID = "legacy-object-triage-v1"
LEGACY_TRIAGE_ADAPTER_ID = "legacy-object-triage"

PROMOTE_CANDIDATE = "PROMOTE_CANDIDATE"
PROMOTED_HIGH_CONFIDENCE = "PROMOTED_HIGH_CONFIDENCE"
REVIEW_ONLY_ATTACHMENT_CANDIDATE = "REVIEW_ONLY_ATTACHMENT_CANDIDATE"
REVIEW_ONLY_SOURCE_UNCLEAR = "REVIEW_ONLY_SOURCE_UNCLEAR"
REVIEW_ONLY_INTEGRITY_BLOCKED = "REVIEW_ONLY_INTEGRITY_BLOCKED"

LEGACY_PUBLIC_HTML_SNAPSHOT_KIND = "legacy_public_html_snapshot"
LEGACY_PUBLIC_JSON_SNAPSHOT_KIND = "legacy_public_json_snapshot"

TEXT_SAMPLE_LIMIT = 256 * 1024

SOURCE_MARKERS_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "credit_china": ("信用中国", "creditchina"),
    "national_enterprise_credit_publicity_system": ("国家企业信用", "企业信用信息公示"),
    "national_construction_market_platform": (
        "全国建筑市场",
        "建筑市场监管",
        "jzsc",
        "施工许可",
        "竣工验收",
        "合同备案",
    ),
    "public_procurement_platform": (
        "公共资源交易",
        "公共资源交易平台",
        "公共资源交易网",
        "广州交易集团",
        "广东省公共资源交易平台",
        "北京市公共资源交易服务平台",
        "江苏省公共资源交易网",
        "中国政府采购网",
    ),
}

RECORD_MARKERS = (
    "招标公告",
    "采购公告",
    "中标候选人",
    "中标结果",
    "中标公告",
    "评标报告",
    "招标文件",
    "投标",
    "施工许可",
    "竣工验收",
    "合同备案",
    "履约",
    "业绩",
    "行政处罚",
    "失信",
    "执行信息",
    "严重违法",
    "异常经营",
)

JSON_PROMOTION_KEYS = frozenset(
    {
        "source_url",
        "sourceUrl",
        "url",
        "snapshot_id",
        "snapshotId",
        "snapshot_id_optional",
        "source_snapshot_id",
        "source_family",
        "sourceFamily",
        "source_registry_id",
        "public_source",
        "publicSource",
    }
)

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class LegacyTriageItem:
    object_key: str
    content_kind: str
    content_type: str
    byte_size: int
    sha256: str
    file_present: bool
    sha256_verified: bool
    byte_size_verified: bool
    hash_path_valid: bool
    triage_state: str
    promotion_eligible: bool
    review_required: bool
    no_legal_conclusion: bool = True
    customer_visible_allowed: bool = False
    triage_confidence: str = "LOW"
    evidence_snapshot_id_optional: str | None = None
    snapshot_kind_optional: str | None = None
    source_family_optional: str | None = None
    source_url_optional: str | None = None
    title_optional: str | None = None
    matched_markers: list[str] = field(default_factory=list)
    promotion_reason: str | None = None
    promotion_blockers: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_legacy_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def build_legacy_object_triage(
    *,
    object_storage_path: str | Path | None = None,
    database_url: str,
    target_backend: str = "postgresql",
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    root = Path(object_storage_path) if object_storage_path is not None else default_legacy_object_storage_path()
    created = created_at or utc_now_iso()
    settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(root),
    )
    session = DatabaseSession(settings=settings)
    try:
        object_records = session.list_records(OBJECT_STORAGE_OBJECT_TYPE)
        inventory_manifest_record = _latest_inventory_manifest_record(
            session.list_records(OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE)
        )
        latest_inventory = inventory_manifest_record.payload if inventory_manifest_record else {}
        object_store = LocalObjectStorage(root_path=root)
        items = triage_legacy_objects(
            root=root,
            object_store=object_store,
            object_records=object_records,
        )
        manifest = build_triage_manifest(
            root=root,
            items=items,
            latest_inventory=latest_inventory,
            database_url=database_url,
            target_backend=target_backend,
            created_at=created,
        )
        blocking_reasons = _blocking_reasons(
            root=root,
            object_records=object_records,
            inventory_manifest_record=inventory_manifest_record,
        )
        result = {
            "triage_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "manifest": manifest,
            "summary": manifest["summary"],
            "execution": {
                "executed": False,
                "target_mutation_enabled": False,
                "large_object_blob_database_import_enabled": False,
                "evidence_snapshot_manifest_generation_enabled": False,
            },
        }
        if execute:
            if blocking_reasons:
                raise RuntimeError(
                    "legacy object triage is not safe to execute: "
                    + ", ".join(blocking_reasons)
                )
            promoted = _promotable_items(items)
            repository = ObjectStorageRepository(
                session=session,
                settings=settings,
                object_store=object_store,
            )
            with session.bulk_write():
                session.upsert_record(_triage_manifest_record(manifest, discovered_at=created))
                for item in promoted:
                    repository.save_manifest(
                        _evidence_manifest_from_item(
                            item,
                            triage_manifest=manifest,
                            created_at=created,
                        )
                    )
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "large_object_blob_database_import_enabled": False,
                "evidence_snapshot_manifest_generation_enabled": True,
                "upserted_legacy_object_triage_manifest_count": 1,
                "upserted_evidence_snapshot_manifest_count": len(promoted),
            }
        return result
    finally:
        session.close()


def triage_legacy_objects(
    *,
    root: Path,
    object_store: LocalObjectStorage,
    object_records: Iterable[PersistedRecord],
) -> list[LegacyTriageItem]:
    rows: list[LegacyTriageItem] = []
    for record in sorted(object_records, key=lambda row: row.record_id):
        payload = dict(record.payload)
        object_key = str(payload.get("object_key") or record.record_id)
        content_kind = str(payload.get("content_kind") or _kind_from_content_type(payload.get("content_type")))
        content_type = str(payload.get("content_type") or "application/octet-stream")
        byte_size = int(payload.get("byte_size") or 0)
        sha256 = str(payload.get("sha256") or "")
        hash_path_valid = bool(payload.get("hash_path_valid"))
        path = object_store.object_path(object_key)
        file_present = path.exists() and path.is_file()
        actual_sha256 = _sha256_file(path) if file_present else ""
        actual_byte_size = path.stat().st_size if file_present else -1
        sha256_verified = bool(sha256 and actual_sha256 == sha256)
        byte_size_verified = bool(byte_size >= 0 and actual_byte_size == byte_size)
        base_blockers: list[str] = []
        if not file_present:
            base_blockers.append("object_file_missing")
        if not sha256_verified:
            base_blockers.append("sha256_mismatch")
        if not byte_size_verified:
            base_blockers.append("byte_size_mismatch")
        if not hash_path_valid:
            base_blockers.append("hash_path_invalid")
        if base_blockers:
            rows.append(
                _blocked_item(
                    object_key=object_key,
                    content_kind=content_kind,
                    content_type=content_type,
                    byte_size=byte_size,
                    sha256=sha256,
                    file_present=file_present,
                    sha256_verified=sha256_verified,
                    byte_size_verified=byte_size_verified,
                    hash_path_valid=hash_path_valid,
                    blockers=base_blockers,
                )
            )
            continue
        if content_kind == "html":
            rows.append(
                _triage_html_item(
                    path=path,
                    object_key=object_key,
                    content_kind=content_kind,
                    content_type=content_type,
                    byte_size=byte_size,
                    sha256=sha256,
                    hash_path_valid=hash_path_valid,
                )
            )
            continue
        if content_kind == "json":
            rows.append(
                _triage_json_item(
                    path=path,
                    object_key=object_key,
                    content_kind=content_kind,
                    content_type=content_type,
                    byte_size=byte_size,
                    sha256=sha256,
                    hash_path_valid=hash_path_valid,
                )
            )
            continue
        if content_kind in {"pdf", "docx", "xlsx", "pptx", "zip"}:
            rows.append(
                _review_item(
                    object_key=object_key,
                    content_kind=content_kind,
                    content_type=content_type,
                    byte_size=byte_size,
                    sha256=sha256,
                    hash_path_valid=hash_path_valid,
                    triage_state=REVIEW_ONLY_ATTACHMENT_CANDIDATE,
                    triage_confidence="MEDIUM",
                    blockers=[f"{content_kind}_requires_stage3_parse_and_source_lineage"],
                )
            )
            continue
        rows.append(
            _review_item(
                object_key=object_key,
                content_kind=content_kind,
                content_type=content_type,
                byte_size=byte_size,
                sha256=sha256,
                hash_path_valid=hash_path_valid,
                triage_state=REVIEW_ONLY_SOURCE_UNCLEAR,
                blockers=["unsupported_or_unclear_legacy_content_kind"],
            )
        )
    return rows


def build_triage_manifest(
    *,
    root: Path,
    items: list[LegacyTriageItem],
    latest_inventory: Mapping[str, Any],
    database_url: str,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    latest_inventory_id = _text(latest_inventory.get("inventory_id") or latest_inventory.get("manifest_id"))
    fingerprint = _triage_fingerprint(
        root=root,
        inventory_id=latest_inventory_id,
        items=items,
    )
    manifest_id = f"LEGACY-OBJECT-TRIAGE-{fingerprint[:16]}"
    payload = {
        "manifest_version": LEGACY_OBJECT_TRIAGE_VERSION,
        "ruleset_id": LEGACY_OBJECT_TRIAGE_RULESET_ID,
        "manifest_id": manifest_id,
        "triage_id": manifest_id,
        "created_at": created_at,
        "object_storage_root": str(root),
        "object_storage_root_exists": root.exists(),
        "source_object_storage_backend": LOCAL_OBJECT_STORAGE_BACKEND,
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "legacy_inventory_manifest_id": latest_inventory_id,
        "triage_fingerprint": fingerprint,
        "summary": _triage_summary(items),
        "triage_items": [item.as_payload() for item in items],
        "sample_items": [
            item.as_payload()
            for item in sorted(
                items,
                key=lambda row: (
                    not row.promotion_eligible,
                    row.triage_state,
                    row.object_key,
                ),
            )[:50]
        ],
        "safety": {
            "source_mutation_enabled": False,
            "object_delete_enabled": False,
            "object_move_enabled": False,
            "large_object_blob_database_import_enabled": False,
            "external_service_connection_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_pass_generation_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _triage_html_item(
    *,
    path: Path,
    object_key: str,
    content_kind: str,
    content_type: str,
    byte_size: int,
    sha256: str,
    hash_path_valid: bool,
) -> LegacyTriageItem:
    sample = _read_text_sample(path)
    title = _extract_title(sample)
    matched_markers = _matched_markers(sample, title)
    source_family = _infer_source_family(sample)
    source_markers = _source_marker_matches(sample)
    record_markers = _record_marker_matches(sample)
    blockers: list[str] = []
    if not title:
        blockers.append("html_title_missing")
    if not source_markers:
        blockers.append("public_source_marker_missing")
    if not record_markers:
        blockers.append("public_record_marker_missing")
    if blockers:
        return _review_item(
            object_key=object_key,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256,
            hash_path_valid=hash_path_valid,
            triage_state=REVIEW_ONLY_SOURCE_UNCLEAR,
            blockers=blockers,
            matched_markers=matched_markers,
            title=title,
            source_family=source_family,
        )
    snapshot_id = _legacy_snapshot_id(sha256)
    return LegacyTriageItem(
        object_key=object_key,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        sha256=sha256,
        file_present=True,
        sha256_verified=True,
        byte_size_verified=True,
        hash_path_valid=hash_path_valid,
        triage_state=PROMOTE_CANDIDATE,
        promotion_eligible=True,
        review_required=True,
        triage_confidence="HIGH",
        evidence_snapshot_id_optional=snapshot_id,
        snapshot_kind_optional=LEGACY_PUBLIC_HTML_SNAPSHOT_KIND,
        source_family_optional=source_family,
        source_url_optional=None,
        title_optional=title,
        matched_markers=matched_markers,
        promotion_reason="high_confidence_public_html_marker_match",
        promotion_blockers=[],
    )


def _triage_json_item(
    *,
    path: Path,
    object_key: str,
    content_kind: str,
    content_type: str,
    byte_size: int,
    sha256: str,
    hash_path_valid: bool,
) -> LegacyTriageItem:
    blockers: list[str] = []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _review_item(
            object_key=object_key,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256,
            hash_path_valid=hash_path_valid,
            triage_state=REVIEW_ONLY_SOURCE_UNCLEAR,
            blockers=[f"json_parse_failed:{exc.__class__.__name__}"],
        )
    keys = sorted(_json_keys(parsed))
    matched_keys = [key for key in keys if key in JSON_PROMOTION_KEYS]
    source_url = _find_json_string(parsed, {"source_url", "sourceUrl", "url"})
    source_family = _find_json_string(parsed, {"source_family", "sourceFamily"})
    serialized = json.dumps(parsed, ensure_ascii=False, sort_keys=True)[:TEXT_SAMPLE_LIMIT]
    inferred_family = source_family or _infer_source_family(serialized)
    title = _find_json_string(parsed, {"title", "project_name", "projectName", "name"})
    if not source_url:
        blockers.append("json_source_url_missing")
    if not any(key in matched_keys for key in ("snapshot_id", "snapshotId", "snapshot_id_optional", "source_snapshot_id", "source_family", "sourceFamily", "public_source", "publicSource")):
        blockers.append("json_snapshot_or_source_family_marker_missing")
    if blockers:
        return _review_item(
            object_key=object_key,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256,
            hash_path_valid=hash_path_valid,
            triage_state=REVIEW_ONLY_SOURCE_UNCLEAR,
            blockers=blockers,
            matched_markers=matched_keys,
            title=title,
            source_family=inferred_family,
            source_url=source_url,
        )
    snapshot_id = _legacy_snapshot_id(sha256)
    return LegacyTriageItem(
        object_key=object_key,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        sha256=sha256,
        file_present=True,
        sha256_verified=True,
        byte_size_verified=True,
        hash_path_valid=hash_path_valid,
        triage_state=PROMOTE_CANDIDATE,
        promotion_eligible=True,
        review_required=True,
        triage_confidence="HIGH",
        evidence_snapshot_id_optional=snapshot_id,
        snapshot_kind_optional=LEGACY_PUBLIC_JSON_SNAPSHOT_KIND,
        source_family_optional=inferred_family,
        source_url_optional=source_url,
        title_optional=title,
        matched_markers=matched_keys,
        promotion_reason="high_confidence_public_json_snapshot_fields",
        promotion_blockers=[],
    )


def _blocked_item(
    *,
    object_key: str,
    content_kind: str,
    content_type: str,
    byte_size: int,
    sha256: str,
    file_present: bool,
    sha256_verified: bool,
    byte_size_verified: bool,
    hash_path_valid: bool,
    blockers: list[str],
) -> LegacyTriageItem:
    return LegacyTriageItem(
        object_key=object_key,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        sha256=sha256,
        file_present=file_present,
        sha256_verified=sha256_verified,
        byte_size_verified=byte_size_verified,
        hash_path_valid=hash_path_valid,
        triage_state=REVIEW_ONLY_INTEGRITY_BLOCKED,
        promotion_eligible=False,
        review_required=True,
        triage_confidence="NONE",
        promotion_blockers=blockers,
    )


def _review_item(
    *,
    object_key: str,
    content_kind: str,
    content_type: str,
    byte_size: int,
    sha256: str,
    hash_path_valid: bool,
    triage_state: str,
    blockers: list[str],
    triage_confidence: str = "LOW",
    matched_markers: list[str] | None = None,
    title: str | None = None,
    source_family: str | None = None,
    source_url: str | None = None,
) -> LegacyTriageItem:
    return LegacyTriageItem(
        object_key=object_key,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        sha256=sha256,
        file_present=True,
        sha256_verified=True,
        byte_size_verified=True,
        hash_path_valid=hash_path_valid,
        triage_state=triage_state,
        promotion_eligible=False,
        review_required=True,
        triage_confidence=triage_confidence,
        source_family_optional=source_family,
        source_url_optional=source_url,
        title_optional=title,
        matched_markers=list(matched_markers or []),
        promotion_blockers=blockers,
    )


def _evidence_manifest_from_item(
    item: LegacyTriageItem,
    *,
    triage_manifest: Mapping[str, Any],
    created_at: str,
) -> EvidenceSnapshotManifest:
    snapshot_id = str(item.evidence_snapshot_id_optional or _legacy_snapshot_id(item.sha256))
    object_metadata = StoredObjectMetadata(
        object_key=item.object_key,
        content_type=item.content_type,
        byte_size=item.byte_size,
        sha256=item.sha256,
        created_at=created_at,
        storage_backend=LOCAL_OBJECT_STORAGE_BACKEND,
    )
    legacy_inventory_id = _text(triage_manifest.get("legacy_inventory_manifest_id"))
    triage_manifest_id = str(triage_manifest["manifest_id"])
    lineage_refs = {
        "legacy_object_key": item.object_key,
        "legacy_inventory_manifest_id": legacy_inventory_id,
        "legacy_triage_manifest_id": triage_manifest_id,
        "triage_confidence": item.triage_confidence,
        "promotion_reason": str(item.promotion_reason or ""),
    }
    return EvidenceSnapshotManifest(
        snapshot_id=snapshot_id,
        object_key=item.object_key,
        source_url_optional=item.source_url_optional,
        source_family_optional=item.source_family_optional,
        snapshot_kind=str(item.snapshot_kind_optional),
        content_type=item.content_type,
        byte_size=item.byte_size,
        sha256=item.sha256,
        lineage_refs={key: value for key, value in lineage_refs.items() if value},
        created_at=created_at,
        storage_backend=LOCAL_OBJECT_STORAGE_BACKEND,
        replay_metadata=build_replay_metadata(
            object_metadata=object_metadata,
            replayed_at=created_at,
        ),
        adapter_id_optional=LEGACY_TRIAGE_ADAPTER_ID,
        source_visibility_state_optional="PUBLIC_SOURCE_UNVERIFIED_LEGACY",
        snapshot_version_optional=LEGACY_OBJECT_TRIAGE_RULESET_ID,
        captured_at_optional=created_at,
        fetch_mode_optional="LEGACY_OBJECT_STORAGE_TRIAGE_NO_LIVE_FETCH",
        fetch_audit={
            "legacy_triage": True,
            "real_provider_call_executed": False,
            "external_service_connection_enabled": False,
            "source_mutation_enabled": False,
        },
        replay_state="READBACK_READY",
        raw_snapshot_metadata={
            "legacy_triage": True,
            "legacy_review_required": True,
            "review_required_reasons": _legacy_review_reasons(item),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_pass_generation_enabled": False,
            "legacy_object_key": item.object_key,
            "legacy_inventory_manifest_id": legacy_inventory_id,
            "legacy_triage_manifest_id": triage_manifest_id,
            "content_kind": item.content_kind,
            "title_optional": item.title_optional,
            "matched_markers": list(item.matched_markers),
            "source_url_present": bool(item.source_url_optional),
            "project_identity_resolved": False,
        },
        source_health={
            "state": "LEGACY_REVIEW_REQUIRED",
            "manual_review_required": True,
            "degraded_reasons": _legacy_review_reasons(item),
        },
    )


def _triage_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_OBJECT_TRIAGE_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "object_storage_root": str(manifest["object_storage_root"]),
            "legacy_inventory_manifest_id": str(manifest.get("legacy_inventory_manifest_id") or ""),
        },
        decision_states={"triage_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_OBJECT_TRIAGE_READY",
            "ruleset_id": str(manifest["ruleset_id"]),
            "promoted_evidence_snapshot_count": manifest["summary"]["promotion_eligible_count"],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "source_mutation_enabled": False,
            "object_delete_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _triage_summary(items: list[LegacyTriageItem]) -> dict[str, Any]:
    return {
        "object_count": len(items),
        "promotion_eligible_count": sum(1 for item in items if item.promotion_eligible),
        "review_required_count": sum(1 for item in items if item.review_required),
        "content_kind_counts": _counts(item.content_kind for item in items),
        "triage_state_counts": _counts(item.triage_state for item in items),
        "snapshot_kind_counts": _counts(
            item.snapshot_kind_optional or "none"
            for item in items
        ),
        "source_family_counts": _counts(
            item.source_family_optional or "unknown"
            for item in items
        ),
        "integrity_blocked_count": sum(
            1 for item in items if item.triage_state == REVIEW_ONLY_INTEGRITY_BLOCKED
        ),
        "attachment_candidate_count": sum(
            1 for item in items if item.triage_state == REVIEW_ONLY_ATTACHMENT_CANDIDATE
        ),
        "large_object_blob_database_import_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _blocking_reasons(
    *,
    root: Path,
    object_records: list[PersistedRecord],
    inventory_manifest_record: PersistedRecord | None,
) -> list[str]:
    reasons: list[str] = []
    if not root.exists():
        reasons.append("object_storage_root_missing")
    if not object_records:
        reasons.append("object_storage_object_records_missing")
    if inventory_manifest_record is None:
        reasons.append("object_storage_inventory_manifest_missing")
    return reasons


def _latest_inventory_manifest_record(records: list[PersistedRecord]) -> PersistedRecord | None:
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


def _promotable_items(items: Iterable[LegacyTriageItem]) -> list[LegacyTriageItem]:
    return [
        item
        for item in items
        if item.promotion_eligible and item.evidence_snapshot_id_optional and item.snapshot_kind_optional
    ]


def _legacy_snapshot_id(sha256: str) -> str:
    return f"LEGACY-SNAPSHOT-{sha256[:16]}"


def _legacy_review_reasons(item: LegacyTriageItem) -> list[str]:
    reasons = list(item.promotion_blockers)
    if not item.source_url_optional:
        reasons.append("legacy_source_url_not_recovered")
    reasons.append("legacy_project_identity_not_resolved")
    reasons.append("legacy_customer_visibility_not_allowed")
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _read_text_sample(path: Path) -> str:
    data = path.read_bytes()[:TEXT_SAMPLE_LIMIT]
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_title(text: str) -> str | None:
    match = TITLE_RE.search(text)
    if not match:
        return None
    title = html.unescape(TAG_RE.sub("", match.group(1)))
    title = WHITESPACE_RE.sub(" ", title).strip()
    return title or None


def _matched_markers(text: str, title: str | None) -> list[str]:
    haystack = f"{title or ''}\n{text}".lower()
    markers: list[str] = []
    for marker in _all_markers():
        if marker.lower() in haystack:
            markers.append(marker)
    return markers


def _source_marker_matches(text: str) -> list[str]:
    lowered = text.lower()
    return [
        marker
        for marker in _source_markers()
        if marker.lower() in lowered
    ]


def _record_marker_matches(text: str) -> list[str]:
    lowered = text.lower()
    return [
        marker
        for marker in RECORD_MARKERS
        if marker.lower() in lowered
    ]


def _infer_source_family(text: str) -> str | None:
    lowered = text.lower()
    for source_family, markers in SOURCE_MARKERS_BY_FAMILY.items():
        if any(marker.lower() in lowered for marker in markers):
            return source_family
    if any(marker.lower() in lowered for marker in RECORD_MARKERS):
        return "legacy_public_record"
    return None


def _all_markers() -> list[str]:
    return list(dict.fromkeys([*_source_markers(), *RECORD_MARKERS]))


def _source_markers() -> list[str]:
    markers: list[str] = []
    for values in SOURCE_MARKERS_BY_FAMILY.values():
        markers.extend(values)
    return list(dict.fromkeys(markers))


def _json_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _json_keys(nested)
        return
    if isinstance(value, list):
        for item in value:
            yield from _json_keys(item)


def _find_json_string(value: Any, keys: set[str]) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in keys and isinstance(nested, str) and nested.strip():
                return nested.strip()
            found = _find_json_string(nested, keys)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _find_json_string(item, keys)
            if found:
                return found
    return None


def _kind_from_content_type(content_type: Any) -> str:
    value = str(content_type or "").lower()
    if "html" in value:
        return "html"
    if "json" in value:
        return "json"
    if "pdf" in value:
        return "pdf"
    if "zip" in value:
        return "zip"
    return "unknown_binary"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _triage_fingerprint(
    *,
    root: Path,
    inventory_id: str | None,
    items: list[LegacyTriageItem],
) -> str:
    rows = [
        {
            "object_key": item.object_key,
            "sha256": item.sha256,
            "triage_state": item.triage_state,
            "promotion_eligible": item.promotion_eligible,
            "snapshot_kind": item.snapshot_kind_optional,
        }
        for item in sorted(items, key=lambda row: row.object_key)
    ]
    encoded = json.dumps(
        {
            "root": str(root),
            "inventory_id": inventory_id,
            "ruleset_id": LEGACY_OBJECT_TRIAGE_RULESET_ID,
            "items": rows,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return str(value)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Triage legacy local object-storage objects and promote high-confidence snapshots."
    )
    parser.add_argument("--object-storage-path", default=str(default_legacy_object_storage_path()))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_legacy_object_triage(
        object_storage_path=args.object_storage_path,
        database_url=args.database_url,
        target_backend=args.target_backend,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"legacy object triage {result['triage_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LEGACY_OBJECT_TRIAGE_MANIFEST_OBJECT_TYPE",
    "PROMOTE_CANDIDATE",
    "PROMOTED_HIGH_CONFIDENCE",
    "REVIEW_ONLY_ATTACHMENT_CANDIDATE",
    "REVIEW_ONLY_INTEGRITY_BLOCKED",
    "REVIEW_ONLY_SOURCE_UNCLEAR",
    "build_legacy_object_triage",
    "triage_legacy_objects",
]
