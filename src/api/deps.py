# Stage: api
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from shared.settings import Settings


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache
def get_settings() -> Settings:
    return Settings(
        repo_root=str(_repo_root()),
        environment="INTERNAL_ONLY",
    )


def build_transport_unavailable(stage_scope: int) -> dict[str, Any]:
    return {
        "stage_scope": stage_scope,
        "availability_state": "CONTROLLED_UNAVAILABLE",
        "contract_state": "CONTRACT_READY",
        "transport_state": "TRANSPORT_NOT_WIRED",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": stage_scope in (8, 9),
        "why_unavailable": "stage transport is intentionally not wired in the current batch",
    }


__all__ = ["build_transport_unavailable", "get_settings"]
