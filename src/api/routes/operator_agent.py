# Stage: api_operator_agent
# Consumes formal objects: persisted task, evidence, project and work-item readbacks only
# Dependent handoff: Stage1 internal task intent only
# Dependent schema/contracts: contracts/agent/conversational_task_entry_contract.json,
# contracts/agent/agent_memory_governance_contract.json

from __future__ import annotations

from typing import Any, Mapping

from fastapi import HTTPException

from api.projections import register_route_table
from shared.agent_memory import (
    AgentMemoryAccessError,
    AgentMemoryConflictError,
    AgentMemoryInputError,
    list_agent_memories,
    mutate_agent_memory,
)
from shared.agent_tool_planner import build_agent_tool_plan
from shared.conversational_agent import build_conversational_agent_turn


OPERATOR_AGENT_ROUTE_METADATA = {
    "surface_mode": "internal-governed-conversation",
    "internal_only": True,
    "readiness_only": False,
    "projection_only": False,
    "live_execution_enabled": False,
    "external_release_enabled": False,
    "public_software_release": False,
    "provider_call_enabled": False,
    "real_provider_call_enabled": False,
    "stage8_real_execution_enabled": False,
    "stage9_real_payment_delivery_refund_enabled": False,
    "automated_refund_enabled": False,
    "conversational_task_entry": True,
    "formal_object_grounding_required": True,
    "conversation_memory_persisted": False,
}


def create_operator_agent_turn(payload: Mapping[str, Any]) -> dict[str, Any]:
    return build_conversational_agent_turn(payload)


def create_operator_agent_tool_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    return build_agent_tool_plan(payload)


def list_operator_agent_memories(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return list_agent_memories(payload)
    except AgentMemoryAccessError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "INTERNAL_AGENT_MEMORY_PERMISSION_DENIED", "message": str(exc)},
        ) from exc
    except AgentMemoryInputError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_AGENT_MEMORY_QUERY", "message": str(exc)},
        ) from exc


def mutate_operator_agent_memory(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return mutate_agent_memory(payload)
    except AgentMemoryAccessError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "INTERNAL_AGENT_MEMORY_PERMISSION_DENIED", "message": str(exc)},
        ) from exc
    except AgentMemoryInputError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_AGENT_MEMORY_MUTATION", "message": str(exc)},
        ) from exc
    except AgentMemoryConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "AGENT_MEMORY_VERSION_OR_STATE_CONFLICT", "message": str(exc)},
        ) from exc


OPERATOR_AGENT_ROUTES = [
    {
        "operationId": "createOperatorAgentTurn",
        "method": "POST",
        "path": "/operator-console/agent/turns",
        "handler": create_operator_agent_turn,
        "explicit_operator_action": True,
        "raw_json_required": False,
        **OPERATOR_AGENT_ROUTE_METADATA,
    },
    {
        "operationId": "createOperatorAgentToolPlan",
        "method": "POST",
        "path": "/operator-console/agent/plans",
        "handler": create_operator_agent_tool_plan,
        "explicit_operator_action": True,
        "raw_json_required": False,
        "agent_tool_planner": True,
        "strict_tool_registry": True,
        "parallel_tool_calls": False,
        "human_action_pause": True,
        **OPERATOR_AGENT_ROUTE_METADATA,
    },
    {
        "operationId": "listOperatorAgentMemories",
        "method": "GET",
        "path": "/operator-console/agent/memories",
        "handler": list_operator_agent_memories,
        **OPERATOR_AGENT_ROUTE_METADATA,
        "agent_memory_governance": True,
        "conversation_memory_persisted": False,
        "governed_principal_project_memory": True,
    },
    {
        "operationId": "mutateOperatorAgentMemory",
        "method": "POST",
        "path": "/operator-console/agent/memories",
        "handler": mutate_operator_agent_memory,
        "explicit_operator_action": True,
        "raw_json_required": False,
        **OPERATOR_AGENT_ROUTE_METADATA,
        "agent_memory_governance": True,
        "conversation_memory_persisted": False,
        "governed_principal_project_memory": True,
    },
]


def register_operator_agent_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, OPERATOR_AGENT_ROUTES)


__all__ = [
    "OPERATOR_AGENT_ROUTES",
    "create_operator_agent_tool_plan",
    "create_operator_agent_turn",
    "list_operator_agent_memories",
    "mutate_operator_agent_memory",
    "register_operator_agent_routes",
]
