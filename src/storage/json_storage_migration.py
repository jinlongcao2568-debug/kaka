from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord


MIGRATION_MANIFEST_OBJECT_TYPE = "storage_migration_manifest"
MIGRATION_MANIFEST_VERSION = 1


def default_json_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "internal_operator_loop_store.json"


def default_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def migrate_json_storage_to_database(
    *,
    source_path: str | Path | None = None,
    database_url: str,
    object_storage_path: str | Path | None = None,
    target_backend: str = "postgresql",
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    source = Path(source_path) if source_path is not None else default_json_storage_path()
    object_root = (
        Path(object_storage_path)
        if object_storage_path is not None
        else default_object_storage_path()
    )
    source_settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(source),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_root),
    )
    target_settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_root),
    )
    source_session = DatabaseSession(settings=source_settings)
    target_session = DatabaseSession(settings=target_settings)
    try:
        plan = build_json_storage_migration_plan(
            source_session=source_session,
            target_session=target_session,
            source_path=source,
            object_storage_path=object_root,
            target_backend=target_backend,
            database_url=database_url,
            created_at=created_at,
        )
        if execute:
            _execute_migration_plan(
                source_session=source_session,
                target_session=target_session,
                plan=plan,
            )
            after_plan = build_json_storage_migration_plan(
                source_session=source_session,
                target_session=target_session,
                source_path=source,
                object_storage_path=object_root,
                target_backend=target_backend,
                database_url=database_url,
                created_at=created_at,
            )
            plan["target_counts_after"] = after_plan["target_counts_before"]
            plan["post_execute_plan_counts"] = after_plan["plan_counts"]
            plan["execution"] = {
                "executed": True,
                "write_mode": "append_safe_upsert",
                "target_mutation_enabled": True,
            }
        else:
            plan["execution"] = {
                "executed": False,
                "write_mode": "dry_run",
                "target_mutation_enabled": False,
            }
        return plan
    finally:
        source_session.close()
        target_session.close()


def build_json_storage_migration_plan(
    *,
    source_session: DatabaseSession,
    target_session: DatabaseSession,
    source_path: Path,
    object_storage_path: Path,
    target_backend: str,
    database_url: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    source_snapshot = source_session.export_backup_snapshot(
        exclude_record_object_types=(MIGRATION_MANIFEST_OBJECT_TYPE,)
    )
    target_snapshot = target_session.export_backup_snapshot(
        exclude_record_object_types=(MIGRATION_MANIFEST_OBJECT_TYPE,)
    )
    append_only = _append_only_plan(
        source_actions=source_snapshot["operator_actions"],
        target_actions=target_snapshot["operator_actions"],
        source_worker_events=source_snapshot["worker_queue_events"],
        target_worker_events=target_snapshot["worker_queue_events"],
    )
    source_hash = _sha256_file(source_path) if source_path.exists() else None
    object_inventory = _object_storage_inventory(object_storage_path)
    record_plan = _record_plan(source_snapshot["records"], target_snapshot["records"])
    stage_state_plan = _keyed_plan(
        source_snapshot["stage_states"],
        target_snapshot["stage_states"],
        key_fields=("stage_scope", "surface_id", "root_record_id"),
    )
    work_item_plan = _keyed_plan(
        source_snapshot["work_items"],
        target_snapshot["work_items"],
        key_fields=("work_item_id",),
    )
    worker_queue_item_plan = _keyed_plan(
        source_snapshot["worker_queue_items"],
        target_snapshot["worker_queue_items"],
        key_fields=("queue_item_id",),
    )
    blocking_reasons = list(append_only["blocking_reasons"])
    if not source_path.exists():
        blocking_reasons.append("source_json_storage_missing")
    manifest_record_id = _migration_manifest_record_id(source_hash, source_path)
    summary = {
        "migration_kind": "json-file-to-database",
        "migration_manifest_version": MIGRATION_MANIFEST_VERSION,
        "migration_record": {
            "object_type": MIGRATION_MANIFEST_OBJECT_TYPE,
            "record_id": manifest_record_id,
        },
        "created_at": created,
        "source": {
            "storage_backend": "json-file",
            "storage_path": str(source_path),
            "storage_exists": source_path.exists(),
            "storage_sha256": source_hash,
            "storage_byte_size": source_path.stat().st_size if source_path.exists() else 0,
            "object_storage_path": str(object_storage_path),
            "object_storage_inventory": object_inventory,
        },
        "target": {
            "storage_backend": target_backend,
            "database_url_redacted": _redact_database_url(database_url),
        },
        "source_counts": _snapshot_counts(source_snapshot),
        "target_counts_before": _snapshot_counts(target_snapshot),
        "plan_counts": {
            "records": record_plan,
            "stage_states": stage_state_plan,
            "work_items": work_item_plan,
            "operator_actions": append_only["operator_actions"],
            "worker_queue_items": worker_queue_item_plan,
            "worker_queue_events": append_only["worker_queue_events"],
        },
        "safety": {
            "destructive_target_clear_enabled": False,
            "source_mutation_enabled": False,
            "large_object_blob_database_import_enabled": False,
            "object_storage_files_stay_in_object_storage": True,
            "append_only_conflict_policy": "block_on_same_id_different_payload",
            "external_service_connection_enabled": False,
        },
        "blocking_reasons": blocking_reasons,
        "safe_to_execute": not blocking_reasons,
    }
    summary["migration_manifest"] = _build_migration_manifest_payload(summary)
    return summary


def _execute_migration_plan(
    *,
    source_session: DatabaseSession,
    target_session: DatabaseSession,
    plan: dict[str, Any],
) -> None:
    if not plan.get("safe_to_execute"):
        reasons = ", ".join(plan.get("blocking_reasons", []))
        raise RuntimeError(f"storage migration is not safe to execute: {reasons}")
    snapshot = source_session.export_backup_snapshot(
        exclude_record_object_types=(MIGRATION_MANIFEST_OBJECT_TYPE,)
    )
    existing_actions = _operator_action_index(target_session.list_all_operator_actions())
    existing_worker_events = _worker_queue_event_index(target_session.list_all_worker_queue_events())
    with target_session.bulk_write():
        for record in snapshot["records"]:
            target_session.upsert_record(record)
        for stage_state in snapshot["stage_states"]:
            target_session.upsert_stage_state(stage_state)
        for work_item in snapshot["work_items"]:
            target_session.upsert_work_item(work_item)
        for action in snapshot["operator_actions"]:
            key = (action.work_item_id, action.action_event_id)
            if key not in existing_actions:
                target_session.append_operator_action(action)
        for queue_item in snapshot["worker_queue_items"]:
            target_session.upsert_worker_queue_item(queue_item)
        for event in snapshot["worker_queue_events"]:
            key = (event.queue_item_id, event.event_id)
            if key not in existing_worker_events:
                target_session.append_worker_queue_event(event)
        manifest_record = _migration_manifest_record(plan)
        target_session.upsert_record(manifest_record)


def _migration_manifest_record(plan: dict[str, Any]) -> PersistedRecord:
    manifest = dict(plan["migration_manifest"])
    return PersistedRecord(
        object_type=MIGRATION_MANIFEST_OBJECT_TYPE,
        record_id=str(plan["migration_record"]["record_id"]),
        stage_scope=0,
        project_id=None,
        object_refs={
            "source_storage_path": str(plan["source"]["storage_path"]),
            "object_storage_path": str(plan["source"]["object_storage_path"]),
        },
        decision_states={"migration_decision_state": "EXECUTED"},
        trace_refs={},
        audit_refs={"migration_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "INTERNAL_STORAGE_MIGRATED",
            "approval_state": "INTERNAL_OPERATOR_ACTION",
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "source_mutation_enabled": False,
            "destructive_target_clear_enabled": False,
        },
        payload=manifest,
        persisted_at=str(plan["created_at"]),
    )


def _build_migration_manifest_payload(plan: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "migration_kind": plan["migration_kind"],
        "migration_manifest_version": plan["migration_manifest_version"],
        "migration_record": dict(plan["migration_record"]),
        "created_at": plan["created_at"],
        "source": dict(plan["source"]),
        "target": dict(plan["target"]),
        "source_counts": dict(plan["source_counts"]),
        "plan_counts": dict(plan["plan_counts"]),
        "safety": dict(plan["safety"]),
        "blocking_reasons": list(plan["blocking_reasons"]),
        "safe_to_execute": bool(plan["safe_to_execute"]),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


def _record_plan(source_rows: Iterable[Any], target_rows: Iterable[Any]) -> dict[str, int]:
    source_by_key = {
        (row.object_type, row.record_id): row
        for row in source_rows
    }
    target_by_key = {
        (row.object_type, row.record_id): row
        for row in target_rows
    }
    return _compare_indexed_payloads(source_by_key, target_by_key)


def _keyed_plan(source_rows: Iterable[Any], target_rows: Iterable[Any], *, key_fields: tuple[str, ...]) -> dict[str, int]:
    source_by_key = {_object_key(row, key_fields): row for row in source_rows}
    target_by_key = {_object_key(row, key_fields): row for row in target_rows}
    return _compare_indexed_payloads(source_by_key, target_by_key)


def _compare_indexed_payloads(source_by_key: dict[tuple[Any, ...], Any], target_by_key: dict[tuple[Any, ...], Any]) -> dict[str, int]:
    inserted = 0
    updated = 0
    unchanged = 0
    for key, source_row in source_by_key.items():
        target_row = target_by_key.get(key)
        if target_row is None:
            inserted += 1
        elif asdict(source_row) == asdict(target_row):
            unchanged += 1
        else:
            updated += 1
    return {
        "source": len(source_by_key),
        "target_existing": len(target_by_key),
        "to_insert": inserted,
        "to_update": updated,
        "unchanged": unchanged,
        "to_upsert": inserted + updated,
    }


def _append_only_plan(
    *,
    source_actions: Iterable[Any],
    target_actions: Iterable[Any],
    source_worker_events: Iterable[Any],
    target_worker_events: Iterable[Any],
) -> dict[str, Any]:
    action_plan, action_conflicts = _append_only_key_plan(
        source_actions,
        target_actions,
        key_fields=("work_item_id", "action_event_id"),
    )
    event_plan, event_conflicts = _append_only_key_plan(
        source_worker_events,
        target_worker_events,
        key_fields=("queue_item_id", "event_id"),
    )
    blocking = []
    if action_conflicts:
        blocking.append("operator_action_append_conflict")
    if event_conflicts:
        blocking.append("worker_queue_event_append_conflict")
    return {
        "operator_actions": action_plan,
        "worker_queue_events": event_plan,
        "conflicts": {
            "operator_actions": action_conflicts,
            "worker_queue_events": event_conflicts,
        },
        "blocking_reasons": blocking,
    }


def _append_only_key_plan(source_rows: Iterable[Any], target_rows: Iterable[Any], *, key_fields: tuple[str, ...]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    source_by_key = {_object_key(row, key_fields): row for row in source_rows}
    target_by_key = {_object_key(row, key_fields): row for row in target_rows}
    to_append = 0
    skipped = 0
    conflicts: list[dict[str, Any]] = []
    for key, source_row in source_by_key.items():
        target_row = target_by_key.get(key)
        if target_row is None:
            to_append += 1
            continue
        if asdict(source_row) == asdict(target_row):
            skipped += 1
            continue
        conflicts.append({"key": [str(part) for part in key], "reason": "same_append_id_different_payload"})
    return (
        {
            "source": len(source_by_key),
            "target_existing": len(target_by_key),
            "to_append": to_append,
            "skipped_existing": skipped,
            "conflict_count": len(conflicts),
        },
        conflicts,
    )


def _operator_action_index(rows: Iterable[Any]) -> set[tuple[str, str]]:
    return {
        (str(row.work_item_id), str(row.action_event_id))
        for row in rows
    }


def _worker_queue_event_index(rows: Iterable[Any]) -> set[tuple[str, str]]:
    return {
        (str(row.queue_item_id), str(row.event_id))
        for row in rows
    }


def _object_key(row: Any, key_fields: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(getattr(row, field_name) for field_name in key_fields)


def _snapshot_counts(snapshot: dict[str, list[Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for record in snapshot["records"]:
        by_type[record.object_type] = by_type.get(record.object_type, 0) + 1
    return {
        "records": len(snapshot["records"]),
        "records_by_object_type": dict(sorted(by_type.items())),
        "stage_states": len(snapshot["stage_states"]),
        "work_items": len(snapshot["work_items"]),
        "operator_actions": len(snapshot["operator_actions"]),
        "worker_queue_items": len(snapshot["worker_queue_items"]),
        "worker_queue_events": len(snapshot["worker_queue_events"]),
    }


def _object_storage_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "file_count": 0,
            "byte_size": 0,
        }
    files = [entry for entry in path.rglob("*") if entry.is_file()]
    return {
        "exists": True,
        "file_count": len(files),
        "byte_size": sum(entry.stat().st_size for entry in files),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _migration_manifest_record_id(source_hash: str | None, source_path: Path) -> str:
    if source_hash:
        suffix = source_hash[:16]
    else:
        suffix = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:16]
    return f"JSON-TO-DB-{suffix}"


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate kaka json-file storage into database envelope tables.")
    parser.add_argument("--source-path", default=str(default_json_storage_path()))
    parser.add_argument("--object-storage-path", default=str(default_object_storage_path()))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = migrate_json_storage_to_database(
        source_path=args.source_path,
        database_url=args.database_url,
        object_storage_path=args.object_storage_path,
        target_backend=args.target_backend,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        mode = "EXECUTED" if result["execution"]["executed"] else "DRY_RUN"
        print(f"storage migration {mode}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["plan_counts"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())
