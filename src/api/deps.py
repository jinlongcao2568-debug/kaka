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


INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY = {
    "internal_orchestration_entry_available": True,
    "internal_orchestration_operation_id": "runStage1ToStage6InternalOrchestration",
    "internal_orchestration_path": "/internal/stage1-6/orchestrations",
    "internal_orchestration_method": "POST",
    "internal_orchestration_payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
    "stage6_readback_mode": "repository_backed_preview",
    "stage1_to_stage5_external_live_transport_state": "BLOCKED_CONTROLLED_UNAVAILABLE",
}


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


def get_provider_adapter_readiness_summary() -> dict[str, Any]:
    return get_settings().provider_adapter_readiness_summary()


def get_provider_adapter_bootstrap_payload() -> dict[str, Any]:
    return get_settings().provider_adapter_bootstrap_payload()


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
                **INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY,
            }
        )
    return transport_state


def validate_internal_orchestration_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("stage1-6 internal orchestration payload must be a JSON object")

    payload_boundary = str(payload.get("payload_boundary", "")).strip()
    if payload_boundary != "SANITIZED_OFFLINE_INTERNAL":
        raise ValueError("payload_boundary must be SANITIZED_OFFLINE_INTERNAL")

    source_mode = str(payload.get("source_mode", "")).strip()
    allowed_source_modes = {
        "OFFLINE_FIXTURE",
        "OFFLINE_SANITIZED",
        "INTERNAL_OFFLINE_REPLAY",
    }
    if source_mode not in allowed_source_modes:
        raise ValueError("source_mode must be offline/sanitized/internal")

    run_mode = str(payload.get("run_mode", "")).strip()
    allowed_run_modes = {"DRY_RUN", "PREVIEW", "INTERNAL_PREVIEW", "OFFLINE_REPLAY"}
    if run_mode not in allowed_run_modes:
        raise ValueError("run_mode must be dry-run, preview, or offline replay")

    blocked_truthy_flags = (
        "crm_runtime_enabled",
        "live_execution_enabled",
        "external_delivery_enabled",
        "external_quote_enabled",
        "external_release_enabled",
        "live_source_enabled",
        "real_transport_enabled",
    )
    for flag in blocked_truthy_flags:
        if bool(payload.get(flag, False)):
            raise ValueError(f"{flag} is blocked for stage1-6 internal orchestration")

    blocked_modes = {"LIVE", "EXTERNAL_LIVE", "PRODUCTION", "REAL_TRANSPORT"}
    for field_name in ("run_mode", "source_mode", "transport_mode", "execution_mode"):
        field_value = str(payload.get(field_name, "")).strip()
        if field_value in blocked_modes:
            raise ValueError(f"{field_name} must not request external/live execution")

    return dict(payload)


__all__ = [
    "INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY",
    "build_transport_unavailable",
    "get_database_session",
    "get_provider_adapter_bootstrap_payload",
    "get_provider_adapter_readiness_summary",
    "get_settings",
    "validate_internal_orchestration_payload",
]
