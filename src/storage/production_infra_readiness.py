from __future__ import annotations

from importlib.util import find_spec
from typing import Any
from urllib.parse import urlsplit, urlunsplit


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
        "why_not_live": "reserved for future queue design; current packet must not connect to external services",
    },
    {
        "backend": "dramatiq",
        "category": "queue-worker",
        "configured_aliases": ("dramatiq",),
        "why_not_live": "reserved for future queue worker design; current packet must not enqueue work",
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
        "why_not_live": "reserved for future local infra composition design; current packet must not add compose runtime",
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
) -> dict[str, Any]:
    active_backend = normalize_storage_backend_name(storage_backend)
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
    reserved_backends = _reserved_backend_readiness(active_backend)
    reserved_by_backend = {entry["backend"]: entry for entry in reserved_backends}

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
            "backends": ["redis", "dramatiq"],
            "readiness_state": _combined_reserved_state(reserved_by_backend, ("redis", "dramatiq")),
            "executable": False,
            "configured": any(reserved_by_backend[backend]["configured"] for backend in ("redis", "dramatiq")),
            "external_service_connection_enabled": False,
            "why_not_live": "Redis/Dramatiq are reserved readback only in the current packet",
        },
        "object_storage_readiness": {
            "backends": ["minio", "s3"],
            "readiness_state": _combined_reserved_state(reserved_by_backend, ("minio", "s3")),
            "executable": False,
            "configured": any(reserved_by_backend[backend]["configured"] for backend in ("minio", "s3")),
            "external_service_connection_enabled": False,
            "why_not_live": "MinIO/S3 are reserved readback only in the current packet",
        },
        "compose_readiness": {
            "backend": "docker-compose",
            "readiness_state": reserved_by_backend["docker-compose"]["readiness_state"],
            "executable": False,
            "configured": reserved_by_backend["docker-compose"]["configured"],
            "compose_runtime_enabled": False,
            "why_not_live": reserved_by_backend["docker-compose"]["why_not_live"],
        },
        "redlines": {
            "no_live_provider_call": True,
            "no_real_sales_outreach": True,
            "no_real_payment": True,
            "no_real_charge": True,
            "no_real_delivery": True,
            "no_real_refund": True,
            "no_automated_refund": True,
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


def _reserved_backend_readiness(active_backend: str) -> list[dict[str, Any]]:
    reserved_backends: list[dict[str, Any]] = []
    for definition in _RESERVED_BACKEND_DEFINITIONS:
        backend = str(definition["backend"])
        configured_aliases = tuple(str(alias) for alias in definition["configured_aliases"])
        configured = active_backend in configured_aliases
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


def _combined_reserved_state(
    reserved_by_backend: dict[str, dict[str, Any]],
    backends: tuple[str, ...],
) -> str:
    if any(reserved_by_backend[backend]["configured"] for backend in backends):
        return READINESS_RESERVED_NOT_LIVE
    return READINESS_NOT_CONFIGURED


__all__ = [
    "DEFAULT_STORAGE_BACKEND",
    "EXECUTABLE_STORAGE_BACKENDS",
    "POSTGRESQL_STORAGE_BACKEND",
    "SQLALCHEMY_STORAGE_BACKEND",
    "SQLITE_STORAGE_BACKEND",
    "build_platform_infra_readiness",
    "is_postgresql_database_url",
    "normalize_storage_backend_name",
]
