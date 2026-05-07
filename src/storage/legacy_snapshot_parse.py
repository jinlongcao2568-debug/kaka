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
from stage3_parsing.service import Stage3Service
from storage.db import DatabaseSession, PersistedRecord
from storage.object_storage import EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE
from storage.repositories.object_storage_repo import ObjectStorageRepository


LEGACY_SNAPSHOT_PARSE_MANIFEST_OBJECT_TYPE = "legacy_snapshot_parse_manifest"
LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE = "legacy_project_cluster_manifest"
LEGACY_SNAPSHOT_PARSE_VERSION = 1
LEGACY_SNAPSHOT_PARSE_RULESET_ID = "legacy-snapshot-parse-cluster-v1"
LEGACY_PUBLIC_HTML_SNAPSHOT_KIND = "legacy_public_html_snapshot"

NON_PROJECT_PLATFORM_PAGE = "NON_PROJECT_PLATFORM_PAGE"
PROJECT_CLUSTERED = "PROJECT_CLUSTERED"
PROJECT_REVIEW_ONLY = "PROJECT_REVIEW_ONLY"

PLATFORM_TITLES = frozenset(
    {
        "广州交易集团有限公司",
        "广东省公共资源交易平台",
        "江苏省公共资源交易网",
        "北京市公共资源交易服务平台",
        "中国政府采购网",
    }
)

NOTICE_SUFFIX_PATTERNS = (
    "中标候选人公示",
    "中标候选人公告",
    "中标结果公告",
    "中标结果公示",
    "中标公告",
    "成交结果公告",
    "成交公告",
    "评标结果公示",
    "评标报告",
    "招标公告",
    "采购公告",
    "竞争性谈判公告",
    "磋商公告",
    "资格预审公告",
    "更正公告",
    "澄清公告",
)

NOISE_SUFFIX_RE = re.compile(r"[-_—–\s（）()【】\\[\\]]+$")
SPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[\s　:：;；,，。.!！?？、/\\|·•（）()【】\\[\\]{}《》<>\"'“”‘’_-]+")


@dataclass(frozen=True)
class LegacySnapshotParseItem:
    snapshot_id: str
    object_key: str | None
    source_family: str | None
    title: str | None
    project_name_candidate: str | None
    normalized_project_name: str | None
    notice_stage: str
    parse_state: str
    attachment_type: str
    parsed_field_count: int
    parsed_fields_summary: list[dict[str, Any]]
    cluster_eligibility: str
    cluster_key_optional: str | None
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True
    failure_reasons: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LegacyProjectCluster:
    cluster_id: str
    cluster_key: str
    normalized_project_name: str
    display_project_name: str
    snapshot_ids: list[str]
    notice_stages: list[str]
    source_families: list[str]
    snapshot_count: int
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True
    cluster_state: str = PROJECT_CLUSTERED

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def build_legacy_snapshot_parse(
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
        repository = ObjectStorageRepository(session=session, settings=settings)
        snapshot_records = _legacy_html_snapshot_records(session.list_records(EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE))
        if limit is not None and limit >= 0:
            snapshot_records = snapshot_records[:limit]
        blocking_reasons: list[str] = []
        if not snapshot_records:
            blocking_reasons.append("legacy_public_html_snapshot_missing")
        parse_items = parse_legacy_snapshots(snapshot_records=snapshot_records, repository=repository)
        clusters = build_project_clusters(parse_items)
        parse_manifest = build_parse_manifest(
            items=parse_items,
            clusters=clusters,
            database_url=database_url,
            target_backend=target_backend,
            object_storage_path=object_root,
            created_at=created,
        )
        cluster_manifest = build_cluster_manifest(
            items=parse_items,
            clusters=clusters,
            database_url=database_url,
            target_backend=target_backend,
            object_storage_path=object_root,
            created_at=created,
            parse_manifest_id=str(parse_manifest["manifest_id"]),
        )
        result = {
            "parse_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "parse_manifest": parse_manifest,
            "cluster_manifest": cluster_manifest,
            "summary": {
                "parse": parse_manifest["summary"],
                "cluster": cluster_manifest["summary"],
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
                session.upsert_record(_parse_manifest_record(parse_manifest, discovered_at=created))
                session.upsert_record(_cluster_manifest_record(cluster_manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_legacy_snapshot_parse_manifest_count": 1,
                "upserted_legacy_project_cluster_manifest_count": 1,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_pass_generation_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        return result
    finally:
        session.close()


def parse_legacy_snapshots(
    *,
    snapshot_records: Iterable[PersistedRecord],
    repository: ObjectStorageRepository,
) -> list[LegacySnapshotParseItem]:
    service = Stage3Service()
    items: list[LegacySnapshotParseItem] = []
    for record in sorted(snapshot_records, key=lambda row: row.record_id):
        manifest = dict(record.payload)
        snapshot_id = record.record_id
        raw_metadata = dict(manifest.get("raw_snapshot_metadata") or {})
        title = _text(raw_metadata.get("title_optional"))
        source_family = _text(manifest.get("source_family_optional"))
        object_key = _text(manifest.get("object_key"))
        failure_reasons: list[str] = []
        try:
            carrier = dict(service.parse_raw_snapshot(snapshot_id, repository=repository))
        except Exception as exc:
            failure_reasons.append(f"stage3_parse_failed:{exc.__class__.__name__}")
            carrier = {
                "parse_state": "REVIEW_REQUIRED",
                "attachment_type": "UNKNOWN_ATTACHMENT",
                "parsed_fields": [],
                "review_required": True,
            }
        fields = list(carrier.get("parsed_fields") or [])
        field_summary = _field_summary(fields)
        field_values = _field_values(field_summary)
        resolved_title = (
            field_values.get("announcement_title")
            or title
            or field_values.get("project_name")
        )
        project_candidate = _project_name_candidate(field_values, resolved_title)
        notice_stage = infer_notice_stage(f"{resolved_title or ''} {project_candidate or ''}")
        normalized_project = normalize_project_name(project_candidate)
        eligibility, cluster_key, review_reasons = _cluster_decision(
            title=resolved_title,
            project_candidate=project_candidate,
            normalized_project=normalized_project,
            fields=field_values,
        )
        parse_state = str(carrier.get("parse_state") or "REVIEW_REQUIRED")
        review_reasons.extend(_parse_review_reasons(carrier, fields, eligibility))
        items.append(
            LegacySnapshotParseItem(
                snapshot_id=snapshot_id,
                object_key=object_key,
                source_family=source_family,
                title=resolved_title,
                project_name_candidate=project_candidate,
                normalized_project_name=normalized_project,
                notice_stage=notice_stage,
                parse_state=parse_state,
                attachment_type=str(carrier.get("attachment_type") or ""),
                parsed_field_count=len(fields),
                parsed_fields_summary=field_summary,
                cluster_eligibility=eligibility,
                cluster_key_optional=cluster_key,
                failure_reasons=failure_reasons,
                review_reasons=list(dict.fromkeys(review_reasons)),
            )
        )
    return items


def build_project_clusters(items: Iterable[LegacySnapshotParseItem]) -> list[LegacyProjectCluster]:
    grouped: dict[str, list[LegacySnapshotParseItem]] = {}
    for item in items:
        if item.cluster_eligibility != PROJECT_CLUSTERED or not item.cluster_key_optional:
            continue
        grouped.setdefault(item.cluster_key_optional, []).append(item)
    clusters: list[LegacyProjectCluster] = []
    for cluster_key, members in sorted(grouped.items()):
        normalized_name = members[0].normalized_project_name or cluster_key
        display_name = _display_project_name(members, normalized_name)
        cluster_id = f"LEGACY-PROJECT-CLUSTER-{hashlib.sha256(cluster_key.encode('utf-8')).hexdigest()[:16]}"
        clusters.append(
            LegacyProjectCluster(
                cluster_id=cluster_id,
                cluster_key=cluster_key,
                normalized_project_name=normalized_name,
                display_project_name=display_name,
                snapshot_ids=[item.snapshot_id for item in sorted(members, key=lambda row: row.snapshot_id)],
                notice_stages=sorted({item.notice_stage for item in members if item.notice_stage}),
                source_families=sorted({item.source_family or "unknown" for item in members}),
                snapshot_count=len(members),
            )
        )
    return clusters


def build_parse_manifest(
    *,
    items: list[LegacySnapshotParseItem],
    clusters: list[LegacyProjectCluster],
    database_url: str,
    target_backend: str,
    object_storage_path: Path,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "type": "parse",
            "ruleset_id": LEGACY_SNAPSHOT_PARSE_RULESET_ID,
            "items": [
                {
                    "snapshot_id": item.snapshot_id,
                    "cluster_key": item.cluster_key_optional,
                    "parse_state": item.parse_state,
                    "notice_stage": item.notice_stage,
                }
                for item in items
            ],
        }
    )
    manifest_id = f"LEGACY-SNAPSHOT-PARSE-{fingerprint[:16]}"
    payload = {
        "manifest_version": LEGACY_SNAPSHOT_PARSE_VERSION,
        "ruleset_id": LEGACY_SNAPSHOT_PARSE_RULESET_ID,
        "manifest_id": manifest_id,
        "parse_id": manifest_id,
        "created_at": created_at,
        "object_storage_path": str(object_storage_path),
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "summary": _parse_summary(items, clusters),
        "items": [item.as_payload() for item in items],
        "sample_items": [item.as_payload() for item in sorted(items, key=lambda row: row.snapshot_id)[:50]],
        "safety": _safety(),
        "parse_fingerprint": fingerprint,
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def build_cluster_manifest(
    *,
    items: list[LegacySnapshotParseItem],
    clusters: list[LegacyProjectCluster],
    database_url: str,
    target_backend: str,
    object_storage_path: Path,
    created_at: str,
    parse_manifest_id: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "type": "cluster",
            "ruleset_id": LEGACY_SNAPSHOT_PARSE_RULESET_ID,
            "clusters": [
                {
                    "cluster_key": cluster.cluster_key,
                    "snapshot_ids": cluster.snapshot_ids,
                }
                for cluster in clusters
            ],
        }
    )
    manifest_id = f"LEGACY-PROJECT-CLUSTER-{fingerprint[:16]}"
    non_project_items = [
        item.as_payload()
        for item in items
        if item.cluster_eligibility != PROJECT_CLUSTERED
    ]
    payload = {
        "manifest_version": LEGACY_SNAPSHOT_PARSE_VERSION,
        "ruleset_id": LEGACY_SNAPSHOT_PARSE_RULESET_ID,
        "manifest_id": manifest_id,
        "cluster_manifest_id": manifest_id,
        "legacy_snapshot_parse_manifest_id": parse_manifest_id,
        "created_at": created_at,
        "object_storage_path": str(object_storage_path),
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "summary": _cluster_summary(items, clusters),
        "clusters": [cluster.as_payload() for cluster in clusters],
        "non_project_or_review_items": non_project_items,
        "sample_clusters": [cluster.as_payload() for cluster in sorted(clusters, key=lambda row: -row.snapshot_count)[:50]],
        "safety": _safety(),
        "cluster_fingerprint": fingerprint,
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def infer_notice_stage(text: str) -> str:
    value = str(text or "")
    if any(token in value for token in ("中标候选人", "成交候选人", "候选人公示")):
        return "candidate_notice"
    if any(token in value for token in ("中标结果", "中标公告", "成交结果", "成交公告")):
        return "award_result"
    if any(token in value for token in ("评标报告", "评标结果")):
        return "bid_evaluation_report"
    if any(token in value for token in ("招标公告", "采购公告", "竞争性谈判公告", "磋商公告", "资格预审公告")):
        return "tender_notice"
    if any(token in value for token in ("更正公告", "澄清公告")):
        return "correction_notice"
    return "unknown_notice_stage"


def normalize_project_name(value: str | None) -> str | None:
    text = _clean_title(value)
    if not text:
        return None
    previous = None
    while previous != text:
        previous = text
        for suffix in NOTICE_SUFFIX_PATTERNS:
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                text = NOISE_SUFFIX_RE.sub("", text).strip()
    normalized = PUNCT_RE.sub("", text).lower()
    return normalized or None


def _project_name_candidate(field_values: Mapping[str, str], title: str | None) -> str | None:
    project_name = _clean_title(field_values.get("project_name"))
    if project_name:
        return project_name
    return _clean_title(title)


def _cluster_decision(
    *,
    title: str | None,
    project_candidate: str | None,
    normalized_project: str | None,
    fields: Mapping[str, str],
) -> tuple[str, str | None, list[str]]:
    clean_title = _clean_title(title)
    if clean_title in PLATFORM_TITLES:
        return NON_PROJECT_PLATFORM_PAGE, None, ["platform_or_list_page_title"]
    if not normalized_project:
        return PROJECT_REVIEW_ONLY, None, ["normalized_project_name_missing"]
    if len(normalized_project) < 6:
        return PROJECT_REVIEW_ONLY, None, ["normalized_project_name_too_short"]
    if not (fields.get("project_name") or clean_title):
        return PROJECT_REVIEW_ONLY, None, ["project_name_and_title_missing"]
    return PROJECT_CLUSTERED, normalized_project, ["review_required_legacy_cluster_exact_key_only"]


def _parse_review_reasons(carrier: Mapping[str, Any], fields: list[Mapping[str, Any]], eligibility: str) -> list[str]:
    reasons = ["legacy_snapshot_parse_review_required"]
    if bool(carrier.get("review_required")):
        reasons.append("stage3_parser_review_required")
    if not fields:
        reasons.append("stage3_parsed_fields_missing")
    if eligibility != PROJECT_CLUSTERED:
        reasons.append(f"cluster_eligibility:{eligibility}")
    for code in list(carrier.get("parse_error_taxonomy") or []):
        reasons.append(f"parse_error:{code}")
    return reasons


def _field_summary(fields: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in fields:
        rows.append(
            {
                "field_name": field.get("field_name"),
                "field_value_optional": field.get("field_value_optional"),
                "source_slice_sha256": field.get("source_slice_sha256"),
                "confidence": field.get("confidence"),
                "review_required": bool(field.get("review_required")),
                "parse_warnings": list(field.get("parse_warnings") or []),
                "locator_type": dict(field.get("locator") or {}).get("type"),
            }
        )
    return rows


def _field_values(fields: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fields:
        name = str(field.get("field_name") or "")
        value = _clean_title(field.get("field_value_optional"))
        if name and value and name not in values:
            values[name] = value
    return values


def _display_project_name(items: list[LegacySnapshotParseItem], normalized_name: str) -> str:
    candidates = [
        item.project_name_candidate
        for item in items
        if item.project_name_candidate and normalize_project_name(item.project_name_candidate) == normalized_name
    ]
    if candidates:
        return sorted(candidates, key=lambda value: (len(value), value))[0]
    return normalized_name


def _legacy_html_snapshot_records(records: list[PersistedRecord]) -> list[PersistedRecord]:
    return [
        record
        for record in records
        if str(record.payload.get("snapshot_kind") or "") == LEGACY_PUBLIC_HTML_SNAPSHOT_KIND
    ]


def _parse_summary(items: list[LegacySnapshotParseItem], clusters: list[LegacyProjectCluster]) -> dict[str, Any]:
    return {
        "snapshot_count": len(items),
        "cluster_count": len(clusters),
        "non_project_or_review_count": sum(1 for item in items if item.cluster_eligibility != PROJECT_CLUSTERED),
        "parse_state_counts": _counts(item.parse_state for item in items),
        "notice_stage_counts": _counts(item.notice_stage for item in items),
        "cluster_eligibility_counts": _counts(item.cluster_eligibility for item in items),
        "source_family_counts": _counts(item.source_family or "unknown" for item in items),
        "review_required_count": sum(1 for item in items if item.review_required),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
    }


def _cluster_summary(items: list[LegacySnapshotParseItem], clusters: list[LegacyProjectCluster]) -> dict[str, Any]:
    clustered_snapshot_ids = {snapshot_id for cluster in clusters for snapshot_id in cluster.snapshot_ids}
    return {
        "cluster_count": len(clusters),
        "clustered_snapshot_count": len(clustered_snapshot_ids),
        "input_snapshot_count": len(items),
        "non_project_or_review_count": len(items) - len(clustered_snapshot_ids),
        "multi_snapshot_cluster_count": sum(1 for cluster in clusters if cluster.snapshot_count > 1),
        "notice_stage_counts": _counts(stage for cluster in clusters for stage in cluster.notice_stages),
        "review_required_count": len(clusters),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_pass_generation_enabled": False,
    }


def _parse_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_SNAPSHOT_PARSE_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={"object_storage_path": str(manifest["object_storage_path"])},
        decision_states={"legacy_snapshot_parse_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_SNAPSHOT_PARSE_READY",
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


def _cluster_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={"legacy_snapshot_parse_manifest_id": str(manifest["legacy_snapshot_parse_manifest_id"])},
        decision_states={"legacy_project_cluster_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LEGACY_PROJECT_CLUSTER_READY",
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


def _safety() -> dict[str, Any]:
    return {
        "external_service_connection_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_pass_generation_enabled": False,
        "large_object_blob_database_import_enabled": False,
        "pdf_ocr_enabled": False,
        "fuzzy_project_merge_enabled": False,
    }


def _clean_title(value: Any) -> str | None:
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


def _text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return str(value)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse legacy HTML snapshots and build project clusters.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--object-storage-path", default=str(default_object_storage_path()))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_legacy_snapshot_parse(
        database_url=args.database_url,
        target_backend=args.target_backend,
        object_storage_path=args.object_storage_path,
        execute=args.execute,
        limit=args.limit,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"legacy snapshot parse {result['parse_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE",
    "LEGACY_SNAPSHOT_PARSE_MANIFEST_OBJECT_TYPE",
    "NON_PROJECT_PLATFORM_PAGE",
    "PROJECT_CLUSTERED",
    "PROJECT_REVIEW_ONLY",
    "build_legacy_snapshot_parse",
    "build_project_clusters",
    "infer_notice_stage",
    "normalize_project_name",
    "parse_legacy_snapshots",
]
