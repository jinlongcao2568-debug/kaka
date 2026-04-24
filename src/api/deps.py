# Stage: api
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from shared.settings import Settings
from storage.db import DatabaseSession


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env(
        repo_root=str(_repo_root()),
        environment="INTERNAL_ONLY",
    )


def get_database_session(*, reload_from_disk: bool = False) -> DatabaseSession:
    return DatabaseSession.default(
        reload_from_disk=reload_from_disk,
        settings=get_settings(),
    )


def build_transport_unavailable(
    stage_scope: int,
    *,
    reserved_operation_id: str | None = None,
    reserved_path: str | None = None,
    reserved_method: str | None = None,
    handoff_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    transport_state: dict[str, Any] = {
        "stage_scope": stage_scope,
        "availability_state": "CONTROLLED_UNAVAILABLE",
        "contract_state": "CONTRACT_READY",
        "transport_state": "TRANSPORT_NOT_WIRED",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": stage_scope in (8, 9),
        "why_unavailable": "stage transport is intentionally not wired in the current batch",
    }
    if reserved_operation_id and reserved_path and reserved_method:
        transport_state.update(
            {
                "reserved_entry_state": "RESERVED_NOT_LIVE",
                "reserved_operation_id": reserved_operation_id,
                "reserved_path": reserved_path,
                "reserved_method": reserved_method,
                "handoff_refs": list(handoff_refs),
                "http_entry_enabled": False,
                "real_transport_enabled": False,
                "orchestrator_enabled": False,
            }
        )
    return transport_state


__all__ = ["build_transport_unavailable", "get_database_session", "get_settings"]
