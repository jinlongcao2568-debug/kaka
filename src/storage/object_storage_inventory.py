from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.object_storage import (
    LOCAL_OBJECT_STORAGE_BACKEND,
    OBJECT_STORAGE_OBJECT_TYPE,
)


OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE = "object_storage_inventory_manifest"
INVENTORY_MANIFEST_VERSION = 1
UNREFERENCED_LEGACY_OBJECT = "UNREFERENCED_LEGACY_OBJECT"
REFERENCED_BY_RECORD = "REFERENCED_BY_RECORD"


@dataclass(frozen=True)
class InventoryObject:
    object_key: str
    relative_path: str
    content_type: str
    content_kind: str
    byte_size: int
    sha256: str
    last_modified_at: str
    hash_path_valid: bool
    storage_backend: str
    orphan_state: str
    referenced_by_record_refs: list[dict[str, str]]

    def as_payload(self, *, discovered_at: str) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "created_at": discovered_at,
                "discovered_at": discovered_at,
                "inventory_source": "legacy_discovered_object_storage_scan",
                "external_service_connection_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        )
        return payload


def default_inventory_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def build_object_storage_inventory(
    *,
    object_storage_path: str | Path | None = None,
    database_url: str,
    target_backend: str = "postgresql",
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    root = Path(object_storage_path) if object_storage_path is not None else default_inventory_object_storage_path()
    created = created_at or utc_now_iso()
    target_settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(root),
    )
    session = DatabaseSession(settings=target_settings)
    try:
        existing_records = session.list_all_records(
            exclude_object_types=(
                OBJECT_STORAGE_OBJECT_TYPE,
                OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE,
            )
        )
        objects = scan_object_storage(root=root, existing_records=existing_records)
        manifest = build_inventory_manifest(
            root=root,
            objects=objects,
            database_url=database_url,
            target_backend=target_backend,
            created_at=created,
        )
        result = {
            "inventory_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": bool(manifest["object_storage_root_exists"]),
            "blocking_reasons": [] if manifest["object_storage_root_exists"] else ["object_storage_root_missing"],
            "manifest": manifest,
            "summary": manifest["summary"],
            "execution": {
                "executed": False,
                "target_mutation_enabled": False,
                "large_object_blob_database_import_enabled": False,
            },
        }
        if execute:
            if not result["safe_to_execute"]:
                raise RuntimeError("object storage inventory is not safe to execute: object_storage_root_missing")
            with session.bulk_write():
                for item in objects:
                    session.upsert_record(_object_record(item, discovered_at=created))
                session.upsert_record(_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "large_object_blob_database_import_enabled": False,
                "upserted_object_storage_object_count": len(objects),
                "upserted_inventory_manifest_count": 1,
            }
        return result
    finally:
        session.close()


def scan_object_storage(*, root: Path, existing_records: Iterable[PersistedRecord]) -> list[InventoryObject]:
    if not root.exists():
        return []
    files = sorted(path for path in root.rglob("*") if path.is_file())
    relative_keys = [_relative_object_key(root, path) for path in files]
    references = _collect_object_references(relative_keys, existing_records)
    rows: list[InventoryObject] = []
    for path, object_key in zip(files, relative_keys):
        digest = _sha256_file(path)
        content = _detect_content(path)
        refs = references.get(object_key, [])
        rows.append(
            InventoryObject(
                object_key=object_key,
                relative_path=object_key,
                content_type=content["content_type"],
                content_kind=content["content_kind"],
                byte_size=path.stat().st_size,
                sha256=digest,
                last_modified_at=_mtime_iso(path),
                hash_path_valid=_hash_path_valid(object_key=object_key, sha256=digest),
                storage_backend=LOCAL_OBJECT_STORAGE_BACKEND,
                orphan_state=REFERENCED_BY_RECORD if refs else UNREFERENCED_LEGACY_OBJECT,
                referenced_by_record_refs=refs,
            )
        )
    return rows


def build_inventory_manifest(
    *,
    root: Path,
    objects: list[InventoryObject],
    database_url: str,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    summary = _inventory_summary(objects)
    fingerprint = _inventory_fingerprint(root=root, objects=objects)
    manifest_id = f"OBJECT-STORAGE-INVENTORY-{fingerprint[:16]}"
    payload = {
        "manifest_version": INVENTORY_MANIFEST_VERSION,
        "manifest_id": manifest_id,
        "inventory_id": manifest_id,
        "created_at": created_at,
        "object_storage_root": str(root),
        "object_storage_root_exists": root.exists(),
        "source_object_storage_backend": LOCAL_OBJECT_STORAGE_BACKEND,
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "inventory_fingerprint": fingerprint,
        "summary": summary,
        "sample_items": [
            _sample_item(item)
            for item in sorted(objects, key=lambda row: (-row.byte_size, row.object_key))[:50]
        ],
        "safety": {
            "source_mutation_enabled": False,
            "object_delete_enabled": False,
            "object_move_enabled": False,
            "evidence_snapshot_manifest_generation_enabled": False,
            "large_object_blob_database_import_enabled": False,
            "external_service_connection_enabled": False,
        },
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def detect_content_type_for_bytes(data: bytes, *, zip_names: list[str] | None = None) -> dict[str, str]:
    stripped = data[:512].lstrip()
    lowered = stripped.lower()
    if data.startswith(b"%PDF"):
        return {"content_kind": "pdf", "content_type": "application/pdf"}
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"content_kind": "png", "content_type": "image/png"}
    if data.startswith(b"\xff\xd8\xff"):
        return {"content_kind": "jpeg", "content_type": "image/jpeg"}
    if data.startswith(b"PK\x03\x04"):
        return _zip_content_type(zip_names or [])
    if lowered.startswith(b"{") or lowered.startswith(b"["):
        return {"content_kind": "json", "content_type": "application/json"}
    if lowered.startswith(b"<!doctype") or lowered.startswith(b"<html") or b"<html" in lowered[:128]:
        return {"content_kind": "html", "content_type": "text/html"}
    if lowered.startswith(b"<?xml") or lowered.startswith(b"<"):
        return {"content_kind": "xml", "content_type": "text/xml"}
    return {"content_kind": "unknown_binary", "content_type": "application/octet-stream"}


def _detect_content(path: Path) -> dict[str, str]:
    with path.open("rb") as handle:
        head = handle.read(512)
    zip_names: list[str] = []
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as archive:
                zip_names = archive.namelist()
        except zipfile.BadZipFile:
            zip_names = []
    return detect_content_type_for_bytes(head, zip_names=zip_names)


def _zip_content_type(names: list[str]) -> dict[str, str]:
    name_set = set(names)
    if "word/document.xml" in name_set:
        return {
            "content_kind": "docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    if "xl/workbook.xml" in name_set:
        return {
            "content_kind": "xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    if "ppt/presentation.xml" in name_set:
        return {
            "content_kind": "pptx",
            "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
    return {"content_kind": "zip", "content_type": "application/zip"}


def _object_record(item: InventoryObject, *, discovered_at: str) -> PersistedRecord:
    payload = item.as_payload(discovered_at=discovered_at)
    return PersistedRecord(
        object_type=OBJECT_STORAGE_OBJECT_TYPE,
        record_id=item.object_key,
        stage_scope=0,
        project_id=None,
        object_refs={"object_key": item.object_key},
        decision_states={"inventory_state": "LEGACY_DISCOVERED"},
        trace_refs={},
        audit_refs={"sha256": item.sha256},
        governed_state={
            "storage_backend": item.storage_backend,
            "content_type": item.content_type,
            "content_kind": item.content_kind,
            "orphan_state": item.orphan_state,
            "hash_path_valid": item.hash_path_valid,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "source_mutation_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=payload,
        persisted_at=build_persisted_at(),
    )


def _manifest_record(manifest: dict[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={"object_storage_root": str(manifest["object_storage_root"])},
        decision_states={"inventory_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "OBJECT_STORAGE_INVENTORY_READY",
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "source_mutation_enabled": False,
            "object_delete_enabled": False,
        },
        payload=manifest,
        persisted_at=discovered_at,
    )


def _inventory_summary(objects: list[InventoryObject]) -> dict[str, Any]:
    content_kind_counts = _counts(item.content_kind for item in objects)
    orphan_counts = _counts(item.orphan_state for item in objects)
    hash_counts = _counts("valid" if item.hash_path_valid else "invalid" for item in objects)
    content_type_counts = _counts(item.content_type for item in objects)
    return {
        "object_count": len(objects),
        "total_byte_size": sum(item.byte_size for item in objects),
        "content_kind_counts": content_kind_counts,
        "content_type_counts": content_type_counts,
        "hash_path_counts": hash_counts,
        "orphan_state_counts": orphan_counts,
        "referenced_object_count": sum(1 for item in objects if item.orphan_state == REFERENCED_BY_RECORD),
        "unreferenced_legacy_object_count": sum(1 for item in objects if item.orphan_state == UNREFERENCED_LEGACY_OBJECT),
        "largest_objects": [_sample_item(item) for item in sorted(objects, key=lambda row: (-row.byte_size, row.object_key))[:10]],
    }


def _collect_object_references(
    object_keys: list[str],
    records: Iterable[PersistedRecord],
) -> dict[str, list[dict[str, str]]]:
    key_set = set(object_keys)
    references: dict[str, list[dict[str, str]]] = {key: [] for key in object_keys}
    for record in records:
        found = set(_iter_matching_strings(record.object_refs, key_set))
        found.update(_iter_matching_strings(record.payload, key_set))
        found.update(_iter_matching_strings(record.trace_refs, key_set))
        found.update(_iter_matching_strings(record.audit_refs, key_set))
        for object_key in sorted(found):
            references.setdefault(object_key, []).append(
                {
                    "object_type": record.object_type,
                    "record_id": record.record_id,
                }
            )
    return {key: refs for key, refs in references.items() if refs}


def _iter_matching_strings(value: Any, key_set: set[str]) -> Iterable[str]:
    if isinstance(value, str):
        if value in key_set:
            yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_matching_strings(item, key_set)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_matching_strings(item, key_set)


def _relative_object_key(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _hash_path_valid(*, object_key: str, sha256: str) -> bool:
    parts = Path(object_key).parts
    return len(parts) >= 3 and parts[-1] == sha256 and parts[-2].lower() == sha256[:2]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mtime_iso(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _inventory_fingerprint(*, root: Path, objects: list[InventoryObject]) -> str:
    rows = [
        {
            "object_key": item.object_key,
            "sha256": item.sha256,
            "byte_size": item.byte_size,
        }
        for item in sorted(objects, key=lambda row: row.object_key)
    ]
    encoded = json.dumps(
        {"root": str(root), "objects": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_sha256(manifest: dict[str, Any]) -> str:
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


def _sample_item(item: InventoryObject) -> dict[str, Any]:
    return {
        "object_key": item.object_key,
        "content_kind": item.content_kind,
        "content_type": item.content_type,
        "byte_size": item.byte_size,
        "sha256": item.sha256,
        "hash_path_valid": item.hash_path_valid,
        "orphan_state": item.orphan_state,
    }


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local object-storage inventory manifest.")
    parser.add_argument("--object-storage-path", default=str(default_inventory_object_storage_path()))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_object_storage_inventory(
        object_storage_path=args.object_storage_path,
        database_url=args.database_url,
        target_backend=args.target_backend,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"object storage inventory {result['inventory_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE",
    "REFERENCED_BY_RECORD",
    "UNREFERENCED_LEGACY_OBJECT",
    "build_object_storage_inventory",
    "detect_content_type_for_bytes",
    "scan_object_storage",
]
