# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Optional


_DEFAULT_STORAGE_BACKEND = "json-file"
_EXECUTABLE_STORAGE_BACKENDS = (_DEFAULT_STORAGE_BACKEND,)
_DEFAULT_STORAGE_SCOPE = "shared"
_PROCESS_STORAGE_SCOPE = "process"
_DEFAULT_STORAGE_RUNTIME_MODE = "stable-default"
_EXPLICIT_STORAGE_RUNTIME_MODE = "explicit-path"
_PROCESS_SCOPED_STORAGE_RUNTIME_MODE = "process-scoped-default"
_STORAGE_DIR_NAME = "kaka"
_STORAGE_FILE_STEM = "internal_operator_loop_store"
_TEST_ISOLATION_TRUTHY = frozenset({"1", "true", "yes", "on", "process"})
_READINESS_EXECUTABLE = "EXECUTABLE"
_READINESS_RESERVED_NOT_LIVE = "RESERVED_NOT_LIVE"
_READINESS_NOT_CONFIGURED = "NOT_CONFIGURED"
_RESERVED_BACKEND_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "backend": "postgresql",
        "category": "storage",
        "configured_aliases": ("postgres", "postgresql"),
        "aliases": ("postgres",),
        "why_not_live": "reserved for a future PostgreSQL storage design packet; current runtime only executes json-file",
    },
    {
        "backend": "sqlalchemy",
        "category": "storage-adapter",
        "configured_aliases": ("sqlalchemy",),
        "aliases": (),
        "why_not_live": "reserved for a future SQLAlchemy adapter design packet; current runtime only executes json-file",
    },
    {
        "backend": "alembic",
        "category": "migration",
        "configured_aliases": (),
        "aliases": (),
        "why_not_live": "reserved for future migration design; current packet must not create or run migrations",
    },
    {
        "backend": "redis",
        "category": "queue-broker",
        "configured_aliases": (),
        "aliases": (),
        "why_not_live": "reserved for future queue design; current packet must not connect to external services",
    },
    {
        "backend": "dramatiq",
        "category": "queue-worker",
        "configured_aliases": (),
        "aliases": (),
        "why_not_live": "reserved for future queue worker design; current packet must not enqueue work",
    },
    {
        "backend": "minio",
        "category": "object-storage",
        "configured_aliases": (),
        "aliases": (),
        "why_not_live": "reserved for future object storage design; current packet must not connect to external services",
    },
    {
        "backend": "s3",
        "category": "object-storage",
        "configured_aliases": (),
        "aliases": (),
        "why_not_live": "reserved for future object storage design; current packet must not connect to external services",
    },
    {
        "backend": "docker-compose",
        "category": "composition",
        "configured_aliases": (),
        "aliases": (),
        "why_not_live": "reserved for future local infra composition design; current packet must not add compose runtime",
    },
)


def _read_env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_storage_scope(storage_scope_value: str | None, storage_test_isolation_value: str | None) -> str:
    if (storage_scope_value or "").lower() == _PROCESS_STORAGE_SCOPE:
        return _PROCESS_STORAGE_SCOPE
    if (storage_test_isolation_value or "").lower() in _TEST_ISOLATION_TRUTHY:
        return _PROCESS_STORAGE_SCOPE
    return _DEFAULT_STORAGE_SCOPE


def _resolve_storage_runtime_mode(storage_path_optional: str | None, storage_scope: str) -> str:
    if storage_path_optional:
        return _EXPLICIT_STORAGE_RUNTIME_MODE
    if storage_scope == _PROCESS_STORAGE_SCOPE:
        return _PROCESS_SCOPED_STORAGE_RUNTIME_MODE
    return _DEFAULT_STORAGE_RUNTIME_MODE


def _normalize_backend(value: str | None) -> str:
    return (value or "").strip().lower()


@dataclass(frozen=True)
class Settings:
    repo_root: Optional[str] = None
    environment: Optional[str] = None
    storage_backend: str = _DEFAULT_STORAGE_BACKEND
    storage_path_optional: Optional[str] = None
    storage_scope: str = _DEFAULT_STORAGE_SCOPE
    storage_runtime_mode: str = _DEFAULT_STORAGE_RUNTIME_MODE

    @classmethod
    def from_env(
        cls,
        *,
        repo_root: str | None = None,
        environment: str | None = None,
    ) -> "Settings":
        storage_path_optional = _read_env_optional("KAKA_STORAGE_PATH")
        storage_scope = _resolve_storage_scope(
            _read_env_optional("KAKA_STORAGE_SCOPE"),
            _read_env_optional("KAKA_STORAGE_TEST_ISOLATION"),
        )
        return cls(
            repo_root=repo_root,
            environment=environment,
            storage_backend=_read_env_optional("KAKA_STORAGE_BACKEND") or _DEFAULT_STORAGE_BACKEND,
            storage_path_optional=storage_path_optional,
            storage_scope=storage_scope,
            storage_runtime_mode=_resolve_storage_runtime_mode(storage_path_optional, storage_scope),
        )

    def resolved_storage_path(self) -> Path:
        if self.storage_path_optional:
            return Path(self.storage_path_optional)
        base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
        file_name = (
            f"{_STORAGE_FILE_STEM}-{os.getpid()}.json"
            if self.storage_scope == _PROCESS_STORAGE_SCOPE
            else f"{_STORAGE_FILE_STEM}.json"
        )
        return base_dir / _STORAGE_DIR_NAME / file_name

    def platform_infra_readiness(self) -> dict[str, Any]:
        active_backend = _normalize_backend(self.storage_backend)
        executable_backends: list[dict[str, Any]] = [
            {
                "backend": backend,
                "readiness_state": _READINESS_EXECUTABLE,
                "executable": True,
                "configured": active_backend == backend,
            }
            for backend in _EXECUTABLE_STORAGE_BACKENDS
        ]
        reserved_backends = self._reserved_backend_readiness(active_backend)
        reserved_by_backend = {entry["backend"]: entry for entry in reserved_backends}

        return {
            "active_backend": active_backend,
            "executable_backends": executable_backends,
            "reserved_backends": reserved_backends,
            "backend_policy": {
                "unsupported_backend_fast_fail": True,
                "no_silent_fallback": True,
                "no_migration_execution": True,
                "no_external_service_connection": True,
                "readback_only": True,
                "runtime_behavior_changed": False,
            },
            "postgresql_readiness": {
                "backend": "postgresql",
                "readiness_state": reserved_by_backend["postgresql"]["readiness_state"],
                "executable": False,
                "configured": reserved_by_backend["postgresql"]["configured"],
                "adapter": "sqlalchemy",
                "adapter_readiness_state": reserved_by_backend["sqlalchemy"]["readiness_state"],
                "adapter_configured": reserved_by_backend["sqlalchemy"]["configured"],
                "why_not_live": reserved_by_backend["postgresql"]["why_not_live"],
            },
            "migration_readiness": {
                "backend": "alembic",
                "readiness_state": reserved_by_backend["alembic"]["readiness_state"],
                "executable": False,
                "configured": reserved_by_backend["alembic"]["configured"],
                "migration_execution_enabled": False,
                "why_not_live": reserved_by_backend["alembic"]["why_not_live"],
            },
            "queue_readiness": {
                "backends": ["redis", "dramatiq"],
                "readiness_state": self._combined_reserved_state(reserved_by_backend, ("redis", "dramatiq")),
                "executable": False,
                "configured": any(reserved_by_backend[backend]["configured"] for backend in ("redis", "dramatiq")),
                "external_service_connection_enabled": False,
                "why_not_live": "Redis/Dramatiq are reserved readback only in the current packet",
            },
            "object_storage_readiness": {
                "backends": ["minio", "s3"],
                "readiness_state": self._combined_reserved_state(reserved_by_backend, ("minio", "s3")),
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
        }

    def _reserved_backend_readiness(self, active_backend: str) -> list[dict[str, Any]]:
        reserved_backends: list[dict[str, Any]] = []
        for definition in _RESERVED_BACKEND_DEFINITIONS:
            backend = str(definition["backend"])
            configured_aliases = tuple(str(alias) for alias in definition["configured_aliases"])
            configured = active_backend in configured_aliases
            entry: dict[str, Any] = {
                "backend": backend,
                "readiness_state": _READINESS_RESERVED_NOT_LIVE if configured else _READINESS_NOT_CONFIGURED,
                "executable": False,
                "configured": configured,
                "why_not_live": str(definition["why_not_live"]),
                "category": str(definition["category"]),
            }
            aliases = [str(alias) for alias in definition["aliases"]]
            if aliases:
                entry["aliases"] = aliases
            reserved_backends.append(entry)
        return reserved_backends

    def _combined_reserved_state(
        self,
        reserved_by_backend: dict[str, dict[str, Any]],
        backends: tuple[str, ...],
    ) -> str:
        if any(reserved_by_backend[backend]["configured"] for backend in backends):
            return _READINESS_RESERVED_NOT_LIVE
        return _READINESS_NOT_CONFIGURED

    def storage_bootstrap_payload(self) -> dict[str, Any]:
        return {
            "storage_backend": self.storage_backend,
            "storage_path": str(self.resolved_storage_path()),
            "storage_path_optional": self.storage_path_optional,
            "storage_scope": self.storage_scope,
            "storage_runtime_mode": self.storage_runtime_mode,
            "platform_infra_readiness": self.platform_infra_readiness(),
        }


__all__ = ["Settings"]
