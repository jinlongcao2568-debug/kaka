from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord


AGENT_MEMORY_GOVERNANCE_CONTRACT_REF = (
    "contracts/agent/agent_memory_governance_contract.json"
)
AGENT_MEMORY_OBJECT_TYPE = "agent_memory_record"
AGENT_MEMORY_AUDIT_OBJECT_TYPE = "agent_memory_audit"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REGION_RE = re.compile(r"^CN-[A-Z0-9-]{2,29}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENSITIVE_RE = re.compile(
    r"(?:api[_\s-]?key|access[_\s-]?token|authorization|bearer\s+\S+|cookie|"
    r"password|passwd|密码\s*[:：=]|secret\s*[:：=]|private[_\s-]?key|"
    r"身份证|银行卡|社保号|手机号|手机号码)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_CN_ID_RE = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\w)")
_SECRET_QUERY_RE = re.compile(
    r"[?&](?:token|access_token|api_key|apikey|signature|sig|auth|session|key)=",
    re.IGNORECASE,
)

_MEMORY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "response_language": {
        "scopes": {"PRINCIPAL"},
        "values": {"zh-CN", "en-US"},
        "default_ttl_days": 180,
        "max_ttl_days": 365,
        "model_safe": True,
    },
    "response_detail": {
        "scopes": {"PRINCIPAL"},
        "values": {"concise", "standard", "detailed"},
        "default_ttl_days": 180,
        "max_ttl_days": 365,
        "model_safe": True,
    },
    "preferred_output_format": {
        "scopes": {"PRINCIPAL", "PROJECT"},
        "values": {"text", "checklist", "table"},
        "default_ttl_days": 90,
        "max_ttl_days": 365,
        "model_safe": True,
    },
    "default_region_code": {
        "scopes": {"PRINCIPAL", "PROJECT"},
        "pattern": _REGION_RE,
        "default_ttl_days": 90,
        "max_ttl_days": 180,
        "model_safe": True,
    },
    "project_workflow_note": {
        "scopes": {"PROJECT"},
        "max_length": 500,
        "default_ttl_days": 30,
        "max_ttl_days": 90,
        "model_safe": True,
    },
}


class AgentMemoryAccessError(ValueError):
    pass


class AgentMemoryInputError(ValueError):
    pass


class AgentMemoryConflictError(ValueError):
    pass


def mutate_agent_memory(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
    now_factory: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    active_session = session or DatabaseSession.default()
    actor = _trusted_actor(payload)
    action = str(payload.get("action") or "").strip().upper()
    scope = str(payload.get("scope") or "").strip().upper()
    project_id = _optional_identifier(payload.get("project_id"), field="project_id")
    memory_key = str(payload.get("memory_key") or "").strip()
    definition = _validate_target(scope=scope, project_id=project_id, memory_key=memory_key)
    expected_version = payload.get("expected_version")
    ttl_days_value = payload.get("ttl_days")
    value_input = payload.get("value")
    if action not in {"UPSERT", "CORRECT", "DELETE"}:
        raise AgentMemoryInputError("action must be UPSERT, CORRECT, or DELETE")
    if expected_version is not None and (
        isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1
    ):
        raise AgentMemoryInputError("expected_version must be a positive integer or null")

    now = _normalized_now(now_factory())
    sweep_expired_agent_memories(session=active_session, now=now)
    memory_id = _memory_id(
        tenant_id=actor["tenant_id"],
        principal_id=actor["principal_id"],
        scope=scope,
        project_id=project_id,
        memory_key=memory_key,
    )
    existing = active_session.get_record(AGENT_MEMORY_OBJECT_TYPE, memory_id)
    existing_payload = dict(existing.payload) if existing is not None else {}
    existing_state = str(existing_payload.get("state") or "")
    existing_version = int(existing_payload.get("version") or 0)

    if expected_version is not None and expected_version != existing_version:
        raise AgentMemoryConflictError(
            f"memory version conflict: expected {expected_version}, current {existing_version}"
        )

    if action == "DELETE":
        if value_input is not None or ttl_days_value is not None:
            raise AgentMemoryInputError("DELETE does not accept value or ttl_days")
        if existing is None:
            raise AgentMemoryConflictError("memory does not exist")
        if expected_version is None:
            raise AgentMemoryInputError("DELETE requires expected_version")
        if existing_state == "DELETED":
            return _mutation_response(
                action=action,
                operation_state="REPLAYED_ALREADY_DELETED",
                memory=_public_memory(existing_payload, now=now, include_value=False),
                actor=actor,
                audit_event_id="",
                idempotent_replay=True,
            )
        next_version = existing_version + 1
        next_payload = {
            **existing_payload,
            "value": None,
            "state": "DELETED",
            "version": next_version,
            "updated_at": now,
            "deleted_at": now,
            "expired_at": existing_payload.get("expired_at"),
            "expires_at": existing_payload.get("expires_at"),
            "purge_eligible_after": _add_days(now, 30),
            "last_mutation": "DELETE",
        }
        event_id = _persist_memory_and_audit(
            session=active_session,
            actor=actor,
            previous=existing_payload,
            current=next_payload,
            operation="DELETE",
        )
        return _mutation_response(
            action=action,
            operation_state="DELETED",
            memory=_public_memory(next_payload, now=now, include_value=False),
            actor=actor,
            audit_event_id=event_id,
        )

    if value_input is None or not isinstance(value_input, str):
        raise AgentMemoryInputError(f"{action} requires a string value")
    value = _validate_value(memory_key, value_input, definition)
    ttl_days = _validate_ttl(ttl_days_value, definition)
    value_sha256 = _sha256_text(value)

    if action == "UPSERT" and existing_state == "ACTIVE":
        if str(existing_payload.get("value_sha256") or "") != value_sha256:
            raise AgentMemoryConflictError(
                "active memory already exists; use CORRECT with expected_version"
            )
        return _mutation_response(
            action=action,
            operation_state="REPLAYED_IDEMPOTENT",
            memory=_public_memory(existing_payload, now=now),
            actor=actor,
            audit_event_id="",
            idempotent_replay=True,
        )
    if action == "CORRECT":
        if existing is None or existing_state != "ACTIVE":
            raise AgentMemoryConflictError("CORRECT requires an active memory")
        if expected_version is None:
            raise AgentMemoryInputError("CORRECT requires expected_version")
        if str(existing_payload.get("value_sha256") or "") == value_sha256:
            return _mutation_response(
                action=action,
                operation_state="REPLAYED_IDEMPOTENT",
                memory=_public_memory(existing_payload, now=now),
                actor=actor,
                audit_event_id="",
                idempotent_replay=True,
            )

    next_version = existing_version + 1
    created_at = str(existing_payload.get("created_at") or now)
    operation = "CORRECT" if existing_state == "ACTIVE" else "UPSERT"
    next_payload = {
        "memory_id": memory_id,
        "tenant_scope_sha256": _tenant_scope_sha256(actor["tenant_id"]),
        "scope": scope,
        "subject_principal_id": actor["principal_id"] if scope == "PRINCIPAL" else None,
        "project_id": project_id or None,
        "memory_key": memory_key,
        "value": value,
        "value_sha256": value_sha256,
        "state": "ACTIVE",
        "version": next_version,
        "created_at": created_at,
        "updated_at": now,
        "expires_at": _add_days(now, ttl_days),
        "expired_at": None,
        "deleted_at": None,
        "purge_eligible_after": None,
        "last_mutation": operation,
        "trust_class": "UNVERIFIED_CONTEXT_ONLY",
        "fact_evidence_eligible": False,
        "citation_eligible": False,
        "gate_input_eligible": False,
        "model_safe_projection_allowed": bool(definition["model_safe"]),
    }
    event_id = _persist_memory_and_audit(
        session=active_session,
        actor=actor,
        previous=existing_payload,
        current=next_payload,
        operation=operation,
    )
    return _mutation_response(
        action=action,
        operation_state="CORRECTED" if operation == "CORRECT" else "UPSERTED",
        memory=_public_memory(next_payload, now=now),
        actor=actor,
        audit_event_id=event_id,
    )


def list_agent_memories(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
    now_factory: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    active_session = session or DatabaseSession.default()
    actor = _trusted_actor(payload)
    allowed_fields = {
        "_internal_auth_context",
        "scope",
        "project_id",
        "include_deleted",
        "include_expired",
    }
    unknown = sorted(set(payload).difference(allowed_fields))
    if unknown:
        raise AgentMemoryInputError("unknown query fields: " + ",".join(unknown))
    scope = str(payload.get("scope") or "ALL").strip().upper()
    if scope not in {"ALL", "PRINCIPAL", "PROJECT"}:
        raise AgentMemoryInputError("scope must be ALL, PRINCIPAL, or PROJECT")
    project_id = _optional_identifier(payload.get("project_id"), field="project_id")
    if scope == "PROJECT" and not project_id:
        raise AgentMemoryInputError("PROJECT scope requires project_id")
    include_deleted = _strict_bool(payload.get("include_deleted", False), "include_deleted")
    include_expired = _strict_bool(payload.get("include_expired", False), "include_expired")
    now = _normalized_now(now_factory())
    sweep_expired_agent_memories(session=active_session, now=now)

    memories: list[dict[str, Any]] = []
    for record in active_session.list_records(AGENT_MEMORY_OBJECT_TYPE):
        item = dict(record.payload)
        if item.get("tenant_scope_sha256") != _tenant_scope_sha256(actor["tenant_id"]):
            continue
        item_scope = str(item.get("scope") or "")
        if scope != "ALL" and item_scope != scope:
            continue
        if item_scope == "PRINCIPAL":
            if item.get("subject_principal_id") != actor["principal_id"]:
                continue
        elif item_scope == "PROJECT":
            if not project_id or item.get("project_id") != project_id:
                continue
        else:
            continue
        state = str(item.get("state") or "")
        if state == "DELETED" and not include_deleted:
            continue
        if state == "EXPIRED" and not include_expired:
            continue
        memories.append(_public_memory(item, now=now, include_value=state == "ACTIVE"))
    memories.sort(key=lambda item: (str(item["scope"]), str(item["memory_key"])))
    return {
        "surface_id": "agent_memory_governance_internal",
        "context_scope": {
            "tenant_scope_sha256": _tenant_scope_sha256(actor["tenant_id"]),
            "principal_id": actor["principal_id"],
            "project_id": project_id or None,
            "requested_scope": scope,
        },
        "memories": memories,
        "count": len(memories),
        "include_deleted": include_deleted,
        "include_expired": include_expired,
        "governance": _governance(),
    }


def build_model_safe_agent_memory_context(
    actor: Mapping[str, Any],
    *,
    project_id: str = "",
    session: DatabaseSession | None = None,
    now_factory: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    """Return the only memory projection that may accompany a model request.

    Memory values remain unverified context. This projection is never a fact,
    evidence, citation, gate input, or approval signal.
    """

    if not actor.get("authenticated") or not str(actor.get("principal_id") or "").strip():
        return _empty_context("UNAVAILABLE_UNAUTHENTICATED")
    active_session = session or DatabaseSession.default()
    trusted = _actor_scope(actor, require_permission=False)
    safe_project_id = _optional_identifier(project_id, field="project_id")
    now = _normalized_now(now_factory())
    sweep_expired_agent_memories(session=active_session, now=now)
    items: list[dict[str, Any]] = []
    for record in active_session.list_records(AGENT_MEMORY_OBJECT_TYPE):
        value = dict(record.payload)
        if value.get("tenant_scope_sha256") != _tenant_scope_sha256(trusted["tenant_id"]):
            continue
        if value.get("state") != "ACTIVE":
            continue
        scope = str(value.get("scope") or "")
        if scope == "PRINCIPAL" and value.get("subject_principal_id") != trusted["principal_id"]:
            continue
        if scope == "PROJECT" and (
            not safe_project_id or value.get("project_id") != safe_project_id
        ):
            continue
        memory_key = str(value.get("memory_key") or "")
        definition = _MEMORY_DEFINITIONS.get(memory_key)
        raw_value = value.get("value")
        if not definition or not definition.get("model_safe") or not isinstance(raw_value, str):
            continue
        if _contains_sensitive_data(raw_value):
            continue
        items.append(
            {
                "memory_id": value.get("memory_id"),
                "scope": scope,
                "project_id": value.get("project_id"),
                "memory_key": memory_key,
                "value": raw_value,
                "version": value.get("version"),
                "expires_at": value.get("expires_at"),
                "trust_class": "UNVERIFIED_CONTEXT_ONLY",
                "fact_evidence_eligible": False,
                "citation_eligible": False,
                "gate_input_eligible": False,
            }
        )
    items.sort(key=lambda item: (str(item["scope"]), str(item["memory_key"])))
    return {
        "context_state": "READY" if items else "EMPTY",
        "tenant_scope_sha256": _tenant_scope_sha256(trusted["tenant_id"]),
        "principal_id": trusted["principal_id"],
        "project_id": safe_project_id or None,
        "items": items,
        "fact_evidence_eligible": False,
        "citation_eligible": False,
        "gate_input_eligible": False,
        "sensitive_data_included": False,
        "raw_conversation_history_included": False,
        "model_provider_call_executed": False,
    }


def sweep_expired_agent_memories(
    *,
    session: DatabaseSession | None = None,
    now: str | None = None,
) -> int:
    active_session = session or DatabaseSession.default()
    current = _normalized_now(now or utc_now_iso())
    expired_count = 0
    for record in active_session.list_records(AGENT_MEMORY_OBJECT_TYPE):
        value = dict(record.payload)
        if value.get("state") != "ACTIVE" or not _is_expired(value, current):
            continue
        previous = copy.deepcopy(value)
        value.update(
            {
                "value": None,
                "state": "EXPIRED",
                "updated_at": current,
                "expired_at": current,
                "purge_eligible_after": _add_days(current, 30),
                "last_mutation": "EXPIRE",
            }
        )
        actor = {
            "tenant_id": str(record.object_refs.get("tenant_id") or "unknown"),
            "principal_id": "agent-memory-expiry-sweeper",
            "role": "system",
        }
        _persist_memory_and_audit(
            session=active_session,
            actor=actor,
            previous=previous,
            current=value,
            operation="EXPIRE",
        )
        expired_count += 1
    return expired_count


def _trusted_actor(payload: Mapping[str, Any]) -> dict[str, str]:
    actor = payload.get("_internal_auth_context")
    if not isinstance(actor, Mapping):
        raise AgentMemoryAccessError("authenticated transport context is required")
    return _actor_scope(actor, require_permission=True)


def _actor_scope(actor: Mapping[str, Any], *, require_permission: bool) -> dict[str, str]:
    if not actor.get("authenticated"):
        raise AgentMemoryAccessError("authenticated transport context is required")
    principal_id = str(actor.get("principal_id") or "").strip()
    if not _ID_RE.fullmatch(principal_id):
        raise AgentMemoryAccessError("valid authenticated principal_id is required")
    if require_permission and "internal_agent_memory" not in set(actor.get("permissions") or []):
        raise AgentMemoryAccessError("internal_agent_memory permission is required")
    tenant_id = str(actor.get("deployment_tenant_id") or "local-development").strip()
    if not tenant_id or len(tenant_id) > 128:
        raise AgentMemoryAccessError("valid deployment tenant scope is required")
    return {
        "tenant_id": tenant_id,
        "principal_id": principal_id,
        "role": str(actor.get("role") or "unknown"),
    }


def _validate_target(*, scope: str, project_id: str, memory_key: str) -> dict[str, Any]:
    if scope not in {"PRINCIPAL", "PROJECT"}:
        raise AgentMemoryInputError("scope must be PRINCIPAL or PROJECT")
    if scope == "PROJECT" and not project_id:
        raise AgentMemoryInputError("PROJECT scope requires project_id")
    if scope == "PRINCIPAL" and project_id:
        raise AgentMemoryInputError("PRINCIPAL scope does not accept project_id")
    definition = _MEMORY_DEFINITIONS.get(memory_key)
    if definition is None:
        raise AgentMemoryInputError("memory_key is not registered")
    if scope not in definition["scopes"]:
        raise AgentMemoryInputError(f"memory_key {memory_key} is not allowed for {scope} scope")
    return definition


def _validate_value(memory_key: str, value: str, definition: Mapping[str, Any]) -> str:
    normalized = value.strip()
    max_length = int(definition.get("max_length") or 64)
    if not normalized or len(normalized) > max_length:
        raise AgentMemoryInputError(
            f"memory value for {memory_key} must contain 1-{max_length} characters"
        )
    if _CONTROL_RE.search(normalized):
        raise AgentMemoryInputError("memory value contains control characters")
    if _contains_sensitive_data(normalized):
        raise AgentMemoryInputError("memory value contains prohibited sensitive data")
    allowed_values = definition.get("values")
    if allowed_values and normalized not in allowed_values:
        raise AgentMemoryInputError(
            f"memory value for {memory_key} is not in the registered allowlist"
        )
    pattern = definition.get("pattern")
    if pattern and pattern.fullmatch(normalized) is None:
        raise AgentMemoryInputError(f"memory value for {memory_key} has an invalid format")
    return normalized


def _validate_ttl(value: Any, definition: Mapping[str, Any]) -> int:
    if value is None:
        return int(definition["default_ttl_days"])
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentMemoryInputError("ttl_days must be an integer")
    maximum = int(definition["max_ttl_days"])
    if value < 1 or value > maximum:
        raise AgentMemoryInputError(f"ttl_days must be between 1 and {maximum}")
    return value


def _persist_memory_and_audit(
    *,
    session: DatabaseSession,
    actor: Mapping[str, str],
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    operation: str,
) -> str:
    memory_id = str(current["memory_id"])
    version = int(current["version"])
    now = str(current["updated_at"])
    event_id = f"AGENT-MEMORY-AUDIT-{memory_id}-{version}-{operation}"
    project_id = str(current.get("project_id") or "") or None
    tenant_id = str(actor.get("tenant_id") or "unknown")
    with session.bulk_write():
        session.upsert_record(
            PersistedRecord(
                object_type=AGENT_MEMORY_OBJECT_TYPE,
                record_id=memory_id,
                stage_scope=0,
                project_id=project_id,
                object_refs={
                    "tenant_id": tenant_id,
                    "scope": str(current.get("scope") or ""),
                    "memory_key": str(current.get("memory_key") or ""),
                },
                decision_states={"memory_state": str(current.get("state") or "")},
                trace_refs={
                    "value_sha256": str(current.get("value_sha256") or ""),
                    "contract_ref": AGENT_MEMORY_GOVERNANCE_CONTRACT_REF,
                },
                audit_refs={
                    "last_actor_principal_id": str(actor.get("principal_id") or "unknown"),
                    "last_actor_role": str(actor.get("role") or "unknown"),
                },
                governed_state={
                    "fact_evidence_eligible": False,
                    "citation_eligible": False,
                    "gate_input_eligible": False,
                    "sensitive_data_allowed": False,
                },
                writeback_state={
                    "formal_fact_writeback": False,
                    "customer_writeback": False,
                },
                payload=copy.deepcopy(dict(current)),
                persisted_at=now,
            )
        )
        session.upsert_record(
            PersistedRecord(
                object_type=AGENT_MEMORY_AUDIT_OBJECT_TYPE,
                record_id=event_id,
                stage_scope=0,
                project_id=project_id,
                object_refs={
                    "memory_id": memory_id,
                    "tenant_id": tenant_id,
                    "memory_key": str(current.get("memory_key") or ""),
                },
                decision_states={"operation": operation},
                trace_refs={
                    "previous_value_sha256": str(previous.get("value_sha256") or ""),
                    "current_value_sha256": str(current.get("value_sha256") or ""),
                    "contract_ref": AGENT_MEMORY_GOVERNANCE_CONTRACT_REF,
                },
                audit_refs={
                    "actor_principal_id": str(actor.get("principal_id") or "unknown"),
                    "actor_role": str(actor.get("role") or "unknown"),
                },
                governed_state={
                    "raw_value_persisted_in_audit": False,
                    "fact_evidence_eligible": False,
                },
                writeback_state={"formal_fact_writeback": False},
                payload={
                    "event_id": event_id,
                    "memory_id": memory_id,
                    "operation": operation,
                    "version": version,
                    "previous_value_sha256": str(previous.get("value_sha256") or ""),
                    "current_value_sha256": str(current.get("value_sha256") or ""),
                    "occurred_at": now,
                    "raw_value_persisted": False,
                },
                persisted_at=now,
            )
        )
    return event_id


def _public_memory(
    value: Mapping[str, Any],
    *,
    now: str,
    include_value: bool = True,
) -> dict[str, Any]:
    state = str(value.get("state") or "")
    if state == "ACTIVE" and _is_expired(value, now):
        state = "EXPIRED"
    return {
        "memory_id": value.get("memory_id"),
        "scope": value.get("scope"),
        "project_id": value.get("project_id"),
        "memory_key": value.get("memory_key"),
        "value": value.get("value") if include_value and state == "ACTIVE" else None,
        "value_sha256": value.get("value_sha256"),
        "state": state,
        "version": value.get("version"),
        "created_at": value.get("created_at"),
        "updated_at": value.get("updated_at"),
        "expires_at": value.get("expires_at"),
        "expired_at": value.get("expired_at"),
        "deleted_at": value.get("deleted_at"),
        "purge_eligible_after": value.get("purge_eligible_after"),
        "trust_class": "UNVERIFIED_CONTEXT_ONLY",
        "fact_evidence_eligible": False,
        "citation_eligible": False,
        "gate_input_eligible": False,
    }


def _mutation_response(
    *,
    action: str,
    operation_state: str,
    memory: Mapping[str, Any],
    actor: Mapping[str, str],
    audit_event_id: str,
    idempotent_replay: bool = False,
) -> dict[str, Any]:
    return {
        "surface_id": "agent_memory_governance_internal",
        "action": action,
        "operation_state": operation_state,
        "idempotent_replay": idempotent_replay,
        "memory": dict(memory),
        "audit": {
            "event_id": audit_event_id,
            "actor_principal_id": actor["principal_id"],
            "actor_role": actor["role"],
            "actor_from_authenticated_transport": True,
            "raw_value_persisted_in_audit": False,
        },
        "governance": _governance(),
    }


def _governance() -> dict[str, Any]:
    return {
        "internal_only": True,
        "private_single_tenant_product_boundary": True,
        "principal_and_project_scope_isolation": True,
        "sensitive_data_allowed": False,
        "raw_conversation_history_persisted": False,
        "memory_is_not_fact_or_evidence": True,
        "memory_can_satisfy_citation": False,
        "memory_can_change_gate_or_approval": False,
        "model_provider_call_executed": False,
        "external_release_enabled": False,
    }


def _empty_context(state: str) -> dict[str, Any]:
    return {
        "context_state": state,
        "tenant_scope_sha256": "",
        "principal_id": None,
        "project_id": None,
        "items": [],
        "fact_evidence_eligible": False,
        "citation_eligible": False,
        "gate_input_eligible": False,
        "sensitive_data_included": False,
        "raw_conversation_history_included": False,
        "model_provider_call_executed": False,
    }


def _memory_id(
    *,
    tenant_id: str,
    principal_id: str,
    scope: str,
    project_id: str,
    memory_key: str,
) -> str:
    subject = principal_id if scope == "PRINCIPAL" else project_id
    digest = hashlib.sha256(
        f"{tenant_id}|{scope}|{subject}|{memory_key}".encode("utf-8")
    ).hexdigest()[:32]
    return f"AGENT-MEMORY-{digest}"


def _tenant_scope_sha256(tenant_id: str) -> str:
    return hashlib.sha256(f"agent-memory|{tenant_id}".encode("utf-8")).hexdigest()


def _contains_sensitive_data(value: str) -> bool:
    return any(
        pattern.search(value)
        for pattern in (_SENSITIVE_RE, _EMAIL_RE, _PHONE_RE, _CN_ID_RE, _SECRET_QUERY_RE)
    )


def _optional_identifier(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not _ID_RE.fullmatch(text):
        raise AgentMemoryInputError(f"{field} has an invalid format")
    return text


def _strict_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise AgentMemoryInputError(f"{field} must be a boolean")


def _normalized_now(value: str) -> str:
    parsed = _parse_datetime(value)
    return parsed.isoformat(timespec="seconds")


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgentMemoryInputError("time value must be ISO-8601 with timezone") from exc
    if parsed.tzinfo is None:
        raise AgentMemoryInputError("time value must include timezone")
    return parsed.astimezone(timezone.utc)


def _add_days(value: str, days: int) -> str:
    return (_parse_datetime(value) + timedelta(days=days)).isoformat(timespec="seconds")


def _is_expired(value: Mapping[str, Any], now: str) -> bool:
    expires_at = str(value.get("expires_at") or "")
    if not expires_at:
        return False
    return _parse_datetime(expires_at) <= _parse_datetime(now)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "AGENT_MEMORY_AUDIT_OBJECT_TYPE",
    "AGENT_MEMORY_GOVERNANCE_CONTRACT_REF",
    "AGENT_MEMORY_OBJECT_TYPE",
    "AgentMemoryAccessError",
    "AgentMemoryConflictError",
    "AgentMemoryInputError",
    "build_model_safe_agent_memory_context",
    "list_agent_memories",
    "mutate_agent_memory",
    "sweep_expired_agent_memories",
]
