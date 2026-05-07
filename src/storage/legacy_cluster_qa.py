from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord
from storage.legacy_object_triage import LEGACY_OBJECT_TRIAGE_MANIFEST_OBJECT_TYPE
from storage.legacy_snapshot_parse import (
    LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE,
    LEGACY_SNAPSHOT_PARSE_MANIFEST_OBJECT_TYPE,
    normalize_project_name,
)


LEGACY_PROJECT_CLUSTER_QA_MANIFEST_OBJECT_TYPE = "legacy_project_cluster_qa_manifest"
LEGACY_CLUSTER_ATTACHMENT_LINK_MANIFEST_OBJECT_TYPE = "legacy_cluster_attachment_link_manifest"
LEGACY_CLUSTER_QA_VERSION = 1
LEGACY_CLUSTER_QA_RULESET_ID = "legacy-cluster-qa-attachment-link-v1"

PROJECT_NAME_HIGH_CONFIDENCE = "PROJECT_NAME_HIGH_CONFIDENCE"
PROJECT_NAME_REFINED_HIGH_CONFIDENCE = "PROJECT_NAME_REFINED_HIGH_CONFIDENCE"
PROJECT_NAME_OVEREXTRACTED_REVIEW = "PROJECT_NAME_OVEREXTRACTED_REVIEW"
PROJECT_NAME_REVIEW_ONLY = "PROJECT_NAME_REVIEW_ONLY"

LINKED_BY_EXACT_NORMALIZED_FILENAME = "LINKED_BY_EXACT_NORMALIZED_FILENAME"
REVIEW_ONLY_UNLINKED_ATTACHMENT = "REVIEW_ONLY_UNLINKED_ATTACHMENT"
REVIEW_ONLY_ATTACHMENT_PATH_NOT_RECOVERED = "REVIEW_ONLY_ATTACHMENT_PATH_NOT_RECOVERED"
REVIEW_ONLY_AMBIGUOUS_ATTACHMENT_MATCH = "REVIEW_ONLY_AMBIGUOUS_ATTACHMENT_MATCH"

ATTACHMENT_CONTENT_KINDS = frozenset({"pdf", "doc", "docx", "xls", "xlsx", "zip"})
ATTACHMENT_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"})

PROJECT_NAME_LABELS = (
    "招标项目名称",
    "采购项目名称",
    "工程项目名称",
    "项目名称",
    "工程名称",
)
PROJECT_NAME_STOP_TOKENS = (
    "招标项目编号",
    "采购项目编号",
    "工程编号",
    "项目编号",
    "资金来源和资金来源构成",
    "资金来源",
    "是否重大项目",
    "工程类型",
    "招标方式",
    "采购方式",
    "资格审查方式",
    "招 标 人",
    "招标人",
    "采购人",
    "建设单位",
    "招标机构",
    "代理机构",
    "发布日期",
    "公告日期",
    "公示日期",
)
OVEREXTRACTED_MARKERS = PROJECT_NAME_STOP_TOKENS
GENERIC_ATTACHMENT_NAMES = frozenset(
    {
        "招标公告",
        "采购公告",
        "中标公告",
        "中标候选人公示",
        "中标结果公告",
        "评标报告",
        "招标文件",
        "施工招标文件",
        "投标文件",
        "定稿",
        "附件",
        "download",
    }
)

LABEL_VALUE_RE_TEMPLATE = r"{label}\s*[:：]\s*(?P<value>.+)"
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class LegacyClusterQaItem:
    cluster_id: str
    original_cluster_key: str
    original_project_name: str
    refined_project_name_optional: str | None
    refined_cluster_key_optional: str | None
    qa_state: str
    name_source: str
    snapshot_ids: list[str]
    snapshot_count: int
    notice_stages: list[str]
    name_quality_reasons: list[str] = field(default_factory=list)
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttachmentPathRef:
    artifact_path: str
    artifact_relative_path: str
    file_name: str
    normalized_candidates: list[str]

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LegacyAttachmentLinkItem:
    object_key: str
    sha256: str
    content_kind: str
    content_type: str
    byte_size: int
    link_state: str
    linked_cluster_id_optional: str | None
    linked_refined_project_name_optional: str | None
    match_basis: str | None
    path_refs: list[dict[str, Any]]
    review_reasons: list[str]
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_run_artifacts_root() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "run-artifacts" / "repo-cleanup"


def build_legacy_cluster_qa(
    *,
    database_url: str,
    target_backend: str = "postgresql",
    run_artifacts_root: str | Path | None = None,
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    artifacts_root = Path(run_artifacts_root) if run_artifacts_root is not None else default_run_artifacts_root()
    settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
    )
    session = DatabaseSession(settings=settings)
    try:
        parse_record = _latest_record(session.list_records(LEGACY_SNAPSHOT_PARSE_MANIFEST_OBJECT_TYPE))
        cluster_record = _latest_record(session.list_records(LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE))
        triage_record = _latest_record(session.list_records(LEGACY_OBJECT_TRIAGE_MANIFEST_OBJECT_TYPE))
        blocking_reasons = _blocking_reasons(
            parse_record=parse_record,
            cluster_record=cluster_record,
            triage_record=triage_record,
        )
        parse_payload = dict(parse_record.payload) if parse_record else {}
        cluster_payload = dict(cluster_record.payload) if cluster_record else {}
        triage_payload = dict(triage_record.payload) if triage_record else {}

        qa_items = qa_legacy_clusters(
            clusters=list(cluster_payload.get("clusters") or []),
            parse_items=list(parse_payload.get("items") or []),
        )
        sha_paths = scan_run_artifact_attachment_paths(artifacts_root)
        attachment_items = link_legacy_attachments(
            triage_items=list(triage_payload.get("triage_items") or []),
            qa_items=qa_items,
            sha_paths=sha_paths,
        )
        qa_manifest = build_cluster_qa_manifest(
            qa_items=qa_items,
            parse_manifest_id=str(parse_payload.get("manifest_id") or ""),
            cluster_manifest_id=str(cluster_payload.get("manifest_id") or ""),
            database_url=database_url,
            target_backend=target_backend,
            run_artifacts_root=artifacts_root,
            created_at=created,
        )
        attachment_manifest = build_attachment_link_manifest(
            attachment_items=attachment_items,
            qa_manifest_id=str(qa_manifest["manifest_id"]),
            triage_manifest_id=str(triage_payload.get("manifest_id") or ""),
            database_url=database_url,
            target_backend=target_backend,
            run_artifacts_root=artifacts_root,
            created_at=created,
        )
        result = {
            "qa_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "qa_manifest": qa_manifest,
            "attachment_link_manifest": attachment_manifest,
            "summary": {
                "cluster_qa": qa_manifest["summary"],
                "attachment_link": attachment_manifest["summary"],
            },
            "execution": {
                "executed": False,
                "target_mutation_enabled": False,
                "database_write_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_pass_generation_enabled": False,
                "large_object_blob_database_import_enabled": False,
            },
        }
        if execute and not blocking_reasons:
            with session.bulk_write():
                session.upsert_record(_cluster_qa_manifest_record(qa_manifest, discovered_at=created))
                session.upsert_record(_attachment_link_manifest_record(attachment_manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_legacy_project_cluster_qa_manifest_count": 1,
                "upserted_legacy_cluster_attachment_link_manifest_count": 1,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_pass_generation_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        return result
    finally:
        session.close()


def qa_legacy_clusters(
    *,
    clusters: Iterable[Mapping[str, Any]],
    parse_items: Iterable[Mapping[str, Any]],
) -> list[LegacyClusterQaItem]:
    parse_by_snapshot_id = {
        str(item.get("snapshot_id")): dict(item)
        for item in parse_items
        if item.get("snapshot_id")
    }
    rows: list[LegacyClusterQaItem] = []
    for cluster in sorted(clusters, key=lambda row: str(row.get("cluster_id") or "")):
        snapshot_ids = [str(value) for value in list(cluster.get("snapshot_ids") or [])]
        member_items = [parse_by_snapshot_id[snapshot_id] for snapshot_id in snapshot_ids if snapshot_id in parse_by_snapshot_id]
        original_name = _clean_text(cluster.get("display_project_name")) or str(cluster.get("cluster_key") or "")
        refined_name, name_source, reasons = _refined_project_name(original_name, member_items)
        refined_key = normalize_project_name(refined_name) if refined_name else None
        original_key = normalize_project_name(original_name)
        original_overextracted = _is_overextracted(original_name)
        refined_overextracted = _is_overextracted(refined_name)
        if original_overextracted:
            reasons.append("original_project_name_overextracted")
        if refined_overextracted:
            reasons.append("refined_project_name_overextracted")

        if refined_name and refined_key and not refined_overextracted:
            qa_state = (
                PROJECT_NAME_REFINED_HIGH_CONFIDENCE
                if refined_key != original_key or original_overextracted
                else PROJECT_NAME_HIGH_CONFIDENCE
            )
        elif original_overextracted or refined_overextracted:
            qa_state = PROJECT_NAME_OVEREXTRACTED_REVIEW
            refined_name = None
            refined_key = None
        else:
            qa_state = PROJECT_NAME_REVIEW_ONLY
            refined_name = refined_name if refined_key else None
            refined_key = refined_key if refined_key else None
            reasons.append("project_name_high_confidence_source_missing")

        rows.append(
            LegacyClusterQaItem(
                cluster_id=str(cluster.get("cluster_id") or ""),
                original_cluster_key=str(cluster.get("cluster_key") or ""),
                original_project_name=original_name,
                refined_project_name_optional=refined_name,
                refined_cluster_key_optional=refined_key,
                qa_state=qa_state,
                name_source=name_source,
                snapshot_ids=snapshot_ids,
                snapshot_count=int(cluster.get("snapshot_count") or len(snapshot_ids)),
                notice_stages=[str(value) for value in list(cluster.get("notice_stages") or [])],
                name_quality_reasons=list(dict.fromkeys(reason for reason in reasons if reason)),
            )
        )
    return rows


def scan_run_artifact_attachment_paths(root: Path) -> dict[str, list[AttachmentPathRef]]:
    if not root.exists() or not root.is_dir():
        return {}
    rows: dict[str, list[AttachmentPathRef]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ATTACHMENT_EXTENSIONS:
            continue
        digest = _sha256_file(path)
        relative_path = _safe_relative_path(path, root)
        candidates = _path_normalized_candidates(relative_path)
        rows.setdefault(digest, []).append(
            AttachmentPathRef(
                artifact_path=str(path),
                artifact_relative_path=relative_path,
                file_name=path.name,
                normalized_candidates=candidates,
            )
        )
    return rows


def link_legacy_attachments(
    *,
    triage_items: Iterable[Mapping[str, Any]],
    qa_items: Iterable[LegacyClusterQaItem],
    sha_paths: Mapping[str, list[AttachmentPathRef]],
) -> list[LegacyAttachmentLinkItem]:
    cluster_by_key: dict[str, LegacyClusterQaItem] = {
        str(item.refined_cluster_key_optional): item
        for item in qa_items
        if item.refined_cluster_key_optional
        and item.qa_state in {PROJECT_NAME_HIGH_CONFIDENCE, PROJECT_NAME_REFINED_HIGH_CONFIDENCE}
    }
    rows: list[LegacyAttachmentLinkItem] = []
    for item in sorted(triage_items, key=lambda row: str(row.get("object_key") or "")):
        content_kind = str(item.get("content_kind") or "")
        if content_kind not in ATTACHMENT_CONTENT_KINDS:
            continue
        object_key = str(item.get("object_key") or "")
        sha256 = str(item.get("sha256") or "")
        path_refs = list(sha_paths.get(sha256) or [])
        matched_keys = sorted(
            {
                candidate
                for path_ref in path_refs
                for candidate in path_ref.normalized_candidates
                if candidate in cluster_by_key
            }
        )
        if len(matched_keys) == 1:
            cluster = cluster_by_key[matched_keys[0]]
            link_state = LINKED_BY_EXACT_NORMALIZED_FILENAME
            linked_cluster_id = cluster.cluster_id
            linked_project_name = cluster.refined_project_name_optional
            match_basis = "run_artifact_path_segment_exact_normalized_match"
            reasons = ["review_required_legacy_attachment_candidate"]
        elif len(matched_keys) > 1:
            link_state = REVIEW_ONLY_AMBIGUOUS_ATTACHMENT_MATCH
            linked_cluster_id = None
            linked_project_name = None
            match_basis = None
            reasons = ["multiple_refined_cluster_keys_matched_attachment_path"]
        elif not path_refs:
            link_state = REVIEW_ONLY_ATTACHMENT_PATH_NOT_RECOVERED
            linked_cluster_id = None
            linked_project_name = None
            match_basis = None
            reasons = ["run_artifact_path_missing_for_attachment_sha256"]
        else:
            link_state = REVIEW_ONLY_UNLINKED_ATTACHMENT
            linked_cluster_id = None
            linked_project_name = None
            match_basis = None
            reasons = ["attachment_path_did_not_exact_match_refined_project_name"]

        rows.append(
            LegacyAttachmentLinkItem(
                object_key=object_key,
                sha256=sha256,
                content_kind=content_kind,
                content_type=str(item.get("content_type") or "application/octet-stream"),
                byte_size=int(item.get("byte_size") or 0),
                link_state=link_state,
                linked_cluster_id_optional=linked_cluster_id,
                linked_refined_project_name_optional=linked_project_name,
                match_basis=match_basis,
                path_refs=[path_ref.as_payload() for path_ref in path_refs],
                review_reasons=reasons,
            )
        )
    return rows


def build_cluster_qa_manifest(
    *,
    qa_items: list[LegacyClusterQaItem],
    parse_manifest_id: str,
    cluster_manifest_id: str,
    database_url: str,
    target_backend: str,
    run_artifacts_root: Path,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "type": "cluster_qa",
            "ruleset_id": LEGACY_CLUSTER_QA_RULESET_ID,
            "items": [
                {
                    "cluster_id": item.cluster_id,
                    "refined_cluster_key": item.refined_cluster_key_optional,
                    "qa_state": item.qa_state,
                }
                for item in qa_items
            ],
        }
    )
    manifest_id = f"LEGACY-CLUSTER-QA-{fingerprint[:16]}"
    payload = {
        "manifest_version": LEGACY_CLUSTER_QA_VERSION,
        "ruleset_id": LEGACY_CLUSTER_QA_RULESET_ID,
        "manifest_id": manifest_id,
        "legacy_snapshot_parse_manifest_id": parse_manifest_id,
        "legacy_project_cluster_manifest_id": cluster_manifest_id,
        "created_at": created_at,
        "run_artifacts_root": str(run_artifacts_root),
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "summary": _qa_summary(qa_items),
        "items": [item.as_payload() for item in qa_items],
        "sample_items": [item.as_payload() for item in sorted(qa_items, key=lambda row: row.cluster_id)[:50]],
        "safety": _safety(),
        "qa_fingerprint": fingerprint,
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def build_attachment_link_manifest(
    *,
    attachment_items: list[LegacyAttachmentLinkItem],
    qa_manifest_id: str,
    triage_manifest_id: str,
    database_url: str,
    target_backend: str,
    run_artifacts_root: Path,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "type": "attachment_link",
            "ruleset_id": LEGACY_CLUSTER_QA_RULESET_ID,
            "items": [
                {
                    "object_key": item.object_key,
                    "link_state": item.link_state,
                    "linked_cluster_id": item.linked_cluster_id_optional,
                }
                for item in attachment_items
            ],
        }
    )
    manifest_id = f"LEGACY-ATTACHMENT-LINK-{fingerprint[:16]}"
    payload = {
        "manifest_version": LEGACY_CLUSTER_QA_VERSION,
        "ruleset_id": LEGACY_CLUSTER_QA_RULESET_ID,
        "manifest_id": manifest_id,
        "legacy_project_cluster_qa_manifest_id": qa_manifest_id,
        "legacy_object_triage_manifest_id": triage_manifest_id,
        "created_at": created_at,
        "run_artifacts_root": str(run_artifacts_root),
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "summary": _attachment_summary(attachment_items),
        "items": [item.as_payload() for item in attachment_items],
        "sample_items": [item.as_payload() for item in sorted(attachment_items, key=lambda row: row.object_key)[:50]],
        "safety": _safety(),
        "attachment_link_fingerprint": fingerprint,
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _refined_project_name(original_name: str, member_items: list[Mapping[str, Any]]) -> tuple[str | None, str, list[str]]:
    reasons: list[str] = []
    field_candidates = []
    for item in member_items:
        for field in list(item.get("parsed_fields_summary") or []):
            if str(field.get("field_name") or "") == "project_name":
                value = _clean_text(field.get("field_value_optional"))
                if value:
                    field_candidates.append(value)
    field_candidate = _best_project_name_candidate(field_candidates)
    if field_candidate and not _is_overextracted(field_candidate):
        reasons.append("stage3_project_name_field_selected")
        return field_candidate, "stage3_project_name", reasons
    if field_candidate:
        reasons.append("stage3_project_name_field_overextracted")

    for value in _candidate_texts(original_name, member_items):
        labeled = extract_labeled_project_name(value)
        if labeled:
            reasons.append("labeled_project_name_extracted")
            return labeled, "title_labeled_project_name", reasons

    fallback = _clean_project_name(original_name)
    if fallback:
        reasons.append("fallback_original_display_name_used")
        return fallback, "original_display_project_name", reasons
    return None, "missing_project_name", ["project_name_missing"]


def extract_labeled_project_name(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    for label in PROJECT_NAME_LABELS:
        pattern = re.compile(LABEL_VALUE_RE_TEMPLATE.format(label=re.escape(label)))
        match = pattern.search(text)
        if not match:
            continue
        tail = match.group("value")
        stop_indexes = [
            index
            for token in PROJECT_NAME_STOP_TOKENS
            if token != label
            for index in [tail.find(token)]
            if index > 0
        ]
        if stop_indexes:
            tail = tail[: min(stop_indexes)]
        candidate = _clean_project_name(tail)
        if candidate:
            return candidate
    return None


def _candidate_texts(original_name: str, member_items: list[Mapping[str, Any]]) -> list[str]:
    values = [original_name]
    for item in member_items:
        for key in ("project_name_candidate", "title"):
            value = _clean_text(item.get(key))
            if value:
                values.append(value)
    return list(dict.fromkeys(values))


def _best_project_name_candidate(values: Iterable[str]) -> str | None:
    candidates = [
        value
        for value in (_clean_project_name(value) for value in values)
        if value
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda value: (int(_is_overextracted(value)), len(value), value))[0]


def _clean_project_name(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    text = re.sub(r"^(?:download[_-]*)+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\.(?:pdf|docx?|xlsx?|zip|rar)$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^[：:;；,，\-_—–\s]+", "", text)
    text = re.sub(r"[：:;；,，\-_—–\s]+$", "", text)
    return text or None


def _is_overextracted(value: Any) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    if len(text) > 120:
        return True
    return any(marker in text for marker in OVEREXTRACTED_MARKERS)


def _path_normalized_candidates(relative_path: str) -> list[str]:
    path = Path(relative_path)
    raw_candidates = [path.stem, *[part for part in path.parts[:-1] if part not in {".", ""}]]
    normalized: list[str] = []
    for candidate in raw_candidates:
        cleaned = _clean_project_name(candidate)
        if not cleaned:
            continue
        for prefix in ("download_", "download-", "附件_", "附件-", "file_", "file-"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):]
        key = normalize_project_name(cleaned)
        if not key or key in GENERIC_ATTACHMENT_NAMES or len(key) < 6:
            continue
        normalized.append(key)
    return list(dict.fromkeys(normalized))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _qa_summary(items: list[LegacyClusterQaItem]) -> dict[str, Any]:
    return {
        "cluster_count": len(items),
        "qa_state_counts": _counts(item.qa_state for item in items),
        "refined_project_name_count": sum(1 for item in items if item.refined_project_name_optional),
        "overextracted_review_count": sum(1 for item in items if item.qa_state == PROJECT_NAME_OVEREXTRACTED_REVIEW),
        "review_required_count": len(items),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
    }


def _attachment_summary(items: list[LegacyAttachmentLinkItem]) -> dict[str, Any]:
    return {
        "attachment_candidate_count": len(items),
        "link_state_counts": _counts(item.link_state for item in items),
        "linked_attachment_count": sum(1 for item in items if item.link_state == LINKED_BY_EXACT_NORMALIZED_FILENAME),
        "unlinked_review_count": sum(1 for item in items if item.link_state != LINKED_BY_EXACT_NORMALIZED_FILENAME),
        "content_kind_counts": _counts(item.content_kind for item in items),
        "review_required_count": len(items),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
    }


def _cluster_qa_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_PROJECT_CLUSTER_QA_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "legacy_project_cluster_manifest_id": str(manifest["legacy_project_cluster_manifest_id"]),
            "legacy_snapshot_parse_manifest_id": str(manifest["legacy_snapshot_parse_manifest_id"]),
        },
        decision_states={"legacy_cluster_qa_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_CLUSTER_QA_READY",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_pass_generation_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _attachment_link_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_CLUSTER_ATTACHMENT_LINK_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "legacy_project_cluster_qa_manifest_id": str(manifest["legacy_project_cluster_qa_manifest_id"]),
            "legacy_object_triage_manifest_id": str(manifest["legacy_object_triage_manifest_id"]),
        },
        decision_states={"legacy_cluster_attachment_link_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_CLUSTER_ATTACHMENT_LINK_READY",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_pass_generation_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _blocking_reasons(
    *,
    parse_record: PersistedRecord | None,
    cluster_record: PersistedRecord | None,
    triage_record: PersistedRecord | None,
) -> list[str]:
    reasons: list[str] = []
    if parse_record is None:
        reasons.append("legacy_snapshot_parse_manifest_missing")
    if cluster_record is None:
        reasons.append("legacy_project_cluster_manifest_missing")
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


def _safety() -> dict[str, Any]:
    return {
        "external_service_connection_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_pass_generation_enabled": False,
        "large_object_blob_database_import_enabled": False,
        "pdf_ocr_enabled": False,
        "pdf_text_parse_enabled": False,
        "fuzzy_project_merge_enabled": False,
    }


def _clean_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    cleaned = SPACE_RE.sub(" ", str(value)).strip()
    return cleaned or None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA legacy project clusters and link legacy attachment candidates.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--run-artifacts-root", default=str(default_run_artifacts_root()))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_legacy_cluster_qa(
        database_url=args.database_url,
        target_backend=args.target_backend,
        run_artifacts_root=args.run_artifacts_root,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"legacy cluster qa {result['qa_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LEGACY_CLUSTER_ATTACHMENT_LINK_MANIFEST_OBJECT_TYPE",
    "LEGACY_PROJECT_CLUSTER_QA_MANIFEST_OBJECT_TYPE",
    "LINKED_BY_EXACT_NORMALIZED_FILENAME",
    "PROJECT_NAME_OVEREXTRACTED_REVIEW",
    "PROJECT_NAME_REFINED_HIGH_CONFIDENCE",
    "REVIEW_ONLY_ATTACHMENT_PATH_NOT_RECOVERED",
    "REVIEW_ONLY_UNLINKED_ATTACHMENT",
    "build_legacy_cluster_qa",
    "extract_labeled_project_name",
    "link_legacy_attachments",
    "qa_legacy_clusters",
    "scan_run_artifact_attachment_paths",
]
