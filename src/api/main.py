# Stage: api
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from api.deps import (
    INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY,
    get_database_session,
    get_settings,
)
from api.routes.stage1 import register_stage1_routes
from api.routes.stage2 import register_stage2_routes
from api.routes.stage3 import register_stage3_routes
from api.routes.stage4 import register_stage4_routes
from api.routes.stage5 import register_stage5_routes
from api.routes.stage6 import (
    register_stage1_to_stage6_internal_orchestration_routes,
    register_stage6_routes,
)
from api.routes.operator_customer_access import register_operator_customer_access_routes
from api.routes.operator_frontend import register_operator_frontend_routes
from api.routes.stage7 import register_stage7_routes
from api.routes.stage8 import register_stage8_routes
from api.routes.stage9 import register_stage9_routes
from shared.provider_adapter_config import PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY
from storage.repositories.monitoring_alerting_repo import MonitoringAlertingRepository
from storage.repositories.production_slo_incident_repo import ProductionSloIncidentRepository
from storage.repositories.provider_adapter_config_repo import ProviderAdapterConfigRepository


RouteHandler = Callable[[Any], Any]
MOUNTED_OPERATION_READBACK_KEYS = (
    "operationId",
    "method",
    "path",
    "surface_mode",
    "internal_only",
    "live_execution_enabled",
    "candidate_only",
    "readiness_only",
    "review_only",
    "projection_only",
    "non_live",
    "release_blocked",
    "external_delivery_enabled",
    "external_release_enabled",
    "direct_export_enabled",
    "external_ready_direct_export",
    "customer_visible_export_enabled",
    "client_page_release_enabled",
    "page_layer_release_enabled",
    "export_artifact_generation_enabled",
    "page_publication_enabled",
    "requires_review",
    "governed_execution_mode",
    "outbox_enabled",
    "real_send_enabled",
    "real_send_attempted",
    "vendor_connection_enabled",
    "stage8_execution_outbox_readiness",
    "stage8_live_pilot_readiness",
    "stage8_approved_provider_execution_readiness",
    "crm_runtime_enabled",
    "external_quote_enabled",
    "crm_quote_prerequisite_readiness",
    "crm_quote_workbench_readiness",
    "crm_quote_workbench_readiness_summary",
    "stage7_approved_crm_quote_provider_execution_readiness",
    "approved_crm_quote_execution_summary",
    "crm_quote_provider_execution_replay_state",
    "leadpack_external_delivery_candidate_readiness",
    "formal_client_export_page_layer_readiness",
    "leadpack_delivery_package_readiness",
    "package_page_delivery_summary",
    "stage9_execution_ledger_readiness",
    "order_payment_delivery_execution_summary",
    "payment_sandbox_provider_records",
    "delivery_sandbox_provider_records",
    "manual_refund_exception_record",
    "payment_delivery_live_pilot",
    "approved_payment_delivery_execution",
    "payment_gateway_enabled",
    "real_payment_gateway_enabled",
    "real_charge_enabled",
    "real_delivery_enabled",
    "real_refund_enabled",
    "automated_refund_enabled",
    "operator_console_readiness",
    "autonomous_operator_workbench",
    "real_sample_autonomous_acceptance",
    "real_sample_flow_visible",
    "real_world_sellability_readiness",
    "stage6_review_loop_status_readback",
    "project_status_rows_visible",
    "productized_owner_workbench",
    "opportunity_queue_visible",
    "commercial_hook_review_visible",
    "buyer_ranking_visible",
    "evidence_risk_visible",
    "delivery_state_visible",
    "next_action_visible",
    "raw_json_required",
    "explicit_operator_action",
    "owner_operator_console_frontend",
    "customer_artifact_portal_frontend",
    "task_creation_entry",
    "task_readback_entry",
    "project_import_entry",
    "real_public_source_profile_catalog",
    "real_public_source_runner_entry",
    "real_public_source_task_run_list",
    "real_public_source_readback",
    "region_adapter_catalog",
    "real_candidate_catalog",
    "real_candidate_discovery_run_list",
    "real_candidate_stage2_capture_run_list",
    "autonomous_search_entry",
    "autonomous_search_run_list",
    "autonomous_search_run_clear",
    "scheduler_status_readback",
    "customer_artifact_access_readiness",
    "download_auth_required",
    "field_allowlist_masking_required",
    "go_live_readiness",
    "deployment_readiness",
    "monitoring_rollback_refs",
    "public_software_release",
    "provider_call_enabled",
    "real_provider_call_enabled",
    "stage8_real_execution_enabled",
    "stage9_real_payment_delivery_refund_enabled",
    "provider_adapter_config_source",
    "provider_adapter_mode",
    "provider_adapter_readback_only",
    "provider_adapter_sandbox_enabled",
    "provider_adapter_dry_run_enabled",
    "provider_adapter_live_execution_enabled",
    "provider_adapter_provider_call_enabled",
    "provider_adapter_real_provider_call_enabled",
    "provider_reliability_state",
    "provider_circuit_breaker_state",
    "provider_adapter_suspended",
    "provider_adapter_suspended_families",
    "provider_status_replayable",
    "provider_reliability_summary",
    "provider_status_readback",
    "provider_credential_redaction_audit",
    "provider_adapter_blocked_reasons",
    "provider_adapter_approval_audit_prerequisites",
    "provider_adapter_families_consumed",
    "crm_quote_provider_adapter_readiness",
    "leadpack_page_delivery_provider_adapter_readiness",
    "sales_outreach_provider_adapter_readiness",
    "payment_collection_provider_adapter_readiness",
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    "accepted_payload_boundary",
    "repository_backed_readback",
    "orchestrates_stage_scope",
)
RESERVED_ENTRY_PLAN_READBACK_KEYS = (
    "stage_scope",
    "availability_state",
    "transport_state",
    "reserved_entry_state",
    "reserved_operation_id",
    "reserved_path",
    "reserved_method",
    "handoff_refs",
    "http_entry_enabled",
    "real_transport_enabled",
    "orchestrator_enabled",
    "internal_orchestration_entry_available",
    "internal_orchestration_operation_id",
    "internal_orchestration_path",
    "internal_orchestration_method",
    "internal_orchestration_payload_boundary",
    "stage6_readback_mode",
    "stage1_to_stage5_external_live_transport_state",
    "route_registrar",
)


def _coerce_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


async def _request_payload(request: Request) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    body = await request.body()
    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"invalid json body: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="request body must be a JSON object")
        payload.update(parsed)

    payload.update({key: _coerce_scalar(value) for key, value in request.query_params.items()})
    payload.update({key: value for key, value in request.path_params.items()})
    return payload


def _endpoint_for(route: dict[str, Any]) -> Callable[[Request], Any]:
    handler: RouteHandler = route["handler"]

    async def endpoint(request: Request) -> Any:
        payload = await _request_payload(request)
        try:
            return handler(payload)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    endpoint.__name__ = route["operationId"]
    endpoint.__doc__ = f"Transport wrapper for {route['operationId']}."
    return endpoint


def _mount_routes(app: FastAPI, routes: list[dict[str, Any]]) -> None:
    for route in routes:
        app.add_api_route(
            route["path"],
            _endpoint_for(route),
            methods=[route["method"]],
            name=route["operationId"],
            operation_id=route["operationId"],
        )


def _stage_transport_readback(stage_transports: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        stage_name: [dict(transport_state) for transport_state in transport_states]
        for stage_name, transport_states in stage_transports.items()
    }


def _reserved_entry_plan_readback(
    disabled_stage_transports: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    return {
        stage_name: [
            {
                key: transport_state[key]
                for key in RESERVED_ENTRY_PLAN_READBACK_KEYS
                if key in transport_state
            }
            for transport_state in transport_states
        ]
        for stage_name, transport_states in disabled_stage_transports.items()
    }


def _mounted_operation_readback(stage_scope: int, route: dict[str, Any]) -> dict[str, Any]:
    operation = {
        key: route[key]
        for key in MOUNTED_OPERATION_READBACK_KEYS
        if key in route
    }
    operation["stage_scope"] = stage_scope
    operation["blocked_by_default"] = bool(route.get("blocked_by_default", False))
    return operation


def _mounted_operations_readback(
    mounted_stage_routes: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for stage_name, routes in mounted_stage_routes.items():
        stage_scope = int(stage_name.removeprefix("stage"))
        operations.extend(_mounted_operation_readback(stage_scope, route) for route in routes)
    return operations


def _operation_readback(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for route in routes:
        operation = {
            key: route[key]
            for key in MOUNTED_OPERATION_READBACK_KEYS
            if key in route
        }
        operation["blocked_by_default"] = bool(route.get("blocked_by_default", False))
        operations.append(operation)
    return operations


def _operation_ids_by_stage(mounted_stage_routes: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {
        stage_name: [route["operationId"] for route in routes]
        for stage_name, routes in mounted_stage_routes.items()
    }


def _build_transport_bootstrap(
    disabled_stage_transports: dict[str, list[dict[str, Any]]],
    mounted_stage_routes: dict[str, list[dict[str, Any]]],
    operator_customer_access_routes: list[dict[str, Any]],
    operator_frontend_routes: list[dict[str, Any]],
    provider_adapter_bootstrap: dict[str, Any],
    storage_bootstrap: dict[str, Any],
) -> dict[str, Any]:
    operation_ids_by_stage = _operation_ids_by_stage(mounted_stage_routes)
    operator_customer_access_operation_ids = [
        route["operationId"]
        for route in operator_customer_access_routes
    ]
    operator_frontend_operation_ids = [
        route["operationId"]
        for route in operator_frontend_routes
    ]
    stage1_to_stage5_reserved_entry_plan = _reserved_entry_plan_readback(disabled_stage_transports)
    provider_adapter_readiness = dict(
        provider_adapter_bootstrap.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY, {})
    )
    worker_queue_bootstrap = dict(storage_bootstrap.get("worker_queue_bootstrap", {}))
    object_storage_bootstrap = dict(storage_bootstrap.get("object_storage_bootstrap", {}))
    backup_restore_readiness = dict(storage_bootstrap.get("backup_restore_readiness", {}))
    rollback_readiness = dict(storage_bootstrap.get("rollback_readiness", {}))
    monitoring_alerting_readiness = dict(storage_bootstrap.get("monitoring_alerting_readiness", {}))
    monitoring_readiness = dict(storage_bootstrap.get("monitoring_readiness", {}))
    alert_readiness = dict(storage_bootstrap.get("alert_readiness", {}))
    alert_rule_catalog = list(storage_bootstrap.get("alert_rule_catalog", []))
    incident_readiness = dict(storage_bootstrap.get("incident_readiness", {}))
    production_slo_incident_readiness = dict(
        storage_bootstrap.get("production_slo_incident_readiness", {})
    )
    approved_production_live_dependency_drill = dict(
        storage_bootstrap.get("approved_production_live_dependency_drill", {})
    )
    production_slo_readiness = dict(storage_bootstrap.get("production_slo_readiness", {}))
    production_monitoring_dashboard = dict(
        storage_bootstrap.get("production_monitoring_dashboard", {})
    )
    production_alert_rule_catalog = list(
        storage_bootstrap.get("production_alert_rule_catalog", [])
    )
    simulated_alert_evaluation_readback = list(
        storage_bootstrap.get("simulated_alert_evaluation_readback", [])
    )
    production_incident_runbook = dict(
        storage_bootstrap.get("production_incident_runbook", {})
    )
    production_drill_evidence = dict(storage_bootstrap.get("production_drill_evidence", {}))
    suspended_state_operation_readback = dict(
        storage_bootstrap.get("suspended_state_operation_readback", {})
    )
    local_stack_readiness = dict(
        storage_bootstrap.get(
            "local_stack_readiness",
            storage_bootstrap.get("platform_infra_readiness", {}).get("compose_readiness", {}),
        )
    )
    return {
        "internal_only": True,
        "live_execution_enabled": False,
        "storage_bootstrap": dict(storage_bootstrap),
        "platform_infra_readiness": dict(storage_bootstrap.get("platform_infra_readiness", {})),
        "local_stack_readiness": local_stack_readiness,
        "compose_readiness": local_stack_readiness,
        "worker_queue_bootstrap": worker_queue_bootstrap,
        "object_storage_bootstrap": object_storage_bootstrap,
        "object_storage_readiness": object_storage_bootstrap,
        "backup_restore_readiness": backup_restore_readiness,
        "rollback_readiness": rollback_readiness,
        "monitoring_alerting_readiness": monitoring_alerting_readiness,
        "monitoring_readiness": monitoring_readiness,
        "alert_rule_catalog": alert_rule_catalog,
        "alert_readiness": alert_readiness,
        "incident_readiness": incident_readiness,
        "production_slo_incident_readiness": production_slo_incident_readiness,
        "approved_production_live_dependency_drill": approved_production_live_dependency_drill,
        "production_slo_readiness": production_slo_readiness,
        "production_monitoring_dashboard": production_monitoring_dashboard,
        "production_alert_rule_catalog": production_alert_rule_catalog,
        "simulated_alert_evaluation_readback": simulated_alert_evaluation_readback,
        "production_incident_runbook": production_incident_runbook,
        "production_drill_evidence": production_drill_evidence,
        "suspended_state_operation_readback": suspended_state_operation_readback,
        "queue_worker_readiness": {
            "queue_backend": worker_queue_bootstrap.get("queue_backend"),
            "effective_queue_backend": worker_queue_bootstrap.get("effective_queue_backend"),
            "worker_runtime": worker_queue_bootstrap.get("worker_runtime"),
            "readiness_state": worker_queue_bootstrap.get("readiness_state"),
            "repository_backed": bool(worker_queue_bootstrap.get("repository_backed", False)),
            "durable_queue_enabled": bool(worker_queue_bootstrap.get("durable_queue_enabled", False)),
            "worker_lease_enabled": bool(worker_queue_bootstrap.get("worker_lease_enabled", False)),
            "retry_enabled": bool(worker_queue_bootstrap.get("retry_enabled", False)),
            "suspend_resume_enabled": bool(worker_queue_bootstrap.get("suspend_resume_enabled", False)),
            "audit_replay_enabled": bool(worker_queue_bootstrap.get("audit_replay_enabled", False)),
            "external_queue_connection_enabled": False,
            "stage1_scheduler_enabled": False,
            "real_provider_execution_enabled": False,
        },
        "provider_adapter_bootstrap": dict(provider_adapter_bootstrap),
        "provider_adapter_config_source": provider_adapter_bootstrap.get("provider_adapter_config_source"),
        "provider_adapter_mode": provider_adapter_bootstrap.get("provider_adapter_mode"),
        "provider_reliability_state": provider_adapter_bootstrap.get("provider_reliability_state"),
        "provider_circuit_breaker_state": provider_adapter_bootstrap.get("provider_circuit_breaker_state"),
        "provider_adapter_suspended": bool(provider_adapter_bootstrap.get("provider_adapter_suspended", False)),
        "provider_adapter_suspended_families": list(
            provider_adapter_bootstrap.get("provider_adapter_suspended_families", [])
        ),
        "provider_status_replayable": bool(provider_adapter_bootstrap.get("provider_status_replayable", True)),
        "provider_reliability_summary": dict(provider_adapter_bootstrap.get("provider_reliability_summary", {})),
        "provider_status_readback": dict(provider_adapter_bootstrap.get("provider_status_readback", {})),
        "provider_credential_redaction_audit": dict(
            provider_adapter_bootstrap.get("provider_credential_redaction_audit", {})
        ),
        "provider_adapter_blocked_reasons": list(
            provider_adapter_bootstrap.get("provider_adapter_blocked_reasons", [])
        ),
        "provider_adapter_approval_audit_prerequisites": dict(
            provider_adapter_bootstrap.get("provider_adapter_approval_audit_prerequisites", {})
        ),
        "model_assist_governance_bootstrap": {
            "capability_state": "APPROVAL_READY",
            "assist_mode": "GOVERNED_ASSIST_READBACK",
            "provider_execution_surface": "LOCAL_DETERMINISTIC_ASSIST",
            "real_model_provider_call_enabled": False,
            "real_model_provider_call_executed": False,
            "customer_visible_claim_enabled": False,
            "formal_fact_write_enabled": False,
            "human_review_required": True,
            "policy_ref": "contracts/model/model_usage_policy.json#governed_model_assist",
            "stage_scopes": [
                "stage3_parser_field_extraction",
                "stage4_public_verification_review",
                "stage5_rule_review_triage",
                "stage7_sales_talk_track",
            ],
            "golden_case_refs": [
                "MODEL-GOLDEN-FIELD-EXTRACTION-CANDIDATE",
                "MODEL-GOLDEN-EVIDENCE-SUMMARY-REVIEW",
                "MODEL-GOLDEN-SALES-TALK-TRACK-DRAFT",
            ],
            "controlled_opening_requirements": {
                "model_output_not_final_fact": True,
                "model_output_not_customer_conclusion": True,
                "model_input_without_policy_blocked": True,
                "credential_or_secret_to_model_blocked": True,
            },
        },
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: provider_adapter_readiness,
        "stage1_to_stage5_transport_state": _stage_transport_readback(disabled_stage_transports),
        "stage1_to_stage5_reserved_entry_plan": stage1_to_stage5_reserved_entry_plan,
        "stage6_to_stage9_mounted_operations": _mounted_operations_readback(mounted_stage_routes),
        "operator_customer_access_mounted_operations": _operation_readback(
            operator_customer_access_routes
        ),
        "operator_frontend_mounted_operations": _operation_readback(operator_frontend_routes),
        "operator_customer_access_bootstrap": {
            "capability_state": "APPROVAL_READY",
            "surface_mode": "internal-readback",
            "internal_only": True,
            "readiness_only": True,
            "projection_only": True,
            "customer_artifact_access_gated": True,
            "account_access_control_required": True,
            "download_auth_required": True,
            "field_allowlist_masking_required": True,
            "approval_audit_readback_required": True,
            "external_release_enabled": False,
            "public_software_release": False,
            "live_execution_enabled": False,
            "provider_live_execution_enabled": False,
            "stage8_real_execution_enabled": False,
            "stage9_real_payment_delivery_refund_enabled": False,
            "automated_refund_enabled": False,
            "mounted_operations": operator_customer_access_operation_ids,
            "frontend_operations": operator_frontend_operation_ids,
            "owner_operator_frontend_path": "/operator-console",
            "customer_artifact_portal_path": "/customer-artifact-portal/{opportunity_id}",
        },
        "entry_strategy": {
            "stage1_to_stage5": {
                "current_entry": "controlled-unavailable external/live transport with internal orchestration handoff",
                "http_entry_enabled": False,
                "real_transport_enabled": False,
                "orchestrator_enabled": False,
                "external_live_transport_enabled": False,
                "internal_orchestration_entry_available": True,
                "internal_orchestration_entry": dict(INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY),
                "reserved_entry_plan": stage1_to_stage5_reserved_entry_plan,
                "source": "stage1-stage5 transport registrars",
            },
            "stage6": {
                "current_entry": "repository-backed preview / workbench mounted transport",
                "http_entry_enabled": True,
                "mounted_operations": operation_ids_by_stage["stage6"],
            },
            "stage7_to_stage9": {
                "current_entry": "internal governed preview / draft workbench mounted transport",
                "http_entry_enabled": True,
                "mounted_operations_by_stage": {
                    stage_name: operation_ids_by_stage[stage_name]
                    for stage_name in ("stage7", "stage8", "stage9")
                },
            },
            "stage1_to_stage6_full_chain_entry": {
                "current_entry": "internal-only sanitized/offline orchestration entry mounted on Stage6",
                "http_entry_enabled": True,
                "internal_only": True,
                "live_execution_enabled": False,
                "accepted_payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
                "operation_id": INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY[
                    "internal_orchestration_operation_id"
                ],
                "path": INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY[
                    "internal_orchestration_path"
                ],
                "method": INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY[
                    "internal_orchestration_method"
                ],
                "executes_stage1_to_stage5_transport": False,
                "executes_external_live_transport": False,
                "executes_real_orchestrator": False,
                "executes_existing_internal_chain": True,
                "persists_stage6_bundle": True,
                "stage6_readback_mode": "repository_backed_preview",
                "mounted_entry_stage": 6,
            },
            "queue_worker": {
                "current_entry": "storage-backed durable queue and worker lease seam",
                "queue_backend": worker_queue_bootstrap.get("queue_backend"),
                "effective_queue_backend": worker_queue_bootstrap.get("effective_queue_backend"),
                "worker_runtime": worker_queue_bootstrap.get("worker_runtime"),
                "repository_backed": True,
                "redis_connection_enabled": False,
                "external_queue_connection_enabled": False,
                "stage1_scheduler_enabled": False,
                "real_provider_execution_enabled": False,
            },
            "object_storage": {
                "current_entry": "local-filesystem evidence snapshot durability seam",
                "object_storage_backend": object_storage_bootstrap.get("active_backend"),
                "effective_backend": object_storage_bootstrap.get("effective_backend"),
                "storage_path": object_storage_bootstrap.get("storage_path"),
                "local_filesystem_executable": bool(
                    object_storage_bootstrap.get("local_filesystem", {}).get("executable", False)
                ),
                "snapshot_manifest_repository_backed": bool(
                    object_storage_bootstrap.get("snapshot_durability", {}).get(
                        "manifest_repository_backed",
                        False,
                    )
                ),
                "snapshot_readback_replay_enabled": bool(
                    object_storage_bootstrap.get("snapshot_durability", {}).get(
                        "readback_replay_enabled",
                        False,
                    )
                ),
                "minio_connection_enabled": False,
                "s3_connection_enabled": False,
                "external_service_connection_enabled": False,
            },
            "local_stack": {
                "current_entry": "Docker/Compose local stack definition and readiness projection only",
                "dockerfile_present": bool(local_stack_readiness.get("dockerfile_present", False)),
                "compose_file_present": bool(local_stack_readiness.get("compose_file_present", False)),
                "docker_compose_config_present": bool(
                    local_stack_readiness.get("docker_compose_config_present", False)
                ),
                "compose_runtime_enabled": False,
                "container_execution_enabled": False,
                "docker_compose_up_executed": False,
                "external_service_connection_enabled": False,
                "real_provider_execution_enabled": False,
                "real_payment_delivery_enabled": False,
                "automated_refund_enabled": False,
                "reserved_services": ["postgres", "redis", "minio"],
            },
            "backup_restore": {
                "current_entry": "local backup manifest, restore dry-run, and rollback readiness projection",
                "backup_manifest_enabled": bool(backup_restore_readiness.get("backup_manifest_enabled", False)),
                "restore_dry_run_enabled": bool(backup_restore_readiness.get("restore_dry_run_enabled", False)),
                "manifest_hash_enabled": bool(backup_restore_readiness.get("manifest_hash_enabled", False)),
                "approval_required": True,
                "audit_required": True,
                "safe_to_restore": False,
                "destructive_restore_enabled": False,
                "restore_execution_enabled": False,
                "rollback_execution_enabled": False,
                "external_backup_service_enabled": False,
                "external_service_connection_enabled": False,
                "migration_execution_enabled": False,
                "rollback_readiness": rollback_readiness,
            },
            "monitoring_alerting": {
                "current_entry": "internal monitoring / alerting / incident readiness readback",
                "monitoring_readiness_state": monitoring_readiness.get("readiness_state"),
                "monitoring_health_state": monitoring_readiness.get("health_state"),
                "alert_rule_catalog_ready": bool(alert_rule_catalog),
                "alert_rule_count": len(alert_rule_catalog),
                "alert_readiness_state": alert_readiness.get("readiness_state"),
                "incident_state": incident_readiness.get("incident_state"),
                "repository_backed_readback": True,
                "replayable_readback": bool(
                    monitoring_alerting_readiness.get("replayable_readback", True)
                ),
                "notification_enabled": False,
                "live_dispatch_enabled": False,
                "external_observability_provider_enabled": False,
                "external_apm_enabled": False,
                "external_paging_enabled": False,
                "incident_automation_enabled": False,
                "manual_owner_action_required": True,
            },
            "production_slo_incident_readiness": {
                "current_entry": "121C production SLO, alert simulation, incident, drill, suspended-state readback",
                "capability_state": production_slo_incident_readiness.get(
                    "target_capability_state"
                ),
                "readiness_state": production_slo_incident_readiness.get("readiness_state"),
                "repository_backed_readback": bool(
                    production_slo_incident_readiness.get("repository_backed_readback", True)
                ),
                "replayable_readback": bool(
                    production_slo_incident_readiness.get("replayable_readback", True)
                ),
                "slo_objective_count": production_slo_readiness.get("objective_count"),
                "dashboard_panel_count": production_monitoring_dashboard.get("panel_count"),
                "alert_rule_count": len(production_alert_rule_catalog),
                "simulated_alert_count": len(simulated_alert_evaluation_readback),
                "simulated_alerts_fire": all(
                    bool(evaluation.get("alert_fired", False))
                    for evaluation in simulated_alert_evaluation_readback
                ),
                "incident_runbook_state": production_incident_runbook.get("runbook_state"),
                "backup_restore_drill_mode": dict(
                    production_drill_evidence.get("backup_restore_drill_evidence", {})
                ).get("drill_mode"),
                "rollback_drill_mode": dict(
                    production_drill_evidence.get("rollback_drill_evidence", {})
                ).get("drill_mode"),
                "suspension_state": suspended_state_operation_readback.get("suspension_state"),
                "manual_resume_required": bool(
                    suspended_state_operation_readback.get("manual_resume_required", True)
                ),
                "notification_enabled": False,
                "live_dispatch_enabled": False,
                "real_alert_dispatch_enabled": False,
                "external_apm_enabled": False,
                "external_paging_enabled": False,
                "incident_automation_enabled": False,
                "destructive_restore_enabled": False,
                "restore_execution_enabled": False,
                "rollback_execution_enabled": False,
                "active_storage_mutation_enabled": False,
                "external_release_enabled": False,
                "go_live_enabled": False,
            },
            "approved_production_live_dependency_drill": {
                "current_entry": "126 approved production live dependency and drill approval readback",
                "drill_id": approved_production_live_dependency_drill.get("drill_id"),
                "controlled_drill_state": approved_production_live_dependency_drill.get(
                    "controlled_drill_state"
                ),
                "approved_production_live_dependency_drill_enabled": bool(
                    approved_production_live_dependency_drill.get(
                        "approved_production_live_dependency_drill_enabled", False
                    )
                ),
                "controlled_execution_scope": approved_production_live_dependency_drill.get(
                    "controlled_execution_scope"
                ),
                "container_execution_enabled": False,
                "docker_compose_up_executed": False,
                "notification_enabled": False,
                "live_dispatch_enabled": False,
                "real_alert_dispatch_enabled": False,
                "external_apm_enabled": False,
                "external_paging_enabled": False,
                "destructive_restore_enabled": False,
                "restore_execution_enabled": False,
                "rollback_execution_enabled": False,
                "incident_automation_enabled": False,
                "external_release_enabled": False,
            },
            "provider_adapter": {
                "current_entry": "sandbox dry-run provider readiness and circuit breaker readback",
                "provider_reliability_state": provider_adapter_bootstrap.get("provider_reliability_state"),
                "provider_circuit_breaker_state": provider_adapter_bootstrap.get("provider_circuit_breaker_state"),
                "provider_adapter_suspended": bool(
                    provider_adapter_bootstrap.get("provider_adapter_suspended", False)
                ),
                "provider_adapter_suspended_families": list(
                    provider_adapter_bootstrap.get("provider_adapter_suspended_families", [])
                ),
                "replayable_provider_status": bool(
                    provider_adapter_bootstrap.get("provider_status_replayable", True)
                ),
                "readback_only": True,
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "live_fallback_allowed": False,
            },
            "stage8_live_pilot": {
                "current_entry": "gated small-sample sales outreach live pilot carrier/readback",
                "http_entry_enabled": True,
                "mounted_operations": operation_ids_by_stage["stage8"],
                "pilot_scope": "small_sample",
                "supported_adapter_families": ["email", "sms", "phone_call", "wecom_im"],
                "batch_send_enabled": False,
                "bulk_send_enabled": False,
                "approval_required": True,
                "audit_required": True,
                "template_approval_required": True,
                "contact_source_audit_required": True,
                "operator_action_required": True,
                "frequency_quiet_hours_opt_out_required": True,
                "provider_reliability_required": True,
                "repository_backed_readback": True,
                "replayable_readback": True,
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "real_send_attempted": False,
                "public_release_enabled": False,
                "external_release_enabled": False,
                "stage9_payment_delivery_refund_enabled": False,
                "automated_refund_enabled": False,
            },
            "stage7_approved_crm_quote_provider_execution": {
                "current_entry": "approved CRM and quote provider execution carrier/readback",
                "http_entry_enabled": True,
                "mounted_operations": operation_ids_by_stage["stage7"],
                "provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER",
                "supported_actions": [
                    "crm_account_sync",
                    "crm_opportunity_sync",
                    "crm_activity_sync",
                    "quote_send",
                    "quote_version",
                    "quote_approval",
                    "quote_expiration",
                    "discount_approval",
                    "quote_audit",
                ],
                "provider_config_required": True,
                "sandbox_pass_required": True,
                "crm_approval_required": True,
                "quote_approval_required": True,
                "quote_audit_required": True,
                "operator_action_audit_required": True,
                "quote_version_policy_required": True,
                "quote_expiration_policy_required": True,
                "discount_approval_policy_required": True,
                "provider_reliability_required": True,
                "repository_backed_readback": True,
                "replayable_readback": True,
                "provider_result_readback_visible": True,
                "deal_tracking_timeline_visible": True,
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "real_crm_sync_enabled": False,
                "external_quote_sent": False,
                "real_external_quote_sent": False,
                "stage8_outreach_enabled": False,
                "stage9_payment_delivery_refund_enabled": False,
                "automated_refund_enabled": False,
                "public_release_enabled": False,
                "external_release_enabled": False,
            },
            "stage8_approved_provider_execution": {
                "current_entry": "approved small-sample sales outreach provider execution carrier/readback",
                "http_entry_enabled": True,
                "mounted_operations": operation_ids_by_stage["stage8"],
                "provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
                "supported_adapter_families": ["email", "sms", "phone_call", "wecom_im"],
                "provider_config_required": True,
                "sandbox_pass_required": True,
                "template_approval_required": True,
                "contact_source_audit_required": True,
                "operator_approval_required": True,
                "operator_action_audit_required": True,
                "frequency_control_required": True,
                "quiet_hours_required": True,
                "opt_out_unsubscribe_required": True,
                "provider_reliability_required": True,
                "complaint_bounce_failure_stop_fail_closed": True,
                "batch_send_enabled": False,
                "bulk_send_enabled": False,
                "repository_backed_readback": True,
                "replayable_readback": True,
                "provider_result_readback_visible": True,
                "execution_timeline_visible": True,
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "real_send_attempted": False,
                "external_delivery_enabled": False,
                "public_release_enabled": False,
                "external_release_enabled": False,
                "stage9_payment_delivery_refund_enabled": False,
                "automated_refund_enabled": False,
            },
            "stage9_payment_delivery_live_pilot": {
                "current_entry": "gated small-sample payment and delivery live pilot carrier/readback",
                "http_entry_enabled": True,
                "mounted_operations": operation_ids_by_stage["stage9"],
                "pilot_scope": "small_sample",
                "batch_execution_enabled": False,
                "bulk_execution_enabled": False,
                "sandbox_payment_pass_required": True,
                "payment_approval_required": True,
                "delivery_approval_required": True,
                "finance_review_required": True,
                "operator_action_audit_required": True,
                "provider_reliability_required": True,
                "artifact_version_lock_required": True,
                "download_auth_required": True,
                "settlement_reconciliation_readback_required": True,
                "rollback_readiness_required": True,
                "manual_refund_exception_manual_approval_audit_required": True,
                "repository_backed_readback": True,
                "replayable_readback": True,
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "real_payment_capture_attempted": False,
                "real_charge_attempted": False,
                "real_delivery_fulfillment_attempted": False,
                "real_customer_download_attempted": False,
                "real_refund_attempted": False,
                "automated_refund_program_present": False,
                "automated_refund_enabled": False,
                "public_release_enabled": False,
                "external_release_enabled": False,
            },
            "stage9_approved_payment_delivery_execution": {
                "current_entry": "approved payment capture/charge and delivery fulfillment provider execution readback",
                "http_entry_enabled": True,
                "mounted_operations": operation_ids_by_stage["stage9"],
                "controlled_provider_adapter_scope": "LOCAL_CONTROLLED_FAKE_PROVIDER",
                "sandbox_payment_pass_required": True,
                "payment_approval_required": True,
                "delivery_approval_required": True,
                "finance_review_required": True,
                "operator_action_audit_required": True,
                "provider_reliability_required": True,
                "callback_verification_required": True,
                "artifact_version_lock_required": True,
                "download_auth_required": True,
                "settlement_reconciliation_readback_required": True,
                "rollback_readiness_required": True,
                "manual_refund_exception_manual_approval_audit_required": True,
                "repository_backed_readback": True,
                "replayable_readback": True,
                "provider_result_readback_visible": True,
                "provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "real_payment_capture_attempted": False,
                "real_charge_attempted": False,
                "real_delivery_fulfillment_attempted": False,
                "real_customer_download_attempted": False,
                "real_refund_attempted": False,
                "automated_refund_program_present": False,
                "automated_refund_enabled": False,
                "public_release_enabled": False,
                "external_release_enabled": False,
            },
            "operator_customer_access": {
                "current_entry": "owner-operated internal console, productized frontend, and gated customer artifact access",
                "http_entry_enabled": True,
                "surface_mode": "internal-readback",
                "capability_state": "APPROVAL_READY",
                "mounted_operations": operator_customer_access_operation_ids,
                "frontend_operations": operator_frontend_operation_ids,
                "owner_operator_frontend": {
                    "path": "/operator-console",
                    "task_creation_visible": True,
                    "project_import_visible": True,
                    "real_public_source_runner_visible": True,
                    "full_chain_run_entry_visible": True,
                    "stage6_to_stage9_workbench_visible": True,
                    "provider_status_visible": True,
                    "scheduler_status_visible": True,
                    "approval_audit_visible": True,
                    "live_execution_enabled": False,
                    "external_release_enabled": False,
                },
                "operator_console_entries": {
                    "task_creation": "/operator-console/tasks",
                    "project_import": "/operator-console/project-imports",
                    "real_public_source_profiles": "/operator-console/real-source-profiles",
                    "real_public_source_run": "/operator-console/real-source-runs",
                    "real_public_source_task_runs": "/operator-console/real-source-task-runs",
                    "real_public_source_readback": "/operator-console/real-source-runs/{snapshot_id}",
                    "real_candidate_catalog": "/operator-console/real-candidates",
                    "real_candidate_discovery_runs": "/operator-console/real-candidate-discovery-runs",
                    "real_candidate_stage2_captures": "/operator-console/real-candidate-stage2-captures",
                    "full_chain_run": INTERNAL_STAGE1_TO_STAGE6_ORCHESTRATION_ENTRY[
                        "internal_orchestration_path"
                    ],
                    "provider_status": "/operator-console/readiness",
                    "scheduler_status": "/operator-console/scheduler-status",
                    "audit_log": "/operator-console/readiness",
                },
                "customer_artifact_access": {
                    "candidate_path": "/customer-artifact-access-candidates/{opportunity_id}",
                    "portal_path": "/customer-artifact-portal/{opportunity_id}",
                    "account_access_control_required": True,
                    "download_auth_required": True,
                    "field_allowlist_masking_required": True,
                    "approval_required": True,
                    "audit_required": True,
                    "readback_required": True,
                    "customer_download_enabled": False,
                    "customer_visible_publication_enabled": False,
                },
                "go_live_readiness": {
                    "path": "/go-live/readiness",
                    "deployment_readiness_visible": True,
                    "monitoring_rollback_refs_visible": True,
                    "remaining_blockers_visible": True,
                    "required_approvals_visible": True,
                    "required_audits_visible": True,
                    "required_operator_actions_visible": True,
                    "go_live_enabled": False,
                },
                "external_release_enabled": False,
                "public_software_release": False,
                "live_execution_enabled": False,
                "real_provider_execution_enabled": False,
                "real_payment_delivery_enabled": False,
                "automated_refund_enabled": False,
            },
        },
        "controlled_opening_requirements": {
            "new_http_endpoint_added": False,
            "internal_stage1_to_stage6_http_endpoint_added": True,
            "operator_customer_access_http_endpoint_added": True,
            "operator_frontend_http_endpoint_added": True,
            "operator_customer_access_external_or_live_endpoint_added": False,
            "customer_artifact_access_public_release_enabled": False,
            "customer_download_without_auth_enabled": False,
            "customer_artifact_download_enabled": False,
            "new_external_or_live_http_endpoint_added": False,
            "stage1_to_stage5_real_transport_enabled": False,
            "stage1_to_stage5_external_live_transport_enabled": False,
            "external_software_release_enabled": False,
            "external_leadpack_delivery_requires_approval_and_audit": True,
            "stage8_real_execution_enabled": False,
            "stage8_governed_execution_outbox_only": True,
            "stage8_real_send_enabled": False,
            "stage8_real_send_attempted": False,
            "stage8_bulk_send_enabled": False,
            "stage8_live_pilot_provider_call_enabled": False,
            "stage9_real_payment_delivery_refund_enabled": False,
            "provider_adapter_live_execution_enabled": False,
            "provider_adapter_provider_call_enabled": False,
            "provider_adapter_real_provider_call_enabled": False,
            "provider_adapter_silent_live_fallback_enabled": False,
            "provider_adapter_circuit_breaker_bypass_enabled": False,
            "redis_connection_enabled": False,
            "external_queue_connection_enabled": False,
            "external_worker_process_enabled": False,
            "minio_connection_enabled": False,
            "s3_connection_enabled": False,
            "external_object_storage_connection_enabled": False,
            "external_backup_service_enabled": False,
            "destructive_restore_enabled": False,
            "restore_execution_enabled": False,
            "rollback_execution_enabled": False,
            "migration_execution_enabled": False,
            "compose_runtime_enabled": False,
            "container_execution_enabled": False,
            "docker_compose_up_executed": False,
            "real_provider_execution_enabled": False,
            "real_payment_delivery_enabled": False,
            "provider_credentials_plaintext_persisted": False,
            "external_observability_provider_enabled": False,
            "external_apm_enabled": False,
            "external_paging_enabled": False,
            "notification_enabled": False,
            "live_alert_dispatch_enabled": False,
            "real_alert_dispatch_enabled": False,
            "incident_automation_enabled": False,
            "active_storage_mutation_enabled": False,
            "automated_refund_program_present": False,
            "automated_refund_program_enabled": False,
            "automated_refund_enabled": False,
        },
    }


def create_app() -> FastAPI:
    settings = get_settings()
    storage_session = get_database_session()
    app = FastAPI(
        title="AX9S Internal Preview API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.storage_session = storage_session
    app.state.storage_bootstrap = settings.storage_bootstrap_payload()
    app.state.provider_adapter_bootstrap = settings.provider_adapter_bootstrap_payload()
    app.state.provider_adapter_config_readback = ProviderAdapterConfigRepository(
        session=storage_session
    ).save(app.state.provider_adapter_bootstrap)
    app.state.monitoring_alerting_readback = MonitoringAlertingRepository(
        session=storage_session,
        settings=settings,
    ).save(app.state.storage_bootstrap["monitoring_alerting_readiness"])
    app.state.production_slo_incident_readback = ProductionSloIncidentRepository(
        session=storage_session,
        settings=settings,
    ).save(app.state.storage_bootstrap["production_slo_incident_readiness"])
    provider_adapter_readiness_summary = dict(
        app.state.provider_adapter_bootstrap[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]
    )
    app.state.disabled_stage_transports = {
        "stage1": register_stage1_routes(),
        "stage2": register_stage2_routes(),
        "stage3": register_stage3_routes(),
        "stage4": register_stage4_routes(),
        "stage5": register_stage5_routes(),
    }
    mounted_stage_routes = {
        "stage6": register_stage1_to_stage6_internal_orchestration_routes() + register_stage6_routes(),
        "stage7": register_stage7_routes(
            provider_adapter_readiness_summary=provider_adapter_readiness_summary
        ),
        "stage8": register_stage8_routes(
            provider_adapter_readiness_summary=provider_adapter_readiness_summary
        ),
        "stage9": register_stage9_routes(
            provider_adapter_readiness_summary=provider_adapter_readiness_summary
        ),
    }
    mounted_routes = [
        route
        for stage_routes in mounted_stage_routes.values()
        for route in stage_routes
    ]
    operator_customer_access_routes = register_operator_customer_access_routes()
    operator_frontend_routes = register_operator_frontend_routes()
    _mount_routes(app, mounted_routes)
    _mount_routes(app, operator_customer_access_routes)
    _mount_routes(app, operator_frontend_routes)
    app.state.mounted_transport_operations = [route["operationId"] for route in mounted_routes]
    app.state.operator_customer_access_operations = [
        route["operationId"]
        for route in operator_customer_access_routes
    ]
    app.state.operator_frontend_operations = [
        route["operationId"]
        for route in operator_frontend_routes
    ]
    app.state.transport_bootstrap = _build_transport_bootstrap(
        app.state.disabled_stage_transports,
        mounted_stage_routes,
        operator_customer_access_routes,
        operator_frontend_routes,
        app.state.provider_adapter_bootstrap,
        app.state.storage_bootstrap,
    )
    return app


__all__ = ["create_app"]
