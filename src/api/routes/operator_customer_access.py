# Stage: api_operator_customer_access
# Consumes formal objects: API/readback projections only
# Dependent handoff: N/A
# Dependent schema/contracts: existing Stage1-9 contracts through mounted routes

from __future__ import annotations

from typing import Any, Mapping

from api.deps import get_settings
from api.projections import (
    build_customer_artifact_access_candidate_surface,
    build_go_live_readiness_surface,
    build_operator_customer_access_readiness_surface,
    register_route_table,
)
from api.routes.stage1 import create_stage1_scheduler_task, read_stage1_scheduler_task
from storage.repositories.operator_action_repo import OperatorActionRepository
from storage.repositories.worker_queue_repo import WorkerQueueRepository


OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA = {
    "surface_mode": "internal-readback",
    "internal_only": True,
    "readiness_only": True,
    "projection_only": True,
    "live_execution_enabled": False,
    "external_release_enabled": False,
    "public_software_release": False,
    "provider_call_enabled": False,
    "real_provider_call_enabled": False,
    "stage8_real_execution_enabled": False,
    "stage9_real_payment_delivery_refund_enabled": False,
    "automated_refund_enabled": False,
}


def _settings_bootstrap() -> tuple[dict[str, Any], dict[str, Any]]:
    settings = get_settings()
    return settings.storage_bootstrap_payload(), settings.provider_adapter_bootstrap_payload()


def _operator_audit_log() -> list[dict[str, Any]]:
    return [entry.as_payload() for entry in OperatorActionRepository().list_all()]


def _operator_operation_readback(routes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return [
        {
            key: route[key]
            for key in (
                "operationId",
                "method",
                "path",
                "surface_mode",
                "internal_only",
                "readiness_only",
                "projection_only",
                "live_execution_enabled",
                "external_release_enabled",
                "public_software_release",
                "provider_call_enabled",
                "real_provider_call_enabled",
                "stage8_real_execution_enabled",
                "stage9_real_payment_delivery_refund_enabled",
                "automated_refund_enabled",
            )
            if key in route
        }
        for route in (routes or OPERATOR_CUSTOMER_ACCESS_ROUTES)
    ]


def preview_operator_customer_access_readiness(payload: Any) -> dict[str, Any]:
    storage_bootstrap, provider_bootstrap = _settings_bootstrap()
    return build_operator_customer_access_readiness_surface(
        payload,
        storage_bootstrap=storage_bootstrap,
        provider_adapter_bootstrap=provider_bootstrap,
        audit_log=_operator_audit_log(),
        operator_operation_readback=_operator_operation_readback(),
    )


def create_operator_task(payload: dict[str, Any]) -> dict[str, Any]:
    response = create_stage1_scheduler_task(payload)
    response.update(
        {
            "surface_id": "operator_task_creation",
            "internal_only": True,
            "repository_backed_readback": True,
            "task_creation_visible": True,
            "stage2_fetch_enabled": False,
            "real_external_fetch_enabled": False,
            "crawler_enabled": False,
            "live_execution_enabled": False,
        }
    )
    return response


def read_operator_task(payload: dict[str, Any]) -> dict[str, Any]:
    response = read_stage1_scheduler_task(payload)
    response.update(
        {
            "surface_id": "operator_task_readback",
            "internal_only": True,
            "live_execution_enabled": False,
        }
    )
    return response


def import_operator_project(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id", "")).strip()
    if not project_id:
        raise ValueError("project_id is required for project import readiness")
    task_payload = {
        **dict(payload),
        "task_id": str(payload.get("task_id") or f"IMPORT-{project_id}"),
        "source_mode": str(payload.get("source_mode") or "INTERNAL_PROJECT_IMPORT"),
        "project_import_entry": True,
    }
    response = create_stage1_scheduler_task(task_payload)
    response.update(
        {
            "surface_id": "operator_project_import",
            "project_import_entry": True,
            "project_import_state": "IMPORTED_AS_INTERNAL_STAGE1_TASK_INTENT",
            "internal_only": True,
            "repository_backed_readback": True,
            "stage2_fetch_enabled": False,
            "real_external_fetch_enabled": False,
            "crawler_enabled": False,
            "live_execution_enabled": False,
        }
    )
    return response


def preview_customer_artifact_access_candidate(payload: Any) -> dict[str, Any]:
    return build_customer_artifact_access_candidate_surface(payload)


def preview_go_live_readiness(payload: Any) -> dict[str, Any]:
    storage_bootstrap, provider_bootstrap = _settings_bootstrap()
    return build_go_live_readiness_surface(
        storage_bootstrap=storage_bootstrap,
        provider_adapter_bootstrap=provider_bootstrap,
        audit_log=_operator_audit_log(),
    )


def _queue_status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in WorkerQueueRepository().list():
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def preview_scheduler_status(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    storage_bootstrap, _ = _settings_bootstrap()
    worker_queue = dict(storage_bootstrap.get("worker_queue_bootstrap", {}))
    return {
        "surface_id": "operator_scheduler_status",
        "internal_only": True,
        "readback_ready": True,
        "repository_backed": True,
        "replayable": True,
        "readiness_state": worker_queue.get("readiness_state"),
        "queue_backend": worker_queue.get("queue_backend"),
        "effective_queue_backend": worker_queue.get("effective_queue_backend"),
        "queue_status_counts": _queue_status_counts(),
        "stage2_fetch_enabled": False,
        "crawler_enabled": False,
        "real_external_fetch_enabled": False,
        "external_queue_connection_enabled": False,
        "real_provider_execution_enabled": False,
    }


OPERATOR_CUSTOMER_ACCESS_ROUTES = [
    {
        "operationId": "previewOperatorCustomerAccessReadiness",
        "method": "GET",
        "path": "/operator-console/readiness",
        "handler": preview_operator_customer_access_readiness,
        "operator_console_readiness": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "createOperatorTask",
        "method": "POST",
        "path": "/operator-console/tasks",
        "handler": create_operator_task,
        "task_creation_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "readOperatorTask",
        "method": "GET",
        "path": "/operator-console/tasks/{queue_item_id}",
        "handler": read_operator_task,
        "task_readback_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "importOperatorProject",
        "method": "POST",
        "path": "/operator-console/project-imports",
        "handler": import_operator_project,
        "project_import_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewCustomerArtifactAccessCandidate",
        "method": "GET",
        "path": "/customer-artifact-access-candidates/{opportunity_id}",
        "handler": preview_customer_artifact_access_candidate,
        "customer_artifact_access_readiness": True,
        "candidate_only": True,
        "review_only": True,
        "download_auth_required": True,
        "field_allowlist_masking_required": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewGoLiveReadiness",
        "method": "GET",
        "path": "/go-live/readiness",
        "handler": preview_go_live_readiness,
        "go_live_readiness": True,
        "deployment_readiness": True,
        "monitoring_rollback_refs": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewOperatorSchedulerStatus",
        "method": "GET",
        "path": "/operator-console/scheduler-status",
        "handler": preview_scheduler_status,
        "scheduler_status_readback": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
]


def register_operator_customer_access_routes(
    router: object | None = None,
) -> list[dict[str, Any]]:
    return register_route_table(router, list(OPERATOR_CUSTOMER_ACCESS_ROUTES))


__all__ = [
    "OPERATOR_CUSTOMER_ACCESS_ROUTES",
    "create_operator_task",
    "import_operator_project",
    "preview_customer_artifact_access_candidate",
    "preview_go_live_readiness",
    "preview_operator_customer_access_readiness",
    "preview_scheduler_status",
    "read_operator_task",
    "register_operator_customer_access_routes",
]
