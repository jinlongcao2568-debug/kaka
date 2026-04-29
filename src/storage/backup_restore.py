from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession
from storage.object_storage import (
    EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE,
    LOCAL_OBJECT_STORAGE_BACKEND,
    OBJECT_STORAGE_OBJECT_TYPE,
)


BACKUP_MANIFEST_OBJECT_TYPE = "backup_restore_manifest"
BACKUP_MANIFEST_VERSION = 1
DEFAULT_CONFLICT_POLICY = "review-required"
INCLUDED_BACKUP_SCOPES = [
    "PersistedRecord",
    "PersistedStageState",
    "PersistedWorkItem",
    "PersistedOperatorAction",
    "worker_queue_state",
    "object_storage_metadata",
    "object_storage_refs",
]
REQUIRED_MANIFEST_FIELDS = (
    "backup_id",
    "created_at",
    "source_storage_backend",
    "object_storage_root_optional",
    "included_scopes",
    "record_counts",
    "storage_record_refs",
    "object_refs_summary",
    "controlled_opening_requirements",
    "approval_required",
    "audit_required",
    "external_service_connection_enabled",
    "manifest_hash",
    "sha256",
)


def build_backup_manifest(
    *,
    session: DatabaseSession | None = None,
    settings: Settings | None = None,
    backup_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    resolved_settings = settings or _settings_from_session(session)
    resolved_session = session or DatabaseSession.default(settings=resolved_settings)
    created = created_at or utc_now_iso()
    resolved_backup_id = backup_id or _default_backup_id(created)
    snapshot = resolved_session.export_backup_snapshot(
        exclude_record_object_types=(BACKUP_MANIFEST_OBJECT_TYPE,)
    )
    records = sorted(snapshot["records"], key=lambda row: (row.object_type, row.record_id))
    stage_states = sorted(
        snapshot["stage_states"],
        key=lambda row: (row.stage_scope, row.surface_id, row.root_record_id),
    )
    work_items = sorted(snapshot["work_items"], key=lambda row: row.work_item_id)
    operator_actions = sorted(
        snapshot["operator_actions"],
        key=lambda row: (row.work_item_id, row.action_event_id),
    )
    worker_queue_items = sorted(
        snapshot["worker_queue_items"],
        key=lambda row: row.queue_item_id,
    )
    worker_queue_events = sorted(
        snapshot["worker_queue_events"],
        key=lambda row: (row.queue_item_id, row.event_id),
    )
    record_counts = _record_counts(
        records=records,
        stage_states=stage_states,
        work_items=work_items,
        operator_actions=operator_actions,
        worker_queue_items=worker_queue_items,
        worker_queue_events=worker_queue_events,
    )
    object_storage_refs = _object_storage_refs(records)
    manifest: dict[str, Any] = {
        "manifest_version": BACKUP_MANIFEST_VERSION,
        "backup_id": resolved_backup_id,
        "created_at": created,
        "source_storage_backend": resolved_session.storage_backend,
        "source_storage_path_optional": str(resolved_session.storage_path),
        "object_storage_backend": resolved_settings.object_storage_backend,
        "object_storage_root_optional": str(resolved_settings.resolved_object_storage_path()),
        "included_scopes": list(INCLUDED_BACKUP_SCOPES),
        "record_counts": record_counts,
        "storage_record_refs": _storage_record_refs(records),
        "object_refs_summary": _object_refs_summary(
            records=records,
            stage_states=stage_states,
            work_items=work_items,
            operator_actions=operator_actions,
            worker_queue_items=worker_queue_items,
            object_storage_refs=object_storage_refs,
        ),
        "worker_queue_state_summary": _worker_queue_state_summary(
            worker_queue_items=worker_queue_items,
            worker_queue_events=worker_queue_events,
        ),
        "controlled_opening_requirements": backup_restore_controlled_opening_requirements(),
        "approval_required": True,
        "audit_required": True,
        "external_service_connection_enabled": False,
        "external_backup_service_enabled": False,
        "destructive_restore_enabled": False,
        "restore_dry_run_only": True,
    }
    manifest_hash = compute_manifest_hash(manifest)
    manifest["manifest_hash"] = manifest_hash
    manifest["sha256"] = manifest_hash
    return manifest


def validate_backup_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    missing_fields = [
        field_name
        for field_name in REQUIRED_MANIFEST_FIELDS
        if field_name not in manifest
    ]
    expected_hash = compute_manifest_hash(manifest)
    actual_hash = str(manifest.get("manifest_hash") or manifest.get("sha256") or "")
    hash_valid = bool(actual_hash) and actual_hash == expected_hash
    return {
        "manifest_valid": not missing_fields and hash_valid,
        "missing_fields": missing_fields,
        "hash_valid": hash_valid,
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "approval_required": bool(manifest.get("approval_required", True)),
        "audit_required": bool(manifest.get("audit_required", True)),
        "external_service_connection_enabled": False,
    }


def build_restore_dry_run(
    manifest: Mapping[str, Any],
    *,
    target_path: str | Path | None = None,
    conflict_policy: str = DEFAULT_CONFLICT_POLICY,
    object_storage_root_optional: str | Path | None = None,
) -> dict[str, Any]:
    validation = validate_backup_manifest(manifest)
    target = Path(target_path) if target_path is not None else None
    root_value = object_storage_root_optional or manifest.get("object_storage_root_optional")
    object_storage_root = Path(root_value) if root_value not in (None, "") else None
    object_ref_review, object_ref_blocking = _validate_object_refs_for_restore(
        manifest,
        object_storage_root=object_storage_root,
    )
    blocking_reasons: list[str] = []
    review_required_reasons = [
        "approval_required=true",
        "audit_required=true",
        "destructive_restore_enabled=false",
        "safe_to_restore=false_by_default",
    ]
    if validation["missing_fields"]:
        blocking_reasons.append("manifest_missing_required_fields")
    if not validation["hash_valid"]:
        blocking_reasons.append("manifest_hash_mismatch")
    if object_ref_blocking:
        blocking_reasons.append("missing_or_invalid_object_refs")
    if object_ref_review:
        review_required_reasons.append("object_refs_require_manual_review")
    if target is None:
        review_required_reasons.append("target_path_not_configured")
    elif target.exists() and conflict_policy != "append-only-new-path":
        review_required_reasons.append("target_path_conflict_requires_manual_review")

    return {
        "restore_mode": "DRY_RUN_ONLY",
        "backup_id": manifest.get("backup_id"),
        "manifest_validation": validation,
        "restore_plan": {
            "target_path": str(target) if target is not None else None,
            "target_path_exists": bool(target.exists()) if target is not None else False,
            "conflict_policy": conflict_policy,
            "source_storage_backend": manifest.get("source_storage_backend"),
            "included_scopes": list(manifest.get("included_scopes", [])),
            "record_counts": dict(manifest.get("record_counts", {})),
            "steps": [
                "validate_manifest_hash",
                "review_target_path_and_conflict_policy",
                "verify_object_storage_refs",
                "require_manual_approval_and_audit_before_any_restore",
            ],
            "missing_object_refs": object_ref_blocking,
            "review_required_object_refs": object_ref_review,
        },
        "safe_to_restore": False,
        "destructive_restore_enabled": False,
        "active_storage_write_enabled": False,
        "active_storage_mutation_enabled": False,
        "current_active_storage_mutation_enabled": False,
        "approval_required": True,
        "audit_required": True,
        "external_service_connection_enabled": False,
        "migration_execution_enabled": False,
        "blocking_reasons": blocking_reasons,
        "review_required_reasons": review_required_reasons,
        "controlled_opening_requirements": backup_restore_controlled_opening_requirements(),
    }


def build_rollback_readiness(
    *,
    manifest: Mapping[str, Any] | None = None,
    rollback_point: str | None = None,
    target_path: str | Path | None = None,
) -> dict[str, Any]:
    backup_id = manifest.get("backup_id") if manifest else None
    resolved_point = rollback_point or str(backup_id or "BACKUP_MANIFEST_REQUIRED")
    return {
        "rollback_point": resolved_point,
        "rollback_plan": {
            "source_backup_id": backup_id,
            "target_path": str(target_path) if target_path is not None else None,
            "restore_mode": "dry-run-only",
            "conflict_policy": DEFAULT_CONFLICT_POLICY,
            "steps": [
                "select_backup_manifest",
                "run_restore_dry_run",
                "review_missing_object_refs",
                "obtain_manual_approval",
                "record_audit_before_any_future_restore_execution",
            ],
        },
        "rollback_state": "REVIEW_REQUIRED",
        "safe_to_restore": False,
        "approval_required": True,
        "audit_required": True,
        "external_service_connection_enabled": False,
        "destructive_restore_enabled": False,
        "restore_execution_enabled": False,
        "rollback_execution_enabled": False,
        "active_storage_mutation_enabled": False,
        "current_active_storage_mutation_enabled": False,
        "migration_execution_enabled": False,
        "provider_execution_enabled": False,
        "real_payment_delivery_enabled": False,
        "automated_refund_enabled": False,
        "external_release_enabled": False,
        "controlled_opening_requirements": backup_restore_controlled_opening_requirements(),
    }


def backup_restore_controlled_opening_requirements() -> dict[str, bool]:
    return {
        "external_backup_service_enabled": False,
        "external_service_connection_enabled": False,
        "destructive_restore_enabled": False,
        "current_active_storage_mutation_enabled": False,
        "active_storage_mutation_enabled": False,
        "migration_execution_enabled": False,
        "real_provider_execution_enabled": False,
        "real_sales_outreach_enabled": False,
        "real_payment_enabled": False,
        "real_charge_enabled": False,
        "real_delivery_enabled": False,
        "real_refund_enabled": False,
        "automated_refund_enabled": False,
        "external_software_release_enabled": False,
    }


def compute_manifest_hash(manifest: Mapping[str, Any]) -> str:
    canonical_payload = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifest_hash", "sha256"}
    }
    encoded = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _settings_from_session(session: DatabaseSession | None) -> Settings:
    if session is not None and getattr(session, "_settings", None) is not None:
        return session._settings
    return Settings.from_env()


def _default_backup_id(created_at: str) -> str:
    compact = "".join(ch for ch in created_at if ch.isdigit())
    suffix = hashlib.sha256(created_at.encode("utf-8")).hexdigest()[:8]
    return f"BACKUP-{compact[:14]}-{suffix}"


def _record_counts(
    *,
    records: list[Any],
    stage_states: list[Any],
    work_items: list[Any],
    operator_actions: list[Any],
    worker_queue_items: list[Any],
    worker_queue_events: list[Any],
) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for record in records:
        by_type[record.object_type] = by_type.get(record.object_type, 0) + 1
    return {
        "PersistedRecord": len(records),
        "PersistedRecord_by_object_type": dict(sorted(by_type.items())),
        "PersistedStageState": len(stage_states),
        "PersistedWorkItem": len(work_items),
        "PersistedOperatorAction": len(operator_actions),
        "worker_queue_items": len(worker_queue_items),
        "worker_queue_events": len(worker_queue_events),
        "object_storage_metadata": by_type.get(OBJECT_STORAGE_OBJECT_TYPE, 0),
        "evidence_snapshot_manifests": by_type.get(EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE, 0),
    }


def _storage_record_refs(records: list[Any]) -> dict[str, Any]:
    by_type: dict[str, list[str]] = {}
    for record in records:
        by_type.setdefault(record.object_type, []).append(record.record_id)
    return {
        "total": len(records),
        "by_object_type": {
            object_type: sorted(record_ids)
            for object_type, record_ids in sorted(by_type.items())
        },
        "sample_refs": [
            {"object_type": record.object_type, "record_id": record.record_id}
            for record in records[:50]
        ],
    }


def _object_storage_refs(records: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for record in records:
        if record.object_type not in {
            OBJECT_STORAGE_OBJECT_TYPE,
            EVIDENCE_SNAPSHOT_MANIFEST_OBJECT_TYPE,
        }:
            continue
        object_key = record.payload.get("object_key")
        if object_key in (None, ""):
            continue
        refs.append(
            {
                "source_object_type": record.object_type,
                "source_record_id": record.record_id,
                "object_key": str(object_key),
                "sha256": record.payload.get("sha256"),
                "byte_size": record.payload.get("byte_size"),
                "storage_backend": record.payload.get("storage_backend", LOCAL_OBJECT_STORAGE_BACKEND),
            }
        )
    return sorted(
        refs,
        key=lambda row: (str(row["object_key"]), str(row["source_record_id"])),
    )


def _object_refs_summary(
    *,
    records: list[Any],
    stage_states: list[Any],
    work_items: list[Any],
    operator_actions: list[Any],
    worker_queue_items: list[Any],
    object_storage_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    storage_record_object_refs = sum(len(record.object_refs) for record in records)
    stage_typed_refs = sum(len(row.typed_object_refs) for row in stage_states)
    work_item_refs = sum(len(row.object_refs) for row in work_items)
    action_refs = sum(len(row.object_refs) for row in operator_actions)
    queue_refs = sum(len(row.trace_refs) + len(row.audit_refs) for row in worker_queue_items)
    object_keys = sorted({str(row["object_key"]) for row in object_storage_refs})
    return {
        "storage_record_object_ref_count": storage_record_object_refs,
        "stage_state_typed_ref_count": stage_typed_refs,
        "work_item_object_ref_count": work_item_refs,
        "operator_action_object_ref_count": action_refs,
        "worker_queue_trace_audit_ref_count": queue_refs,
        "object_storage_ref_count": len(object_storage_refs),
        "object_storage_refs": object_storage_refs,
        "object_keys": object_keys,
    }


def _worker_queue_state_summary(
    *,
    worker_queue_items: list[Any],
    worker_queue_events: list[Any],
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_queue: dict[str, int] = {}
    for item in worker_queue_items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_queue[item.queue_name] = by_queue.get(item.queue_name, 0) + 1
    return {
        "queue_item_count": len(worker_queue_items),
        "queue_event_count": len(worker_queue_events),
        "by_status": dict(sorted(by_status.items())),
        "by_queue": dict(sorted(by_queue.items())),
        "state_persistence_enabled": True,
        "audit_replay_enabled": True,
    }


def _validate_object_refs_for_restore(
    manifest: Mapping[str, Any],
    *,
    object_storage_root: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs = list(manifest.get("object_refs_summary", {}).get("object_storage_refs", []))
    review_required: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    if not refs:
        return review_required, blocking
    if object_storage_root is None:
        for ref in refs:
            review_required.append({**dict(ref), "reason": "object_storage_root_not_configured"})
        return review_required, blocking
    root = object_storage_root.resolve()
    for raw_ref in refs:
        ref = dict(raw_ref)
        object_key = str(ref.get("object_key", ""))
        try:
            path = _safe_object_path(root, object_key)
        except ValueError:
            blocking.append({**ref, "reason": "object_key_escapes_root"})
            continue
        if not path.exists():
            blocking.append({**ref, "reason": "object_missing"})
            continue
        expected_size = ref.get("byte_size")
        if expected_size is not None and path.stat().st_size != int(expected_size):
            blocking.append({**ref, "reason": "object_byte_size_mismatch"})
            continue
        expected_hash = ref.get("sha256")
        if expected_hash:
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_hash != str(expected_hash):
                blocking.append({**ref, "reason": "object_sha256_mismatch"})
    return review_required, blocking


def _safe_object_path(root: Path, object_key: str) -> Path:
    key_path = Path(object_key.strip().replace("\\", "/"))
    if not object_key or key_path.is_absolute() or ".." in key_path.parts:
        raise ValueError("invalid object key")
    candidate = (root / key_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("object key escapes root")
    return candidate


__all__ = [
    "BACKUP_MANIFEST_OBJECT_TYPE",
    "DEFAULT_CONFLICT_POLICY",
    "INCLUDED_BACKUP_SCOPES",
    "backup_restore_controlled_opening_requirements",
    "build_backup_manifest",
    "build_restore_dry_run",
    "build_rollback_readiness",
    "compute_manifest_hash",
    "validate_backup_manifest",
]
