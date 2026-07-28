from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from storage.db import DatabaseSession, PersistedWorkerQueueEvent, PersistedWorkerQueueItem
from storage.repositories.worker_queue_repo import WorkerQueueRepository
from storage.sqlalchemy_backend import REQUIRED_STORAGE_SCHEMA_REVISION
from storage.worker_queue import INTERNAL_QUEUE_STATUSES


SUPPORT_WORKBENCH_CONTRACT_REF = (
    "contracts/governance/operator_support_workbench_contract.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SENSITIVE_RE = re.compile(
    r"(?:api[_ -]?key|access[_ -]?token|authorization|bearer\s+\S+|cookie|password|"
    r"passwd|secret\s*[:=]|private[_ -]?key|身份证|银行卡)",
    re.IGNORECASE,
)
_BLOCKED_EXTERNAL_FLAGS = (
    "live_execution_enabled",
    "external_release_enabled",
    "customer_visible_allowed",
    "payment_execution_enabled",
    "delivery_execution_enabled",
    "automatic_refund_enabled",
)
_BLOCKER_STATUSES = {"failed", "dead-letter", "suspended"}


class OperatorSupportAccessError(ValueError):
    pass


class OperatorSupportInputError(ValueError):
    pass


class OperatorSupportConflictError(ValueError):
    pass


def build_operator_support_overview(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    actor = _trusted_actor(payload)
    _reject_unknown(
        payload,
        {"_internal_auth_context", "limit", "queue_name", "status", "queue_item_id"},
    )
    limit = _bounded_int(payload.get("limit"), default=50, minimum=1, maximum=100)
    queue_name = _optional_identifier(payload.get("queue_name"), "queue_name")
    queue_item_id = _optional_identifier(payload.get("queue_item_id"), "queue_item_id")
    status = str(payload.get("status") or "").strip()
    if status and status not in INTERNAL_QUEUE_STATUSES:
        raise OperatorSupportInputError("unsupported queue status filter")
    active_session = session or DatabaseSession.default()
    repository = WorkerQueueRepository(session=active_session)
    items = repository.list(queue_name=queue_name or None, status=status or None)
    if queue_item_id:
        items = [item for item in items if item.queue_item_id == queue_item_id]
    items.sort(key=lambda item: (item.updated_at, item.queue_item_id), reverse=True)
    visible_items = items[:limit]
    item_ids = {item.queue_item_id for item in visible_items}
    events = [
        event
        for event in active_session.list_all_worker_queue_events()
        if event.queue_item_id in item_ids
    ]
    events.sort(key=lambda event: (event.occurred_at, event.event_id), reverse=True)
    summaries = [_task_summary(item) for item in visible_items]
    blockers = [summary for summary in summaries if summary["support_blocker"]]
    status_counts = {
        queue_status: sum(1 for item in items if item.status == queue_status)
        for queue_status in INTERNAL_QUEUE_STATUSES
    }
    return {
        "surface_id": "operator_support_workbench_internal",
        "context": {
            "deployment_tenant_id": actor["tenant_id"],
            "tenant_scope_sha256": actor["tenant_scope_sha256"],
            "deployment_mode": "PRIVATE_SINGLE_TENANT",
            "visible_tenant_count": 1,
            "cross_tenant_query_enabled": False,
        },
        "metrics": {
            "matching_task_count": len(items),
            "returned_task_count": len(summaries),
            "blocker_count": len(blockers),
            "audit_event_count": len(events),
            "status_counts": status_counts,
        },
        "tasks": summaries,
        "blockers": blockers,
        "audit_events": [_event_summary(event) for event in events[:100]],
        "versions": _version_readback(active_session),
        "capabilities": {
            "task_query": True,
            "current_tenant_query": True,
            "blocker_query": True,
            "queue_audit_replay": True,
            "version_readback": True,
            "governed_failed_task_retry": True,
            "task_cancel_path": "/operator-console/long-tasks/cancel",
            "direct_fact_edit": False,
            "raw_payload_edit": False,
        },
        "governance": _governance(),
    }


def retry_operator_support_task(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    actor = _trusted_actor(payload)
    _reject_unknown(
        payload,
        {
            "_internal_auth_context",
            "action",
            "queue_item_id",
            "expected_status",
            "expected_updated_at",
            "confirmation",
            "reason",
        },
    )
    if str(payload.get("action") or "").strip().upper() != "RETRY":
        raise OperatorSupportInputError("only RETRY support action is available")
    if str(payload.get("confirmation") or "") != "RETRY_FAILED_INTERNAL_TASK":
        raise OperatorSupportInputError("exact retry confirmation is required")
    queue_item_id = _identifier(payload.get("queue_item_id"), "queue_item_id")
    expected_status = str(payload.get("expected_status") or "").strip()
    if expected_status not in {"failed", "dead-letter"}:
        raise OperatorSupportInputError("expected_status must be failed or dead-letter")
    expected_updated_at = str(payload.get("expected_updated_at") or "").strip()
    if not expected_updated_at or len(expected_updated_at) > 64:
        raise OperatorSupportInputError("expected_updated_at is required")
    reason = str(payload.get("reason") or "").strip()
    if not 10 <= len(reason) <= 500 or _SENSITIVE_RE.search(reason):
        raise OperatorSupportInputError("reason must contain 10-500 safe characters")
    active_session = session or DatabaseSession.default()
    repository = WorkerQueueRepository(session=active_session)
    current = repository.get(queue_item_id)
    if current is None:
        raise OperatorSupportConflictError("queue item does not exist")
    if any(_truthy(current.payload.get(flag)) for flag in _BLOCKED_EXTERNAL_FLAGS):
        raise OperatorSupportConflictError(
            "support retry cannot expand or replay live/customer/payment/delivery boundaries"
        )
    original_payload = copy.deepcopy(current.payload)
    try:
        retried = repository.manual_retry(
            queue_item_id=queue_item_id,
            expected_status=expected_status,
            expected_updated_at=expected_updated_at,
            requested_by=actor["principal_id"],
            reason=reason,
        )
    except ValueError as exc:
        raise OperatorSupportConflictError(str(exc)) from exc
    if retried.payload != original_payload:
        raise RuntimeError("manual retry unexpectedly mutated queue payload")
    event = repository.list_events(queue_item_id)[-1]
    return {
        "surface_id": "operator_support_workbench_internal",
        "action": "RETRY",
        "operation_state": "GOVERNED_MANUAL_RETRY_QUEUED",
        "task": _task_summary(retried),
        "audit_event": _event_summary(event),
        "governance": _governance(),
    }


def _task_summary(item: PersistedWorkerQueueItem) -> dict[str, Any]:
    payload = dict(item.payload)
    nested = dict(payload.get("task_payload") or {})
    scheduler = dict(payload.get("scheduler_task") or {})
    project_id = str(
        nested.get("project_id") or scheduler.get("project_id") or item.trace_refs.get("project_id") or ""
    )
    task_id = str(
        nested.get("task_id") or scheduler.get("task_id") or item.trace_refs.get("task_id") or ""
    )
    external_boundary_open = any(_truthy(payload.get(flag)) for flag in _BLOCKED_EXTERNAL_FLAGS)
    support_blocker = (
        item.status in _BLOCKER_STATUSES
        or bool(item.cancel_requested_at and item.status == "running")
        or bool(item.last_error_category)
    )
    return {
        "queue_item_id": item.queue_item_id,
        "queue_name": item.queue_name,
        "status": item.status,
        "task_id": task_id or None,
        "project_id": project_id or None,
        "runtime_job_kind": str(payload.get("runtime_job_kind") or "") or None,
        "required_worker_capability": str(payload.get("required_worker_capability") or "") or None,
        "priority": item.priority,
        "attempt_count": item.attempt_count,
        "max_attempts": item.max_attempts,
        "progress_stage": item.progress_stage,
        "progress_percent": item.progress_percent,
        "error_category": item.last_error_category,
        "support_blocker": support_blocker,
        "support_retry_available": (
            item.status in {"failed", "dead-letter"} and not external_boundary_open
        ),
        "cancel_requested": bool(item.cancel_requested_at),
        "next_run_at": item.next_run_at,
        "updated_at": item.updated_at,
        "raw_payload_exposed": False,
        "raw_error_exposed": False,
        "external_boundary_open": external_boundary_open,
    }


def _event_summary(event: PersistedWorkerQueueEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "queue_item_id": event.queue_item_id,
        "queue_name": event.queue_name,
        "event_type": event.event_type,
        "previous_status": event.previous_status,
        "next_status": event.next_status,
        "attempt_count": event.attempt_count,
        "occurred_at": event.occurred_at,
        "raw_detail_exposed": False,
    }


def _version_readback(session: DatabaseSession) -> dict[str, Any]:
    api_catalog = _load_json(_REPO_ROOT / "contracts" / "api" / "api_catalog.json")
    onboarding_contract = _load_json(
        _REPO_ROOT / "contracts" / "governance" / "product_onboarding_config_contract.json"
    )
    support_contract = _load_json(
        _REPO_ROOT / "contracts" / "governance" / "operator_support_workbench_contract.json"
    )
    return {
        "application_api_version": "0.1.0",
        "api_catalog_version": api_catalog.get("catalogVersion"),
        "support_contract_version": support_contract.get("contract_version"),
        "product_onboarding_contract_version": onboarding_contract.get("contract_version"),
        "storage_backend": session.storage_backend,
        "storage_schema_revision": session.storage_schema_revision,
        "required_storage_schema_revision": REQUIRED_STORAGE_SCHEMA_REVISION,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _trusted_actor(payload: Mapping[str, Any]) -> dict[str, str]:
    context = payload.get("_internal_auth_context")
    auth = dict(context) if isinstance(context, Mapping) else {}
    permissions = {str(item) for item in auth.get("permissions", [])}
    role = str(auth.get("role") or "").strip()
    principal_id = str(auth.get("principal_id") or "").strip()
    tenant_id = str(auth.get("deployment_tenant_id") or "").strip()
    if (
        not auth.get("authenticated")
        or role not in {"owner", "admin"}
        or "internal_support_admin" not in permissions
        or not principal_id
        or not tenant_id
    ):
        raise OperatorSupportAccessError("owner/admin support permission is required")
    return {
        "principal_id": principal_id,
        "role": role,
        "tenant_id": tenant_id,
        "tenant_scope_sha256": hashlib.sha256(tenant_id.encode("utf-8")).hexdigest(),
    }


def _identifier(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _ID_RE.fullmatch(normalized):
        raise OperatorSupportInputError(f"{field} must be a safe identifier")
    return normalized


def _optional_identifier(value: Any, field: str) -> str:
    return "" if value in {None, ""} else _identifier(value, field)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = default if value in {None, ""} else int(value)
    except (TypeError, ValueError) as exc:
        raise OperatorSupportInputError("limit must be an integer") from exc
    if not minimum <= number <= maximum:
        raise OperatorSupportInputError(f"limit must be between {minimum} and {maximum}")
    return number


def _reject_unknown(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise OperatorSupportInputError("unsupported support fields: " + ", ".join(unknown))


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _governance() -> dict[str, Any]:
    return {
        "contract_ref": SUPPORT_WORKBENCH_CONTRACT_REF,
        "private_single_tenant": True,
        "owner_admin_only": True,
        "raw_task_payload_exposed": False,
        "raw_error_exposed": False,
        "fact_layer_edit_enabled": False,
        "retry_mutates_task_payload": False,
        "live_and_external_actions_enabled": False,
    }


__all__ = [
    "OperatorSupportAccessError",
    "OperatorSupportConflictError",
    "OperatorSupportInputError",
    "SUPPORT_WORKBENCH_CONTRACT_REF",
    "build_operator_support_overview",
    "retry_operator_support_task",
]
