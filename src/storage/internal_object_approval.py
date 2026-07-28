from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy.exc import IntegrityError as SqlAlchemyIntegrityError

from storage.db import DatabaseSession, PersistedOperatorAction
from storage.repositories.operator_action_repo import OperatorActionRepository
from storage.repositories.saleable_opportunity_repo import SaleableOpportunityRepository


APPROVAL_PENDING = "PENDING_REVIEW"
APPROVAL_APPROVED = "APPROVED"
APPROVAL_REJECTED = "REJECTED"
APPROVAL_REVOKED = "REVOKED"
SUPPORTED_APPROVAL_RESOURCE_TYPES = frozenset({"opportunity"})
SUPPORTED_APPROVAL_ACTIONS = frozenset({"internal_preview_download"})
_RESOURCE_VERSION_HASH_KEY = "approval_resource_version_sha256"
_APPROVAL_SCOPE_HASH_KEY = "approval_scope_sha256"
_APPROVAL_VALID_UNTIL_KEY = "approval_valid_until"
_APPROVAL_REQUEST_GENERATION_KEY = "approval_request_generation"
_APPROVAL_TERMINAL_STATES = frozenset(
    {APPROVAL_APPROVED, APPROVAL_REJECTED, APPROVAL_REVOKED}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _work_item_id(*, resource_type: str, resource_id: str, action: str) -> str:
    return f"internal-approval:{resource_type}:{resource_id}:{action}"


def _resource_version_hash(
    *,
    resource_type: str,
    resource_id: str,
    session: DatabaseSession | None,
) -> str | None:
    if resource_type != "opportunity":
        return None
    record = SaleableOpportunityRepository(session=session).get_by_id(resource_id)
    if record is None:
        return None
    canonical_payload = json.dumps(
        record.payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical_payload).hexdigest()


def _append_unique(
    repository: OperatorActionRepository,
    event: PersistedOperatorAction,
    *,
    conflict_message: str,
) -> PersistedOperatorAction:
    try:
        return repository.append(event)
    except (ValueError, sqlite3.IntegrityError, SqlAlchemyIntegrityError) as exc:
        raise ValueError(conflict_message) from exc


def _approval_readback(
    request_event: PersistedOperatorAction,
    decision_event: PersistedOperatorAction | None,
    *,
    current_resource_version_hash: str | None,
    current_approval_scope_sha256: str | None,
) -> dict[str, Any]:
    state = decision_event.action_state if decision_event is not None else APPROVAL_PENDING
    requester = request_event.requested_by
    reviewer = decision_event.reviewer if decision_event is not None else ""
    separation_of_duties_satisfied = bool(reviewer) and reviewer != requester
    approved_resource_version_hash = str(
        request_event.trace_refs.get(_RESOURCE_VERSION_HASH_KEY) or ""
    )
    resource_version_matches = bool(
        approved_resource_version_hash and current_resource_version_hash
    ) and compare_digest(approved_resource_version_hash, current_resource_version_hash)
    approved_scope_sha256 = str(request_event.trace_refs.get(_APPROVAL_SCOPE_HASH_KEY) or "")
    approval_scope_matches = bool(
        approved_scope_sha256 and current_approval_scope_sha256
    ) and compare_digest(approved_scope_sha256, current_approval_scope_sha256)
    valid_until = (
        str(decision_event.trace_refs.get(_APPROVAL_VALID_UNTIL_KEY) or "")
        if decision_event is not None
        else ""
    )
    valid_until_at = _parse_iso_timestamp(valid_until)
    approval_expired = state == APPROVAL_APPROVED and (
        valid_until_at is None or _now() >= valid_until_at
    )
    approval_revoked = state == APPROVAL_REVOKED
    return {
        "request_id": request_event.action_event_id,
        "resource_type": request_event.object_refs.get("resource_type", ""),
        "resource_id": request_event.object_refs.get("resource_id", ""),
        "action": request_event.object_refs.get("action", ""),
        "state": state,
        "reason": request_event.reason,
        "requested_by": requester,
        "requested_by_role": request_event.requested_by_role,
        "requested_at": request_event.requested_at,
        "reviewer": reviewer or None,
        "reviewer_role": decision_event.reviewer_role if decision_event is not None else None,
        "decision_reason": decision_event.reason if decision_event is not None else None,
        "decided_at": decision_event.completed_at if decision_event is not None else None,
        "valid_until": valid_until or None,
        "approval_expired": approval_expired,
        "approval_revoked": approval_revoked,
        "decision_event_id": decision_event.action_event_id if decision_event is not None else None,
        "separation_of_duties_satisfied": separation_of_duties_satisfied,
        "resource_exists": current_resource_version_hash is not None,
        "resource_version_sha256": approved_resource_version_hash or None,
        "resource_version_matches": resource_version_matches,
        "approval_scope_sha256": approved_scope_sha256 or None,
        "approval_scope_matches": approval_scope_matches,
        "approval_subject": requester,
        "approval_satisfied": (
            state == APPROVAL_APPROVED
            and not approval_expired
            and separation_of_duties_satisfied
            and resource_version_matches
            and approval_scope_matches
        ),
        "approval_usage_policy": "REPEATABLE_INTERNAL_PREVIEW_WITHIN_VALIDITY_EACH_USE_AUDITED",
        "authentication_implies_approval": False,
    }


def _events_for_request(
    repository: OperatorActionRepository,
    request_id: str,
) -> tuple[PersistedOperatorAction, PersistedOperatorAction | None]:
    request_event: PersistedOperatorAction | None = None
    decision_events: list[PersistedOperatorAction] = []
    for event in repository.list_all():
        if event.action_event_id == request_id and event.action_state == APPROVAL_PENDING:
            request_event = event
        if (
            event.object_refs.get("approval_request_id") == request_id
            and event.action_state in _APPROVAL_TERMINAL_STATES
        ):
            decision_events.append(event)
    if request_event is None:
        raise KeyError(request_id)
    decision_event = (
        max(
            decision_events,
            key=lambda event: (str(event.completed_at or ""), event.action_event_id),
        )
        if decision_events
        else None
    )
    return request_event, decision_event


def request_object_approval(
    *,
    resource_type: str,
    resource_id: str,
    action: str,
    reason: str,
    requested_by: str,
    requested_by_role: str,
    approval_scope_sha256: str,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    if resource_type not in SUPPORTED_APPROVAL_RESOURCE_TYPES:
        raise ValueError("unsupported approval resource_type")
    if action not in SUPPORTED_APPROVAL_ACTIONS:
        raise ValueError("unsupported approval action")
    if len(approval_scope_sha256) != 64:
        raise ValueError("approval scope SHA256 is required")
    repository = OperatorActionRepository(session=session)
    current_resource_version_hash = _resource_version_hash(
        resource_type=resource_type,
        resource_id=resource_id,
        session=session,
    )
    if current_resource_version_hash is None:
        raise KeyError(resource_id)
    existing = approval_for_resource(
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        current_approval_scope_sha256=approval_scope_sha256,
        session=session,
    )
    if (
        existing
        and existing["state"] == APPROVAL_PENDING
        and existing.get("resource_version_matches")
        and existing.get("approval_scope_matches")
    ):
        raise ValueError("an approval request is already pending for this object and action")
    if existing and existing.get("approval_satisfied"):
        raise ValueError("an active approval already exists for this object version and action")
    if (
        existing
        and existing["state"] == APPROVAL_REJECTED
        and existing.get("resource_version_matches")
        and existing.get("approval_scope_matches")
    ):
        raise ValueError("a rejected approval can only be re-requested after the target changes")

    requested_at = _now_iso()
    work_item_id = _work_item_id(
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
    )
    request_generation = 1 + sum(
        event.action_state == APPROVAL_PENDING
        for event in repository.list(work_item_id=work_item_id)
    )
    request_slot = (
        f"{work_item_id}:{current_resource_version_hash}:{approval_scope_sha256}:"
        f"{request_generation}"
    ).encode("utf-8")
    request_id = f"APR-{hashlib.sha256(request_slot).hexdigest().upper()}"
    request_event = PersistedOperatorAction(
        action_event_id=request_id,
        work_item_id=work_item_id,
        stage_scope=7,
        action_id="REQUEST_OBJECT_APPROVAL",
        button_flow_id="request_object_approval",
        action_state=APPROVAL_PENDING,
        resulting_assignment_lifecycle_state=APPROVAL_PENDING,
        requested_by_role=requested_by_role,
        requested_by=requested_by,
        assigned_owner_role="reviewer",
        assigned_owner="",
        reviewer_role="",
        reviewer="",
        reason=reason,
        object_refs={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
        },
        trace_refs={
            "approval_work_item_version": "2",
            _APPROVAL_REQUEST_GENERATION_KEY: str(request_generation),
            _RESOURCE_VERSION_HASH_KEY: current_resource_version_hash,
            _APPROVAL_SCOPE_HASH_KEY: approval_scope_sha256,
        },
        audit_refs={"approval_request_id": request_id},
        requested_at=requested_at,
        completed_at=None,
    )
    _append_unique(
        repository,
        request_event,
        conflict_message="an approval request is already pending for this object and action",
    )
    return _approval_readback(
        request_event,
        None,
        current_resource_version_hash=current_resource_version_hash,
        current_approval_scope_sha256=approval_scope_sha256,
    )


def decide_object_approval(
    *,
    request_id: str,
    decision: str,
    reason: str,
    reviewer: str,
    reviewer_role: str,
    current_approval_scope_sha256: str,
    valid_for_seconds: int = 15 * 60,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    normalized_decision = decision.strip().upper()
    if normalized_decision not in {APPROVAL_APPROVED, APPROVAL_REJECTED}:
        raise ValueError("decision must be APPROVED or REJECTED")
    if valid_for_seconds <= 0:
        raise ValueError("approval validity must be positive")
    repository = OperatorActionRepository(session=session)
    request_event, existing_decision = _events_for_request(repository, request_id)
    if existing_decision is not None:
        raise ValueError("approval request already has a decision")
    if reviewer == request_event.requested_by:
        raise PermissionError("approval requester cannot approve or reject the same request")
    current_resource_version_hash = _resource_version_hash(
        resource_type=str(request_event.object_refs.get("resource_type") or ""),
        resource_id=str(request_event.object_refs.get("resource_id") or ""),
        session=session,
    )
    approved_resource_version_hash = str(
        request_event.trace_refs.get(_RESOURCE_VERSION_HASH_KEY) or ""
    )
    if not current_resource_version_hash or not approved_resource_version_hash or not compare_digest(
        current_resource_version_hash,
        approved_resource_version_hash,
    ):
        raise ValueError("approval resource changed or no longer exists; create a new request")
    approved_scope_sha256 = str(request_event.trace_refs.get(_APPROVAL_SCOPE_HASH_KEY) or "")
    if not approved_scope_sha256 or not current_approval_scope_sha256 or not compare_digest(
        approved_scope_sha256,
        current_approval_scope_sha256,
    ):
        raise ValueError("approval target package changed; create a new request")

    completed_at_value = _now()
    completed_at = completed_at_value.isoformat()
    valid_until = (
        (completed_at_value + timedelta(seconds=valid_for_seconds)).isoformat()
        if normalized_decision == APPROVAL_APPROVED
        else ""
    )
    decision_event = PersistedOperatorAction(
        action_event_id=f"APRDEC-{request_id}",
        work_item_id=request_event.work_item_id,
        stage_scope=request_event.stage_scope,
        action_id=f"DECIDE_OBJECT_APPROVAL_{normalized_decision}",
        button_flow_id="decide_object_approval",
        action_state=normalized_decision,
        resulting_assignment_lifecycle_state=normalized_decision,
        requested_by_role=request_event.requested_by_role,
        requested_by=request_event.requested_by,
        assigned_owner_role=request_event.requested_by_role,
        assigned_owner=request_event.requested_by,
        reviewer_role=reviewer_role,
        reviewer=reviewer,
        reason=reason,
        object_refs={
            **request_event.object_refs,
            "approval_request_id": request_id,
        },
        trace_refs={
            "approval_work_item_version": "2",
            _APPROVAL_VALID_UNTIL_KEY: valid_until,
            _RESOURCE_VERSION_HASH_KEY: current_resource_version_hash,
            _APPROVAL_SCOPE_HASH_KEY: current_approval_scope_sha256,
        },
        audit_refs={
            "approval_request_id": request_id,
            "approval_decision_event_id": "pending_append",
        },
        requested_at=request_event.requested_at,
        completed_at=completed_at,
    )
    decision_event = PersistedOperatorAction(
        **{
            **decision_event.__dict__,
            "audit_refs": {
                "approval_request_id": request_id,
                "approval_decision_event_id": decision_event.action_event_id,
            },
        }
    )
    _append_unique(
        repository,
        decision_event,
        conflict_message="approval request already has a decision",
    )
    return _approval_readback(
        request_event,
        decision_event,
        current_resource_version_hash=current_resource_version_hash,
        current_approval_scope_sha256=current_approval_scope_sha256,
    )


def revoke_object_approval(
    *,
    request_id: str,
    reason: str,
    revoked_by: str,
    revoked_by_role: str,
    current_approval_scope_sha256: str | None,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    repository = OperatorActionRepository(session=session)
    request_event, decision_event = _events_for_request(repository, request_id)
    if decision_event is None or decision_event.action_state != APPROVAL_APPROVED:
        raise ValueError("only an approved, non-revoked request can be revoked")
    if revoked_by == request_event.requested_by:
        raise PermissionError("approval requester cannot revoke the same request")

    revoked_at = _now_iso()
    revocation_event = PersistedOperatorAction(
        action_event_id=f"APRREV-{request_id}",
        work_item_id=request_event.work_item_id,
        stage_scope=request_event.stage_scope,
        action_id="REVOKE_OBJECT_APPROVAL",
        button_flow_id="revoke_object_approval",
        action_state=APPROVAL_REVOKED,
        resulting_assignment_lifecycle_state=APPROVAL_REVOKED,
        requested_by_role=request_event.requested_by_role,
        requested_by=request_event.requested_by,
        assigned_owner_role=request_event.requested_by_role,
        assigned_owner=request_event.requested_by,
        reviewer_role=revoked_by_role,
        reviewer=revoked_by,
        reason=reason,
        object_refs={
            **request_event.object_refs,
            "approval_request_id": request_id,
        },
        trace_refs={
            "approval_work_item_version": "2",
            _APPROVAL_VALID_UNTIL_KEY: str(
                decision_event.trace_refs.get(_APPROVAL_VALID_UNTIL_KEY) or ""
            ),
            _RESOURCE_VERSION_HASH_KEY: str(
                request_event.trace_refs.get(_RESOURCE_VERSION_HASH_KEY) or ""
            ),
            _APPROVAL_SCOPE_HASH_KEY: str(
                request_event.trace_refs.get(_APPROVAL_SCOPE_HASH_KEY) or ""
            ),
        },
        audit_refs={
            "approval_request_id": request_id,
            "approval_decision_event_id": decision_event.action_event_id,
            "approval_revocation_event_id": f"APRREV-{request_id}",
        },
        requested_at=request_event.requested_at,
        completed_at=revoked_at,
    )
    _append_unique(
        repository,
        revocation_event,
        conflict_message="approval request is already revoked",
    )
    current_resource_version_hash = _resource_version_hash(
        resource_type=str(request_event.object_refs.get("resource_type") or ""),
        resource_id=str(request_event.object_refs.get("resource_id") or ""),
        session=session,
    )
    return _approval_readback(
        request_event,
        revocation_event,
        current_resource_version_hash=current_resource_version_hash,
        current_approval_scope_sha256=current_approval_scope_sha256,
    )


def approval_by_request_id(
    request_id: str,
    *,
    current_approval_scope_sha256: str | None = None,
    session: DatabaseSession | None = None,
) -> dict[str, Any] | None:
    repository = OperatorActionRepository(session=session)
    try:
        request_event, decision_event = _events_for_request(repository, request_id)
    except KeyError:
        return None
    current_resource_version_hash = _resource_version_hash(
        resource_type=str(request_event.object_refs.get("resource_type") or ""),
        resource_id=str(request_event.object_refs.get("resource_id") or ""),
        session=session,
    )
    return _approval_readback(
        request_event,
        decision_event,
        current_resource_version_hash=current_resource_version_hash,
        current_approval_scope_sha256=current_approval_scope_sha256,
    )


def approval_for_resource(
    *,
    resource_type: str,
    resource_id: str,
    action: str,
    current_approval_scope_sha256: str | None = None,
    session: DatabaseSession | None = None,
) -> dict[str, Any] | None:
    if resource_type not in SUPPORTED_APPROVAL_RESOURCE_TYPES:
        return None
    if action not in SUPPORTED_APPROVAL_ACTIONS:
        return None
    repository = OperatorActionRepository(session=session)
    events = repository.list(
        work_item_id=_work_item_id(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
        )
    )
    requests = [event for event in events if event.action_state == APPROVAL_PENDING]
    if not requests:
        return None
    request_event = max(requests, key=lambda event: (event.requested_at, event.action_event_id))
    decisions = [
        event
        for event in events
        if event.object_refs.get("approval_request_id") == request_event.action_event_id
        and event.action_state in _APPROVAL_TERMINAL_STATES
    ]
    decision_event = (
        max(decisions, key=lambda event: (str(event.completed_at or ""), event.action_event_id))
        if decisions
        else None
    )
    return _approval_readback(
        request_event,
        decision_event,
        current_resource_version_hash=_resource_version_hash(
            resource_type=resource_type,
            resource_id=resource_id,
            session=session,
        ),
        current_approval_scope_sha256=current_approval_scope_sha256,
    )


def approval_context_for_download(
    payload: Mapping[str, Any],
    *,
    current_approval_scope_sha256: str,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    opportunity_id = str(payload.get("opportunity_id") or "").strip()
    return approval_for_resource(
        resource_type="opportunity",
        resource_id=opportunity_id,
        action="internal_preview_download",
        current_approval_scope_sha256=current_approval_scope_sha256,
        session=session,
    ) or {
        "resource_type": "opportunity",
        "resource_id": opportunity_id,
        "action": "internal_preview_download",
        "state": "NOT_REQUESTED",
        "approval_satisfied": False,
        "separation_of_duties_satisfied": False,
        "authentication_implies_approval": False,
    }


def record_approved_object_action(
    *,
    resource_type: str,
    resource_id: str,
    action: str,
    performed_by: str,
    performed_by_role: str,
    current_approval_scope_sha256: str,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    approval = approval_for_resource(
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        current_approval_scope_sha256=current_approval_scope_sha256,
        session=session,
    )
    if approval is None or not approval.get("approval_satisfied"):
        raise PermissionError("an active approval for the current object version is required")
    if performed_by != approval.get("approval_subject"):
        raise PermissionError("the approved principal must perform this object action")
    repository = OperatorActionRepository(session=session)
    execution_event_id = f"APREXEC-{uuid4().hex.upper()}"
    execution_event = PersistedOperatorAction(
        action_event_id=execution_event_id,
        work_item_id=_work_item_id(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
        ),
        stage_scope=7,
        action_id="AUTHORIZE_INTERNAL_PREVIEW_DOWNLOAD_RESPONSE",
        button_flow_id="approved_internal_preview_download",
        action_state="GRANTED",
        resulting_assignment_lifecycle_state="GRANTED",
        requested_by_role=performed_by_role,
        requested_by=performed_by,
        assigned_owner_role=performed_by_role,
        assigned_owner=performed_by,
        reviewer_role=str(approval.get("reviewer_role") or ""),
        reviewer=str(approval.get("reviewer") or ""),
        reason="approved internal preview download response generation granted",
        object_refs={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "approval_request_id": str(approval.get("request_id") or ""),
        },
        trace_refs={
            "approval_work_item_version": "2",
            _RESOURCE_VERSION_HASH_KEY: str(approval.get("resource_version_sha256") or ""),
            _APPROVAL_SCOPE_HASH_KEY: str(approval.get("approval_scope_sha256") or ""),
        },
        audit_refs={
            "approval_request_id": str(approval.get("request_id") or ""),
            "approval_decision_event_id": str(approval.get("decision_event_id") or ""),
            "approval_execution_event_id": execution_event_id,
        },
        requested_at=_now_iso(),
        completed_at=_now_iso(),
    )
    repository.append(execution_event)
    return {
        **approval,
        "execution_event_id": execution_event_id,
        "executed_by": performed_by,
        "executed_by_role": performed_by_role,
    }


__all__ = [
    "APPROVAL_APPROVED",
    "APPROVAL_PENDING",
    "APPROVAL_REJECTED",
    "APPROVAL_REVOKED",
    "SUPPORTED_APPROVAL_ACTIONS",
    "SUPPORTED_APPROVAL_RESOURCE_TYPES",
    "approval_by_request_id",
    "approval_context_for_download",
    "approval_for_resource",
    "decide_object_approval",
    "record_approved_object_action",
    "revoke_object_approval",
    "request_object_approval",
]
