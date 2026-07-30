from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from shared.agent_memory import build_model_safe_agent_memory_context
from shared.conversational_agent import build_conversational_agent_turn
from shared.utils import build_id, utc_now_iso
from storage.db import DatabaseSession, PersistedRecord


AGENT_TOOL_REGISTRY_REF = "contracts/agent/agent_tool_registry.json"
AGENT_TOOL_PLAN_CONTRACT_REF = "contracts/agent/agent_tool_plan_contract.json"
_PLAN_OBJECT_TYPE = "agent_tool_plan"
_STEP_OBJECT_TYPE = "agent_tool_step"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_RESULT_FIELDS = (
    "intent",
    "answer_state",
    "answer",
    "facts",
    "citations",
    "required_inputs",
    "suggested_actions",
    "task",
    "runtime",
    "governance",
    "memory_context",
)


@lru_cache(maxsize=1)
def load_agent_tool_registry() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / AGENT_TOOL_REGISTRY_REF
    return json.loads(path.read_text(encoding="utf-8"))


def build_responses_tool_configuration(
    allowed_tool_names: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Project the internal registry into the strict Responses function-tool shape.

    This only builds a provider request fragment. It does not call a model or execute a tool.
    """

    registry = load_agent_tool_registry()
    index = {str(tool["name"]): dict(tool) for tool in registry.get("tools", [])}
    selected_names = list(allowed_tool_names) if allowed_tool_names is not None else list(index)
    if not selected_names:
        raise ValueError("at least one allowed tool is required")
    if len(selected_names) != len(set(selected_names)):
        raise ValueError("allowed tool names must be unique")
    unknown = sorted(set(selected_names).difference(index))
    if unknown:
        raise ValueError("unregistered allowed tools: " + ",".join(unknown))
    tools = [
        {
            "type": "function",
            "name": name,
            "description": str(index[name]["description"]),
            "parameters": copy.deepcopy(dict(index[name]["parameters"])),
            "strict": True,
        }
        for name in selected_names
    ]
    return {
        "tools": tools,
        "tool_choice": {
            "type": "allowed_tools",
            "mode": "auto",
            "tools": [{"type": "function", "name": name} for name in selected_names],
        },
        "parallel_tool_calls": False,
        "provider_call_executed": False,
        "registry_version": str(registry.get("version") or ""),
    }


def build_agent_tool_plan(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
    monotonic_factory: Any = time.monotonic,
) -> dict[str, Any]:
    active_session = session or DatabaseSession.default()
    registry = load_agent_tool_registry()
    budget = dict(registry["execution_budget"])
    actor = dict(payload.get("_internal_auth_context") or {})
    plan_id = str(payload.get("plan_id") or "").strip()
    proposal_source = str(payload.get("proposal_source") or "").strip()
    execute_read_only = bool(payload.get("execute_read_only", False))
    calls = [dict(item) for item in list(payload.get("calls") or []) if isinstance(item, Mapping)]
    request_for_hash = {
        "plan_id": plan_id,
        "proposal_source": proposal_source,
        "execute_read_only": execute_read_only,
        "calls": calls,
    }
    plan_request_sha256 = _sha256(request_for_hash)

    if plan_id:
        existing = active_session.get_record(_PLAN_OBJECT_TYPE, plan_id)
        if existing is not None:
            existing_hash = str(existing.payload.get("plan_request_sha256") or "")
            if existing_hash != plan_request_sha256:
                return _plan_id_conflict_response(
                    plan_id=plan_id,
                    plan_request_sha256=plan_request_sha256,
                    existing_hash=existing_hash,
                    registry=registry,
                )
            replay = copy.deepcopy(dict(existing.payload.get("response") or {}))
            replay["original_plan_state"] = str(replay.get("plan_state") or "")
            replay["plan_state"] = "REPLAYED_IDEMPOTENT"
            replay["idempotent_replay"] = True
            replay["execution_performed_this_request"] = False
            return replay

    validation_started = monotonic_factory()
    tool_index = {str(tool["name"]): dict(tool) for tool in registry.get("tools", [])}
    errors, validated_steps = _validate_plan(
        plan_id=plan_id,
        proposal_source=proposal_source,
        calls=calls,
        actor=actor,
        tool_index=tool_index,
        budget=budget,
    )
    created_at = utc_now_iso()

    if errors:
        steps = [
            _rejected_step(
                plan_id=plan_id,
                call=call,
                tool=tool_index.get(str(call.get("tool_name") or "")),
                now=created_at,
            )
            for call in calls
        ]
        response = _base_plan_response(
            plan_id=plan_id,
            plan_request_sha256=plan_request_sha256,
            proposal_source=proposal_source,
            plan_state="REJECTED",
            execute_read_only=execute_read_only,
            steps=steps,
            errors=errors,
            budget=budget,
            registry=registry,
            actor=actor,
            created_at=created_at,
            elapsed_milliseconds=_elapsed_ms(validation_started, monotonic_factory),
        )
        _persist_plan_audit(active_session, response=response, actor=actor)
        return response

    steps: list[dict[str, Any]] = []
    errors = []
    executed_count = 0
    human_pause_seen = False
    plan_started = monotonic_factory()
    for validated in validated_steps:
        call = validated["call"]
        tool = validated["tool"]
        call_id = str(call["call_id"])
        tool_name = str(tool["name"])
        started_at = utc_now_iso()
        arguments = dict(call["arguments"])
        arguments_sha256 = _sha256(arguments)

        if bool(tool.get("requires_human_action")) or str(tool.get("execution_mode")) == "HUMAN_HANDOFF_ONLY":
            human_pause_seen = True
            output = _human_handoff_output(tool=tool, arguments=arguments)
            steps.append(
                _step_payload(
                    plan_id=plan_id,
                    call_id=call_id,
                    tool=tool,
                    arguments=arguments,
                    arguments_sha256=arguments_sha256,
                    output=output,
                    step_state="PAUSED_HUMAN_ACTION",
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                    execution_performed=False,
                )
            )
            break

        if not execute_read_only:
            steps.append(
                _step_payload(
                    plan_id=plan_id,
                    call_id=call_id,
                    tool=tool,
                    arguments=arguments,
                    arguments_sha256=arguments_sha256,
                    output={},
                    step_state="VALIDATED",
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                    execution_performed=False,
                )
            )
            continue

        if _elapsed_ms(plan_started, monotonic_factory) >= int(budget["time_budget_milliseconds"]):
            error = _error("PLAN_TIME_BUDGET_EXCEEDED", call_id=call_id, tool_name=tool_name)
            errors.append(error)
            steps.append(
                _step_payload(
                    plan_id=plan_id,
                    call_id=call_id,
                    tool=tool,
                    arguments=arguments,
                    arguments_sha256=arguments_sha256,
                    output={},
                    step_state="FAILED",
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                    execution_performed=False,
                    error=error,
                )
            )
            break

        try:
            output = _execute_read_only_tool(
                tool_name=tool_name,
                arguments=arguments,
                actor=actor,
                session=active_session,
            )
            output_bytes = len(_canonical_json(output).encode("utf-8"))
            if output_bytes > int(budget["max_output_bytes_per_step"]):
                raise ValueError("tool output exceeded the configured byte budget")
            executed_count += 1
            steps.append(
                _step_payload(
                    plan_id=plan_id,
                    call_id=call_id,
                    tool=tool,
                    arguments=arguments,
                    arguments_sha256=arguments_sha256,
                    output=output,
                    step_state="COMPLETED_READ_ONLY",
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                    execution_performed=True,
                )
            )
        except (TypeError, ValueError) as exc:
            error = _error(
                "READ_ONLY_TOOL_FAILED",
                call_id=call_id,
                tool_name=tool_name,
                detail=str(exc)[:240],
            )
            errors.append(error)
            steps.append(
                _step_payload(
                    plan_id=plan_id,
                    call_id=call_id,
                    tool=tool,
                    arguments=arguments,
                    arguments_sha256=arguments_sha256,
                    output={},
                    step_state="FAILED",
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                    execution_performed=False,
                    error=error,
                )
            )
            break

    if errors:
        plan_state = "FAILED_READ_ONLY_STEP"
    elif human_pause_seen and executed_count:
        plan_state = "PARTIAL_PAUSED_HUMAN_ACTION"
    elif human_pause_seen:
        plan_state = "PAUSED_HUMAN_ACTION"
    elif execute_read_only:
        plan_state = "COMPLETED_READ_ONLY"
    else:
        plan_state = "VALIDATED_NOT_EXECUTED"

    response = _base_plan_response(
        plan_id=plan_id,
        plan_request_sha256=plan_request_sha256,
        proposal_source=proposal_source,
        plan_state=plan_state,
        execute_read_only=execute_read_only,
        steps=steps,
        errors=errors,
        budget=budget,
        registry=registry,
        actor=actor,
        created_at=created_at,
        elapsed_milliseconds=_elapsed_ms(plan_started, monotonic_factory),
    )
    _persist_plan_audit(active_session, response=response, actor=actor)
    return response


def _validate_plan(
    *,
    plan_id: str,
    proposal_source: str,
    calls: list[dict[str, Any]],
    actor: Mapping[str, Any],
    tool_index: Mapping[str, dict[str, Any]],
    budget: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    validated: list[dict[str, Any]] = []
    if not plan_id or not _ID_RE.fullmatch(plan_id) or len(plan_id) > 128:
        errors.append(_error("INVALID_PLAN_ID"))
    if proposal_source not in {"DETERMINISTIC_REQUEST", "MODEL_SHADOW_PROPOSAL"}:
        errors.append(_error("INVALID_PROPOSAL_SOURCE"))
    if not calls:
        errors.append(_error("PLAN_CALLS_REQUIRED"))
    if len(calls) > int(budget["max_plan_steps"]):
        errors.append(_error("PLAN_STEP_BUDGET_EXCEEDED"))

    call_ids = [str(call.get("call_id") or "") for call in calls]
    duplicate_call_ids = sorted(call_id for call_id, count in Counter(call_ids).items() if call_id and count > 1)
    if duplicate_call_ids:
        errors.append(_error("DUPLICATE_CALL_ID", detail=",".join(duplicate_call_ids)))

    tool_names = [str(call.get("tool_name") or "") for call in calls]
    for tool_name, count in Counter(tool_names).items():
        if count > int(budget["max_calls_per_tool"]):
            errors.append(_error("PER_TOOL_CALL_BUDGET_EXCEEDED", tool_name=tool_name))

    executable_read_count = 0
    permissions = set(actor.get("permissions") or [])
    for call in calls:
        call_id = str(call.get("call_id") or "")
        tool_name = str(call.get("tool_name") or "")
        arguments = call.get("arguments")
        if not _ID_RE.fullmatch(call_id) or len(call_id) > 128:
            errors.append(_error("INVALID_CALL_ID", call_id=call_id, tool_name=tool_name))
            continue
        tool = tool_index.get(tool_name)
        if tool is None:
            errors.append(_error("TOOL_NOT_REGISTERED", call_id=call_id, tool_name=tool_name))
            continue
        required_permission = str(tool.get("required_permission") or "")
        if required_permission not in permissions:
            errors.append(
                _error(
                    "TOOL_PERMISSION_DENIED",
                    call_id=call_id,
                    tool_name=tool_name,
                    detail=required_permission,
                )
            )
        schema_errors = _validate_arguments(arguments, dict(tool.get("parameters") or {}))
        for detail in schema_errors:
            errors.append(
                _error("INVALID_TOOL_ARGUMENTS", call_id=call_id, tool_name=tool_name, detail=detail)
            )
        if tool_name == "task_status_read" and isinstance(arguments, Mapping):
            if not arguments.get("project_id") and not arguments.get("queue_item_id"):
                errors.append(
                    _error(
                        "INVALID_TOOL_ARGUMENTS",
                        call_id=call_id,
                        tool_name=tool_name,
                        detail="project_id_or_queue_item_id_required",
                    )
                )
        if not bool(tool.get("requires_human_action")):
            executable_read_count += 1
        validated.append({"call": call, "tool": tool})

    if executable_read_count > int(budget["max_executable_read_calls"]):
        errors.append(_error("EXECUTABLE_READ_BUDGET_EXCEEDED"))
    return errors, validated


def _validate_arguments(arguments: Any, schema: Mapping[str, Any]) -> list[str]:
    if not isinstance(arguments, Mapping):
        return ["arguments_must_be_object"]
    properties = dict(schema.get("properties") or {})
    required = set(schema.get("required") or [])
    errors: list[str] = []
    missing = sorted(required.difference(arguments))
    if missing:
        errors.append("missing_required:" + ",".join(missing))
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments).difference(properties))
        if unknown:
            errors.append("unknown_arguments:" + ",".join(unknown))
    for key, value in arguments.items():
        field_schema = properties.get(key)
        if not isinstance(field_schema, Mapping):
            continue
        expected = field_schema.get("type")
        allowed_types = list(expected) if isinstance(expected, list) else [expected]
        if value is None and "null" in allowed_types:
            continue
        if "string" not in allowed_types or not isinstance(value, str):
            errors.append(f"invalid_type:{key}")
            continue
        pattern = str(field_schema.get("pattern") or "")
        if pattern and re.fullmatch(pattern, value) is None:
            errors.append(f"pattern_mismatch:{key}")
    return errors


def _execute_read_only_tool(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    actor: Mapping[str, Any],
    session: DatabaseSession,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"_internal_auth_context": dict(actor)}
    if tool_name == "agent_memory_context_read":
        return {
            "memory_context": build_model_safe_agent_memory_context(
                actor,
                project_id=str(arguments.get("project_id") or ""),
                session=session,
            ),
            "governance": {
                "memory_is_not_fact_or_evidence": True,
                "memory_can_satisfy_citation": False,
                "memory_can_change_gate_or_approval": False,
                "model_provider_call_executed": False,
            },
        }
    if tool_name == "task_status_read":
        payload.update(
            {
                "message": "查询任务进度",
                "project_id": arguments.get("project_id"),
                "queue_item_id": arguments.get("queue_item_id"),
            }
        )
    elif tool_name == "project_evidence_read":
        payload.update({"message": "这个项目有哪些证据和风险？", "project_id": arguments["project_id"]})
    elif tool_name == "project_next_step_read":
        payload.update({"message": "这个项目下一步该做什么？", "project_id": arguments["project_id"]})
    elif tool_name == "internal_stage1_task_proposal":
        payload.update(
            {
                "message": "创建内部任务",
                "project_id": arguments["project_id"],
                "region_code": arguments.get("region_code"),
                "confirm_internal_task": False,
            }
        )
    else:
        raise ValueError(f"tool {tool_name!r} has no deterministic executor")
    result = build_conversational_agent_turn(payload, session=session)
    return {key: copy.deepcopy(result.get(key)) for key in _RESULT_FIELDS if key in result}


def _human_handoff_output(*, tool: Mapping[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    handoff = dict(tool.get("human_handoff") or {})
    return {
        "handoff_state": "WAITING_AUTHENTICATED_OPERATOR_CONFIRMATION",
        "project_id": arguments.get("project_id"),
        "region_code": arguments.get("region_code"),
        "surface": handoff.get("surface"),
        "confirmation_field": handoff.get("confirmation_field"),
        "planner_execution_after_approval_enabled": False,
        "task_created": False,
        "real_external_fetch_enabled": False,
        "live_execution_enabled": False,
    }


def _step_payload(
    *,
    plan_id: str,
    call_id: str,
    tool: Mapping[str, Any],
    arguments: Mapping[str, Any],
    arguments_sha256: str,
    output: Mapping[str, Any],
    step_state: str,
    started_at: str,
    completed_at: str,
    execution_performed: bool,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step_id": build_id("AGENT-TOOL-STEP", plan_id, call_id),
        "plan_id": plan_id,
        "call_id": call_id,
        "tool_name": str(tool.get("name") or ""),
        "arguments": dict(arguments),
        "arguments_sha256": arguments_sha256,
        "output": dict(output),
        "output_sha256": _sha256(output),
        "step_state": step_state,
        "required_permission": str(tool.get("required_permission") or ""),
        "risk_class": str(tool.get("risk_class") or ""),
        "execution_mode": str(tool.get("execution_mode") or ""),
        "execution_performed": execution_performed,
        "mutation_performed": False,
        "live_execution_performed": False,
        "error": dict(error or {}),
        "started_at": started_at,
        "completed_at": completed_at,
    }


def _rejected_step(
    *, plan_id: str, call: Mapping[str, Any], tool: Mapping[str, Any] | None, now: str
) -> dict[str, Any]:
    submitted_arguments = (
        dict(call.get("arguments") or {}) if isinstance(call.get("arguments"), Mapping) else {}
    )
    fallback_tool = dict(tool or {"name": str(call.get("tool_name") or "")})
    return _step_payload(
        plan_id=plan_id,
        call_id=str(call.get("call_id") or ""),
        tool=fallback_tool,
        arguments={},
        arguments_sha256=_sha256(submitted_arguments),
        output={},
        step_state="REJECTED",
        started_at=now,
        completed_at=now,
        execution_performed=False,
    )


def _base_plan_response(
    *,
    plan_id: str,
    plan_request_sha256: str,
    proposal_source: str,
    plan_state: str,
    execute_read_only: bool,
    steps: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    budget: Mapping[str, Any],
    registry: Mapping[str, Any],
    actor: Mapping[str, Any],
    created_at: str,
    elapsed_milliseconds: int,
) -> dict[str, Any]:
    return {
        "surface_id": "agent_tool_plan_internal",
        "plan_id": plan_id,
        "plan_request_sha256": plan_request_sha256,
        "proposal_source": proposal_source,
        "plan_state": plan_state,
        "original_plan_state": "",
        "idempotent_replay": False,
        "execute_read_only_requested": execute_read_only,
        "execution_performed_this_request": any(step.get("execution_performed") for step in steps),
        "steps": steps,
        "errors": errors,
        "budget": {
            **dict(budget),
            "actual_step_count": len(steps),
            "actual_executed_read_count": sum(
                1 for step in steps if step.get("step_state") == "COMPLETED_READ_ONLY"
            ),
            "elapsed_milliseconds": elapsed_milliseconds,
        },
        "registry": {
            "catalog_id": registry.get("catalog_id"),
            "version": registry.get("version"),
            "strict": True,
            "parallel_tool_calls": False,
            "allowed_tool_names": [str(tool["name"]) for tool in registry.get("tools", [])],
        },
        "audit": {
            "plan_record_id": plan_id,
            "step_record_ids": [step["step_id"] for step in steps],
            "actor_principal_id": str(actor.get("principal_id") or "unknown-internal-actor"),
            "actor_role": str(actor.get("role") or "unknown"),
            "created_at": created_at,
            "raw_prompt_persisted": False,
            "raw_model_reasoning_persisted": False,
        },
        "governance": {
            "internal_only": True,
            "model_provider_call_enabled": False,
            "model_provider_call_executed": False,
            "read_only_tools_only_executable": True,
            "mutating_tool_execution_by_planner_enabled": False,
            "human_handoff_is_not_approval": True,
            "live_execution_enabled": False,
            "external_contact_enabled": False,
            "payment_enabled": False,
            "refund_enabled": False,
            "customer_delivery_enabled": False,
            "customer_publication_enabled": False,
            "query_miss_is_not_clearance": True,
        },
    }


def _persist_plan_audit(
    session: DatabaseSession,
    *,
    response: Mapping[str, Any],
    actor: Mapping[str, Any],
) -> None:
    plan_id = str(response.get("plan_id") or "")
    if not plan_id:
        return
    project_ids = {
        str(step.get("arguments", {}).get("project_id") or "")
        for step in response.get("steps", [])
        if step.get("arguments", {}).get("project_id")
    }
    project_id = next(iter(project_ids)) if len(project_ids) == 1 else None
    now = str(response.get("audit", {}).get("created_at") or utc_now_iso())
    with session.bulk_write():
        for step in response.get("steps", []):
            session.upsert_record(
                PersistedRecord(
                    object_type=_STEP_OBJECT_TYPE,
                    record_id=str(step["step_id"]),
                    stage_scope=0,
                    project_id=str(step.get("arguments", {}).get("project_id") or "") or None,
                    object_refs={
                        "plan_id": plan_id,
                        "call_id": str(step.get("call_id") or ""),
                        "tool_name": str(step.get("tool_name") or ""),
                    },
                    decision_states={"step_state": str(step.get("step_state") or "")},
                    trace_refs={
                        "arguments_sha256": str(step.get("arguments_sha256") or ""),
                        "output_sha256": str(step.get("output_sha256") or ""),
                    },
                    audit_refs={
                        "actor_principal_id": str(actor.get("principal_id") or "unknown-internal-actor"),
                        "actor_role": str(actor.get("role") or "unknown"),
                    },
                    governed_state={
                        "mutation_performed": False,
                        "live_execution_performed": False,
                        "requires_human_action": step.get("step_state") == "PAUSED_HUMAN_ACTION",
                    },
                    writeback_state={
                        "formal_fact_writeback": False,
                        "customer_writeback": False,
                    },
                    payload=copy.deepcopy(dict(step)),
                    persisted_at=now,
                )
            )
        session.upsert_record(
            PersistedRecord(
                object_type=_PLAN_OBJECT_TYPE,
                record_id=plan_id,
                stage_scope=0,
                project_id=project_id,
                object_refs={
                    "tool_registry_ref": AGENT_TOOL_REGISTRY_REF,
                    "tool_plan_contract_ref": AGENT_TOOL_PLAN_CONTRACT_REF,
                },
                decision_states={"plan_state": str(response.get("plan_state") or "")},
                trace_refs={
                    "plan_request_sha256": str(response.get("plan_request_sha256") or ""),
                    "registry_version": str(response.get("registry", {}).get("version") or ""),
                },
                audit_refs={
                    "actor_principal_id": str(actor.get("principal_id") or "unknown-internal-actor"),
                    "actor_role": str(actor.get("role") or "unknown"),
                },
                governed_state=copy.deepcopy(dict(response.get("governance") or {})),
                writeback_state={
                    "planner_mutation_executed": False,
                    "live_execution_enabled": False,
                },
                payload={
                    "plan_request_sha256": str(response.get("plan_request_sha256") or ""),
                    "response": copy.deepcopy(dict(response)),
                },
                persisted_at=now,
            )
        )


def _plan_id_conflict_response(
    *,
    plan_id: str,
    plan_request_sha256: str,
    existing_hash: str,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "surface_id": "agent_tool_plan_internal",
        "plan_id": plan_id,
        "plan_request_sha256": plan_request_sha256,
        "proposal_source": "",
        "plan_state": "REJECTED",
        "original_plan_state": "",
        "idempotent_replay": False,
        "execute_read_only_requested": False,
        "execution_performed_this_request": False,
        "steps": [],
        "errors": [
            _error(
                "PLAN_ID_HASH_CONFLICT",
                detail=f"existing={existing_hash[:12]};received={plan_request_sha256[:12]}",
            )
        ],
        "budget": {},
        "registry": {
            "catalog_id": registry.get("catalog_id"),
            "version": registry.get("version"),
            "strict": True,
            "parallel_tool_calls": False,
            "allowed_tool_names": [str(tool["name"]) for tool in registry.get("tools", [])],
        },
        "audit": {"plan_record_id": plan_id, "conflict_did_not_overwrite_existing_audit": True},
        "governance": {
            "internal_only": True,
            "model_provider_call_enabled": False,
            "model_provider_call_executed": False,
            "mutating_tool_execution_by_planner_enabled": False,
            "live_execution_enabled": False,
        },
    }


def _error(
    code: str,
    *,
    call_id: str = "",
    tool_name: str = "",
    detail: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "call_id": call_id,
        "tool_name": tool_name,
        "detail": detail,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _elapsed_ms(started: float, monotonic_factory: Any) -> int:
    return max(0, int((float(monotonic_factory()) - float(started)) * 1000))


__all__ = [
    "AGENT_TOOL_PLAN_CONTRACT_REF",
    "AGENT_TOOL_REGISTRY_REF",
    "build_responses_tool_configuration",
    "build_agent_tool_plan",
    "load_agent_tool_registry",
]
