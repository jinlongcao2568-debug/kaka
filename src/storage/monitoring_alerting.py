from __future__ import annotations

from typing import Any, Mapping


MONITORING_ALERTING_READINESS_OBJECT_TYPE = "monitoring_alerting_readiness"
MONITORING_ALERTING_READINESS_RECORD_ID = "MONITORING_ALERTING_READINESS_CURRENT"
MONITORING_ALERTING_SCHEMA_VERSION = 1

READBACK_READY = "READBACK_READY"
READBACK_FAIL_CLOSED = "FAIL_CLOSED_STALE_OR_MISSING_REFS"
READBACK_MISSING = "MISSING_READINESS"

_HEALTHY_STATES = {"EXECUTABLE", "CONFIG_PRESENT_NOT_EXECUTED", "SANDBOX_DRY_RUN_READBACK"}
_LIVE_CONTROLLED_OPENING_BOUNDARY_FIELDS = (
    "notification_enabled",
    "live_dispatch_enabled",
    "live_alert_dispatch_enabled",
    "external_observability_provider_enabled",
    "external_apm_enabled",
    "external_paging_enabled",
    "incident_automation_enabled",
    "external_service_connection_enabled",
    "real_provider_execution_enabled",
    "real_alert_dispatch_enabled",
)


def build_monitoring_alerting_readiness(
    *,
    platform_infra_readiness: Mapping[str, Any],
    provider_adapter_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    platform = dict(platform_infra_readiness)
    provider = dict(provider_adapter_readiness or {})
    components = _build_monitoring_components(platform=platform, provider=provider)
    alert_rule_catalog = _build_alert_rule_catalog()
    monitoring_readiness = _build_monitoring_readiness(components)
    alert_readiness = _build_alert_readiness(alert_rule_catalog)
    incident_readiness = _build_incident_readiness(platform)
    readiness_id = MONITORING_ALERTING_READINESS_RECORD_ID

    payload: dict[str, Any] = {
        "schema_version": MONITORING_ALERTING_SCHEMA_VERSION,
        "readiness_id": readiness_id,
        "readiness_scope": "INTERNAL_MONITORING_ALERTING_INCIDENT_READINESS",
        "readback_only": True,
        "replayable_readback": True,
        "monitoring_readiness": monitoring_readiness,
        "monitoring_components": components,
        "alert_rule_catalog": alert_rule_catalog,
        "alert_readiness": alert_readiness,
        "incident_readiness": incident_readiness,
        "readiness_refs": {
            "component_ids": [component["component_id"] for component in components],
            "alert_rule_ids": [rule["alert_rule_id"] for rule in alert_rule_catalog],
            "backup_refs": list(incident_readiness["backup_refs"]),
            "rollback_refs": list(incident_readiness["rollback_refs"]),
            "runbook_refs": list(incident_readiness["runbook_refs"]),
        },
        "controlled_opening_boundaries": monitoring_alerting_controlled_opening_boundaries(),
    }
    payload["validation"] = validate_monitoring_alerting_readiness(payload)
    return payload


def monitoring_alerting_controlled_opening_boundaries() -> dict[str, bool]:
    return {
        "external_observability_provider_enabled": False,
        "external_apm_enabled": False,
        "external_paging_enabled": False,
        "notification_enabled": False,
        "live_alert_dispatch_enabled": False,
        "real_alert_dispatch_enabled": False,
        "incident_automation_enabled": False,
        "external_service_connection_enabled": False,
        "real_provider_execution_enabled": False,
        "real_sales_outreach_enabled": False,
        "real_payment_enabled": False,
        "real_charge_enabled": False,
        "real_delivery_enabled": False,
        "real_refund_enabled": False,
        "automated_refund_enabled": False,
        "external_software_release_enabled": False,
    }


def validate_monitoring_alerting_readiness(payload: Mapping[str, Any]) -> dict[str, Any]:
    missing_fields = [
        field_name
        for field_name in (
            "readiness_id",
            "monitoring_readiness",
            "monitoring_components",
            "alert_rule_catalog",
            "alert_readiness",
            "incident_readiness",
            "controlled_opening_boundaries",
        )
        if field_name not in payload
    ]
    monitoring_components = _list_of_mappings(payload.get("monitoring_components"))
    alert_rules = _list_of_mappings(payload.get("alert_rule_catalog"))
    component_ids = {
        str(component.get("component_id"))
        for component in monitoring_components
        if component.get("component_id") not in (None, "")
    }
    alert_rule_ids = {
        str(rule.get("alert_rule_id"))
        for rule in alert_rules
        if rule.get("alert_rule_id") not in (None, "")
    }

    stale_or_missing_refs: list[dict[str, Any]] = []
    for rule in alert_rules:
        rule_id = str(rule.get("alert_rule_id", "UNKNOWN_ALERT_RULE"))
        for component_id in list(rule.get("signal_component_ids", [])):
            if str(component_id) not in component_ids:
                stale_or_missing_refs.append(
                    {
                        "ref_type": "alert_rule_signal_component",
                        "alert_rule_id": rule_id,
                        "missing_component_id": str(component_id),
                    }
                )

    alert_readiness = _mapping(payload.get("alert_readiness"))
    for rule_id in list(alert_readiness.get("catalog_rule_ids", [])):
        if str(rule_id) not in alert_rule_ids:
            stale_or_missing_refs.append(
                {
                    "ref_type": "alert_readiness_catalog_rule",
                    "missing_alert_rule_id": str(rule_id),
                }
            )

    incident_readiness = _mapping(payload.get("incident_readiness"))
    for ref_name in ("runbook_refs", "rollback_refs", "backup_refs"):
        refs = [str(ref) for ref in list(incident_readiness.get(ref_name, [])) if str(ref)]
        if not refs:
            stale_or_missing_refs.append(
                {
                    "ref_type": f"incident_{ref_name}",
                    "missing_ref_group": ref_name,
                }
            )

    live_controlled_opening_boundary_violations = _live_controlled_opening_boundary_violations(payload)
    valid = not missing_fields and not stale_or_missing_refs and not live_controlled_opening_boundary_violations
    return {
        "valid": valid,
        "readback_state": READBACK_READY if valid else READBACK_FAIL_CLOSED,
        "missing_fields": missing_fields,
        "stale_or_missing_refs": stale_or_missing_refs,
        "live_controlled_opening_boundary_violations": live_controlled_opening_boundary_violations,
        "no_broad_fallback": True,
        "fail_closed": not valid,
    }


def monitoring_alerting_readback_failure(readiness_id: str) -> dict[str, Any]:
    return {
        "readiness_id": readiness_id,
        "readback_state": READBACK_MISSING,
        "payload_present": False,
        "replayable_readback": False,
        "fail_closed": True,
        "no_broad_fallback": True,
        "notification_enabled": False,
        "live_dispatch_enabled": False,
        "incident_automation_enabled": False,
        "external_paging_enabled": False,
        "blocking_reasons": ["monitoring_alerting_readiness_record_missing"],
    }


def _build_monitoring_components(
    *,
    platform: Mapping[str, Any],
    provider: Mapping[str, Any],
) -> list[dict[str, Any]]:
    executable_backends = _list_of_mappings(platform.get("executable_backends"))
    active_backend = str(platform.get("active_backend", "UNKNOWN"))
    active_backend_readiness = _find_by_key(executable_backends, "backend", active_backend)
    queue_readiness = _mapping(platform.get("queue_readiness"))
    worker_readiness = _mapping(platform.get("worker_runtime_readiness"))
    object_storage = _mapping(platform.get("object_storage_readiness"))
    backup_restore = _mapping(platform.get("backup_restore_readiness"))
    rollback = _mapping(platform.get("rollback_readiness"))
    local_stack = _mapping(platform.get("compose_readiness"))

    return [
        _component(
            component_id="storage.backend",
            component_family="storage_backend",
            readiness_state=str(active_backend_readiness.get("readiness_state", "UNKNOWN")),
            executable=bool(active_backend_readiness.get("executable", False)),
            signal_sources=["platform_infra_readiness.executable_backends", "Settings.storage_backend"],
            degraded_reasons=[] if active_backend_readiness.get("executable") else ["active_storage_backend_not_executable"],
            blocking_reasons=[],
            audit_refs={"config_source": "Settings.storage_backend", "active_backend": active_backend},
        ),
        _component(
            component_id="queue.worker",
            component_family="queue_worker",
            readiness_state=str(worker_readiness.get("readiness_state", "UNKNOWN")),
            executable=bool(worker_readiness.get("executable", True)),
            signal_sources=[
                "platform_infra_readiness.queue_readiness",
                "platform_infra_readiness.worker_runtime_readiness",
                "platform_infra_readiness.worker_queue_bootstrap",
            ],
            degraded_reasons=_degraded_if_false(
                queue_readiness,
                {
                    "external_service_connection_enabled": "external_queue_connection_disabled_by_design",
                },
            ),
            blocking_reasons=[],
            audit_refs={"queue_backend": str(queue_readiness.get("queue_backend", ""))},
        ),
        _component(
            component_id="object_storage.local_snapshot",
            component_family="object_storage",
            readiness_state=str(object_storage.get("readiness_state", "UNKNOWN")),
            executable=bool(object_storage.get("executable", False)),
            signal_sources=["platform_infra_readiness.object_storage_readiness"],
            degraded_reasons=[] if object_storage.get("executable") else ["object_storage_backend_reserved_not_live"],
            blocking_reasons=[],
            audit_refs={"object_storage_backend": str(object_storage.get("active_backend", ""))},
        ),
        _component(
            component_id="backup_restore.local_manifest",
            component_family="backup_restore",
            readiness_state=str(backup_restore.get("readiness_state", "UNKNOWN")),
            executable=bool(backup_restore.get("backup_manifest_enabled", False)),
            signal_sources=["platform_infra_readiness.backup_restore_readiness"],
            degraded_reasons=[
                "restore_execution_disabled_by_design",
                "destructive_restore_disabled_by_design",
            ],
            blocking_reasons=[],
            audit_refs={"approval_required": str(backup_restore.get("approval_required", True))},
        ),
        _component(
            component_id="rollback.manual_review",
            component_family="rollback",
            readiness_state=str(rollback.get("readiness_state", "UNKNOWN")),
            executable=bool(rollback.get("restore_dry_run_enabled", False)),
            signal_sources=["platform_infra_readiness.rollback_readiness"],
            degraded_reasons=["rollback_execution_disabled_by_design"],
            blocking_reasons=[],
            audit_refs={"rollback_state": str(rollback.get("rollback_state", ""))},
        ),
        _component(
            component_id="local_stack.compose_definition",
            component_family="local_stack",
            readiness_state=str(local_stack.get("readiness_state", "UNKNOWN")),
            executable=bool(local_stack.get("configured", False)),
            signal_sources=["platform_infra_readiness.compose_readiness"],
            degraded_reasons=["compose_runtime_not_executed_by_design"],
            blocking_reasons=[] if local_stack.get("configured") else ["compose_config_missing"],
            audit_refs={"compose_runtime_enabled": str(local_stack.get("compose_runtime_enabled", False))},
        ),
        _component(
            component_id="provider.controlled_opening_boundary",
            component_family="provider_controlled_opening_boundary",
            readiness_state=str(provider.get("mode", "SANDBOX_DRY_RUN_READBACK")),
            executable=True,
            signal_sources=["provider_adapter_readiness_summary", "provider_adapter_bootstrap"],
            degraded_reasons=list(provider.get("blocked_reasons", [])),
            blocking_reasons=[],
            audit_refs={
                "config_source_ref": str(provider.get("config_source_ref", "")),
                "readback_only": str(provider.get("readback_only", True)),
            },
        ),
    ]


def _build_monitoring_readiness(components: list[dict[str, Any]]) -> dict[str, Any]:
    degraded_reasons = sorted(
        {
            reason
            for component in components
            for reason in list(component.get("degraded_reasons", []))
        }
    )
    blocking_reasons = sorted(
        {
            reason
            for component in components
            for reason in list(component.get("blocking_reasons", []))
        }
    )
    health_state = "BLOCKED" if blocking_reasons else ("DEGRADED" if degraded_reasons else "HEALTHY")
    return {
        "readiness_state": "INTERNAL_READBACK_READY" if not blocking_reasons else "FAIL_CLOSED",
        "health_state": health_state,
        "component_count": len(components),
        "component_ids": [component["component_id"] for component in components],
        "signal_sources": sorted(
            {
                source
                for component in components
                for source in list(component.get("signal_sources", []))
            }
        ),
        "last_observed_at_optional": None,
        "degraded_reasons": degraded_reasons,
        "blocking_reasons": blocking_reasons,
        "audit_refs": {
            "task_packet": "PTL-I100-112F-monitoring-alerting-readiness",
            "source": "Settings.platform_infra_readiness",
        },
        "replayable_readback": True,
    }


def _build_alert_rule_catalog() -> list[dict[str, Any]]:
    return [
        _alert_rule(
            "storage_backend_not_executable",
            "critical",
            "active storage backend readiness_state != EXECUTABLE",
            "storage_owner",
            ["storage.backend"],
        ),
        _alert_rule(
            "queue_worker_not_progressing",
            "high",
            "queue/worker readiness not executable or retry/dead-letter growth requires owner review",
            "storage_owner",
            ["queue.worker"],
        ),
        _alert_rule(
            "object_storage_snapshot_unreadable",
            "critical",
            "snapshot manifest replay reports missing object, hash mismatch, or reserved external backend",
            "storage_owner",
            ["object_storage.local_snapshot"],
        ),
        _alert_rule(
            "backup_restore_manifest_invalid",
            "critical",
            "backup manifest validation missing required fields or hash mismatch",
            "governance_owner",
            ["backup_restore.local_manifest", "rollback.manual_review"],
        ),
        _alert_rule(
            "local_stack_config_missing",
            "medium",
            "Dockerfile / compose / dockerignore readiness config missing",
            "platform_owner",
            ["local_stack.compose_definition"],
        ),
        _alert_rule(
            "provider_controlled_opening_boundary_violation",
            "critical",
            "provider live execution, real provider call, payment, delivery, refund, or external release flag becomes true",
            "governance_owner",
            ["provider.controlled_opening_boundary"],
        ),
        _alert_rule(
            "incident_manual_action_required",
            "high",
            "incident readiness requires manual owner action, approval, audit, backup, and rollback refs",
            "incident_owner",
            ["backup_restore.local_manifest", "rollback.manual_review", "provider.controlled_opening_boundary"],
        ),
    ]


def _build_alert_readiness(alert_rule_catalog: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "readiness_state": "CATALOG_READY_READBACK_ONLY",
        "health_state": "HEALTHY",
        "catalog_rule_ids": [rule["alert_rule_id"] for rule in alert_rule_catalog],
        "rule_count": len(alert_rule_catalog),
        "notification_enabled": False,
        "live_dispatch_enabled": False,
        "external_observability_provider_enabled": False,
        "external_apm_enabled": False,
        "external_paging_enabled": False,
        "suppression_state": "NOT_SUPPRESSED",
        "suspended_state": "NOT_SUSPENDED",
        "approval_required": True,
        "audit_required": True,
        "readiness_only": True,
        "live_dispatch_blocking_reasons": [
            "external_observability_provider_not_configured_by_design",
            "notification_dispatch_disabled_by_112F_controlled_opening_boundary",
            "approval_and_audit_required_before_any_live_alerting",
        ],
        "audit_refs": {
            "rule_catalog_source": "storage.monitoring_alerting._build_alert_rule_catalog",
            "task_packet": "PTL-I100-112F-monitoring-alerting-readiness",
        },
        "replayable_readback": True,
    }


def _build_incident_readiness(platform: Mapping[str, Any]) -> dict[str, Any]:
    backup_restore = _mapping(platform.get("backup_restore_readiness"))
    rollback = _mapping(platform.get("rollback_readiness"))
    backup_refs = [
        "platform_infra_readiness.backup_restore_readiness",
        "storage.backup_restore.BACKUP_MANIFEST_OBJECT_TYPE",
    ]
    rollback_refs = [
        "platform_infra_readiness.rollback_readiness",
        str(rollback.get("rollback_point", "BACKUP_MANIFEST_REQUIRED")),
    ]
    return {
        "incident_state": "MANUAL_OWNER_ACTION_READY",
        "runbook_refs": [
            "control/current_task.yaml#PTL-I100-112F-monitoring-alerting-readiness",
            "docs/D12_部署发布与运行治理规范.md#incident-readiness",
        ],
        "rollback_refs": rollback_refs,
        "backup_refs": backup_refs,
        "backup_restore_readiness_state": str(backup_restore.get("readiness_state", "UNKNOWN")),
        "rollback_state": str(rollback.get("rollback_state", "REVIEW_REQUIRED")),
        "manual_owner_action_required": True,
        "incident_automation_enabled": False,
        "external_paging_enabled": False,
        "notification_enabled": False,
        "live_dispatch_enabled": False,
        "approval_required": True,
        "audit_required": True,
        "replayable_readback": True,
        "blocking_reasons": [],
        "degraded_reasons": [
            "manual_owner_action_required",
            "incident_automation_disabled_by_design",
            "external_paging_disabled_by_design",
        ],
        "audit_refs": {
            "backup_manifest_enabled": str(backup_restore.get("backup_manifest_enabled", False)),
            "rollback_execution_enabled": str(rollback.get("rollback_execution_enabled", False)),
        },
    }


def _alert_rule(
    alert_rule_id: str,
    severity: str,
    threshold_summary: str,
    owner_role: str,
    signal_component_ids: list[str],
) -> dict[str, Any]:
    return {
        "alert_rule_id": alert_rule_id,
        "severity": severity,
        "threshold_summary": threshold_summary,
        "owner_role": owner_role,
        "signal_component_ids": list(signal_component_ids),
        "notification_enabled": False,
        "live_dispatch_enabled": False,
        "suppression_state": "NOT_SUPPRESSED",
        "suspended_state": "NOT_SUSPENDED",
        "approval_required": True,
        "audit_required": True,
        "readiness_only": True,
    }


def _component(
    *,
    component_id: str,
    component_family: str,
    readiness_state: str,
    executable: bool,
    signal_sources: list[str],
    degraded_reasons: list[str],
    blocking_reasons: list[str],
    audit_refs: Mapping[str, str],
) -> dict[str, Any]:
    if blocking_reasons:
        health_state = "BLOCKED"
    elif degraded_reasons or (readiness_state not in _HEALTHY_STATES and not executable):
        health_state = "DEGRADED"
    else:
        health_state = "HEALTHY"
    return {
        "component_id": component_id,
        "component_family": component_family,
        "readiness_state": readiness_state,
        "health_state": health_state,
        "signal_sources": list(signal_sources),
        "last_observed_at_optional": None,
        "degraded_reasons": list(degraded_reasons),
        "blocking_reasons": list(blocking_reasons),
        "audit_refs": dict(audit_refs),
        "replayable_readback": True,
    }


def _degraded_if_false(source: Mapping[str, Any], false_reason_by_field: Mapping[str, str]) -> list[str]:
    reasons: list[str] = []
    for field_name, reason in false_reason_by_field.items():
        if bool(source.get(field_name, False)) is False:
            reasons.append(reason)
    return reasons


def _find_by_key(rows: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get(key)) == value:
            return row
    return {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _live_controlled_opening_boundary_violations(value: Any, *, path: str = "$") -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _LIVE_CONTROLLED_OPENING_BOUNDARY_FIELDS and bool(child):
                violations.append({"path": child_path, "field": str(key)})
            violations.extend(_live_controlled_opening_boundary_violations(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_live_controlled_opening_boundary_violations(child, path=f"{path}[{index}]"))
    return violations


__all__ = [
    "MONITORING_ALERTING_READINESS_OBJECT_TYPE",
    "MONITORING_ALERTING_READINESS_RECORD_ID",
    "READBACK_FAIL_CLOSED",
    "READBACK_MISSING",
    "READBACK_READY",
    "build_monitoring_alerting_readiness",
    "monitoring_alerting_readback_failure",
    "monitoring_alerting_controlled_opening_boundaries",
    "validate_monitoring_alerting_readiness",
]
