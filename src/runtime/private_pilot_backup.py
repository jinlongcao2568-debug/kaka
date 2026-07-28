from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import uuid4


PRIVATE_PILOT_BACKUP_ID = "runtime.private_pilot_backup.v1"
PRIVATE_PILOT_BACKUP_MANIFEST_VERSION = 1
REQUIRED_SCHEMA_REVISION = "20260717_0002"
DATABASE_DUMP_FILENAME = "database.dump"
OBJECT_ARCHIVE_FILENAME = "objects.tar.gz"
OBJECT_INVENTORY_FILENAME = "objects-inventory.jsonl"
MANIFEST_FILENAME = "manifest.json"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$")
_SAFE_DATABASE_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,253}$")
_DATABASE_COUNT_QUERY = """
SELECT json_build_object(
  'records', (SELECT count(*) FROM records),
  'stage_states', (SELECT count(*) FROM stage_states),
  'work_items', (SELECT count(*) FROM work_items),
  'operator_actions', (SELECT count(*) FROM operator_actions),
  'worker_queue_items', (SELECT count(*) FROM worker_queue_items),
  'worker_queue_events', (SELECT count(*) FROM worker_queue_events)
)::text;
""".strip()
_CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class PrivatePilotBackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostgresConnectionConfig:
    host: str
    port: int
    user: str
    database: str
    password_file: Path

    def __post_init__(self) -> None:
        if not _SAFE_DATABASE_HOST.fullmatch(self.host):
            raise PrivatePilotBackupError("PostgreSQL host is invalid")
        if self.port < 1 or self.port > 65535:
            raise PrivatePilotBackupError("PostgreSQL port is invalid")
        for label, value in (("user", self.user), ("database", self.database)):
            if not _SAFE_IDENTIFIER.fullmatch(value):
                raise PrivatePilotBackupError(f"PostgreSQL {label} is invalid")
        if not self.password_file.is_file():
            raise PrivatePilotBackupError("PostgreSQL password file is missing")
        try:
            password_text = self.password_file.read_text(encoding="utf-8").strip()
        except UnicodeError as exc:
            raise PrivatePilotBackupError("PostgreSQL password file must be UTF-8 text") from exc
        if any(character in password_text for character in ("\r", "\n", "\0")):
            raise PrivatePilotBackupError("PostgreSQL password file contains an invalid character")
        password = password_text.encode("utf-8")
        if len(password) < 16 or len(password) > 4096:
            raise PrivatePilotBackupError(
                "PostgreSQL password file must contain between 16 and 4096 bytes"
            )


@dataclass(frozen=True)
class PrivatePilotBackupConfig:
    tenant_id: str
    instance_id: str
    postgres: PostgresConnectionConfig
    object_storage_root: Path
    backup_root: Path
    backup_id: str
    writers_paused_ack: str
    schedule_interval_seconds: int = 21_600
    rpo_target_seconds: int = 28_800

    def __post_init__(self) -> None:
        for label, value in (
            ("tenant_id", self.tenant_id),
            ("instance_id", self.instance_id),
            ("backup_id", self.backup_id),
        ):
            if not _SAFE_IDENTIFIER.fullmatch(value):
                raise PrivatePilotBackupError(f"backup {label} is invalid")
        if self.schedule_interval_seconds < 300 or self.schedule_interval_seconds > 604_800:
            raise PrivatePilotBackupError("backup schedule interval is outside 5m-7d")
        if self.rpo_target_seconds < self.schedule_interval_seconds:
            raise PrivatePilotBackupError(
                "RPO target cannot be shorter than the configured backup interval"
            )
        source_root = self.object_storage_root.resolve()
        backup_root = self.backup_root.resolve()
        expected_ack = f"WRITERS_PAUSED:{self.tenant_id}-{self.instance_id}"
        if not hmac_compare(self.writers_paused_ack, expected_ack):
            raise PrivatePilotBackupError(
                "backup requires the exact writers-paused acknowledgement"
            )
        if source_root == Path(source_root.anchor) or backup_root == Path(backup_root.anchor):
            raise PrivatePilotBackupError("backup roots cannot be filesystem roots")
        if not source_root.is_dir():
            raise PrivatePilotBackupError("object storage source root is missing")
        if source_root == backup_root or source_root in backup_root.parents or backup_root in source_root.parents:
            raise PrivatePilotBackupError(
                "backup root and object storage source must be separate directory trees"
            )
        if self.object_storage_root.is_symlink() or self.backup_root.is_symlink():
            raise PrivatePilotBackupError("backup roots cannot be symbolic links")

    @classmethod
    def from_env(cls) -> "PrivatePilotBackupConfig":
        tenant_id = _required_env("KAKA_DEPLOYMENT_TENANT_ID")
        instance_id = _required_env("KAKA_DEPLOYMENT_INSTANCE_ID")
        created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_id = str(os.getenv("KAKA_BACKUP_ID") or f"BACKUP-{tenant_id}-{instance_id}-{created}")
        return cls(
            tenant_id=tenant_id,
            instance_id=instance_id,
            postgres=_postgres_from_env(),
            object_storage_root=Path(_required_env("KAKA_BACKUP_OBJECT_STORAGE_ROOT")),
            backup_root=Path(_required_env("KAKA_BACKUP_ROOT")),
            backup_id=backup_id,
            writers_paused_ack=_required_env("KAKA_BACKUP_WRITERS_PAUSED_ACK"),
            schedule_interval_seconds=_env_int(
                "KAKA_BACKUP_SCHEDULE_INTERVAL_SECONDS",
                default=21_600,
                minimum=300,
                maximum=604_800,
            ),
            rpo_target_seconds=_env_int(
                "KAKA_BACKUP_RPO_TARGET_SECONDS",
                default=28_800,
                minimum=300,
                maximum=1_209_600,
            ),
        )


@dataclass(frozen=True)
class PrivatePilotRestoreConfig:
    backup_root: Path
    backup_id: str
    source_database_name: str
    target_postgres: PostgresConnectionConfig
    target_object_parent: Path
    report_root: Path
    isolated_ack: str
    rto_target_seconds: int = 3_600

    def __post_init__(self) -> None:
        if not _SAFE_IDENTIFIER.fullmatch(self.backup_id):
            raise PrivatePilotBackupError("restore backup_id is invalid")
        if not _SAFE_IDENTIFIER.fullmatch(self.source_database_name):
            raise PrivatePilotBackupError("restore source database name is invalid")
        if self.target_postgres.database == self.source_database_name:
            raise PrivatePilotBackupError("restore target database must differ from active source")
        expected_ack = f"RESTORE_ISOLATED:{self.target_postgres.database}"
        if not hmac_compare(self.isolated_ack, expected_ack):
            raise PrivatePilotBackupError(
                "isolated restore acknowledgement does not match the exact target database"
            )
        backup_root = self.backup_root.resolve()
        target_parent = self.target_object_parent.resolve()
        report_root = self.report_root.resolve()
        if backup_root == target_parent or backup_root in target_parent.parents or target_parent in backup_root.parents:
            raise PrivatePilotBackupError("restore object target must be separate from backup root")
        if target_parent == Path(target_parent.anchor) or report_root == Path(report_root.anchor):
            raise PrivatePilotBackupError("restore targets cannot be filesystem roots")
        if (
            backup_root == report_root
            or backup_root in report_root.parents
            or report_root in backup_root.parents
        ):
            raise PrivatePilotBackupError("restore report root must be separate from backup root")
        if self.target_object_parent.is_symlink() or self.report_root.is_symlink():
            raise PrivatePilotBackupError("restore targets cannot be symbolic links")
        if self.rto_target_seconds < 60 or self.rto_target_seconds > 86_400:
            raise PrivatePilotBackupError("RTO target is outside 1m-24h")

    @classmethod
    def from_env(cls) -> "PrivatePilotRestoreConfig":
        source_database = _required_env("KAKA_RESTORE_SOURCE_DATABASE_NAME")
        target_postgres = _postgres_from_env(prefix="KAKA_RESTORE_TARGET_DATABASE_")
        return cls(
            backup_root=Path(_required_env("KAKA_BACKUP_ROOT")),
            backup_id=_required_env("KAKA_BACKUP_ID"),
            source_database_name=source_database,
            target_postgres=target_postgres,
            target_object_parent=Path(_required_env("KAKA_RESTORE_TARGET_OBJECT_PARENT")),
            report_root=Path(_required_env("KAKA_RESTORE_REPORT_ROOT")),
            isolated_ack=_required_env("KAKA_RESTORE_ISOLATED_ACK"),
            rto_target_seconds=_env_int(
                "KAKA_RESTORE_RTO_TARGET_SECONDS",
                default=3_600,
                minimum=60,
                maximum=86_400,
            ),
        )


def create_private_pilot_backup(
    config: PrivatePilotBackupConfig,
    *,
    runner: _CommandRunner = subprocess.run,
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    started_at = _utc_now_iso()
    backup_root = config.backup_root.resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    final_dir = backup_root / config.backup_id
    if final_dir.exists():
        raise PrivatePilotBackupError("backup target already exists; backup IDs are immutable")
    partial_dir = backup_root / f".{config.backup_id}.{uuid4().hex}.partial"
    partial_dir.mkdir(parents=False, exist_ok=False)
    try:
        before_inventory = inventory_object_storage(config.object_storage_root)
        dump_path = partial_dir / DATABASE_DUMP_FILENAME
        with _postgres_password_environment(config.postgres) as pg_env:
            _run_checked(
                [
                    "pg_dump",
                    "--host",
                    config.postgres.host,
                    "--port",
                    str(config.postgres.port),
                    "--username",
                    config.postgres.user,
                    "--dbname",
                    config.postgres.database,
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    "--serializable-deferrable",
                    "--file",
                    str(dump_path),
                ],
                env=pg_env,
                runner=runner,
                timeout_seconds=3_600,
                operation="pg_dump",
            )
            schema_revision = _psql_scalar(
                config.postgres,
                "SELECT version_num FROM alembic_version LIMIT 1;",
                env=pg_env,
                runner=runner,
            )
            record_counts = json.loads(
                _psql_scalar(
                    config.postgres,
                    _DATABASE_COUNT_QUERY,
                    env=pg_env,
                    runner=runner,
                )
            )
        if schema_revision != REQUIRED_SCHEMA_REVISION:
            raise PrivatePilotBackupError(
                f"source schema revision {schema_revision!r} is not {REQUIRED_SCHEMA_REVISION!r}"
            )
        if not dump_path.is_file() or dump_path.stat().st_size == 0:
            raise PrivatePilotBackupError("pg_dump did not create a non-empty artifact")

        archive_path = partial_dir / OBJECT_ARCHIVE_FILENAME
        inventory_path = partial_dir / OBJECT_INVENTORY_FILENAME
        create_object_storage_archive(
            config.object_storage_root,
            archive_path=archive_path,
            inventory_path=inventory_path,
            inventory=before_inventory,
        )
        verify_object_storage_archive(
            archive_path,
            inventory_path=inventory_path,
        )
        after_inventory = inventory_object_storage(config.object_storage_root)
        if before_inventory != after_inventory:
            raise PrivatePilotBackupError(
                "object storage changed during backup; retry after pausing writers"
            )

        completed_at = _utc_now_iso()
        duration_seconds = round(time.monotonic() - started_monotonic, 3)
        worst_case_rpo_seconds = round(config.schedule_interval_seconds + duration_seconds, 3)
        artifacts = {
            DATABASE_DUMP_FILENAME: _file_descriptor(dump_path),
            OBJECT_ARCHIVE_FILENAME: _file_descriptor(archive_path),
            OBJECT_INVENTORY_FILENAME: _file_descriptor(inventory_path),
        }
        manifest: dict[str, Any] = {
            "manifest_version": PRIVATE_PILOT_BACKUP_MANIFEST_VERSION,
            "backup_runtime_id": PRIVATE_PILOT_BACKUP_ID,
            "backup_id": config.backup_id,
            "backup_state": "COMPLETE",
            "source_tenant_id": config.tenant_id,
            "source_instance_id": config.instance_id,
            "source_database_name": config.postgres.database,
            "source_schema_revision": schema_revision,
            "source_object_storage_kind": "local-filesystem-content-backup",
            "started_at": started_at,
            "completed_at": completed_at,
            "backup_duration_seconds": duration_seconds,
            "database_record_counts": _normalized_counts(record_counts),
            "object_inventory_summary": {
                "file_count": len(before_inventory),
                "total_bytes": sum(int(item["byte_size"]) for item in before_inventory),
                "inventory_sha256": _sha256_file(inventory_path),
            },
            "artifacts": artifacts,
            "consistency": {
                "database_consistent_snapshot": True,
                "pg_dump_serializable_deferrable": True,
                "object_inventory_stable_before_after": True,
                "application_writers_paused_by_tool": False,
                "operator_writers_paused_acknowledged": True,
            },
            "rpo": {
                "target_seconds": config.rpo_target_seconds,
                "configured_schedule_interval_seconds": config.schedule_interval_seconds,
                "estimated_worst_case_seconds": worst_case_rpo_seconds,
                "target_met_by_estimate": worst_case_rpo_seconds <= config.rpo_target_seconds,
                "measurement_mode": "CONFIG_PLUS_ACTUAL_BACKUP_DURATION",
                "recurring_schedule_observation_required": True,
            },
            "rto": {
                "measured_restore_seconds": None,
                "restore_drill_required": True,
            },
            "active_storage_mutated": False,
            "external_release_enabled": False,
        }
        manifest["manifest_sha256"] = compute_backup_manifest_hash(manifest)
        _write_json_atomic(partial_dir / MANIFEST_FILENAME, manifest)
        os.replace(partial_dir, final_dir)
        return {**manifest, "backup_directory": str(final_dir)}
    except Exception:
        shutil.rmtree(partial_dir, ignore_errors=True)
        raise


def restore_private_pilot_backup_isolated(
    config: PrivatePilotRestoreConfig,
    *,
    runner: _CommandRunner = subprocess.run,
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    started_at = _utc_now_iso()
    backup_dir = (config.backup_root.resolve() / config.backup_id).resolve()
    if backup_dir.parent != config.backup_root.resolve():
        raise PrivatePilotBackupError("backup ID escapes backup root")
    manifest = validate_private_pilot_backup(backup_dir)
    if manifest["source_database_name"] != config.source_database_name:
        raise PrivatePilotBackupError("restore source database does not match backup manifest")

    target_object_root = (config.target_object_parent.resolve() / config.backup_id).resolve()
    if target_object_root.parent != config.target_object_parent.resolve():
        raise PrivatePilotBackupError("restore object target escapes configured parent")
    if target_object_root.exists():
        raise PrivatePilotBackupError("isolated restore object target already exists")
    report_path = config.report_root.resolve() / f"{config.backup_id}-restore-report.json"
    if report_path.exists():
        raise PrivatePilotBackupError("restore report already exists")
    target_object_root.parent.mkdir(parents=True, exist_ok=True)
    extract_verified_object_archive(
        backup_dir / OBJECT_ARCHIVE_FILENAME,
        inventory_path=backup_dir / OBJECT_INVENTORY_FILENAME,
        target_root=target_object_root,
    )

    try:
        with _postgres_password_environment(config.target_postgres) as pg_env:
            _run_checked(
                [
                    "pg_restore",
                    "--host",
                    config.target_postgres.host,
                    "--port",
                    str(config.target_postgres.port),
                    "--username",
                    config.target_postgres.user,
                    "--dbname",
                    config.target_postgres.database,
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    str(backup_dir / DATABASE_DUMP_FILENAME),
                ],
                env=pg_env,
                runner=runner,
                timeout_seconds=3_600,
                operation="pg_restore",
            )
            restored_revision = _psql_scalar(
                config.target_postgres,
                "SELECT version_num FROM alembic_version LIMIT 1;",
                env=pg_env,
                runner=runner,
            )
            restored_counts = _normalized_counts(
                json.loads(
                    _psql_scalar(
                        config.target_postgres,
                        _DATABASE_COUNT_QUERY,
                        env=pg_env,
                        runner=runner,
                    )
                )
            )
        expected_counts = _normalized_counts(manifest["database_record_counts"])
        if restored_revision != manifest["source_schema_revision"]:
            raise PrivatePilotBackupError("restored schema revision does not match backup")
        if restored_counts != expected_counts:
            raise PrivatePilotBackupError("restored database record counts do not match backup")
    except Exception:
        # The target is isolated and intentionally retained for forensic inspection.
        raise

    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    report = {
        "report_version": 1,
        "backup_runtime_id": PRIVATE_PILOT_BACKUP_ID,
        "backup_id": config.backup_id,
        "restore_state": "VALIDATED_ISOLATED_RESTORE",
        "started_at": started_at,
        "completed_at": _utc_now_iso(),
        "rto": {
            "target_seconds": config.rto_target_seconds,
            "measured_restore_seconds": duration_seconds,
            "target_met": duration_seconds <= config.rto_target_seconds,
            "measurement_mode": "ACTUAL_ISOLATED_RESTORE_DRILL",
        },
        "restored_schema_revision": restored_revision,
        "restored_database_record_counts": restored_counts,
        "restored_object_inventory": dict(manifest["object_inventory_summary"]),
        "target_database_name": config.target_postgres.database,
        "target_object_root": str(target_object_root),
        "isolated_target": True,
        "active_database_mutated": False,
        "active_object_storage_mutated": False,
        "active_cutover_executed": False,
        "rollback_release_image_required_separately": True,
    }
    config.report_root.resolve().mkdir(parents=True, exist_ok=True)
    _write_json_atomic(report_path, report)
    return {**report, "report_path": str(report_path)}


def validate_private_pilot_backup(backup_dir: Path) -> dict[str, Any]:
    resolved = backup_dir.resolve()
    manifest_path = resolved / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise PrivatePilotBackupError("backup manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrivatePilotBackupError("backup manifest is unreadable or invalid") from exc
    if not isinstance(manifest, Mapping):
        raise PrivatePilotBackupError("backup manifest must be an object")
    payload = dict(manifest)
    if payload.get("manifest_version") != PRIVATE_PILOT_BACKUP_MANIFEST_VERSION:
        raise PrivatePilotBackupError("backup manifest version is unsupported")
    if payload.get("backup_state") != "COMPLETE":
        raise PrivatePilotBackupError("backup manifest is not complete")
    expected_hash = compute_backup_manifest_hash(payload)
    if not hmac_compare(str(payload.get("manifest_sha256") or ""), expected_hash):
        raise PrivatePilotBackupError("backup manifest hash mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise PrivatePilotBackupError("backup artifact descriptors are missing")
    for filename in (DATABASE_DUMP_FILENAME, OBJECT_ARCHIVE_FILENAME, OBJECT_INVENTORY_FILENAME):
        descriptor = artifacts.get(filename)
        if not isinstance(descriptor, Mapping):
            raise PrivatePilotBackupError(f"backup artifact descriptor is missing: {filename}")
        artifact_path = resolved / filename
        if not artifact_path.is_file():
            raise PrivatePilotBackupError(f"backup artifact is missing: {filename}")
        if artifact_path.stat().st_size != int(descriptor.get("byte_size") or -1):
            raise PrivatePilotBackupError(f"backup artifact size mismatch: {filename}")
        if not hmac_compare(_sha256_file(artifact_path), str(descriptor.get("sha256") or "")):
            raise PrivatePilotBackupError(f"backup artifact hash mismatch: {filename}")
    return payload


def inventory_object_storage(root: Path) -> list[dict[str, Any]]:
    resolved = root.resolve()
    if not resolved.is_dir() or resolved.is_symlink():
        raise PrivatePilotBackupError("object storage root is not a safe directory")
    inventory: list[dict[str, Any]] = []
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise PrivatePilotBackupError("object storage cannot contain symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(resolved).as_posix()
        if not _safe_relative_path(relative):
            raise PrivatePilotBackupError("object storage contains an unsafe path")
        inventory.append(
            {
                "path": relative,
                "byte_size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return inventory


def create_object_storage_archive(
    source_root: Path,
    *,
    archive_path: Path,
    inventory_path: Path,
    inventory: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    resolved_source = source_root.resolve()
    resolved_inventory = [dict(item) for item in (inventory or inventory_object_storage(source_root))]
    inventory_path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for item in resolved_inventory
        ),
        encoding="utf-8",
    )
    with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for item in resolved_inventory:
            relative = str(item["path"])
            source = (resolved_source / relative).resolve()
            if source.parent != resolved_source and resolved_source not in source.parents:
                raise PrivatePilotBackupError("object archive source escapes root")
            if not source.is_file() or source.is_symlink():
                raise PrivatePilotBackupError("object archive source changed or is unsafe")
            archive.add(source, arcname=relative, recursive=False)


def extract_verified_object_archive(
    archive_path: Path,
    *,
    inventory_path: Path,
    target_root: Path,
) -> list[dict[str, Any]]:
    if target_root.exists():
        raise PrivatePilotBackupError("object restore target must not already exist")
    inventory = _load_inventory(inventory_path)
    expected_by_path = {str(item["path"]): dict(item) for item in inventory}
    target_root.mkdir(parents=True, exist_ok=False)
    extracted: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                name = member.name.replace("\\", "/")
                if not _safe_relative_path(name):
                    raise PrivatePilotBackupError("object archive contains an unsafe path")
                if member.isdir():
                    (target_root / name).mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile() or member.issym() or member.islnk():
                    raise PrivatePilotBackupError("object archive contains a non-regular entry")
                if name not in expected_by_path or name in extracted:
                    raise PrivatePilotBackupError("object archive and inventory do not match")
                destination = (target_root / name).resolve()
                if target_root.resolve() not in destination.parents:
                    raise PrivatePilotBackupError("object archive target escapes restore root")
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise PrivatePilotBackupError("object archive entry cannot be read")
                with source, destination.open("xb") as handle:
                    shutil.copyfileobj(source, handle, length=1024 * 1024)
                descriptor = expected_by_path[name]
                if destination.stat().st_size != int(descriptor["byte_size"]):
                    raise PrivatePilotBackupError("restored object size mismatch")
                if not hmac_compare(_sha256_file(destination), str(descriptor["sha256"])):
                    raise PrivatePilotBackupError("restored object hash mismatch")
                extracted.add(name)
        if extracted != set(expected_by_path):
            raise PrivatePilotBackupError("object archive is missing inventoried files")
        return inventory
    except Exception:
        shutil.rmtree(target_root, ignore_errors=True)
        raise


def verify_object_storage_archive(
    archive_path: Path,
    *,
    inventory_path: Path,
) -> None:
    inventory = _load_inventory(inventory_path)
    expected_by_path = {str(item["path"]): dict(item) for item in inventory}
    observed: set[str] = set()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            name = member.name.replace("\\", "/")
            if not _safe_relative_path(name):
                raise PrivatePilotBackupError("object archive contains an unsafe path")
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise PrivatePilotBackupError("object archive contains a non-regular entry")
            if name not in expected_by_path or name in observed:
                raise PrivatePilotBackupError("object archive and inventory do not match")
            source = archive.extractfile(member)
            if source is None:
                raise PrivatePilotBackupError("object archive entry cannot be read")
            digest = hashlib.sha256()
            byte_size = 0
            with source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    byte_size += len(chunk)
            descriptor = expected_by_path[name]
            if byte_size != int(descriptor["byte_size"]):
                raise PrivatePilotBackupError("archived object size mismatch")
            if not hmac_compare(digest.hexdigest(), str(descriptor["sha256"])):
                raise PrivatePilotBackupError("archived object hash mismatch")
            observed.add(name)
    if observed != set(expected_by_path):
        raise PrivatePilotBackupError("object archive is missing inventoried files")


def compute_backup_manifest_hash(manifest: Mapping[str, Any]) -> str:
    canonical = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_inventory(path: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PrivatePilotBackupError("object inventory is unreadable") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PrivatePilotBackupError(
                f"object inventory is invalid at line {line_number}"
            ) from exc
        if not isinstance(item, Mapping):
            raise PrivatePilotBackupError("object inventory entry is invalid")
        relative = str(item.get("path") or "")
        sha256 = str(item.get("sha256") or "")
        byte_size = item.get("byte_size")
        if (
            not _safe_relative_path(relative)
            or relative in seen
            or not re.fullmatch(r"[a-f0-9]{64}", sha256)
            or not isinstance(byte_size, int)
            or byte_size < 0
        ):
            raise PrivatePilotBackupError("object inventory entry failed validation")
        seen.add(relative)
        inventory.append({"path": relative, "byte_size": byte_size, "sha256": sha256})
    return inventory


@contextmanager
def _postgres_password_environment(config: PostgresConnectionConfig) -> Iterator[dict[str, str]]:
    password = config.password_file.read_text(encoding="utf-8").strip()
    escaped = password.replace("\\", "\\\\").replace(":", "\\:")
    fd, name = tempfile.mkstemp(prefix="kaka-pgpass-", suffix=".conf")
    pgpass = Path(name)
    try:
        os.write(
            fd,
            f"{config.host}:{config.port}:{config.database}:{config.user}:{escaped}\n".encode(
                "utf-8"
            ),
        )
        os.close(fd)
        os.chmod(pgpass, 0o600)
        env = dict(os.environ)
        env.pop("PGPASSWORD", None)
        env["PGPASSFILE"] = str(pgpass)
        yield env
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        pgpass.unlink(missing_ok=True)


def _psql_scalar(
    config: PostgresConnectionConfig,
    query: str,
    *,
    env: Mapping[str, str],
    runner: _CommandRunner,
) -> str:
    result = _run_checked(
        [
            "psql",
            "--host",
            config.host,
            "--port",
            str(config.port),
            "--username",
            config.user,
            "--dbname",
            config.database,
            "--no-password",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
            "--command",
            query,
        ],
        env=env,
        runner=runner,
        timeout_seconds=120,
        operation="psql_validation",
    )
    value = str(result.stdout or "").strip()
    if not value:
        raise PrivatePilotBackupError("psql validation returned an empty result")
    return value


def _run_checked(
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    runner: _CommandRunner,
    timeout_seconds: int,
    operation: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            list(args),
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PrivatePilotBackupError(f"{operation} could not execute: {type(exc).__name__}") from exc
    if result.returncode != 0:
        raise PrivatePilotBackupError(f"{operation} failed with exit code {result.returncode}")
    return result


def _postgres_from_env(prefix: str = "KAKA_STORAGE_DATABASE_") -> PostgresConnectionConfig:
    return PostgresConnectionConfig(
        host=_required_env(f"{prefix}HOST"),
        port=_env_int(f"{prefix}PORT", default=5432, minimum=1, maximum=65535),
        user=_required_env(f"{prefix}USER"),
        database=_required_env(f"{prefix}NAME"),
        password_file=Path(_required_env(f"{prefix}PASSWORD_FILE")),
    )


def _required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise PrivatePilotBackupError(f"{name} is required")
    return value


def _env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise PrivatePilotBackupError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise PrivatePilotBackupError(f"{name} is outside the supported range")
    return value


def _file_descriptor(path: Path) -> dict[str, Any]:
    return {"byte_size": path.stat().st_size, "sha256": _sha256_file(path)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: str) -> bool:
    path = Path(str(value or "").replace("\\", "/"))
    return bool(value) and not path.is_absolute() and ".." not in path.parts and path.as_posix() not in {"", "."}


def _normalized_counts(value: Mapping[str, Any]) -> dict[str, int]:
    expected_keys = {
        "records",
        "stage_states",
        "work_items",
        "operator_actions",
        "worker_queue_items",
        "worker_queue_events",
    }
    if set(value) != expected_keys:
        raise PrivatePilotBackupError("database record count payload is incomplete")
    normalized = {key: int(value[key]) for key in sorted(expected_keys)}
    if any(count < 0 for count in normalized.values()):
        raise PrivatePilotBackupError("database record counts cannot be negative")
    return normalized


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(str(left), str(right))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kaka private-pilot backup and isolated restore")
    parser.add_argument("mode", choices=("backup", "restore-isolated", "validate"))
    args = parser.parse_args(argv)
    try:
        if args.mode == "backup":
            result = create_private_pilot_backup(PrivatePilotBackupConfig.from_env())
        elif args.mode == "restore-isolated":
            result = restore_private_pilot_backup_isolated(PrivatePilotRestoreConfig.from_env())
        else:
            root = Path(_required_env("KAKA_BACKUP_ROOT"))
            backup_id = _required_env("KAKA_BACKUP_ID")
            result = validate_private_pilot_backup(root / backup_id)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "backup_runtime_id": PRIVATE_PILOT_BACKUP_ID,
                    "state": "FAILED_CLOSED",
                    "error_category": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PRIVATE_PILOT_BACKUP_ID",
    "PostgresConnectionConfig",
    "PrivatePilotBackupConfig",
    "PrivatePilotBackupError",
    "PrivatePilotRestoreConfig",
    "compute_backup_manifest_hash",
    "create_object_storage_archive",
    "create_private_pilot_backup",
    "extract_verified_object_archive",
    "inventory_object_storage",
    "restore_private_pilot_backup_isolated",
    "validate_private_pilot_backup",
    "verify_object_storage_archive",
]
