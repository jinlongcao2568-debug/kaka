from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from storage.object_storage import (
    LOCAL_OBJECT_STORAGE_BACKEND,
    RESERVED_OBJECT_STORAGE_BACKENDS,
    normalize_object_storage_backend_name,
)


DEFAULT_STORAGE_BACKEND = "json-file"
SQLITE_STORAGE_BACKEND = "sqlite"
SQLALCHEMY_STORAGE_BACKEND = "sqlalchemy"
POSTGRESQL_STORAGE_BACKEND = "postgresql"
POSTGRESQL_STORAGE_ALIASES = frozenset({"postgres", "postgresql"})
EXECUTABLE_STORAGE_BACKENDS = (
    DEFAULT_STORAGE_BACKEND,
    SQLITE_STORAGE_BACKEND,
    SQLALCHEMY_STORAGE_BACKEND,
    POSTGRESQL_STORAGE_BACKEND,
)

READINESS_EXECUTABLE = "EXECUTABLE"
READINESS_NOT_CONFIGURED = "NOT_CONFIGURED"
READINESS_CONFIG_REQUIRED = "CONFIG_REQUIRED"
READINESS_DRIVER_MISSING = "DRIVER_MISSING"
READINESS_RESERVED_NOT_LIVE = "RESERVED_NOT_LIVE"

_RESERVED_BACKEND_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "backend": "alembic",
        "category": "migration",
        "configured_aliases": (),
        "why_not_live": "reserved for future migration design; current packet must not create or run migrations",
    },
    {
        "backend": "redis",
        "category": "queue-broker",
        "configured_aliases": ("redis",),
        "why_not_live": "reserved for future external queue broker design; current packet must not connect to external services",
    },
    {
        "backend": "dramatiq",
        "category": "queue-worker",
        "configured_aliases": ("dramatiq",),
        "why_not_live": "reserved for future external worker process design; current packet must not run external queue workers",
    },
    {
        "backend": "minio",
        "category": "object-storage",
        "configured_aliases": ("minio",),
        "why_not_live": "reserved for future object storage design; current packet must not connect to external services",
    },
    {
        "backend": "s3",
        "category": "object-storage",
        "configured_aliases": ("s3",),
        "why_not_live": "reserved for future object storage design; current packet must not connect to external services",
    },
    {
        "backend": "docker-compose",
        "category": "composition",
        "configured_aliases": ("docker-compose",),
        "why_not_live": "local stack configuration is static readiness metadata only; current packet must not run compose runtime",
    },
)


def normalize_storage_backend_name(value: str | None) -> str:
    backend = (value or "").strip().lower()
    if backend == "postgres":
        return POSTGRESQL_STORAGE_BACKEND
    return backend


def storage_database_url_dialect(database_url: str | None) -> str | None:
    if not database_url:
        return None
    scheme = urlsplit(database_url).scheme.strip().lower()
    if not scheme:
        return None
    return scheme.split("+", 1)[0]


def is_postgresql_database_url(database_url: str | None) -> bool:
    return storage_database_url_dialect(database_url) in POSTGRESQL_STORAGE_ALIASES


def redact_database_url(database_url: str | None) -> str | None:
    if not database_url:
        return None
    parsed = urlsplit(database_url)
    if not parsed.netloc or not (parsed.username or parsed.password):
        return database_url

    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    user = parsed.username or "user"
    redacted = parsed._replace(netloc=f"{user}:***@{host}")
    return urlunsplit(redacted)


def build_platform_infra_readiness(
    *,
    storage_backend: str,
    storage_database_url_optional: str | None,
    queue_backend: str = "storage",
    worker_runtime: str = "internal-storage-worker",
    object_storage_backend: str = LOCAL_OBJECT_STORAGE_BACKEND,
    object_storage_path_optional: str | None = None,
    repo_root: str | None = None,
) -> dict[str, Any]:
    active_backend = normalize_storage_backend_name(storage_backend)
    active_object_storage_backend = normalize_object_storage_backend_name(object_storage_backend)
    sqlalchemy_available = find_spec("sqlalchemy") is not None
    database_url_configured = bool(storage_database_url_optional)
    database_url_dialect = storage_database_url_dialect(storage_database_url_optional)
    sqlalchemy_readiness = _sqlalchemy_readiness(
        active_backend=active_backend,
        sqlalchemy_available=sqlalchemy_available,
        database_url_configured=database_url_configured,
        database_url_dialect=database_url_dialect,
    )
    postgresql_readiness = _postgresql_readiness(
        active_backend=active_backend,
        sqlalchemy_available=sqlalchemy_available,
        database_url_configured=database_url_configured,
        database_url_dialect=database_url_dialect,
    )
    reserved_backends = _reserved_backend_readiness(
        active_backend,
        active_object_storage_backend=active_object_storage_backend,
    )
    reserved_by_backend = {entry["backend"]: entry for entry in reserved_backends}
    worker_queue_bootstrap = _worker_queue_bootstrap_readiness(
        queue_backend=queue_backend,
        worker_runtime=worker_runtime,
        active_storage_backend=active_backend,
        reserved_by_backend=reserved_by_backend,
    )
    compose_readiness = _compose_local_stack_readiness(
        repo_root=repo_root,
        active_backend=active_backend,
        active_object_storage_backend=active_object_storage_backend,
        reserved_by_backend=reserved_by_backend,
    )

    return {
        "active_backend": active_backend,
        "storage_database_url_configured": database_url_configured,
        "storage_database_url_redacted": redact_database_url(storage_database_url_optional),
        "storage_database_url_dialect": database_url_dialect,
        "executable_backends": [
            _json_file_readiness(active_backend),
            _sqlite_readiness(active_backend),
            sqlalchemy_readiness,
            postgresql_readiness,
        ],
        "reserved_backends": reserved_backends,
        "backend_policy": {
            "unsupported_backend_fast_fail": True,
            "missing_database_url_fast_fail": True,
            "no_silent_fallback": True,
            "no_migration_execution": True,
            "no_external_service_connection": True,
            "internal_durable_queue_enabled": True,
            "local_object_storage_enabled": active_object_storage_backend == LOCAL_OBJECT_STORAGE_BACKEND,
            "snapshot_manifest_durability_enabled": True,
            "readback_only": True,
            "runtime_behavior_changed": False,
        },
        "sqlalchemy_readiness": sqlalchemy_readiness,
        "postgresql_readiness": postgresql_readiness,
        "migration_readiness": {
            "backend": "alembic",
            "readiness_state": reserved_by_backend["alembic"]["readiness_state"],
            "executable": False,
            "configured": reserved_by_backend["alembic"]["configured"],
            "migration_execution_enabled": False,
            "schema_metadata_defined": True,
            "why_not_live": reserved_by_backend["alembic"]["why_not_live"],
        },
        "queue_readiness": {
            "queue_backend": worker_queue_bootstrap["queue_backend"],
            "effective_queue_backend": worker_queue_bootstrap["effective_queue_backend"],
            "internal_durable_queue": {
                "backend": "storage",
                "readiness_state": READINESS_EXECUTABLE,
                "executable": True,
                "repository_backed": True,
                "active_storage_backend": active_backend,
                "state_persistence_enabled": True,
                "audit_replay_enabled": True,
            },
            "external_backends": ["redis", "dramatiq"],
            "readiness_state": _combined_reserved_state(reserved_by_backend, ("redis", "dramatiq")),
            "executable": False,
            "configured": any(reserved_by_backend[backend]["configured"] for backend in ("redis", "dramatiq")),
            "external_service_connection_enabled": False,
            "redis_connection_enabled": False,
            "dramatiq_worker_enabled": False,
            "why_not_live": "Redis/Dramatiq are reserved readback only in the current packet",
        },
        "worker_runtime_readiness": {
            "worker_runtime": worker_queue_bootstrap["worker_runtime"],
            "readiness_state": READINESS_EXECUTABLE,
            "executable": True,
            "lease_persistence_enabled": True,
            "heartbeat_persistence_enabled": True,
            "attempt_count_persistence_enabled": True,
            "retry_persistence_enabled": True,
            "timeout_recovery_enabled": True,
            "suspend_resume_persistence_enabled": True,
            "dead_letter_persistence_enabled": True,
            "audit_replay_enabled": True,
            "stage1_scheduler_enabled": False,
            "external_worker_process_enabled": False,
            "real_provider_execution_enabled": False,
        },
        "worker_queue_bootstrap": worker_queue_bootstrap,
        "object_storage_readiness": _object_storage_readiness(
            active_object_storage_backend=active_object_storage_backend,
            object_storage_path_optional=object_storage_path_optional,
            reserved_by_backend=reserved_by_backend,
        ),
        "compose_readiness": compose_readiness,
        "local_stack_readiness": compose_readiness,
        "redlines": {
            "no_live_provider_call": True,
            "no_real_sales_outreach": True,
            "no_real_payment": True,
            "no_real_charge": True,
            "no_real_delivery": True,
            "no_real_refund": True,
            "no_automated_refund": True,
            "compose_runtime_enabled": False,
            "container_execution_enabled": False,
            "docker_compose_up_executed": False,
            "real_provider_execution_enabled": False,
            "real_payment_delivery_enabled": False,
            "automated_refund_enabled": False,
            "external_software_release_enabled": False,
        },
    }


def _json_file_readiness(active_backend: str) -> dict[str, Any]:
    return {
        "backend": DEFAULT_STORAGE_BACKEND,
        "readiness_state": READINESS_EXECUTABLE,
        "executable": True,
        "configured": active_backend == DEFAULT_STORAGE_BACKEND,
        "requires_database_url": False,
    }


def _sqlite_readiness(active_backend: str) -> dict[str, Any]:
    return {
        "backend": SQLITE_STORAGE_BACKEND,
        "readiness_state": READINESS_EXECUTABLE,
        "executable": True,
        "configured": active_backend == SQLITE_STORAGE_BACKEND,
        "requires_database_url": False,
    }


def _sqlalchemy_readiness(
    *,
    active_backend: str,
    sqlalchemy_available: bool,
    database_url_configured: bool,
    database_url_dialect: str | None,
) -> dict[str, Any]:
    configured = active_backend == SQLALCHEMY_STORAGE_BACKEND
    readiness_state = _sql_backend_state(
        configured=configured,
        driver_available=sqlalchemy_available,
        database_url_configured=database_url_configured,
    )
    return {
        "backend": SQLALCHEMY_STORAGE_BACKEND,
        "readiness_state": readiness_state,
        "executable": readiness_state == READINESS_EXECUTABLE,
        "configured": configured,
        "driver_available": sqlalchemy_available,
        "database_url_configured": database_url_configured,
        "database_url_dialect": database_url_dialect,
        "requires_database_url": True,
        "adapter": "sqlalchemy-core",
        "readback_level": "seam_config_and_repository_envelope",
        "local_contract_dialect": "sqlite",
        "migration_execution_enabled": False,
        "no_silent_fallback": True,
    }


def _postgresql_readiness(
    *,
    active_backend: str,
    sqlalchemy_available: bool,
    database_url_configured: bool,
    database_url_dialect: str | None,
) -> dict[str, Any]:
    configured = active_backend == POSTGRESQL_STORAGE_BACKEND
    readiness_state = _sql_backend_state(
        configured=configured,
        driver_available=sqlalchemy_available,
        database_url_configured=database_url_configured,
    )
    if configured and database_url_configured and database_url_dialect not in POSTGRESQL_STORAGE_ALIASES:
        readiness_state = READINESS_CONFIG_REQUIRED

    return {
        "backend": POSTGRESQL_STORAGE_BACKEND,
        "aliases": ["postgres"],
        "readiness_state": readiness_state,
        "executable": readiness_state == READINESS_EXECUTABLE,
        "configured": configured,
        "driver_available": sqlalchemy_available,
        "database_url_configured": database_url_configured,
        "database_url_dialect": database_url_dialect,
        "requires_database_url": True,
        "adapter": "sqlalchemy-core",
        "readback_level": "seam_config_and_repository_envelope",
        "migration_execution_enabled": False,
        "live_ready": False,
        "no_silent_fallback": True,
    }


def _sql_backend_state(
    *,
    configured: bool,
    driver_available: bool,
    database_url_configured: bool,
) -> str:
    if not configured:
        return READINESS_NOT_CONFIGURED
    if not driver_available:
        return READINESS_DRIVER_MISSING
    if not database_url_configured:
        return READINESS_CONFIG_REQUIRED
    return READINESS_EXECUTABLE


def _reserved_backend_readiness(
    active_backend: str,
    *,
    active_object_storage_backend: str,
) -> list[dict[str, Any]]:
    reserved_backends: list[dict[str, Any]] = []
    for definition in _RESERVED_BACKEND_DEFINITIONS:
        backend = str(definition["backend"])
        configured_aliases = tuple(str(alias) for alias in definition["configured_aliases"])
        configured = active_backend in configured_aliases
        if backend in RESERVED_OBJECT_STORAGE_BACKENDS:
            configured = active_object_storage_backend in configured_aliases
        reserved_backends.append(
            {
                "backend": backend,
                "readiness_state": READINESS_RESERVED_NOT_LIVE if configured else READINESS_NOT_CONFIGURED,
                "executable": False,
                "configured": configured,
                "why_not_live": str(definition["why_not_live"]),
                "category": str(definition["category"]),
            }
        )
    return reserved_backends


def _object_storage_readiness(
    *,
    active_object_storage_backend: str,
    object_storage_path_optional: str | None,
    reserved_by_backend: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    local_active = active_object_storage_backend == LOCAL_OBJECT_STORAGE_BACKEND
    minio_s3_state = _combined_reserved_state(reserved_by_backend, ("minio", "s3"))
    return {
        "active_backend": active_object_storage_backend,
        "effective_backend": LOCAL_OBJECT_STORAGE_BACKEND if local_active else active_object_storage_backend,
        "backends": [LOCAL_OBJECT_STORAGE_BACKEND, "minio", "s3"],
        "readiness_state": READINESS_EXECUTABLE if local_active else minio_s3_state,
        "executable": local_active,
        "configured": True,
        "storage_path": object_storage_path_optional,
        "storage_backend": LOCAL_OBJECT_STORAGE_BACKEND,
        "local_filesystem": {
            "backend": LOCAL_OBJECT_STORAGE_BACKEND,
            "readiness_state": READINESS_EXECUTABLE,
            "executable": True,
            "configured": local_active,
            "storage_path": object_storage_path_optional,
            "byte_persistence_enabled": True,
            "readback_enabled": True,
        },
        "snapshot_durability": {
            "readiness_state": READINESS_EXECUTABLE if local_active else READINESS_RESERVED_NOT_LIVE,
            "manifest_repository_backed": True,
            "metadata_backend": "existing_storage_records",
            "content_addressed_object_keys": True,
            "content_type_recorded": True,
            "byte_size_recorded": True,
            "sha256_recorded": True,
            "lineage_refs_recorded": True,
            "created_at_recorded": True,
            "readback_replay_enabled": local_active,
            "fail_closed_on_missing_object": True,
        },
        "reserved_backends": [
            dict(reserved_by_backend["minio"]),
            dict(reserved_by_backend["s3"]),
        ],
        "minio_reserved_state": reserved_by_backend["minio"]["readiness_state"],
        "s3_reserved_state": reserved_by_backend["s3"]["readiness_state"],
        "connection_enabled": False,
        "external_service_connection_enabled": False,
        "minio_connection_enabled": False,
        "s3_connection_enabled": False,
        "why_not_live": "Object storage is local-filesystem only in this packet; MinIO/S3 are reserved readiness metadata and never connected",
    }


def _combined_reserved_state(
    reserved_by_backend: dict[str, dict[str, Any]],
    backends: tuple[str, ...],
) -> str:
    if any(reserved_by_backend[backend]["configured"] for backend in backends):
        return READINESS_RESERVED_NOT_LIVE
    return READINESS_NOT_CONFIGURED


def _repo_root(repo_root: str | None) -> Path:
    if repo_root:
        return Path(repo_root)
    return Path(__file__).resolve().parents[2]


def _compose_local_stack_readiness(
    *,
    repo_root: str | None,
    active_backend: str,
    active_object_storage_backend: str,
    reserved_by_backend: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    root = _repo_root(repo_root)
    dockerfile_present = (root / "Dockerfile").is_file()
    compose_file_present = (root / "docker-compose.yml").is_file()
    dockerignore_present = (root / ".dockerignore").is_file()
    config_present = dockerfile_present and compose_file_present and dockerignore_present
    local_stack_services = [
        {
            "service": "app",
            "role": "local_runtime_bootstrap",
            "profile": "default",
            "readiness_state": "CONFIG_PRESENT" if config_present else READINESS_NOT_CONFIGURED,
            "configured": config_present,
            "local_stack_only": True,
            "container_execution_enabled": False,
            "external_service_connection_enabled": False,
            "real_provider_execution_enabled": False,
        },
        {
            "service": "postgres",
            "role": "reserved_local_database",
            "profile": "reserved-local-deps",
            "readiness_state": READINESS_RESERVED_NOT_LIVE,
            "configured": False,
            "local_stack_only": True,
            "container_execution_enabled": False,
            "external_service_connection_enabled": False,
            "migration_execution_enabled": False,
        },
        {
            "service": "redis",
            "role": "reserved_local_queue_broker",
            "profile": "reserved-local-deps",
            "readiness_state": READINESS_RESERVED_NOT_LIVE,
            "configured": False,
            "local_stack_only": True,
            "container_execution_enabled": False,
            "external_service_connection_enabled": False,
            "redis_connection_enabled": False,
        },
        {
            "service": "minio",
            "role": "reserved_local_object_storage",
            "profile": "reserved-local-deps",
            "readiness_state": READINESS_RESERVED_NOT_LIVE,
            "configured": False,
            "local_stack_only": True,
            "container_execution_enabled": False,
            "external_service_connection_enabled": False,
            "minio_connection_enabled": False,
            "s3_connection_enabled": False,
        },
    ]
    service_dependency_summary = {
        "app": {
            "depends_on": ["json-file-or-sqlite-storage", "storage-backed-worker-queue", "local-filesystem-object-storage"],
            "runtime_entry": "api.main:create_app bootstrap projection",
            "storage_backend": active_backend,
            "object_storage_backend": active_object_storage_backend,
            "compose_service": "app",
            "local_stack_only": True,
            "container_execution_enabled": False,
            "external_service_connection_enabled": False,
        },
        "postgres": {
            "compose_service": "postgres",
            "dependency_role": "reserved_local_postgres",
            "readiness_state": READINESS_RESERVED_NOT_LIVE,
            "profile": "reserved-local-deps",
            "external_service_connection_enabled": False,
            "container_execution_enabled": False,
            "migration_execution_enabled": False,
            "live_ready": False,
        },
        "redis": {
            "compose_service": "redis",
            "dependency_role": "reserved_local_redis_queue",
            "readiness_state": READINESS_RESERVED_NOT_LIVE,
            "profile": "reserved-local-deps",
            "external_service_connection_enabled": False,
            "container_execution_enabled": False,
            "redis_connection_enabled": False,
            "live_ready": False,
        },
        "minio": {
            "compose_service": "minio",
            "dependency_role": "reserved_local_minio_object_storage",
            "readiness_state": READINESS_RESERVED_NOT_LIVE,
            "profile": "reserved-local-deps",
            "external_service_connection_enabled": False,
            "container_execution_enabled": False,
            "minio_connection_enabled": False,
            "s3_connection_enabled": False,
            "live_ready": False,
        },
    }
    return {
        "backend": "docker-compose",
        "readiness_state": "CONFIG_PRESENT_NOT_EXECUTED" if config_present else READINESS_NOT_CONFIGURED,
        "executable": False,
        "configured": config_present,
        "dockerfile_present": dockerfile_present,
        "compose_file_present": compose_file_present,
        "dockerignore_present": dockerignore_present,
        "docker_compose_config_present": compose_file_present,
        "compose_runtime_enabled": False,
        "container_execution_enabled": False,
        "docker_compose_up_executed": False,
        "local_stack_definition_only": True,
        "reserved_profile": "reserved-local-deps",
        "local_stack_services": local_stack_services,
        "service_dependency_summary": service_dependency_summary,
        "postgres": service_dependency_summary["postgres"],
        "redis": service_dependency_summary["redis"],
        "minio": service_dependency_summary["minio"],
        "external_service_connection_enabled": False,
        "real_provider_execution_enabled": False,
        "real_payment_delivery_enabled": False,
        "automated_refund_enabled": False,
        "external_release_enabled": False,
        "why_not_live": reserved_by_backend["docker-compose"]["why_not_live"],
    }


def _worker_queue_bootstrap_readiness(
    *,
    queue_backend: str,
    worker_runtime: str,
    active_storage_backend: str,
    reserved_by_backend: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    configured_queue_backend = str(queue_backend or "storage").strip().lower()
    configured_external_queue = configured_queue_backend in {"redis", "dramatiq", "external"}
    return {
        "queue_backend": configured_queue_backend,
        "effective_queue_backend": "storage",
        "active_storage_backend": active_storage_backend,
        "worker_runtime": str(worker_runtime or "internal-storage-worker").strip(),
        "readiness_state": READINESS_EXECUTABLE,
        "repository_backed": True,
        "durable_queue_enabled": True,
        "worker_lease_enabled": True,
        "heartbeat_enabled": True,
        "attempt_count_enabled": True,
        "retry_enabled": True,
        "timeout_recovery_enabled": True,
        "suspend_resume_enabled": True,
        "dead_letter_enabled": True,
        "audit_replay_enabled": True,
        "status_values": ["queued", "running", "succeeded", "failed", "suspended", "retry", "dead-letter"],
        "redis_reserved_state": reserved_by_backend["redis"]["readiness_state"],
        "dramatiq_reserved_state": reserved_by_backend["dramatiq"]["readiness_state"],
        "external_queue_backend_configured": configured_external_queue,
        "external_queue_connection_enabled": False,
        "redis_connection_enabled": False,
        "dramatiq_worker_enabled": False,
        "stage1_scheduler_enabled": False,
        "real_provider_execution_enabled": False,
        "why_not_live": "queue/worker durability uses existing storage only; Redis/Dramatiq, Stage1 scheduler, and provider execution remain reserved/not connected",
    }


__all__ = [
    "DEFAULT_STORAGE_BACKEND",
    "EXECUTABLE_STORAGE_BACKENDS",
    "LOCAL_OBJECT_STORAGE_BACKEND",
    "POSTGRESQL_STORAGE_BACKEND",
    "SQLALCHEMY_STORAGE_BACKEND",
    "SQLITE_STORAGE_BACKEND",
    "build_platform_infra_readiness",
    "is_postgresql_database_url",
    "normalize_storage_backend_name",
]
