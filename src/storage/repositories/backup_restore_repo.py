from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from shared.settings import Settings
from storage.backup_restore import (
    BACKUP_MANIFEST_OBJECT_TYPE,
    build_backup_manifest,
    build_restore_dry_run,
    build_rollback_readiness,
    validate_backup_manifest,
)
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


class BackupRestoreRepository:
    def __init__(
        self,
        *,
        session: DatabaseSession | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.session = session or DatabaseSession.default(settings=self.settings)

    def create_manifest(
        self,
        *,
        backup_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        manifest = build_backup_manifest(
            session=self.session,
            settings=self.settings,
            backup_id=backup_id,
            created_at=created_at,
        )
        return self.save_manifest(manifest)

    def save_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(manifest)
        backup_id = str(payload["backup_id"])
        validation = validate_backup_manifest(payload)
        self.session.upsert_record(
            PersistedRecord(
                object_type=BACKUP_MANIFEST_OBJECT_TYPE,
                record_id=backup_id,
                stage_scope=0,
                project_id=None,
                object_refs={
                    "backup_id": backup_id,
                    "manifest_hash": str(payload.get("manifest_hash", "")),
                },
                decision_states={
                    "manifest_valid": str(validation["manifest_valid"]),
                    "restore_mode": "DRY_RUN_ONLY",
                },
                trace_refs={
                    "backup_id": backup_id,
                    "manifest_hash": str(payload.get("manifest_hash", "")),
                },
                audit_refs={
                    "backup_id": backup_id,
                    "audit_required": str(payload.get("audit_required", True)),
                },
                governed_state={
                    "approval_required": bool(payload.get("approval_required", True)),
                    "audit_required": bool(payload.get("audit_required", True)),
                    "external_service_connection_enabled": False,
                    "destructive_restore_enabled": False,
                },
                writeback_state={},
                payload=payload,
                persisted_at=build_persisted_at(),
            )
        )
        return payload

    def get_manifest(self, backup_id: str) -> dict[str, Any] | None:
        record = self.session.get_record(BACKUP_MANIFEST_OBJECT_TYPE, backup_id)
        if record is None:
            return None
        return dict(record.payload)

    def readback_manifest(self, backup_id: str) -> dict[str, Any]:
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return {
                "backup_id": backup_id,
                "manifest_present": False,
                "manifest_valid": False,
                "external_service_connection_enabled": False,
            }
        validation = validate_backup_manifest(manifest)
        return {
            "backup_id": backup_id,
            "manifest_present": True,
            "manifest_valid": validation["manifest_valid"],
            "manifest_validation": validation,
            "manifest": manifest,
            "record_counts": dict(manifest.get("record_counts", {})),
            "included_scopes": list(manifest.get("included_scopes", [])),
            "approval_required": True,
            "audit_required": True,
            "external_service_connection_enabled": False,
            "destructive_restore_enabled": False,
        }

    def restore_dry_run(
        self,
        backup_id: str,
        *,
        target_path: str | Path | None = None,
        conflict_policy: str = "review-required",
        object_storage_root_optional: str | Path | None = None,
    ) -> dict[str, Any]:
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return {
                "restore_mode": "DRY_RUN_ONLY",
                "backup_id": backup_id,
                "manifest_validation": {
                    "manifest_valid": False,
                    "missing_fields": ["manifest"],
                    "hash_valid": False,
                    "actual_hash": "",
                    "expected_hash": "",
                    "external_service_connection_enabled": False,
                },
                "restore_plan": {
                    "target_path": str(target_path) if target_path is not None else None,
                    "conflict_policy": conflict_policy,
                    "missing_object_refs": [],
                    "review_required_object_refs": [],
                },
                "safe_to_restore": False,
                "destructive_restore_enabled": False,
                "restore_execution_enabled": False,
                "active_storage_write_enabled": False,
                "active_storage_mutation_enabled": False,
                "approval_required": True,
                "audit_required": True,
                "external_service_connection_enabled": False,
                "blocking_reasons": ["backup_manifest_not_found"],
            }
        return build_restore_dry_run(
            manifest,
            target_path=target_path,
            conflict_policy=conflict_policy,
            object_storage_root_optional=object_storage_root_optional,
        )

    def rollback_readiness(
        self,
        backup_id: str | None = None,
        *,
        rollback_point: str | None = None,
        target_path: str | Path | None = None,
    ) -> dict[str, Any]:
        manifest = self.get_manifest(backup_id) if backup_id else None
        return build_rollback_readiness(
            manifest=manifest,
            rollback_point=rollback_point,
            target_path=target_path,
        )


__all__ = ["BackupRestoreRepository"]
