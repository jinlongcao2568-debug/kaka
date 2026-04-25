from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import mkstemp
from time import sleep
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso


LOCAL_OBJECT_STORAGE_BACKEND = "local-filesystem"
LOCAL_OBJECT_STORAGE_ALIASES = frozenset(
    {"", "local", "local-filesystem", "filesystem", "file", "fs"}
)
RESERVED_OBJECT_STORAGE_BACKENDS = frozenset({"minio", "s3"})
OBJECT_STORAGE_OBJECT_TYPE = "object_storage_object"
EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE = "evidence_snapshot_manifest"


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorageMissingError(ObjectStorageError):
    pass


class ObjectStorageIntegrityError(ObjectStorageError):
    pass


class ObjectStorageBackendReservedError(ObjectStorageError):
    pass


@dataclass(frozen=True)
class StoredObjectMetadata:
    object_key: str
    content_type: str
    byte_size: int
    sha256: str
    created_at: str
    storage_backend: str = LOCAL_OBJECT_STORAGE_BACKEND

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceSnapshotManifest:
    snapshot_id: str
    object_key: str
    source_url_optional: str | None
    source_family_optional: str | None
    snapshot_kind: str
    content_type: str
    byte_size: int
    sha256: str
    lineage_refs: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    storage_backend: str = LOCAL_OBJECT_STORAGE_BACKEND
    replay_metadata: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lineage_refs"] = dict(self.lineage_refs)
        payload["replay_metadata"] = dict(self.replay_metadata)
        return payload


def normalize_object_storage_backend_name(value: str | None) -> str:
    backend = (value or "").strip().lower()
    if backend in LOCAL_OBJECT_STORAGE_ALIASES:
        return LOCAL_OBJECT_STORAGE_BACKEND
    return backend


def default_object_storage_path(settings: Settings | None = None) -> Path:
    resolved_settings = settings or Settings.from_env()
    if resolved_settings.object_storage_path_optional:
        return Path(resolved_settings.object_storage_path_optional)
    return resolved_settings.resolved_storage_path().parent / "object-storage"


class LocalObjectStorage:
    def __init__(self, *, root_path: Path, backend: str = LOCAL_OBJECT_STORAGE_BACKEND) -> None:
        normalized_backend = normalize_object_storage_backend_name(backend)
        if normalized_backend != LOCAL_OBJECT_STORAGE_BACKEND:
            raise ObjectStorageBackendReservedError(
                f"object storage backend {backend!r} is reserved/not-live; "
                "only local-filesystem is executable in this packet"
            )
        self.root_path = root_path
        self.storage_backend = LOCAL_OBJECT_STORAGE_BACKEND

    def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
        object_key: str | None = None,
        created_at: str | None = None,
    ) -> StoredObjectMetadata:
        byte_size = len(data)
        sha256 = hashlib.sha256(data).hexdigest()
        resolved_key = self._normalize_object_key(object_key or self._default_object_key(sha256))
        target_path = self.object_path(resolved_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = mkstemp(
            prefix=f"{target_path.name}-",
            suffix=".tmp",
            dir=str(target_path.parent),
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            self._replace_with_retry(temp_path, target_path)
        except Exception:
            if not temp_path.exists():
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
        return StoredObjectMetadata(
            object_key=resolved_key,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256,
            created_at=created_at or utc_now_iso(),
            storage_backend=self.storage_backend,
        )

    def read_bytes(
        self,
        object_key: str,
        *,
        expected_sha256: str | None = None,
        expected_byte_size: int | None = None,
    ) -> bytes:
        resolved_key = self._normalize_object_key(object_key)
        target_path = self.object_path(resolved_key)
        if not target_path.exists():
            raise ObjectStorageMissingError(f"object storage ref {resolved_key!r} is missing")
        data = target_path.read_bytes()
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise ObjectStorageIntegrityError(
                f"object storage ref {resolved_key!r} sha256 mismatch"
            )
        if expected_byte_size is not None and len(data) != expected_byte_size:
            raise ObjectStorageIntegrityError(
                f"object storage ref {resolved_key!r} byte_size mismatch"
            )
        return data

    def object_path(self, object_key: str) -> Path:
        resolved_key = self._normalize_object_key(object_key)
        root = self.root_path.resolve()
        path = (root / Path(resolved_key)).resolve()
        if root != path and root not in path.parents:
            raise ValueError("object_key escapes object storage root")
        return path

    def describe(self) -> dict[str, Any]:
        return {
            "storage_backend": self.storage_backend,
            "root_path": str(self.root_path),
            "executable": True,
            "external_service_connection_enabled": False,
        }

    def _normalize_object_key(self, object_key: str) -> str:
        key = object_key.strip().replace("\\", "/")
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise ValueError("object_key must be a relative non-empty path")
        return key

    def _default_object_key(self, sha256: str) -> str:
        return f"objects/{sha256[:2]}/{sha256}"

    def _replace_with_retry(self, temp_path: Path, target_path: Path, *, retries: int = 8) -> None:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                os.replace(temp_path, target_path)
                return
            except PermissionError as exc:
                last_error = exc
            except OSError as exc:
                last_error = exc
            sleep(0.025 * (attempt + 1))
        if last_error is not None:
            raise last_error


def build_replay_metadata(
    *,
    object_metadata: StoredObjectMetadata,
    readback_state: str = "READBACK_READY",
    object_present: bool = True,
    sha256_verified: bool = True,
    byte_size_verified: bool = True,
    replayed_at: str | None = None,
) -> dict[str, Any]:
    return {
        "readback_state": readback_state,
        "object_key": object_metadata.object_key,
        "storage_backend": object_metadata.storage_backend,
        "object_present": object_present,
        "sha256_verified": sha256_verified,
        "byte_size_verified": byte_size_verified,
        "replayed_at": replayed_at,
    }


def manifest_from_payload(payload: Mapping[str, Any]) -> EvidenceSnapshotManifest:
    return EvidenceSnapshotManifest(
        snapshot_id=str(payload["snapshot_id"]),
        object_key=str(payload["object_key"]),
        source_url_optional=(
            str(payload["source_url_optional"])
            if payload.get("source_url_optional") not in (None, "")
            else None
        ),
        source_family_optional=(
            str(payload["source_family_optional"])
            if payload.get("source_family_optional") not in (None, "")
            else None
        ),
        snapshot_kind=str(payload["snapshot_kind"]),
        content_type=str(payload["content_type"]),
        byte_size=int(payload["byte_size"]),
        sha256=str(payload["sha256"]),
        lineage_refs={
            str(key): str(value)
            for key, value in dict(payload.get("lineage_refs", {})).items()
        },
        created_at=str(payload["created_at"]),
        storage_backend=str(payload.get("storage_backend", LOCAL_OBJECT_STORAGE_BACKEND)),
        replay_metadata=dict(payload.get("replay_metadata", {})),
    )


def stored_object_from_payload(payload: Mapping[str, Any]) -> StoredObjectMetadata:
    return StoredObjectMetadata(
        object_key=str(payload["object_key"]),
        content_type=str(payload["content_type"]),
        byte_size=int(payload["byte_size"]),
        sha256=str(payload["sha256"]),
        created_at=str(payload["created_at"]),
        storage_backend=str(payload.get("storage_backend", LOCAL_OBJECT_STORAGE_BACKEND)),
    )


__all__ = [
    "EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE",
    "LOCAL_OBJECT_STORAGE_BACKEND",
    "OBJECT_STORAGE_OBJECT_TYPE",
    "RESERVED_OBJECT_STORAGE_BACKENDS",
    "EvidenceSnapshotManifest",
    "LocalObjectStorage",
    "ObjectStorageBackendReservedError",
    "ObjectStorageError",
    "ObjectStorageIntegrityError",
    "ObjectStorageMissingError",
    "StoredObjectMetadata",
    "build_replay_metadata",
    "default_object_storage_path",
    "manifest_from_payload",
    "normalize_object_storage_backend_name",
    "stored_object_from_payload",
]
