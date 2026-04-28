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
from stage2_ingestion import (
    REAL_PUBLIC_ATTACHMENT_PROFILES,
    REAL_PUBLIC_ENTRY_PROFILES,
)
from stage2_ingestion.service import Stage2Service
from storage.db import PersistedOperatorAction, build_persisted_at
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


def _json_safe_snapshot_replay(replay: Mapping[str, Any]) -> dict[str, Any]:
    safe = dict(replay)
    raw_bytes = safe.pop("bytes", None)
    if isinstance(raw_bytes, (bytes, bytearray)):
        safe["bytes_present"] = True
        safe["bytes_redacted_for_json"] = True
        safe["byte_size_readback"] = len(raw_bytes)
        safe["byte_preview_hex"] = bytes(raw_bytes[:16]).hex()
    else:
        safe["bytes_present"] = raw_bytes is not None
        safe["bytes_redacted_for_json"] = False
    return safe


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


def _entry_profiles_readback() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "expected_title_contains": profile.expected_title_contains,
            "sample_detail_url": profile.sample_detail_url,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
        }
        for profile in REAL_PUBLIC_ENTRY_PROFILES
    ]


def _attachment_profiles_readback() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "detail_page_url_optional": profile.detail_page_url_optional,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
        }
        for profile in REAL_PUBLIC_ATTACHMENT_PROFILES
    ]


def list_real_public_source_profiles(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    return {
        "surface_id": "operator_real_public_source_profiles",
        "internal_only": True,
        "readiness_only": True,
        "projection_only": True,
        "repository_backed_readback": False,
        "entry_profiles": _entry_profiles_readback(),
        "attachment_profiles": _attachment_profiles_readback(),
        "entry_profile_count": len(REAL_PUBLIC_ENTRY_PROFILES),
        "attachment_profile_count": len(REAL_PUBLIC_ATTACHMENT_PROFILES),
        "allowed_capture_kinds": ["entry", "attachment"],
        "uncontrolled_crawler_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def _lineage_refs_from_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for source_key, target_key in (
        ("task_id", "owner_task_id"),
        ("project_id", "project_id"),
        ("source_blueprint_batch_id", "source_blueprint_batch_id"),
    ):
        value = str(payload.get(source_key, "")).strip()
        if value:
            refs[target_key] = value
    refs["operator_surface"] = "operator_console_real_source_runner"
    return refs


def _real_source_run_work_item_id() -> str:
    return "operator-real-public-source-task-runs"


def _record_real_source_run(
    *,
    capture_kind: str,
    profile_id: str,
    result: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    requested_at = build_persisted_at()
    snapshot_id = str(result.get("snapshot_id_optional") or result.get("snapshot_id") or "").strip()
    status = str(result.get("status") or result.get("readback_state") or "UNKNOWN")
    fail_closed = bool(result.get("fail_closed", False))
    action_state = "FAILED_CLOSED" if fail_closed else status
    run_id = f"REAL-SOURCE-RUN-{snapshot_id or profile_id}-{requested_at}".replace(":", "").replace("+", "")
    object_refs = {
        "capture_kind": capture_kind,
        "profile_id": profile_id,
        "status": status,
    }
    if snapshot_id:
        object_refs["snapshot_id"] = snapshot_id
    for key in ("task_id", "project_id", "source_blueprint_batch_id"):
        value = str(payload.get(key, "")).strip()
        if value:
            object_refs[key] = value
    action = PersistedOperatorAction(
        action_event_id=run_id,
        work_item_id=_real_source_run_work_item_id(),
        stage_scope=2,
        action_id="real_public_source_capture",
        button_flow_id="owner_console_real_source_runner",
        action_state=action_state,
        resulting_assignment_lifecycle_state=None,
        requested_by_role="single_operator",
        requested_by="卡卡罗特",
        assigned_owner_role="single_operator",
        assigned_owner="卡卡罗特",
        reviewer_role="single_operator",
        reviewer="卡卡罗特",
        reason="owner_console_allowlisted_real_public_source_capture",
        object_refs=object_refs,
        trace_refs={
            "operator_console_route": "/operator-console/real-source-runs",
            "readback_path": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else "",
        },
        audit_refs={
            "run_audit_ref": run_id,
            "public_boundary": "allowlisted_public_source_only",
        },
        requested_at=requested_at,
        completed_at=requested_at,
    )
    OperatorActionRepository().append(action)
    return _real_source_run_action_payload(action)


def _real_source_run_action_payload(action: PersistedOperatorAction) -> dict[str, Any]:
    refs = dict(action.object_refs)
    snapshot_id = refs.get("snapshot_id")
    return {
        "run_id": action.action_event_id,
        "capture_kind": refs.get("capture_kind"),
        "profile_id": refs.get("profile_id"),
        "snapshot_id_optional": snapshot_id,
        "status": refs.get("status") or action.action_state,
        "action_state": action.action_state,
        "task_id_optional": refs.get("task_id"),
        "project_id_optional": refs.get("project_id"),
        "requested_at": action.requested_at,
        "completed_at": action.completed_at,
        "readback_path_optional": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else None,
        "repository_backed": True,
        "internal_only": True,
        "uncontrolled_crawler_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
    }


def list_owner_real_public_source_task_runs(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    actions = OperatorActionRepository().list(work_item_id=_real_source_run_work_item_id())
    runs = [_real_source_run_action_payload(action) for action in actions]
    runs.sort(key=lambda row: str(row.get("requested_at") or ""), reverse=True)
    status_counts: dict[str, int] = {}
    for row in runs:
        status = str(row.get("status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "surface_id": "operator_real_public_source_task_runs",
        "internal_only": True,
        "repository_backed_readback": True,
        "run_count": len(runs),
        "status_counts": status_counts,
        "runs": runs,
        "allowed_capture_kinds": ["entry", "attachment"],
        "uncontrolled_crawler_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def run_owner_real_public_source_capture(payload: Mapping[str, Any]) -> dict[str, Any]:
    capture_kind = str(payload.get("capture_kind", "")).strip().lower()
    profile_id = str(payload.get("profile_id", "")).strip()
    if not profile_id:
        raise ValueError("profile_id is required")

    service = Stage2Service()
    lineage_refs = _lineage_refs_from_payload(payload)
    if capture_kind == "entry":
        profile = next((item for item in REAL_PUBLIC_ENTRY_PROFILES if item.profile_id == profile_id), None)
        if profile is None:
            raise ValueError(f"unregistered_entry_profile_id:{profile_id}")
        result = service.fetch_real_public_entry_url(
            profile.url,
            profile_id=profile.profile_id,
            lineage_refs=lineage_refs,
        )
    elif capture_kind == "attachment":
        profile = next((item for item in REAL_PUBLIC_ATTACHMENT_PROFILES if item.profile_id == profile_id), None)
        if profile is None:
            raise ValueError(f"unregistered_attachment_profile_id:{profile_id}")
        result = service.fetch_real_public_attachment_url(
            profile.url,
            profile_id=profile.profile_id,
            lineage_refs=lineage_refs,
            detail_page_url=profile.detail_page_url_optional,
        )
    else:
        raise ValueError("capture_kind must be entry or attachment")

    return {
        "surface_id": "operator_real_public_source_run",
        "capture_kind": capture_kind,
        "profile_id": profile_id,
        "snapshot_id_optional": result.get("snapshot_id_optional"),
        "capture_status": result.get("status"),
        "run_record": _record_real_source_run(
            capture_kind=capture_kind,
            profile_id=profile_id,
            result=result,
            payload=payload,
        ),
        "repository_backed_readback": True,
        "readback_path_template": "/operator-console/real-source-runs/{snapshot_id}",
        "result": result,
        "internal_only": True,
        "uncontrolled_crawler_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def read_owner_real_public_source_capture(payload: Mapping[str, Any]) -> dict[str, Any]:
    snapshot_id = str(payload.get("snapshot_id", "")).strip()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    replay = _json_safe_snapshot_replay(Stage2Service().replay_public_source_snapshot(snapshot_id))
    return {
        "surface_id": "operator_real_public_source_readback",
        "snapshot_id": snapshot_id,
        "readback_state": replay.get("readback_state"),
        "repository_backed_readback": True,
        "replayable": bool(replay.get("replayable", False)),
        "result": replay,
        "internal_only": True,
        "uncontrolled_crawler_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


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
        "operationId": "listRealPublicSourceProfiles",
        "method": "GET",
        "path": "/operator-console/real-source-profiles",
        "handler": list_real_public_source_profiles,
        "real_public_source_profile_catalog": True,
        "repository_backed_readback": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "runOwnerRealPublicSourceCapture",
        "method": "POST",
        "path": "/operator-console/real-source-runs",
        "handler": run_owner_real_public_source_capture,
        "real_public_source_runner_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "listOwnerRealPublicSourceTaskRuns",
        "method": "GET",
        "path": "/operator-console/real-source-task-runs",
        "handler": list_owner_real_public_source_task_runs,
        "real_public_source_task_run_list": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "readOwnerRealPublicSourceCapture",
        "method": "GET",
        "path": "/operator-console/real-source-runs/{snapshot_id}",
        "handler": read_owner_real_public_source_capture,
        "real_public_source_readback": True,
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
    "list_owner_real_public_source_task_runs",
    "list_real_public_source_profiles",
    "preview_customer_artifact_access_candidate",
    "preview_go_live_readiness",
    "preview_operator_customer_access_readiness",
    "preview_scheduler_status",
    "read_owner_real_public_source_capture",
    "read_operator_task",
    "register_operator_customer_access_routes",
    "run_owner_real_public_source_capture",
]
