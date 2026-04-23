# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Optional


_DEFAULT_STORAGE_BACKEND = "json-file"
_DEFAULT_STORAGE_SCOPE = "shared"
_PROCESS_STORAGE_SCOPE = "process"
_DEFAULT_STORAGE_RUNTIME_MODE = "stable-default"
_EXPLICIT_STORAGE_RUNTIME_MODE = "explicit-path"
_PROCESS_SCOPED_STORAGE_RUNTIME_MODE = "process-scoped-default"
_STORAGE_DIR_NAME = "kaka"
_STORAGE_FILE_STEM = "internal_operator_loop_store"
_TEST_ISOLATION_TRUTHY = frozenset({"1", "true", "yes", "on", "process"})


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

    def storage_bootstrap_payload(self) -> dict[str, str | None]:
        return {
            "storage_backend": self.storage_backend,
            "storage_path": str(self.resolved_storage_path()),
            "storage_path_optional": self.storage_path_optional,
            "storage_scope": self.storage_scope,
            "storage_runtime_mode": self.storage_runtime_mode,
        }


__all__ = ["Settings"]
