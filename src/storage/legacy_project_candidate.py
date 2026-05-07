from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord
from storage.legacy_attachment_parse import LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE
from storage.legacy_cluster_qa import (
    LEGACY_CLUSTER_ATTACHMENT_LINK_MANIFEST_OBJECT_TYPE,
    LEGACY_PROJECT_CLUSTER_QA_MANIFEST_OBJECT_TYPE,
    LINKED_BY_EXACT_NORMALIZED_FILENAME,
    PROJECT_NAME_OVEREXTRACTED_REVIEW,
)
from storage.legacy_snapshot_parse import (
    LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE,
    normalize_project_name,
)


LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE = "legacy_cluster_attachment_link_v2_manifest"
LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE = "legacy_project_candidate_manifest"
LEGACY_PROJECT_CANDIDATE_VERSION = 1
LEGACY_PROJECT_CANDIDATE_RULESET_ID = "legacy-project-candidate-v1"

LINKED_BY_V1_EXACT_NORMALIZED_FILENAME = "LINKED_BY_V1_EXACT_NORMALIZED_FILENAME"
LINKED_BY_PARSED_PROJECT_NAME_UNIQUE_MATCH = "LINKED_BY_PARSED_PROJECT_NAME_UNIQUE_MATCH"
REVIEW_ONLY_ATTACHMENT_PARSE_MISSING = "REVIEW_ONLY_ATTACHMENT_PARSE_MISSING"
REVIEW_ONLY_ATTACHMENT_PROJECT_NAME_MISSING = "REVIEW_ONLY_ATTACHMENT_PROJECT_NAME_MISSING"
REVIEW_ONLY_ATTACHMENT_FIELD_OVEREXTRACTED = "REVIEW_ONLY_ATTACHMENT_FIELD_OVEREXTRACTED"
REVIEW_ONLY_ATTACHMENT_PARSED_PROJECT_NAME_UNMATCHED = "REVIEW_ONLY_ATTACHMENT_PARSED_PROJECT_NAME_UNMATCHED"
REVIEW_ONLY_AMBIGUOUS_PARSED_PROJECT_NAME_MATCH = "REVIEW_ONLY_AMBIGUOUS_PARSED_PROJECT_NAME_MATCH"

PROJECT_CANDIDATE_REVIEW_READY = "PROJECT_CANDIDATE_REVIEW_READY"
PROJECT_CANDIDATE_REVIEW_ONLY = "PROJECT_CANDIDATE_REVIEW_ONLY"

LINKED_STATES = frozenset(
    {
        LINKED_BY_V1_EXACT_NORMALIZED_FILENAME,
        LINKED_BY_PARSED_PROJECT_NAME_UNIQUE_MATCH,
    }
)
OVEREXTRACTED_FIELD_MARKERS = (
    "项目编号",
    "招标项目编号",
    "采购项目编号",
    "资金来源",
    "招标方式",
    "资格审查方式",
    "工程类型",
)


@dataclass(frozen=True)
class LegacyAttachmentLinkV2Item:
    object_key: str
    sha256: str
    content_kind: str
    content_type: str
    byte_size: int
    link_state: str
    linked_cluster_id_optional: str | None
    linked_refined_project_name_optional: str | None
    match_basis: str | None
    v1_link_state_optional: str | None
    attachment_parse_state_optional: str | None
    parsed_project_name_optional: str | None
    parsed_project_name_normalized_optional: str | None
    parsed_field_count: int
    parsed_fields_summary: list[dict[str, Any]] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LegacyProjectCandidateItem:
    candidate_id: str
    candidate_state: str
    cluster_id: str
    cluster_key: str
    refined_project_name_optional: str | None
    normalized_project_key_optional: str | None
    snapshot_ids: list[str]
    notice_stages: list[str]
    source_families: list[str]
    linked_attachment_object_keys: list[str]
    linked_attachment_count: int
    attachment_field_summaries: list[dict[str, Any]] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_legacy_project_candidates(
    *,
    database_url: str,
    target_backend: str = "postgresql",
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
    )
    session = DatabaseSession(settings=settings)
    try:
        cluster_record = _latest_record(session.list_records(LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE))
        qa_record = _latest_record(session.list_records(LEGACY_PROJECT_CLUSTER_QA_MANIFEST_OBJECT_TYPE))
        link_v1_record = _latest_record(session.list_records(LEGACY_CLUSTER_ATTACHMENT_LINK_MANIFEST_OBJECT_TYPE))
        attachment_parse_record = _latest_record(session.list_records(LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE))
        blocking_reasons = _blocking_reasons(
            cluster_record=cluster_record,
            qa_record=qa_record,
            link_v1_record=link_v1_record,
            attachment_parse_record=attachment_parse_record,
        )
        cluster_payload = dict(cluster_record.payload) if cluster_record else {}
        qa_payload = dict(qa_record.payload) if qa_record else {}
        link_v1_payload = dict(link_v1_record.payload) if link_v1_record else {}
        attachment_parse_payload = dict(attachment_parse_record.payload) if attachment_parse_record else {}
        link_v2_items = build_attachment_link_v2_items(
            clusters=list(cluster_payload.get("clusters") or []),
            qa_items=list(qa_payload.get("items") or []),
            link_v1_items=list(link_v1_payload.get("items") or []),
            attachment_parse_items=list(attachment_parse_payload.get("items") or []),
        )
        candidate_items = build_project_candidate_items(
            clusters=list(cluster_payload.get("clusters") or []),
            qa_items=list(qa_payload.get("items") or []),
            link_v2_items=link_v2_items,
        )
        link_v2_manifest = build_attachment_link_v2_manifest(
            items=link_v2_items,
            cluster_manifest_id=str(cluster_payload.get("manifest_id") or ""),
            qa_manifest_id=str(qa_payload.get("manifest_id") or ""),
            link_v1_manifest_id=str(link_v1_payload.get("manifest_id") or ""),
            attachment_parse_manifest_id=str(attachment_parse_payload.get("manifest_id") or ""),
            database_url=database_url,
            target_backend=target_backend,
            created_at=created,
        )
        candidate_manifest = build_project_candidate_manifest(
            items=candidate_items,
            cluster_manifest_id=str(cluster_payload.get("manifest_id") or ""),
            qa_manifest_id=str(qa_payload.get("manifest_id") or ""),
            link_v2_manifest_id=str(link_v2_manifest["manifest_id"]),
            database_url=database_url,
            target_backend=target_backend,
            created_at=created,
        )
        result = {
            "candidate_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "attachment_link_v2_manifest": link_v2_manifest,
            "project_candidate_manifest": candidate_manifest,
            "summary": {
                "attachment_link_v2": link_v2_manifest["summary"],
                "project_candidate": candidate_manifest["summary"],
            },
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
                session.upsert_record(_attachment_link_v2_manifest_record(link_v2_manifest, discovered_at=created))
                session.upsert_record(_project_candidate_manifest_record(candidate_manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_legacy_cluster_attachment_link_v2_manifest_count": 1,
                "upserted_legacy_project_candidate_manifest_count": 1,
                "evidence_snapshot_manifest_generation_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_pass_generation_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        return result
    finally:
        session.close()


def build_attachment_link_v2_items(
    *,
    clusters: Iterable[Mapping[str, Any]],
    qa_items: Iterable[Mapping[str, Any]],
    link_v1_items: Iterable[Mapping[str, Any]],
    attachment_parse_items: Iterable[Mapping[str, Any]],
) -> list[LegacyAttachmentLinkV2Item]:
    cluster_ids = {str(cluster.get("cluster_id") or "") for cluster in clusters if cluster.get("cluster_id")}
    qa_by_cluster_id = {
        str(item.get("cluster_id") or ""): dict(item)
        for item in qa_items
        if item.get("cluster_id")
    }
    clusters_by_refined_key = _clusters_by_refined_key(qa_by_cluster_id.values(), cluster_ids=cluster_ids)
    parse_by_object_key = {
        str(item.get("object_key") or ""): dict(item)
        for item in attachment_parse_items
        if item.get("object_key")
    }
    v1_by_object_key = {
        str(item.get("object_key") or ""): dict(item)
        for item in link_v1_items
        if item.get("object_key")
    }
    object_keys = sorted(set(parse_by_object_key) | set(v1_by_object_key))
    rows: list[LegacyAttachmentLinkV2Item] = []
    for object_key in object_keys:
        v1 = v1_by_object_key.get(object_key, {})
        parsed = parse_by_object_key.get(object_key, {})
        rows.append(
            _link_v2_item(
                object_key=object_key,
                v1=v1,
                parsed=parsed,
                qa_by_cluster_id=qa_by_cluster_id,
                clusters_by_refined_key=clusters_by_refined_key,
            )
        )
    return rows


def build_project_candidate_items(
    *,
    clusters: Iterable[Mapping[str, Any]],
    qa_items: Iterable[Mapping[str, Any]],
    link_v2_items: Iterable[LegacyAttachmentLinkV2Item],
) -> list[LegacyProjectCandidateItem]:
    cluster_by_id = {
        str(cluster.get("cluster_id") or ""): dict(cluster)
        for cluster in clusters
        if cluster.get("cluster_id")
    }
    qa_by_cluster_id = {
        str(item.get("cluster_id") or ""): dict(item)
        for item in qa_items
        if item.get("cluster_id")
    }
    links_by_cluster_id: dict[str, list[LegacyAttachmentLinkV2Item]] = {}
    for item in link_v2_items:
        if item.link_state in LINKED_STATES and item.linked_cluster_id_optional:
            links_by_cluster_id.setdefault(item.linked_cluster_id_optional, []).append(item)
    rows: list[LegacyProjectCandidateItem] = []
    for cluster_id, cluster in sorted(cluster_by_id.items()):
        qa = qa_by_cluster_id.get(cluster_id, {})
        linked = sorted(links_by_cluster_id.get(cluster_id, []), key=lambda row: row.object_key)
        refined_name = _text(qa.get("refined_project_name_optional")) or _text(cluster.get("display_project_name"))
        normalized_key = _text(qa.get("refined_cluster_key_optional")) or _text(cluster.get("cluster_key"))
        qa_state = _text(qa.get("qa_state"))
        candidate_state = (
            PROJECT_CANDIDATE_REVIEW_READY
            if refined_name and normalized_key and qa_state != PROJECT_NAME_OVEREXTRACTED_REVIEW
            else PROJECT_CANDIDATE_REVIEW_ONLY
        )
        reasons = ["legacy_project_candidate_review_required"]
        reasons.extend(str(reason) for reason in list(qa.get("name_quality_reasons") or []))
        if not linked:
            reasons.append("linked_attachment_missing_or_review_only")
        if candidate_state == PROJECT_CANDIDATE_REVIEW_ONLY:
            reasons.append("project_candidate_identity_review_only")
        rows.append(
            LegacyProjectCandidateItem(
                candidate_id=_candidate_id(cluster_id=cluster_id, normalized_key=normalized_key),
                candidate_state=candidate_state,
                cluster_id=cluster_id,
                cluster_key=str(cluster.get("cluster_key") or ""),
                refined_project_name_optional=refined_name,
                normalized_project_key_optional=normalized_key,
                snapshot_ids=[str(value) for value in list(cluster.get("snapshot_ids") or [])],
                notice_stages=[str(value) for value in list(cluster.get("notice_stages") or [])],
                source_families=[str(value) for value in list(cluster.get("source_families") or [])],
                linked_attachment_object_keys=[item.object_key for item in linked],
                linked_attachment_count=len(linked),
                attachment_field_summaries=_attachment_field_summaries(linked),
                review_reasons=list(dict.fromkeys(reason for reason in reasons if reason)),
                review_required=True,
                customer_visible_allowed=False,
                no_legal_conclusion=True,
            )
        )
    return rows


def build_attachment_link_v2_manifest(
    *,
    items: list[LegacyAttachmentLinkV2Item],
    cluster_manifest_id: str,
    qa_manifest_id: str,
    link_v1_manifest_id: str,
    attachment_parse_manifest_id: str,
    database_url: str,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "type": "attachment_link_v2",
            "ruleset_id": LEGACY_PROJECT_CANDIDATE_RULESET_ID,
            "items": [
                {
                    "object_key": item.object_key,
                    "link_state": item.link_state,
                    "linked_cluster_id": item.linked_cluster_id_optional,
                    "match_basis": item.match_basis,
                }
                for item in items
            ],
        }
    )
    manifest_id = f"LEGACY-ATTACHMENT-LINK-V2-{fingerprint[:16]}"
    payload = {
        "manifest_version": LEGACY_PROJECT_CANDIDATE_VERSION,
        "ruleset_id": LEGACY_PROJECT_CANDIDATE_RULESET_ID,
        "manifest_id": manifest_id,
        "legacy_project_cluster_manifest_id": cluster_manifest_id,
        "legacy_project_cluster_qa_manifest_id": qa_manifest_id,
        "legacy_cluster_attachment_link_manifest_id": link_v1_manifest_id,
        "legacy_attachment_parse_manifest_id": attachment_parse_manifest_id,
        "created_at": created_at,
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "summary": _link_v2_summary(items),
        "items": [item.as_payload() for item in items],
        "sample_items": [item.as_payload() for item in sorted(items, key=lambda row: row.object_key)[:50]],
        "safety": _safety(),
        "attachment_link_v2_fingerprint": fingerprint,
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def build_project_candidate_manifest(
    *,
    items: list[LegacyProjectCandidateItem],
    cluster_manifest_id: str,
    qa_manifest_id: str,
    link_v2_manifest_id: str,
    database_url: str,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "type": "project_candidate",
            "ruleset_id": LEGACY_PROJECT_CANDIDATE_RULESET_ID,
            "items": [
                {
                    "candidate_id": item.candidate_id,
                    "cluster_id": item.cluster_id,
                    "candidate_state": item.candidate_state,
                    "linked_attachment_object_keys": item.linked_attachment_object_keys,
                }
                for item in items
            ],
        }
    )
    manifest_id = f"LEGACY-PROJECT-CANDIDATE-{fingerprint[:16]}"
    payload = {
        "manifest_version": LEGACY_PROJECT_CANDIDATE_VERSION,
        "ruleset_id": LEGACY_PROJECT_CANDIDATE_RULESET_ID,
        "manifest_id": manifest_id,
        "legacy_project_cluster_manifest_id": cluster_manifest_id,
        "legacy_project_cluster_qa_manifest_id": qa_manifest_id,
        "legacy_cluster_attachment_link_v2_manifest_id": link_v2_manifest_id,
        "created_at": created_at,
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "summary": _candidate_summary(items),
        "items": [item.as_payload() for item in items],
        "sample_items": [item.as_payload() for item in sorted(items, key=lambda row: row.candidate_id)[:50]],
        "safety": _safety(),
        "project_candidate_fingerprint": fingerprint,
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _link_v2_item(
    *,
    object_key: str,
    v1: Mapping[str, Any],
    parsed: Mapping[str, Any],
    qa_by_cluster_id: Mapping[str, Mapping[str, Any]],
    clusters_by_refined_key: Mapping[str, list[Mapping[str, Any]]],
) -> LegacyAttachmentLinkV2Item:
    content_kind = _text(parsed.get("content_kind")) or _text(v1.get("content_kind")) or ""
    content_type = _text(parsed.get("content_type")) or _text(v1.get("content_type")) or "application/octet-stream"
    byte_size = _int(parsed.get("byte_size") if parsed else v1.get("byte_size"))
    sha256 = _text(parsed.get("sha256")) or _text(v1.get("sha256")) or ""
    v1_state = _text(v1.get("link_state"))
    parse_state = _text(parsed.get("parse_state"))
    parsed_fields = list(parsed.get("parsed_fields_summary") or [])
    parsed_field_count = _int(parsed.get("parsed_field_count"))

    if v1_state == LINKED_BY_EXACT_NORMALIZED_FILENAME and _text(v1.get("linked_cluster_id_optional")):
        cluster_id = _text(v1.get("linked_cluster_id_optional"))
        qa = qa_by_cluster_id.get(cluster_id or "", {})
        return LegacyAttachmentLinkV2Item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            link_state=LINKED_BY_V1_EXACT_NORMALIZED_FILENAME,
            linked_cluster_id_optional=cluster_id,
            linked_refined_project_name_optional=_text(qa.get("refined_project_name_optional"))
            or _text(v1.get("linked_refined_project_name_optional")),
            match_basis="v1_run_artifact_path_segment_exact_normalized_match",
            v1_link_state_optional=v1_state,
            attachment_parse_state_optional=parse_state,
            parsed_project_name_optional=_project_name_from_fields(parsed_fields),
            parsed_project_name_normalized_optional=normalize_project_name(_project_name_from_fields(parsed_fields)),
            parsed_field_count=parsed_field_count,
            parsed_fields_summary=_safe_field_summary(parsed_fields),
            review_reasons=_reasons(v1.get("review_reasons"), "legacy_attachment_link_v2_review_required"),
        )

    if not parsed:
        return _review_link_v2_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            link_state=REVIEW_ONLY_ATTACHMENT_PARSE_MISSING,
            v1_link_state_optional=v1_state,
            attachment_parse_state_optional=None,
            parsed_fields_summary=[],
            parsed_field_count=0,
            parsed_project_name=None,
            parsed_project_key=None,
            review_reasons=["legacy_attachment_parse_item_missing"],
        )

    project_name = _project_name_from_fields(parsed_fields)
    if not project_name:
        return _review_link_v2_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            link_state=REVIEW_ONLY_ATTACHMENT_PROJECT_NAME_MISSING,
            v1_link_state_optional=v1_state,
            attachment_parse_state_optional=parse_state,
            parsed_fields_summary=parsed_fields,
            parsed_field_count=parsed_field_count,
            parsed_project_name=None,
            parsed_project_key=None,
            review_reasons=["attachment_project_name_field_missing"],
        )
    if _is_overextracted(project_name):
        return _review_link_v2_item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            link_state=REVIEW_ONLY_ATTACHMENT_FIELD_OVEREXTRACTED,
            v1_link_state_optional=v1_state,
            attachment_parse_state_optional=parse_state,
            parsed_fields_summary=parsed_fields,
            parsed_field_count=parsed_field_count,
            parsed_project_name=project_name,
            parsed_project_key=normalize_project_name(project_name),
            review_reasons=["attachment_project_name_field_overextracted"],
        )
    project_key = normalize_project_name(project_name)
    matched_clusters = list(clusters_by_refined_key.get(project_key or "") or [])
    if len(matched_clusters) == 1:
        cluster = matched_clusters[0]
        return LegacyAttachmentLinkV2Item(
            object_key=object_key,
            sha256=sha256,
            content_kind=content_kind,
            content_type=content_type,
            byte_size=byte_size,
            link_state=LINKED_BY_PARSED_PROJECT_NAME_UNIQUE_MATCH,
            linked_cluster_id_optional=_text(cluster.get("cluster_id")),
            linked_refined_project_name_optional=_text(cluster.get("refined_project_name_optional")),
            match_basis="attachment_parsed_project_name_unique_normalized_match",
            v1_link_state_optional=v1_state,
            attachment_parse_state_optional=parse_state,
            parsed_project_name_optional=project_name,
            parsed_project_name_normalized_optional=project_key,
            parsed_field_count=parsed_field_count,
            parsed_fields_summary=_safe_field_summary(parsed_fields),
            review_reasons=_reasons(parsed.get("review_reasons"), "legacy_attachment_link_v2_review_required"),
        )
    link_state = (
        REVIEW_ONLY_AMBIGUOUS_PARSED_PROJECT_NAME_MATCH
        if len(matched_clusters) > 1
        else REVIEW_ONLY_ATTACHMENT_PARSED_PROJECT_NAME_UNMATCHED
    )
    return _review_link_v2_item(
        object_key=object_key,
        sha256=sha256,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        link_state=link_state,
        v1_link_state_optional=v1_state,
        attachment_parse_state_optional=parse_state,
        parsed_fields_summary=parsed_fields,
        parsed_field_count=parsed_field_count,
        parsed_project_name=project_name,
        parsed_project_key=project_key,
        review_reasons=[
            "multiple_refined_cluster_keys_matched_attachment_project_name"
            if len(matched_clusters) > 1
            else "attachment_parsed_project_name_did_not_match_cluster_qa_key"
        ],
    )


def _review_link_v2_item(
    *,
    object_key: str,
    sha256: str,
    content_kind: str,
    content_type: str,
    byte_size: int,
    link_state: str,
    v1_link_state_optional: str | None,
    attachment_parse_state_optional: str | None,
    parsed_fields_summary: list[Any],
    parsed_field_count: int,
    parsed_project_name: str | None,
    parsed_project_key: str | None,
    review_reasons: list[str],
) -> LegacyAttachmentLinkV2Item:
    return LegacyAttachmentLinkV2Item(
        object_key=object_key,
        sha256=sha256,
        content_kind=content_kind,
        content_type=content_type,
        byte_size=byte_size,
        link_state=link_state,
        linked_cluster_id_optional=None,
        linked_refined_project_name_optional=None,
        match_basis=None,
        v1_link_state_optional=v1_link_state_optional,
        attachment_parse_state_optional=attachment_parse_state_optional,
        parsed_project_name_optional=parsed_project_name,
        parsed_project_name_normalized_optional=parsed_project_key,
        parsed_field_count=parsed_field_count,
        parsed_fields_summary=_safe_field_summary(parsed_fields_summary),
        review_reasons=_reasons(review_reasons, "legacy_attachment_link_v2_review_required"),
    )


def _clusters_by_refined_key(
    qa_items: Iterable[Mapping[str, Any]],
    *,
    cluster_ids: set[str],
) -> dict[str, list[Mapping[str, Any]]]:
    rows: dict[str, list[Mapping[str, Any]]] = {}
    for item in qa_items:
        cluster_id = _text(item.get("cluster_id"))
        key = _text(item.get("refined_cluster_key_optional"))
        if not cluster_id or cluster_id not in cluster_ids or not key:
            continue
        if _text(item.get("qa_state")) == PROJECT_NAME_OVEREXTRACTED_REVIEW:
            continue
        rows.setdefault(key, []).append(dict(item))
    return rows


def _project_name_from_fields(fields: Iterable[Any]) -> str | None:
    candidates = []
    for field in fields:
        payload = dict(field) if isinstance(field, Mapping) else {}
        if str(payload.get("field_name") or "") != "project_name":
            continue
        value = _clean_text(payload.get("field_value_optional"))
        if value:
            candidates.append(value)
    if not candidates:
        return None
    return sorted(candidates, key=lambda value: (int(_is_overextracted(value)), len(value), value))[0]


def _attachment_field_summaries(linked: Iterable[LegacyAttachmentLinkV2Item]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in linked:
        rows.append(
            {
                "object_key": item.object_key,
                "link_state": item.link_state,
                "match_basis": item.match_basis,
                "parsed_field_count": item.parsed_field_count,
                "parsed_fields_summary": _safe_field_summary(item.parsed_fields_summary),
            }
        )
    return rows[:50]


def _safe_field_summary(fields: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in list(fields)[:50]:
        payload = dict(field) if isinstance(field, Mapping) else {}
        rows.append(
            {
                "field_name": _text(payload.get("field_name")),
                "field_value_optional": _limit_text(_text(payload.get("field_value_optional"))),
                "source_slice_sha256": _text(payload.get("source_slice_sha256")),
                "locator_type": _text(payload.get("locator_type")),
                "confidence": payload.get("confidence"),
                "review_required": bool(payload.get("review_required")),
                "parse_warnings": list(payload.get("parse_warnings") or []),
            }
        )
    return rows


def _attachment_link_v2_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "legacy_project_cluster_manifest_id": str(manifest["legacy_project_cluster_manifest_id"]),
            "legacy_project_cluster_qa_manifest_id": str(manifest["legacy_project_cluster_qa_manifest_id"]),
            "legacy_cluster_attachment_link_manifest_id": str(manifest["legacy_cluster_attachment_link_manifest_id"]),
            "legacy_attachment_parse_manifest_id": str(manifest["legacy_attachment_parse_manifest_id"]),
        },
        decision_states={"legacy_cluster_attachment_link_v2_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_CLUSTER_ATTACHMENT_LINK_V2_READY",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state=_writeback_state(),
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _project_candidate_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "legacy_project_cluster_manifest_id": str(manifest["legacy_project_cluster_manifest_id"]),
            "legacy_project_cluster_qa_manifest_id": str(manifest["legacy_project_cluster_qa_manifest_id"]),
            "legacy_cluster_attachment_link_v2_manifest_id": str(manifest["legacy_cluster_attachment_link_v2_manifest_id"]),
        },
        decision_states={"legacy_project_candidate_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_PROJECT_CANDIDATE_READY",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state=_writeback_state(),
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _link_v2_summary(items: list[LegacyAttachmentLinkV2Item]) -> dict[str, Any]:
    return {
        "attachment_candidate_count": len(items),
        "linked_attachment_count": sum(1 for item in items if item.link_state in LINKED_STATES),
        "review_only_attachment_count": sum(1 for item in items if item.link_state not in LINKED_STATES),
        "link_state_counts": _counts(item.link_state for item in items),
        "content_kind_counts": _counts(item.content_kind for item in items),
        "review_required_count": len(items),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
    }


def _candidate_summary(items: list[LegacyProjectCandidateItem]) -> dict[str, Any]:
    return {
        "project_candidate_count": len(items),
        "candidate_state_counts": _counts(item.candidate_state for item in items),
        "candidate_with_linked_attachment_count": sum(1 for item in items if item.linked_attachment_count > 0),
        "linked_attachment_count": sum(item.linked_attachment_count for item in items),
        "review_required_count": len(items),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_pass_generation_enabled": False,
        "large_object_blob_database_import_enabled": False,
    }


def _blocking_reasons(
    *,
    cluster_record: PersistedRecord | None,
    qa_record: PersistedRecord | None,
    link_v1_record: PersistedRecord | None,
    attachment_parse_record: PersistedRecord | None,
) -> list[str]:
    reasons: list[str] = []
    if cluster_record is None:
        reasons.append("legacy_project_cluster_manifest_missing")
    if qa_record is None:
        reasons.append("legacy_project_cluster_qa_manifest_missing")
    if link_v1_record is None:
        reasons.append("legacy_cluster_attachment_link_manifest_missing")
    if attachment_parse_record is None:
        reasons.append("legacy_attachment_parse_manifest_missing")
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


def _candidate_id(*, cluster_id: str, normalized_key: str | None) -> str:
    digest = hashlib.sha256(f"{cluster_id}|{normalized_key or ''}".encode("utf-8")).hexdigest()
    return f"LEGACY-PROJECT-CANDIDATE-{digest[:16]}"


def _is_overextracted(value: Any) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    if len(text) > 120:
        return True
    return any(marker in text for marker in OVEREXTRACTED_FIELD_MARKERS)


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
        "fuzzy_project_merge_enabled": False,
        "pdf_ocr_bulk_enablement": False,
    }


def _writeback_state() -> dict[str, Any]:
    return {
        "evidence_snapshot_manifest_generation_enabled": False,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_pass_generation_enabled": False,
        "large_object_blob_database_import_enabled": False,
    }


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


def _reasons(*groups: Any) -> list[str]:
    reasons: list[str] = []
    for group in groups:
        if group in (None, "", [], {}):
            continue
        if isinstance(group, str):
            reasons.append(group)
            continue
        if isinstance(group, Iterable):
            reasons.extend(str(value) for value in group if value)
            continue
        reasons.append(str(group))
    reasons.append("legacy_customer_visibility_not_allowed")
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _clean_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    cleaned = " ".join(str(value).split()).strip()
    return cleaned or None


def _limit_text(value: str | None, *, limit: int = 500) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:limit] + "..."


def _text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return str(value)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build legacy attachment link v2 and project candidate manifests.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_legacy_project_candidates(
        database_url=args.database_url,
        target_backend=args.target_backend,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"legacy project candidates {result['candidate_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE",
    "LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE",
    "LINKED_BY_PARSED_PROJECT_NAME_UNIQUE_MATCH",
    "LINKED_BY_V1_EXACT_NORMALIZED_FILENAME",
    "PROJECT_CANDIDATE_REVIEW_ONLY",
    "PROJECT_CANDIDATE_REVIEW_READY",
    "REVIEW_ONLY_AMBIGUOUS_PARSED_PROJECT_NAME_MATCH",
    "REVIEW_ONLY_ATTACHMENT_FIELD_OVEREXTRACTED",
    "REVIEW_ONLY_ATTACHMENT_PARSE_MISSING",
    "REVIEW_ONLY_ATTACHMENT_PARSED_PROJECT_NAME_UNMATCHED",
    "REVIEW_ONLY_ATTACHMENT_PROJECT_NAME_MISSING",
    "build_attachment_link_v2_items",
    "build_legacy_project_candidates",
    "build_project_candidate_items",
]
