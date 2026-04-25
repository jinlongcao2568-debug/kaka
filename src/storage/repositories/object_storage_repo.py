from __future__ import annotations

from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.object_storage import (
    EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE,
    LOCAL_OBJECT_STORAGE_BACKEND,
    OBJECT_STORAGE_OBJECT_TYPE,
    EvidenceSnapshotManifest,
    LocalObjectStorage,
    ObjectStorageMissingError,
    StoredObjectMetadata,
    build_replay_metadata,
    default_object_storage_path,
    manifest_from_payload,
    stored_object_from_payload,
)


class ObjectStorageRepository:
    def __init__(
        self,
        *,
        session: DatabaseSession | None = None,
        settings: Settings | None = None,
        object_store: LocalObjectStorage | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.session = session or DatabaseSession.default(settings=self.settings)
        self.object_store = object_store or LocalObjectStorage(
            root_path=default_object_storage_path(self.settings),
            backend=self.settings.object_storage_backend,
        )

    def put_object(
        self,
        data: bytes,
        *,
        content_type: str,
        object_key: str | None = None,
        created_at: str | None = None,
    ) -> StoredObjectMetadata:
        metadata = self.object_store.put_bytes(
            data,
            content_type=content_type,
            object_key=object_key,
            created_at=created_at,
        )
        self._persist_stored_object(metadata)
        return metadata

    def get_object_metadata(self, object_key: str) -> StoredObjectMetadata | None:
        record = self.session.get_record(OBJECT_STORAGE_OBJECT_TYPE, object_key)
        if record is None:
            return None
        return stored_object_from_payload(record.payload)

    def read_object(self, object_key: str) -> bytes:
        metadata = self.get_object_metadata(object_key)
        if metadata is None:
            raise ObjectStorageMissingError(f"object storage metadata {object_key!r} is missing")
        return self.object_store.read_bytes(
            object_key,
            expected_sha256=metadata.sha256,
            expected_byte_size=metadata.byte_size,
        )

    def save_snapshot(
        self,
        data: bytes,
        *,
        snapshot_id: str,
        snapshot_kind: str,
        content_type: str,
        source_url_optional: str | None = None,
        source_family_optional: str | None = None,
        lineage_refs: Mapping[str, str] | None = None,
        object_key: str | None = None,
        created_at: str | None = None,
    ) -> EvidenceSnapshotManifest:
        created = created_at or utc_now_iso()
        object_metadata = self.put_object(
            data,
            content_type=content_type,
            object_key=object_key,
            created_at=created,
        )
        manifest = EvidenceSnapshotManifest(
            snapshot_id=snapshot_id,
            object_key=object_metadata.object_key,
            source_url_optional=source_url_optional,
            source_family_optional=source_family_optional,
            snapshot_kind=snapshot_kind,
            content_type=object_metadata.content_type,
            byte_size=object_metadata.byte_size,
            sha256=object_metadata.sha256,
            lineage_refs={
                str(key): str(value)
                for key, value in dict(lineage_refs or {}).items()
                if value not in (None, "")
            },
            created_at=created,
            storage_backend=object_metadata.storage_backend,
            replay_metadata=build_replay_metadata(
                object_metadata=object_metadata,
                replayed_at=created,
            ),
        )
        self.save_manifest(manifest)
        return manifest

    def save_manifest(self, manifest: EvidenceSnapshotManifest) -> EvidenceSnapshotManifest:
        payload = manifest.as_payload()
        self.session.upsert_record(
            PersistedRecord(
                object_type=EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE,
                record_id=manifest.snapshot_id,
                stage_scope=0,
                project_id=manifest.lineage_refs.get("project_id"),
                object_refs={"object_key": manifest.object_key, **manifest.lineage_refs},
                decision_states={},
                trace_refs={
                    key: value
                    for key, value in manifest.lineage_refs.items()
                    if "trace" in key.lower()
                },
                audit_refs={
                    key: value
                    for key, value in manifest.lineage_refs.items()
                    if "audit" in key.lower()
                },
                governed_state={
                    "snapshot_kind": manifest.snapshot_kind,
                    "readback_state": manifest.replay_metadata.get("readback_state", "READBACK_READY"),
                    "external_service_connection_enabled": False,
                },
                writeback_state={},
                payload=payload,
                persisted_at=build_persisted_at(),
            )
        )
        return manifest

    def get_manifest(self, snapshot_id: str) -> EvidenceSnapshotManifest | None:
        record = self.session.get_record(EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE, snapshot_id)
        if record is None:
            return None
        return manifest_from_payload(record.payload)

    def read_snapshot_bytes(self, snapshot_id: str) -> bytes:
        manifest = self.get_manifest(snapshot_id)
        if manifest is None:
            raise ObjectStorageMissingError(f"snapshot manifest {snapshot_id!r} is missing")
        return self.object_store.read_bytes(
            manifest.object_key,
            expected_sha256=manifest.sha256,
            expected_byte_size=manifest.byte_size,
        )

    def replay_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        manifest = self.get_manifest(snapshot_id)
        if manifest is None:
            return {
                "snapshot_id": snapshot_id,
                "readback_state": "MISSING_MANIFEST",
                "manifest_present": False,
                "object_present": False,
                "external_service_connection_enabled": False,
            }
        try:
            data = self.object_store.read_bytes(
                manifest.object_key,
                expected_sha256=manifest.sha256,
                expected_byte_size=manifest.byte_size,
            )
        except ObjectStorageMissingError:
            return {
                "snapshot_id": snapshot_id,
                "readback_state": "MISSING_OBJECT",
                "manifest_present": True,
                "object_present": False,
                "object_key": manifest.object_key,
                "manifest": manifest.as_payload(),
                "external_service_connection_enabled": False,
            }

        return {
            "snapshot_id": snapshot_id,
            "readback_state": "READBACK_READY",
            "manifest_present": True,
            "object_present": True,
            "object_key": manifest.object_key,
            "content_type": manifest.content_type,
            "byte_size": manifest.byte_size,
            "sha256": manifest.sha256,
            "snapshot_kind": manifest.snapshot_kind,
            "lineage_refs": dict(manifest.lineage_refs),
            "manifest": manifest.as_payload(),
            "bytes": data,
            "external_service_connection_enabled": False,
        }

    def readiness_replay(self) -> dict[str, Any]:
        return {
            "active_object_storage_backend": LOCAL_OBJECT_STORAGE_BACKEND,
            "object_storage_backend": self.settings.object_storage_backend,
            "object_storage_path": str(self.object_store.root_path),
            "local_filesystem_executable": True,
            "manifest_repository_backed": True,
            "snapshot_readback_enabled": True,
            "snapshot_replay_enabled": True,
            "external_service_connection_enabled": False,
            "minio_connection_enabled": False,
            "s3_connection_enabled": False,
        }

    def _persist_stored_object(self, metadata: StoredObjectMetadata) -> None:
        self.session.upsert_record(
            PersistedRecord(
                object_type=OBJECT_STORAGE_OBJECT_TYPE,
                record_id=metadata.object_key,
                stage_scope=0,
                project_id=None,
                object_refs={"object_key": metadata.object_key},
                decision_states={},
                trace_refs={},
                audit_refs={},
                governed_state={
                    "storage_backend": metadata.storage_backend,
                    "content_type": metadata.content_type,
                },
                writeback_state={},
                payload=metadata.as_payload(),
                persisted_at=build_persisted_at(),
            )
        )


__all__ = ["ObjectStorageRepository"]
