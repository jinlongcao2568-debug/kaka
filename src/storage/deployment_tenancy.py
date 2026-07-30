# Stage: deployment_tenancy
# Consumes formal objects: deployment boundary seal
# Dependent handoff: N/A
# Dependent schema/contracts: PRODUCTIZATION_MASTER_PLAN.md#SEC-004

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.object_storage import LocalObjectStorage, default_object_storage_path


DEPLOYMENT_BOUNDARY_OBJECT_TYPE = "deployment_boundary_seal"
DEPLOYMENT_BOUNDARY_RECORD_ID = "private-single-tenant-boundary"
DEPLOYMENT_BOUNDARY_OBJECT_KEY = "deployment-boundary/private-single-tenant-seal.json"
DEPLOYMENT_BOUNDARY_SCHEMA_VERSION = "1.0"


def _seal_payload(settings: Settings) -> dict[str, Any]:
    identity = settings.deployment_boundary_identity()
    return {
        "schema_version": DEPLOYMENT_BOUNDARY_SCHEMA_VERSION,
        "deployment_tenancy_mode": settings.deployment_tenancy_mode,
        **identity,
    }


def _seal_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    required = ("tenant_id", "instance_id", "data_namespace", "boundary_sha256")
    identity = {key: str(payload.get(key) or "").strip() for key in required}
    if any(not identity[key] for key in required):
        raise ValueError("deployment boundary seal is malformed or incomplete")
    return identity


def _assert_matching_seal(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    source: str,
) -> None:
    if _seal_identity(actual) != _seal_identity(expected):
        raise ValueError(
            f"{source} deployment boundary seal does not match the configured private tenant; "
            "refusing cross-customer storage mount"
        )


def _read_object_storage_seal(object_store: LocalObjectStorage) -> dict[str, Any] | None:
    seal_path = object_store.object_path(DEPLOYMENT_BOUNDARY_OBJECT_KEY)
    if not seal_path.exists():
        return None
    try:
        payload = json.loads(object_store.read_bytes(DEPLOYMENT_BOUNDARY_OBJECT_KEY).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("object storage deployment boundary seal is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("object storage deployment boundary seal must be a JSON object")
    return payload


def _claim_or_validate_object_storage_seal(
    object_store: LocalObjectStorage,
    expected: Mapping[str, Any],
    *,
    created_at: str,
) -> None:
    seal_path = object_store.object_path(DEPLOYMENT_BOUNDARY_OBJECT_KEY)
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        {**expected, "created_at": created_at},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        fd = os.open(seal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        stored = _read_object_storage_seal(object_store)
        if stored is None:
            raise ValueError("object storage deployment boundary seal disappeared during startup")
        _assert_matching_seal(stored, expected, source="object storage")
        return
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        seal_path.unlink(missing_ok=True)
        raise


def ensure_private_single_tenant_boundary(
    *,
    settings: Settings,
    session: DatabaseSession,
) -> dict[str, Any]:
    settings.assert_deployment_tenancy_boundary()
    readiness = settings.deployment_tenancy_readiness()
    if not settings.is_private_single_tenant_deployment():
        return {
            **readiness,
            "storage_boundary_seal_ready": False,
            "object_storage_boundary_seal_ready": False,
            "deployment_boundary_enforced": False,
        }

    expected = _seal_payload(settings)
    stored_record = session.get_record(
        DEPLOYMENT_BOUNDARY_OBJECT_TYPE,
        DEPLOYMENT_BOUNDARY_RECORD_ID,
    )
    if stored_record is not None:
        _assert_matching_seal(stored_record.payload, expected, source="database")

    object_store = LocalObjectStorage(
        root_path=default_object_storage_path(settings),
        backend=settings.object_storage_backend,
    )
    stored_object_seal = _read_object_storage_seal(object_store)
    if stored_object_seal is not None:
        _assert_matching_seal(stored_object_seal, expected, source="object storage")

    created_at = utc_now_iso()
    _claim_or_validate_object_storage_seal(
        object_store,
        expected,
        created_at=created_at,
    )
    if stored_record is None:
        session.upsert_record(
            PersistedRecord(
                object_type=DEPLOYMENT_BOUNDARY_OBJECT_TYPE,
                record_id=DEPLOYMENT_BOUNDARY_RECORD_ID,
                stage_scope=0,
                project_id=None,
                object_refs={
                    "deployment_data_namespace_sha256": str(
                        readiness["deployment_data_namespace_sha256"]
                    )
                },
                decision_states={"boundary_state": "PRIVATE_SINGLE_TENANT_SEALED"},
                trace_refs={},
                audit_refs={},
                governed_state={
                    "single_customer_per_deployment": True,
                    "cross_tenant_routing_enabled": False,
                    "multi_tenant_saas_ready": False,
                },
                writeback_state={},
                payload={**expected, "created_at": created_at},
                persisted_at=build_persisted_at(),
            )
        )
    return {
        **readiness,
        "storage_boundary_seal_ready": True,
        "object_storage_boundary_seal_ready": True,
        "deployment_boundary_enforced": True,
        "boundary_sha256": str(expected["boundary_sha256"]),
    }


__all__ = [
    "DEPLOYMENT_BOUNDARY_OBJECT_KEY",
    "DEPLOYMENT_BOUNDARY_OBJECT_TYPE",
    "DEPLOYMENT_BOUNDARY_RECORD_ID",
    "ensure_private_single_tenant_boundary",
]
