from __future__ import annotations

from typing import Any, Mapping

from fastapi import HTTPException

from api.projections import register_route_table
from shared.operator_support_workbench import (
    OperatorSupportAccessError,
    OperatorSupportConflictError,
    OperatorSupportInputError,
    build_operator_support_overview,
    retry_operator_support_task,
)


OPERATOR_SUPPORT_ROUTE_METADATA = {
    "surface_mode": "internal-private-single-tenant-support",
    "internal_only": True,
    "owner_admin_only": True,
    "customer_self_service": False,
    "live_execution_enabled": False,
    "external_release_enabled": False,
    "fact_layer_edit_enabled": False,
    "raw_payload_edit_enabled": False,
}


def _raise_support_error(exc: ValueError) -> None:
    if isinstance(exc, OperatorSupportAccessError):
        raise HTTPException(
            status_code=403,
            detail={"code": "INTERNAL_SUPPORT_ADMIN_PERMISSION_DENIED", "message": str(exc)},
        ) from exc
    if isinstance(exc, OperatorSupportConflictError):
        raise HTTPException(
            status_code=409,
            detail={"code": "SUPPORT_TASK_STATE_CONFLICT", "message": str(exc)},
        ) from exc
    raise HTTPException(
        status_code=400,
        detail={"code": "INVALID_SUPPORT_WORKBENCH_REQUEST", "message": str(exc)},
    ) from exc


def read_operator_support_overview(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return build_operator_support_overview(payload)
    except (OperatorSupportAccessError, OperatorSupportConflictError, OperatorSupportInputError) as exc:
        _raise_support_error(exc)
    raise AssertionError("unreachable")


def retry_operator_support_queue_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return retry_operator_support_task(payload)
    except (OperatorSupportAccessError, OperatorSupportConflictError, OperatorSupportInputError) as exc:
        _raise_support_error(exc)
    raise AssertionError("unreachable")


OPERATOR_SUPPORT_ROUTES = [
    {
        "operationId": "readOperatorSupportOverview",
        "method": "GET",
        "path": "/operator-console/support/overview",
        "handler": read_operator_support_overview,
        **OPERATOR_SUPPORT_ROUTE_METADATA,
    },
    {
        "operationId": "retryOperatorSupportTask",
        "method": "POST",
        "path": "/operator-console/support/task-actions",
        "handler": retry_operator_support_queue_task,
        "explicit_operator_action": True,
        "raw_json_required": False,
        "exact_confirmation_required": True,
        **OPERATOR_SUPPORT_ROUTE_METADATA,
    },
]


def register_operator_support_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, OPERATOR_SUPPORT_ROUTES)


__all__ = [
    "OPERATOR_SUPPORT_ROUTES",
    "read_operator_support_overview",
    "register_operator_support_routes",
    "retry_operator_support_queue_task",
]
