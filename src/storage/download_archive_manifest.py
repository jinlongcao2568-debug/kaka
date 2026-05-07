from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord


DOWNLOAD_RUN_MANIFEST_OBJECT_TYPE = "download_run_manifest"
DOWNLOAD_ARCHIVE_MANIFEST_VERSION = 1
DOWNLOAD_ARCHIVE_RULESET_ID = "download-archive-v1"
DOWNLOAD_RUN_TYPE = "real_public_capture_download_archive"

CAPTURE_KIND_ENTRY = "entry"
CAPTURE_KIND_DETAIL = "detail"
CAPTURE_KIND_ATTACHMENT = "attachment"
CAPTURE_KIND_DEBUG_ARTIFACT = "debug_artifact"

VALID_CAPTURE_KINDS = frozenset(
    {
        CAPTURE_KIND_ENTRY,
        CAPTURE_KIND_DETAIL,
        CAPTURE_KIND_ATTACHMENT,
        CAPTURE_KIND_DEBUG_ARTIFACT,
    }
)
CAPTURE_KIND_DIRECTORIES = {
    CAPTURE_KIND_ENTRY: "pages",
    CAPTURE_KIND_DETAIL: "pages",
    CAPTURE_KIND_ATTACHMENT: "attachments",
    CAPTURE_KIND_DEBUG_ARTIFACT: "debug_artifacts",
}
DEFAULT_BUCKET_ID = "UNASSIGNED"

_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)
_WINDOWS_INVALID_CHARS = set('<>:"/\\|?*')
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class DownloadArchiveItem:
    download_item_id: str
    run_id: str
    candidate_id_optional: str | None
    project_id_optional: str | None
    source_url: str
    source_family_optional: str | None
    capture_kind: str
    original_filename_optional: str | None
    archive_relative_path_optional: str | None
    object_key_optional: str | None
    snapshot_id_optional: str | None
    sha256_optional: str | None
    byte_size_optional: int | None
    content_type_optional: str | None
    download_status: str
    failure_reason_optional: str | None
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_real_capture_run_artifacts_root() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "run-artifacts" / "real-capture"


def build_download_run_id(*, prefix: str = "DLRUN", created_at: str | None = None) -> str:
    created = created_at or utc_now_iso()
    return f"{prefix}-{sanitize_download_segment(created, fallback='run')}"


def sanitize_download_segment(value: Any, *, fallback: str = "item", max_length: int = 120) -> str:
    raw = str(value or "").strip()
    chars: list[str] = []
    for char in raw:
        if char in _WINDOWS_INVALID_CHARS or ord(char) < 32:
            chars.append("_")
        else:
            chars.append(char)
    cleaned = re.sub(r"\s+", " ", "".join(chars)).strip(" ._")
    cleaned = re.sub(r"_+", "_", cleaned)
    if cleaned in {"", ".", ".."}:
        cleaned = fallback
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:max_length].rstrip(" ._") or fallback


def planned_download_archive_path(
    *,
    run_id: str,
    candidate_or_project_id: str | None,
    capture_kind: str,
    original_filename: str | None = None,
    source_url: str | None = None,
    download_item_id: str | None = None,
    run_artifacts_root: str | Path | None = None,
) -> Path:
    root = Path(run_artifacts_root) if run_artifacts_root is not None else default_real_capture_run_artifacts_root()
    relative_path = planned_download_archive_relative_path(
        run_id=run_id,
        candidate_or_project_id=candidate_or_project_id,
        capture_kind=capture_kind,
        original_filename=original_filename,
        source_url=source_url,
        download_item_id=download_item_id,
    )
    target = root / sanitize_download_segment(run_id, fallback="run") / Path(*relative_path.split("/"))
    _ensure_inside_root(root=root, target=target)
    return target


def planned_download_archive_relative_path(
    *,
    run_id: str,
    candidate_or_project_id: str | None,
    capture_kind: str,
    original_filename: str | None = None,
    source_url: str | None = None,
    download_item_id: str | None = None,
) -> str:
    _validate_capture_kind(capture_kind)
    bucket = sanitize_download_segment(candidate_or_project_id, fallback=DEFAULT_BUCKET_ID)
    directory = CAPTURE_KIND_DIRECTORIES[capture_kind]
    item_id = sanitize_download_segment(download_item_id, fallback=_generated_item_id(run_id, source_url or "", capture_kind, bucket))
    filename = _archive_filename(
        capture_kind=capture_kind,
        original_filename=original_filename,
        source_url=source_url,
        download_item_id=item_id,
    )
    return "/".join(["downloads", bucket, directory, filename])


def build_download_archive_manifest(
    *,
    run_id: str | None = None,
    items: Iterable[Mapping[str, Any]] | None = None,
    database_url: str | None = None,
    target_backend: str = "postgresql",
    run_artifacts_root: str | Path | None = None,
    session: DatabaseSession | None = None,
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    resolved_run_id = str(run_id or build_download_run_id(created_at=created)).strip()
    if not resolved_run_id:
        raise ValueError("run_id is required")
    root = Path(run_artifacts_root) if run_artifacts_root is not None else default_real_capture_run_artifacts_root()
    run_root = root / sanitize_download_segment(resolved_run_id, fallback="run")
    _ensure_inside_root(root=root, target=run_root)
    archive_items = build_download_archive_items(
        run_id=resolved_run_id,
        raw_items=list(items or []),
    )
    manifest = _build_manifest_payload(
        run_id=resolved_run_id,
        root=root,
        run_root=run_root,
        archive_items=archive_items,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created,
    )
    result = {
        "download_archive_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": manifest["summary"],
        "execution": {
            "executed": False,
            "target_mutation_enabled": False,
            "database_write_enabled": False,
            "filesystem_write_enabled": False,
            "download_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
    }
    if execute:
        if session is None and not database_url:
            raise RuntimeError("database_url is required when execute=True")
        close_session = False
        if session is None:
            settings = Settings(
                storage_backend=target_backend,
                storage_database_url_optional=database_url,
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            close_session = True
        try:
            session.upsert_record(_manifest_record(manifest, persisted_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "filesystem_write_enabled": False,
                "download_execution_enabled": False,
                "large_object_blob_database_import_enabled": False,
                "upserted_download_run_manifest_count": 1,
            }
        finally:
            if close_session:
                session.close()
    return result


def append_download_archive_items(
    *,
    run_id: str,
    items: Iterable[Mapping[str, Any]],
    session: DatabaseSession | None = None,
    database_url: str | None = None,
    target_backend: str = "postgresql",
    run_artifacts_root: str | Path | None = None,
    execute: bool = True,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    manifest_id = _manifest_id_for_run(run_id)
    close_session = False
    resolved_session = session
    if execute and resolved_session is None:
        if not database_url:
            raise RuntimeError("database_url is required when execute=True")
        settings = Settings(
            storage_backend=target_backend,
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
        )
        resolved_session = DatabaseSession(settings=settings)
        close_session = True
    try:
        existing_items: list[Mapping[str, Any]] = []
        if resolved_session is not None:
            existing_record = resolved_session.get_record(DOWNLOAD_RUN_MANIFEST_OBJECT_TYPE, manifest_id)
            if existing_record is not None:
                existing_items = [
                    item
                    for item in existing_record.payload.get("items", [])
                    if isinstance(item, Mapping)
                ]
        new_items = [item.as_payload() for item in build_download_archive_items(run_id=run_id, raw_items=items)]
        merged_items = _merge_items_by_download_item_id(existing_items, new_items)
        return build_download_archive_manifest(
            run_id=run_id,
            items=merged_items,
            database_url=database_url or (resolved_session.storage_database_url if resolved_session else None),
            target_backend=target_backend if resolved_session is None else resolved_session.storage_backend,
            run_artifacts_root=run_artifacts_root,
            session=resolved_session,
            execute=execute,
            created_at=created,
        )
    finally:
        if close_session and resolved_session is not None:
            resolved_session.close()


def build_stage2_download_archive_item(
    *,
    run_id: str,
    capture_kind: str,
    fetch_result: Mapping[str, Any],
    project_id: str | None = None,
    candidate_id: str | None = None,
    lineage_refs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_capture_kind(capture_kind)
    resolved_project_id, resolved_candidate_id = _resolve_stage2_bucket_ids(
        project_id=project_id,
        candidate_id=candidate_id,
        lineage_refs=lineage_refs,
    )
    source_url = _stage2_source_url(fetch_result=fetch_result, capture_kind=capture_kind)
    original_filename = (
        _optional_str(fetch_result.get("attachment_filename"))
        if capture_kind == CAPTURE_KIND_ATTACHMENT
        else None
    )
    manifest = fetch_result.get("manifest_optional")
    manifest_payload = manifest if isinstance(manifest, Mapping) else {}
    snapshot_id = _optional_str(fetch_result.get("snapshot_id_optional") or manifest_payload.get("snapshot_id"))
    object_key = _optional_str(manifest_payload.get("object_key"))
    download_status = _stage2_download_status(fetch_result=fetch_result, snapshot_id=snapshot_id)
    raw_item = {
        "run_id": run_id,
        "candidate_id_optional": resolved_candidate_id,
        "project_id_optional": resolved_project_id,
        "source_url": source_url,
        "source_family_optional": _optional_str(fetch_result.get("source_family")),
        "capture_kind": capture_kind,
        "original_filename_optional": original_filename,
        "object_key_optional": object_key,
        "snapshot_id_optional": snapshot_id,
        "sha256_optional": _optional_str(fetch_result.get("sha256") or manifest_payload.get("sha256")),
        "byte_size_optional": _optional_int(fetch_result.get("byte_size") or manifest_payload.get("byte_size")),
        "content_type_optional": _optional_str(fetch_result.get("content_type") or manifest_payload.get("content_type")),
        "download_status": download_status,
        "failure_reason_optional": _stage2_failure_reason(fetch_result),
    }
    return build_download_archive_items(run_id=run_id, raw_items=[raw_item])[0].as_payload()


def build_download_archive_items(
    *,
    run_id: str,
    raw_items: Iterable[Mapping[str, Any]],
) -> list[DownloadArchiveItem]:
    items: list[DownloadArchiveItem] = []
    for raw in raw_items:
        capture_kind = str(raw.get("capture_kind") or "").strip()
        _validate_capture_kind(capture_kind)
        source_url = str(raw.get("source_url") or "").strip()
        if not source_url:
            raise ValueError("source_url is required for every download archive item")
        project_id = _optional_str(raw.get("project_id_optional") or raw.get("project_id"))
        candidate_id = _optional_str(raw.get("candidate_id_optional") or raw.get("candidate_id"))
        bucket_id = project_id or candidate_id or DEFAULT_BUCKET_ID
        download_item_id = _optional_str(raw.get("download_item_id")) or _generated_item_id(
            run_id,
            source_url,
            capture_kind,
            bucket_id,
            _optional_str(raw.get("original_filename_optional") or raw.get("original_filename")),
            _optional_str(raw.get("snapshot_id_optional") or raw.get("snapshot_id")),
            _optional_str(raw.get("object_key_optional") or raw.get("object_key")),
        )
        original_filename = _optional_str(raw.get("original_filename_optional") or raw.get("original_filename"))
        relative_path = planned_download_archive_relative_path(
            run_id=run_id,
            candidate_or_project_id=bucket_id,
            capture_kind=capture_kind,
            original_filename=original_filename,
            source_url=source_url,
            download_item_id=download_item_id,
        )
        items.append(
            DownloadArchiveItem(
                download_item_id=download_item_id,
                run_id=run_id,
                candidate_id_optional=candidate_id,
                project_id_optional=project_id,
                source_url=source_url,
                source_family_optional=_optional_str(raw.get("source_family_optional") or raw.get("source_family")),
                capture_kind=capture_kind,
                original_filename_optional=original_filename,
                archive_relative_path_optional=relative_path,
                object_key_optional=_optional_str(raw.get("object_key_optional") or raw.get("object_key")),
                snapshot_id_optional=_optional_str(raw.get("snapshot_id_optional") or raw.get("snapshot_id")),
                sha256_optional=_optional_str(raw.get("sha256_optional") or raw.get("sha256")),
                byte_size_optional=_optional_int(raw.get("byte_size_optional") or raw.get("byte_size")),
                content_type_optional=_optional_str(raw.get("content_type_optional") or raw.get("content_type")),
                download_status=str(raw.get("download_status") or "PLANNED"),
                failure_reason_optional=_optional_str(raw.get("failure_reason_optional") or raw.get("failure_reason")),
            )
        )
    return items


def load_download_archive_input(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return {"items": data}
    if not isinstance(data, dict):
        raise ValueError("download archive input JSON must be an object or an array")
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("download archive input JSON field 'items' must be an array")
    return {"run_id": data.get("run_id"), "items": items}


def _build_manifest_payload(
    *,
    run_id: str,
    root: Path,
    run_root: Path,
    archive_items: list[DownloadArchiveItem],
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    manifest_id = _manifest_id_for_run(run_id)
    payload = {
        "manifest_version": DOWNLOAD_ARCHIVE_MANIFEST_VERSION,
        "manifest_id": manifest_id,
        "download_run_manifest_id": manifest_id,
        "download_archive_ruleset_id": DOWNLOAD_ARCHIVE_RULESET_ID,
        "run_id": run_id,
        "run_type": DOWNLOAD_RUN_TYPE,
        "created_at": created_at,
        "run_artifacts_root": str(root),
        "run_archive_root": str(run_root),
        "planned_manifest_file_path": str(run_root / "manifest.json"),
        "downloads_root": str(run_root / "downloads"),
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "summary": _summary(archive_items),
        "items": [item.as_payload() for item in archive_items],
        "sample_items": [item.as_payload() for item in archive_items[:50]],
        "safety": {
            "external_service_connection_enabled": False,
            "download_execution_enabled": False,
            "filesystem_write_enabled": False,
            "large_object_blob_database_import_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    payload["manifest_fingerprint"] = _manifest_fingerprint(payload)
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _manifest_record(manifest: Mapping[str, Any], *, persisted_at: str) -> PersistedRecord:
    item_project_ids = sorted(
        {
            str(item["project_id_optional"])
            for item in manifest.get("items", [])
            if isinstance(item, Mapping) and item.get("project_id_optional")
        }
    )
    project_id = item_project_ids[0] if len(item_project_ids) == 1 else None
    return PersistedRecord(
        object_type=DOWNLOAD_RUN_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=project_id,
        object_refs={
            "run_id": str(manifest["run_id"]),
            "run_archive_root": str(manifest["run_archive_root"]),
            "downloads_root": str(manifest["downloads_root"]),
        },
        decision_states={"download_archive_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "DOWNLOAD_ARCHIVE_MANIFEST_READY",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "database_write_enabled": True,
            "filesystem_write_enabled": False,
            "download_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=persisted_at,
    )


def _manifest_id_for_run(run_id: str) -> str:
    return f"DOWNLOAD-RUN-MANIFEST-{sanitize_download_segment(run_id, fallback='run')}"


def _merge_items_by_download_item_id(
    existing_items: Iterable[Mapping[str, Any]],
    new_items: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    order: list[str] = []
    merged: dict[str, Mapping[str, Any]] = {}
    for item in [*existing_items, *new_items]:
        item_id = _optional_str(item.get("download_item_id"))
        if not item_id:
            continue
        if item_id not in merged:
            order.append(item_id)
        merged[item_id] = item
    return [merged[item_id] for item_id in order]


def _resolve_stage2_bucket_ids(
    *,
    project_id: str | None,
    candidate_id: str | None,
    lineage_refs: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    refs = dict(lineage_refs or {})
    resolved_project_id = (
        _optional_str(project_id)
        or _optional_str(refs.get("project_id"))
        or _optional_str(refs.get("project_root_id"))
    )
    resolved_candidate_id = _optional_str(candidate_id) or _optional_str(refs.get("candidate_id"))
    return resolved_project_id, resolved_candidate_id


def _stage2_source_url(*, fetch_result: Mapping[str, Any], capture_kind: str) -> str:
    if capture_kind == CAPTURE_KIND_ENTRY:
        return str(fetch_result.get("entry_url") or fetch_result.get("final_url") or "").strip()
    if capture_kind == CAPTURE_KIND_DETAIL:
        return str(fetch_result.get("detail_url") or fetch_result.get("final_url") or "").strip()
    if capture_kind == CAPTURE_KIND_ATTACHMENT:
        return str(fetch_result.get("attachment_url") or fetch_result.get("final_url") or "").strip()
    return str(fetch_result.get("source_url") or fetch_result.get("final_url") or "").strip()


def _stage2_download_status(*, fetch_result: Mapping[str, Any], snapshot_id: str | None) -> str:
    status = str(fetch_result.get("status") or "").strip().upper()
    if status == "FETCHED" and snapshot_id:
        return "FETCHED_WITH_SNAPSHOT"
    if status == "FETCHED":
        return "FETCHED_NO_SNAPSHOT_REVIEW"
    return "REVIEW_NO_SNAPSHOT"


def _stage2_failure_reason(fetch_result: Mapping[str, Any]) -> str | None:
    reasons = fetch_result.get("degraded_reasons") or fetch_result.get("failure_reasons") or []
    if isinstance(reasons, str):
        return _optional_str(reasons)
    if isinstance(reasons, Iterable):
        joined = ";".join(str(reason) for reason in reasons if reason not in (None, ""))
        return _optional_str(joined)
    return None


def _summary(items: Iterable[DownloadArchiveItem]) -> dict[str, Any]:
    rows = list(items)
    return {
        "item_count": len(rows),
        "capture_kind_counts": _counts(item.capture_kind for item in rows),
        "download_status_counts": _counts(item.download_status for item in rows),
        "project_bucket_count": len({item.project_id_optional for item in rows if item.project_id_optional}),
        "candidate_bucket_count": len({item.candidate_id_optional for item in rows if item.candidate_id_optional}),
        "unassigned_bucket_count": sum(
            1 for item in rows if not item.project_id_optional and not item.candidate_id_optional
        ),
        "planned_archive_path_count": sum(1 for item in rows if item.archive_relative_path_optional),
        "object_key_ref_count": sum(1 for item in rows if item.object_key_optional),
        "snapshot_ref_count": sum(1 for item in rows if item.snapshot_id_optional),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
    }


def _archive_filename(
    *,
    capture_kind: str,
    original_filename: str | None,
    source_url: str | None,
    download_item_id: str,
) -> str:
    if original_filename:
        filename = _safe_original_filename(original_filename)
    else:
        filename = _filename_from_url(source_url) or _default_filename_for_capture_kind(capture_kind)
    safe_name = sanitize_download_segment(filename, fallback=_default_filename_for_capture_kind(capture_kind))
    safe_item_id = sanitize_download_segment(download_item_id, fallback="item", max_length=64)
    if safe_name.startswith(f"{safe_item_id}-"):
        return safe_name
    return f"{safe_item_id}-{safe_name}"


def _safe_original_filename(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("original_filename must not be empty")
    if _DRIVE_PREFIX.match(raw) or raw.startswith("\\\\") or "/" in raw or "\\" in raw:
        raise ValueError("original_filename must be a basename, not a path")
    if raw in {".", ".."}:
        raise ValueError("original_filename must not be a path traversal segment")
    return raw


def _filename_from_url(source_url: str | None) -> str | None:
    if not source_url:
        return None
    parsed = urlsplit(source_url)
    name = unquote(Path(parsed.path).name).strip()
    if not name or name in {".", ".."}:
        return None
    return name


def _default_filename_for_capture_kind(capture_kind: str) -> str:
    if capture_kind == CAPTURE_KIND_ENTRY:
        return "entry.html"
    if capture_kind == CAPTURE_KIND_DETAIL:
        return "detail.html"
    if capture_kind == CAPTURE_KIND_ATTACHMENT:
        return "attachment.bin"
    return "debug_artifact.bin"


def _generated_item_id(*parts: Any) -> str:
    encoded = json.dumps([str(part) for part in parts if part not in (None, "")], sort_keys=True).encode("utf-8")
    return f"DLI-{hashlib.sha256(encoded).hexdigest()[:16]}"


def _validate_capture_kind(capture_kind: str) -> None:
    if capture_kind not in VALID_CAPTURE_KINDS:
        raise ValueError(f"unsupported capture_kind {capture_kind!r}; expected one of {sorted(VALID_CAPTURE_KINDS)}")


def _ensure_inside_root(*, root: Path, target: Path) -> None:
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"download archive path escapes real-capture root: {target}") from exc


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    number = int(value)
    if number < 0:
        raise ValueError("byte_size must be non-negative")
    return number


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {
            key: value
            for key, value in manifest.items()
            if key not in {"manifest_fingerprint", "manifest_sha256"}
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


def _redact_database_url(database_url: str | None) -> str:
    if not database_url:
        return "NOT_CONFIGURED"
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a dry-run download archive manifest.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-artifacts-root", default=str(default_real_capture_run_artifacts_root()))
    parser.add_argument("--input-json", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_payload = load_download_archive_input(args.input_json) if args.input_json else {"items": []}
    result = build_download_archive_manifest(
        run_id=args.run_id or input_payload.get("run_id"),
        items=input_payload.get("items", []),
        database_url=args.database_url,
        target_backend=args.target_backend,
        run_artifacts_root=args.run_artifacts_root,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"download archive manifest {result['download_archive_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAPTURE_KIND_ATTACHMENT",
    "CAPTURE_KIND_DEBUG_ARTIFACT",
    "CAPTURE_KIND_DETAIL",
    "CAPTURE_KIND_ENTRY",
    "DOWNLOAD_ARCHIVE_MANIFEST_VERSION",
    "DOWNLOAD_ARCHIVE_RULESET_ID",
    "DOWNLOAD_RUN_MANIFEST_OBJECT_TYPE",
    "append_download_archive_items",
    "build_download_archive_items",
    "build_download_archive_manifest",
    "build_download_run_id",
    "build_stage2_download_archive_item",
    "default_real_capture_run_artifacts_root",
    "load_download_archive_input",
    "planned_download_archive_path",
    "planned_download_archive_relative_path",
    "sanitize_download_segment",
]
