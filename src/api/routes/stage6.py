# Stage: api_stage6
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.deps import (
    INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY,
    get_settings,
    validate_internal_orchestration_payload,
)
from api.projections import build_stage6_preview_surface, get_surface_runtime_defaults, register_route_table
from api.schemas.stage6 import (
    Stage1ToStage6InternalOrchestrationResponse,
    Stage6OperatorActionResponse,
    Stage6ReviewReportWorkbenchResponse,
    Stage6WorkItemListResponse,
)
from shared.contracts_runtime import ContractStore, StageBundle
from stage1_tasking.service import Stage1Service
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from storage.repository_boundary import (
    OperationalContractError,
    list_stage_work_items,
    persist_stage_bundle,
    record_operator_action,
)


def _validate_handoff(store: ContractStore, producer_bundle: StageBundle, consumer_stage: int) -> None:
    result = store.evaluate_handoff_consumer(
        producer_bundle=producer_bundle,
        consumer_stage=consumer_stage,
    )
    if result and result.decision_state == "BLOCK":
        raise ValueError(f"{result.semantic_scope} blocked: {result.reasons}")


def _run_internal_chain_to_stage6(payload: dict[str, Any]) -> dict[str, StageBundle]:
    settings = get_settings()
    store = ContractStore.default(settings)
    stage1 = Stage1Service(settings).run(payload)
    _validate_handoff(store, stage1, 2)
    stage2 = Stage2Service(settings).run(stage1)
    _validate_handoff(store, stage2, 3)
    stage3 = Stage3Service(settings).run(stage2)
    _validate_handoff(store, stage3, 4)
    stage4 = Stage4Service(settings).run(stage3)
    _validate_handoff(store, stage4, 5)
    stage5 = Stage5Service(settings).run(stage4)
    _validate_handoff(store, stage5, 6)
    stage6 = Stage6Service(settings).run(stage5)
    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "stage4": stage4,
        "stage5": stage5,
        "stage6": stage6,
    }


def preview_stage6_review_report_workbench(payload: Any) -> Stage6ReviewReportWorkbenchResponse:
    return build_stage6_preview_surface(payload)


def run_stage1_to_stage6_internal_orchestration(
    payload: Any,
) -> Stage1ToStage6InternalOrchestrationResponse:
    internal_payload = validate_internal_orchestration_payload(payload)
    chain = _run_internal_chain_to_stage6(internal_payload)
    stage6 = persist_stage_bundle(chain["stage6"])
    project_fact = stage6.record("project_fact")
    readback_selector = {
        "project_id": project_fact.get("project_id"),
        "project_fact_id": project_fact.get("project_fact_id"),
    }
    stage6_readback = build_stage6_preview_surface(readback_selector)
    return {
        "operation_id": INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY[
            "internal_orchestration_operation_id"
        ],
        "orchestration_scope": "stage1_to_stage6",
        "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
        "source_mode": str(internal_payload.get("source_mode")),
        "run_mode": str(internal_payload.get("run_mode")),
        "internal_only": True,
        "live_execution_enabled": False,
        "external_live_transport_enabled": False,
        "stage1_to_stage5_transport_state": "BLOCKED_CONTROLLED_UNAVAILABLE",
        "stage1_to_stage5_http_entry_enabled": False,
        "stage1_to_stage5_real_transport_enabled": False,
        "stage1_to_stage5_external_live_transport_enabled": False,
        "stage6_repository_backed_preview": True,
        "stage6_persisted": True,
        "stage6_project_id": project_fact.get("project_id"),
        "stage6_project_fact_id": project_fact.get("project_fact_id"),
        "stage6_readback": stage6_readback,
    }


def list_stage6_work_items(payload: Any) -> Stage6WorkItemListResponse:
    if not isinstance(payload, dict):
        persist_stage_bundle(payload)
    surface_defaults = get_surface_runtime_defaults("review_report_workbench")
    return {
        "work_items": list_stage_work_items(6, payload if isinstance(payload, dict) else None),
        "internal_only": bool(surface_defaults["internal_only"]),
        "live_execution_enabled": bool(surface_defaults["live_execution_enabled"]),
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
    }


def submit_stage6_operator_action(payload: Any) -> Stage6OperatorActionResponse:
    surface_defaults = get_surface_runtime_defaults("review_report_workbench")
    response: Stage6OperatorActionResponse = {
        "surface_id": "review_report_workbench",
        "surface_mode": str(surface_defaults["surface_mode"]),
        "internal_only": bool(surface_defaults["internal_only"]),
        "live_execution_enabled": bool(surface_defaults["live_execution_enabled"]),
        "blocked_by_default": bool(surface_defaults["blocked_by_default"]),
    }
    try:
        action_result = record_operator_action(payload, stage_scope=6)
        response["operational_loop_persisted"] = True
        response["operational_context_status"] = "persisted"
        response["persisted_operational_context"] = action_result["work_item"]
        response["action_result"] = action_result["action_event"]
    except OperationalContractError as exc:
        response["error"] = exc.as_payload()
    return response


STAGE1_TO_STAGE6_INTERNAL_ORCHESTRATION_ROUTES = [
    {
        "operationId": "runStage1ToStage6InternalOrchestration",
        "method": "POST",
        "path": "/internal/stage1-6/orchestrations",
        "handler": run_stage1_to_stage6_internal_orchestration,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
        "accepted_payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
        "repository_backed_readback": True,
        "orchestrates_stage_scope": "stage1_to_stage6",
    },
]


STAGE6_ROUTES = [
    {
        "operationId": "previewStage6ReviewReportWorkbench",
        "method": "GET",
        "path": "/review-report-workbench",
        "handler": preview_stage6_review_report_workbench,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
    },
    {
        "operationId": "listStage6WorkItems",
        "method": "GET",
        "path": "/review-report-work-items",
        "handler": list_stage6_work_items,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
    },
    {
        "operationId": "submitStage6OperatorAction",
        "method": "POST",
        "path": "/review-report-workbench/{project_fact_id}/operator-actions",
        "handler": submit_stage6_operator_action,
        "surface_mode": "preview-only",
        "internal_only": True,
        "live_execution_enabled": False,
        "blocked_by_default": False,
    }
]


def register_stage6_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(STAGE6_ROUTES))


def register_stage1_to_stage6_internal_orchestration_routes(
    router: object | None = None,
) -> list[dict[str, Any]]:
    return register_route_table(router, list(STAGE1_TO_STAGE6_INTERNAL_ORCHESTRATION_ROUTES))


__all__ = [
    "STAGE1_TO_STAGE6_INTERNAL_ORCHESTRATION_ROUTES",
    "STAGE6_ROUTES",
    "list_stage6_work_items",
    "preview_stage6_review_report_workbench",
    "register_stage1_to_stage6_internal_orchestration_routes",
    "register_stage6_routes",
    "run_stage1_to_stage6_internal_orchestration",
    "submit_stage6_operator_action",
]
