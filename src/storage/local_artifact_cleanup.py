from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord
from storage.object_storage import LOCAL_OBJECT_STORAGE_BACKEND
from storage.object_storage_inventory import detect_content_type_for_bytes
from storage.repositories.object_storage_repo import ObjectStorageRepository


LOCAL_ARTIFACT_CLEANUP_MANIFEST_OBJECT_TYPE = "local_artifact_cleanup_manifest"
LOCAL_ARTIFACT_CLEANUP_VERSION = 1

COPY_TO_OBJECT_STORAGE_AND_ARCHIVE = "COPY_TO_OBJECT_STORAGE_AND_ARCHIVE"
ARCHIVE_ONLY = "ARCHIVE_ONLY"

EVIDENCE_ORIGINAL = "EVIDENCE_ORIGINAL"
RUNTIME_DEBUG_ARTIFACT = "RUNTIME_DEBUG_ARTIFACT"
REVIEW_ONLY_LOCAL_ARTIFACT = "REVIEW_ONLY_LOCAL_ARTIFACT"

EVIDENCE_EXTENSIONS = frozenset(
    {
        ".html",
        ".json",
        ".jsonl",
        ".pdf",
        ".doc",
        ".docx",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".rar",
        ".txt",
        ".md",
    }
)
RUNTIME_EXTENSIONS = frozenset({".log", ".pid", ".err"})
RUNTIME_PREFIXES = (
    ".playwright-mcp/",
    "tmp/",
    "handoff/runlogs/",
)
ROOT_DEBUG_PREFIXES = (
    "gz_ywtb_",
    "jzsc_",
    "mwr-",
)
SCRIPT_EXCLUDE_PATHS = frozenset(
    {
        "src/storage/local_artifact_cleanup.py",
        "scripts/cleanup-local-artifacts.ps1",
    }
)


@dataclass(frozen=True)
class CleanupItem:
    source_path: str
    byte_size: int
    sha256: str
    extension: str
    content_kind: str
    content_type: str
    artifact_class: str
    action: str
    object_key_optional: str | None
    archive_path: str
    review_required: bool = True
    no_legal_conclusion: bool = True
    customer_visible_allowed: bool = False
    reasons: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def default_run_artifacts_root() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "run-artifacts" / "repo-cleanup"


def build_local_artifact_cleanup(
    *,
    repo_root: str | Path,
    database_url: str,
    target_backend: str = "postgresql",
    object_storage_path: str | Path | None = None,
    run_artifacts_root: str | Path | None = None,
    execute: bool = False,
    created_at: str | None = None,
    untracked_paths: Iterable[str] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    created = created_at or utc_now_iso()
    object_root = Path(object_storage_path) if object_storage_path is not None else default_object_storage_path()
    run_root = Path(run_artifacts_root) if run_artifacts_root is not None else default_run_artifacts_root()
    cleanup_root = _cleanup_run_root(run_root, created_at=created)
    paths = list(untracked_paths) if untracked_paths is not None else _git_untracked_paths(root)
    items = build_cleanup_items(repo_root=root, cleanup_root=cleanup_root, paths=paths)
    manifest = build_cleanup_manifest(
        repo_root=root,
        object_storage_path=object_root,
        run_artifacts_root=run_root,
        cleanup_root=cleanup_root,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created,
        items=items,
    )
    result = {
        "cleanup_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": manifest["summary"],
        "execution": {
            "executed": False,
            "target_mutation_enabled": False,
            "source_delete_enabled": False,
            "source_move_enabled": False,
            "object_storage_write_enabled": False,
            "database_write_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
    }
    if execute and items:
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
            moved_count = 0
            copied_count = 0
            object_keys: dict[str, str] = {}
            with session.bulk_write():
                for item in items:
                    source = _resolve_source(root, item.source_path)
                    if item.action == COPY_TO_OBJECT_STORAGE_AND_ARCHIVE and source.exists():
                        metadata = repository.put_object(
                            source.read_bytes(),
                            content_type=item.content_type,
                        )
                        object_keys[item.source_path] = metadata.object_key
                        copied_count += 1
                    if source.exists():
                        _move_to_archive(source=source, target=Path(item.archive_path), cleanup_root=cleanup_root)
                        moved_count += 1
                updated_manifest = _manifest_with_object_keys(manifest, object_keys)
                session.upsert_record(_manifest_record(updated_manifest, discovered_at=created))
            result["manifest"] = updated_manifest
            result["summary"] = updated_manifest["summary"]
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "source_delete_enabled": False,
                "source_move_enabled": True,
                "object_storage_write_enabled": copied_count > 0,
                "database_write_enabled": True,
                "large_object_blob_database_import_enabled": False,
                "copied_to_object_storage_count": copied_count,
                "moved_to_run_artifacts_count": moved_count,
                "upserted_local_artifact_cleanup_manifest_count": 1,
            }
        finally:
            session.close()
    return result


def build_cleanup_items(
    *,
    repo_root: Path,
    cleanup_root: Path,
    paths: Iterable[str],
) -> list[CleanupItem]:
    items: list[CleanupItem] = []
    for raw_path in sorted(dict.fromkeys(_normalize_rel_path(path) for path in paths)):
        if not raw_path or raw_path in SCRIPT_EXCLUDE_PATHS:
            continue
        source = _resolve_source(repo_root, raw_path)
        if not source.exists() or not source.is_file():
            continue
        digest = _sha256_file(source)
        extension = source.suffix.lower()
        data_head = source.read_bytes()[:512]
        content = _detect_content(path=source, data_head=data_head)
        artifact_class, action, reasons = _classify(raw_path, extension)
        target = _archive_target(cleanup_root=cleanup_root, relative_path=raw_path)
        items.append(
            CleanupItem(
                source_path=raw_path,
                byte_size=source.stat().st_size,
                sha256=digest,
                extension=extension,
                content_kind=content["content_kind"],
                content_type=content["content_type"],
                artifact_class=artifact_class,
                action=action,
                object_key_optional=None,
                archive_path=str(target),
                reasons=reasons,
            )
        )
    return items


def build_cleanup_manifest(
    *,
    repo_root: Path,
    object_storage_path: Path,
    run_artifacts_root: Path,
    cleanup_root: Path,
    database_url: str,
    target_backend: str,
    created_at: str,
    items: list[CleanupItem],
) -> dict[str, Any]:
    fingerprint = _cleanup_fingerprint(repo_root=repo_root, items=items)
    manifest_id = f"LOCAL-ARTIFACT-CLEANUP-{fingerprint[:16]}"
    payload = {
        "manifest_version": LOCAL_ARTIFACT_CLEANUP_VERSION,
        "manifest_id": manifest_id,
        "cleanup_id": manifest_id,
        "created_at": created_at,
        "repo_root": str(repo_root),
        "object_storage_path": str(object_storage_path),
        "run_artifacts_root": str(run_artifacts_root),
        "cleanup_archive_root": str(cleanup_root),
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "cleanup_fingerprint": fingerprint,
        "summary": _summary(items),
        "items": [item.as_payload() for item in items],
        "sample_items": [item.as_payload() for item in sorted(items, key=lambda row: -row.byte_size)[:50]],
        "safety": {
            "tracked_file_processing_enabled": False,
            "source_delete_enabled": False,
            "source_move_enabled": True,
            "object_storage_write_enabled": True,
            "large_object_blob_database_import_enabled": False,
            "external_service_connection_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _classify(path: str, extension: str) -> tuple[str, str, list[str]]:
    normalized = _normalize_rel_path(path)
    top = normalized.split("/", 1)[0]
    if _is_runtime_debug(normalized, extension):
        if extension in EVIDENCE_EXTENSIONS and extension not in RUNTIME_EXTENSIONS:
            return (
                EVIDENCE_ORIGINAL,
                COPY_TO_OBJECT_STORAGE_AND_ARCHIVE,
                ["runtime_path_with_evidence_extension"],
            )
        return (
            RUNTIME_DEBUG_ARTIFACT,
            ARCHIVE_ONLY,
            ["runtime_debug_path_or_extension"],
        )
    if extension in EVIDENCE_EXTENSIONS:
        return (
            EVIDENCE_ORIGINAL,
            COPY_TO_OBJECT_STORAGE_AND_ARCHIVE,
            ["evidence_like_extension"],
        )
    if top == "handoff":
        return (
            REVIEW_ONLY_LOCAL_ARTIFACT,
            ARCHIVE_ONLY,
            ["handoff_untracked_runtime_output_not_evidence_extension"],
        )
    return (
        REVIEW_ONLY_LOCAL_ARTIFACT,
        ARCHIVE_ONLY,
        ["untracked_local_artifact_requires_review"],
    )


def _is_runtime_debug(path: str, extension: str) -> bool:
    if extension in RUNTIME_EXTENSIONS:
        return True
    if any(path.startswith(prefix) for prefix in RUNTIME_PREFIXES):
        return True
    name = Path(path).name
    if any(name.startswith(prefix) for prefix in ROOT_DEBUG_PREFIXES):
        return True
    return False


def _detect_content(*, path: Path, data_head: bytes) -> dict[str, str]:
    detected = detect_content_type_for_bytes(data_head)
    if detected["content_kind"] != "unknown_binary":
        return detected
    extension = path.suffix.lower()
    fallback = {
        ".doc": ("doc", "application/msword"),
        ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ".rar": ("rar", "application/vnd.rar"),
        ".txt": ("text", "text/plain"),
        ".md": ("markdown", "text/markdown"),
        ".log": ("log", "text/plain"),
        ".pid": ("pid", "text/plain"),
        ".ps1": ("powershell", "text/plain"),
        ".py": ("python", "text/x-python"),
        ".js": ("javascript", "text/javascript"),
        ".yml": ("yaml", "text/yaml"),
        ".yaml": ("yaml", "text/yaml"),
    }
    if extension in fallback:
        content_kind, content_type = fallback[extension]
        return {"content_kind": content_kind, "content_type": content_type}
    return detected


def _manifest_with_object_keys(manifest: Mapping[str, Any], object_keys: Mapping[str, str]) -> dict[str, Any]:
    updated = dict(manifest)
    items: list[dict[str, Any]] = []
    for item in list(manifest.get("items", [])):
        row = dict(item)
        if row.get("source_path") in object_keys:
            row["object_key_optional"] = object_keys[str(row["source_path"])]
        items.append(row)
    updated["items"] = items
    updated["sample_items"] = sorted(items, key=lambda row: -int(row.get("byte_size", 0)))[:50]
    updated["summary"] = _summary(
        CleanupItem(**{key: value for key, value in row.items() if key in CleanupItem.__dataclass_fields__})
        for row in items
    )
    updated["manifest_sha256"] = _manifest_sha256(updated)
    return updated


def _summary(items: Iterable[CleanupItem]) -> dict[str, Any]:
    rows = list(items)
    evidence_count = sum(1 for item in rows if item.action == COPY_TO_OBJECT_STORAGE_AND_ARCHIVE)
    archive_count = sum(1 for item in rows if item.action == ARCHIVE_ONLY)
    return {
        "untracked_file_count": len(rows),
        "total_byte_size": sum(item.byte_size for item in rows),
        "total_mb": round(sum(item.byte_size for item in rows) / (1024 * 1024), 2),
        "evidence_like_count": evidence_count,
        "archive_only_count": archive_count,
        "action_counts": _counts(item.action for item in rows),
        "artifact_class_counts": _counts(item.artifact_class for item in rows),
        "extension_counts": _counts(item.extension or "(none)" for item in rows),
        "content_kind_counts": _counts(item.content_kind for item in rows),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
    }


def _manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=LOCAL_ARTIFACT_CLEANUP_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "repo_root": str(manifest["repo_root"]),
            "object_storage_path": str(manifest["object_storage_path"]),
            "cleanup_archive_root": str(manifest["cleanup_archive_root"]),
        },
        decision_states={"cleanup_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "LOCAL_ARTIFACT_CLEANUP_READY",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "source_delete_enabled": False,
            "source_move_enabled": True,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _git_untracked_paths(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=str(repo_root),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    paths = [
        _normalize_rel_path(part.decode("utf-8", errors="surrogateescape"))
        for part in completed.stdout.split(b"\0")
        if part
    ]
    paths.extend(_known_local_artifact_paths(repo_root))
    return sorted(dict.fromkeys(paths))


def _known_local_artifact_paths(repo_root: Path) -> list[str]:
    tracked = _git_tracked_paths(repo_root)
    candidates: list[Path] = []
    for relative_dir in (".playwright-mcp", "tmp", "handoff/runlogs"):
        directory = repo_root / relative_dir
        if directory.exists():
            candidates.extend(path for path in directory.rglob("*") if path.is_file())
    for pattern in ("*.log", "*.pid", "gz_ywtb_*", "jzsc_*.json", "mwr-*.png"):
        candidates.extend(path for path in repo_root.glob(pattern) if path.is_file())
    paths: list[str] = []
    for path in candidates:
        rel = _normalize_rel_path(str(path.resolve().relative_to(repo_root)))
        if rel not in tracked:
            paths.append(rel)
    return paths


def _git_tracked_paths(repo_root: Path) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(repo_root),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        _normalize_rel_path(part.decode("utf-8", errors="surrogateescape"))
        for part in completed.stdout.split(b"\0")
        if part
    }


def _move_to_archive(*, source: Path, target: Path, cleanup_root: Path) -> None:
    resolved_cleanup_root = cleanup_root.resolve()
    resolved_target = target.resolve()
    if resolved_cleanup_root != resolved_target and resolved_cleanup_root not in resolved_target.parents:
        raise ValueError("archive target escapes cleanup root")
    resolved_target = _unique_target_path(resolved_target)
    resolved_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(resolved_target))


def _unique_target_path(target: Path) -> Path:
    if not target.exists():
        return target
    digest = _sha256_file(target)[:12] if target.is_file() else "existing"
    candidate = target.with_name(f"{target.stem}.{digest}{target.suffix}")
    index = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.stem}.{digest}.{index}{target.suffix}")
        index += 1
    return candidate


def _archive_target(*, cleanup_root: Path, relative_path: str) -> Path:
    clean_parts = [
        part
        for part in Path(_normalize_rel_path(relative_path)).parts
        if part not in ("", ".", "..")
    ]
    return cleanup_root.joinpath(*clean_parts)


def _cleanup_run_root(run_artifacts_root: Path, *, created_at: str) -> Path:
    safe = (
        created_at.replace(":", "")
        .replace("+", "_")
        .replace("/", "-")
        .replace("\\", "-")
    )
    return run_artifacts_root / safe


def _resolve_source(repo_root: Path, relative_path: str) -> Path:
    path = (repo_root / Path(_normalize_rel_path(relative_path))).resolve()
    if repo_root != path and repo_root not in path.parents:
        raise ValueError("source path escapes repo root")
    return path


def _normalize_rel_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cleanup_fingerprint(*, repo_root: Path, items: list[CleanupItem]) -> str:
    encoded = json.dumps(
        {
            "repo_root": str(repo_root),
            "items": [
                {
                    "source_path": item.source_path,
                    "sha256": item.sha256,
                    "byte_size": item.byte_size,
                    "action": item.action,
                }
                for item in sorted(items, key=lambda row: row.source_path)
            ],
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean local untracked runtime artifacts safely.")
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--object-storage-path", default=str(default_object_storage_path()))
    parser.add_argument("--run-artifacts-root", default=str(default_run_artifacts_root()))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_local_artifact_cleanup(
        repo_root=args.repo_root,
        database_url=args.database_url,
        target_backend=args.target_backend,
        object_storage_path=args.object_storage_path,
        run_artifacts_root=args.run_artifacts_root,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"local artifact cleanup {result['cleanup_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARCHIVE_ONLY",
    "COPY_TO_OBJECT_STORAGE_AND_ARCHIVE",
    "EVIDENCE_ORIGINAL",
    "LOCAL_ARTIFACT_CLEANUP_MANIFEST_OBJECT_TYPE",
    "REVIEW_ONLY_LOCAL_ARTIFACT",
    "RUNTIME_DEBUG_ARTIFACT",
    "build_cleanup_items",
    "build_local_artifact_cleanup",
]
