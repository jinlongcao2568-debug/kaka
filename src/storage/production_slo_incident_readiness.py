from __future__ import annotations

from typing import Any, Mapping


PRODUCTION_SLO_INCIDENT_READINESS_OBJECT_TYPE = "production_slo_incident_readiness"
PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID = "PRODUCTION_SLO_INCIDENT_READINESS_CURRENT"
PRODUCTION_SLO_INCIDENT_SCHEMA_VERSION = 1

PRODUCTION_READINESS_READY = "PRODUCTION_READY"
PRODUCTION_READINESS_FAIL_CLOSED = "FAIL_CLOSED_STALE_OR_MISSING_REFS"
PRODUCTION_READINESS_MISSING = "MISSING_READINESS"
APPROVED_PRODUCTION_LIVE_DEPENDENCY_DRILL_KEY = "approved_production_live_dependency_drill"

_LIVE_OR_DESTRUCTIVE_FIELDS = frozenset(
    {
        "notification_enabled",
        "live_dispatch_enabled",
        "live_alert_dispatch_enabled",
        "real_alert_dispatch_enabled",
        "external_observability_provider_enabled",
        "external_apm_enabled",
        "external_paging_enabled",
        "incident_automation_enabled",
        "external_service_connection_enabled",
        "real_provider_execution_enabled",
        "provider_call_enabled",
        "real_provider_call_enabled",
        "real_sales_outreach_enabled",
        "real_send_attempted",
        "real_payment_enabled",
        "real_charge_enabled",
        "real_delivery_enabled",
        "real_delivery_fulfillment_attempted",
        "real_refund_enabled",
        "automated_refund_enabled",
        "destructive_restore_enabled",
        "restore_execution_enabled",
        "rollback_execution_enabled",
        "active_storage_mutation_enabled",
        "current_active_storage_mutation_enabled",
        "active_storage_write_enabled",
        "migration_execution_enabled",
        "external_software_release_enabled",
        "production_release_enabled",
        "go_live_enabled",
    }
)

_REQUIRED_RUNBOOK_STEPS = (
    "detection",
    "triage",
    "suspend",
    "rollback_dry_run",
    "restore_dry_run",
    "manual_owner_action",
    "resume_readiness",
    "post_incident_audit",
)

_REQUIRED_FAILURE_FAMILIES = (
    "source",
    "provider",
    "outreach",
    "payment",
    "delivery",
    "backup_restore",
    "rollback",
)


def build_production_slo_incident_readiness(
    *,
    platform_infra_readiness: Mapping[str, Any],
    monitoring_alerting_readiness: Mapping[str, Any],
    provider_adapter_readiness: Mapping[str, Any] | None = None,
    simulated_failures: list[Mapping[str, Any]] | None = None,
    approved_dependency_drill_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    platform = dict(platform_infra_readiness)
    monitoring = dict(monitoring_alerting_readiness)
    provider = dict(provider_adapter_readiness or {})
    backup_restore = _mapping(platform.get("backup_restore_readiness"))
    rollback = _mapping(platform.get("rollback_readiness"))

    failures = _default_simulated_failures() if simulated_failures is None else [
        dict(failure) for failure in simulated_failures
    ]
    alert_catalog = _build_alert_rule_catalog(monitoring)
    alert_evaluations = evaluate_production_alert_rules(
        alert_catalog,
        simulated_failures=failures,
    )
    backup_drill = _build_backup_restore_drill_evidence(backup_restore)
    rollback_drill = _build_rollback_drill_evidence(rollback)
    suspended_state = _build_suspended_state_operation_readback(
        alert_evaluations=alert_evaluations,
        provider_adapter_readiness=provider,
    )
    incident_runbook = _build_incident_runbook(
        backup_drill=backup_drill,
        rollback_drill=rollback_drill,
        suspended_state=suspended_state,
    )
    approved_drill = _build_approved_production_live_dependency_drill(
        platform=platform,
        provider=provider,
        alert_evaluations=alert_evaluations,
        backup_drill=backup_drill,
        rollback_drill=rollback_drill,
        incident_runbook=incident_runbook,
        suspended_state=suspended_state,
        approval_inputs=approved_dependency_drill_inputs,
    )
    slo_carrier = _build_slo_readiness_carrier(
        platform=platform,
        monitoring=monitoring,
        backup_restore=backup_restore,
        rollback=rollback,
        provider=provider,
    )
    dashboard = _build_monitoring_dashboard_readback(
        monitoring=monitoring,
        alert_evaluations=alert_evaluations,
        suspended_state=suspended_state,
    )
    source_refs = _build_source_refs(
        monitoring=monitoring,
        backup_restore=backup_restore,
        rollback=rollback,
        provider=provider,
    )
    payload: dict[str, Any] = {
        "schema_version": PRODUCTION_SLO_INCIDENT_SCHEMA_VERSION,
        "readiness_id": PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID,
        "task_packet": "PTL-I100-121C-production-slo-monitoring-incident-readiness",
        "readiness_scope": "PRODUCTION_SLO_MONITORING_INCIDENT_READINESS_READBACK",
        "target_capability_state": PRODUCTION_READINESS_READY,
        "readiness_state": PRODUCTION_READINESS_READY,
        "readback_only": True,
        "repository_backed_readback": True,
        "replayable_readback": True,
        "external_release_enabled": False,
        "production_release_enabled": False,
        "go_live_enabled": False,
        "source_refs": source_refs,
        "slo_readiness_carrier": slo_carrier,
        "monitoring_dashboard_readback": dashboard,
        "alert_rule_catalog": alert_catalog,
        "simulated_failure_inputs": failures,
        "simulated_alert_evaluation_readback": alert_evaluations,
        "incident_runbook_carrier": incident_runbook,
        "backup_restore_drill_evidence": backup_drill,
        "rollback_drill_evidence": rollback_drill,
        "suspended_state_operation_readback": suspended_state,
        APPROVED_PRODUCTION_LIVE_DEPENDENCY_DRILL_KEY: approved_drill,
        "controlled_opening_requirements": production_slo_incident_controlled_opening_requirements(),
    }
    payload["validation"] = validate_production_slo_incident_readiness(payload)
    return payload


def evaluate_production_alert_rules(
    alert_rule_catalog: list[Mapping[str, Any]],
    *,
    simulated_failures: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    failures_by_family: dict[str, list[dict[str, Any]]] = {}
    for failure in simulated_failures:
        failure_payload = dict(failure)
        family = str(failure_payload.get("failure_family", "")).strip()
        if not family:
            continue
        failures_by_family.setdefault(family, []).append(failure_payload)

    evaluations: list[dict[str, Any]] = []
    for rule in alert_rule_catalog:
        rule_payload = dict(rule)
        rule_families = [
            str(family)
            for family in list(rule_payload.get("failure_families", []))
            if str(family)
        ]
        matched_failures = [
            failure
            for family in rule_families
            for failure in failures_by_family.get(family, [])
        ]
        evaluations.append(
            {
                "evaluation_id": f"EVAL-{rule_payload.get('alert_rule_id')}",
                "alert_rule_id": rule_payload.get("alert_rule_id"),
                "failure_families": rule_families,
                "matched_failure_ids": [
                    str(failure.get("failure_id")) for failure in matched_failures
                ],
                "alert_fired": bool(matched_failures),
                "evaluation_mode": "SIMULATED_READBACK_ONLY",
                "notification_enabled": False,
                "live_dispatch_enabled": False,
                "real_alert_dispatch_enabled": False,
                "external_paging_enabled": False,
                "external_apm_enabled": False,
                "incident_automation_enabled": False,
                "dispatch_state": "DISABLED_READBACK_ONLY",
                "owner_action_required": bool(matched_failures),
                "manual_ack_required": bool(matched_failures),
                "audit_refs": [
                    f"alert_rule:{rule_payload.get('alert_rule_id')}",
                    *[
                        f"simulated_failure:{failure.get('failure_id')}"
                        for failure in matched_failures
                    ],
                ],
                "no_live_dispatch_reason": "121C simulates alert evaluation only",
            }
        )
    return evaluations


def validate_production_slo_incident_readiness(payload: Mapping[str, Any]) -> dict[str, Any]:
    missing_fields = [
        field_name
        for field_name in (
            "readiness_id",
            "source_refs",
            "slo_readiness_carrier",
            "monitoring_dashboard_readback",
            "alert_rule_catalog",
            "simulated_alert_evaluation_readback",
            "incident_runbook_carrier",
            "backup_restore_drill_evidence",
            "rollback_drill_evidence",
            "suspended_state_operation_readback",
            "controlled_opening_requirements",
        )
        if field_name not in payload
    ]
    stale_or_missing_refs: list[dict[str, Any]] = []
    source_refs = _mapping(payload.get("source_refs"))
    for ref_name in (
        "monitoring_alerting_readiness_id",
        "backup_restore_readiness_ref",
        "rollback_readiness_ref",
        "provider_adapter_readiness_ref",
        "stage8_outreach_execution_outbox_ref",
        "stage9_payment_delivery_live_pilot_ref",
    ):
        if not source_refs.get(ref_name):
            stale_or_missing_refs.append(
                {"ref_type": "source_ref", "missing_ref": ref_name}
            )

    alert_rules = _list_of_mappings(payload.get("alert_rule_catalog"))
    alert_rule_ids = {
        str(rule.get("alert_rule_id"))
        for rule in alert_rules
        if rule.get("alert_rule_id") not in (None, "")
    }
    evaluations = _list_of_mappings(payload.get("simulated_alert_evaluation_readback"))
    evaluation_rule_ids = {
        str(evaluation.get("alert_rule_id"))
        for evaluation in evaluations
        if evaluation.get("alert_rule_id") not in (None, "")
    }
    for evaluation in evaluations:
        rule_id = str(evaluation.get("alert_rule_id", ""))
        if rule_id not in alert_rule_ids:
            stale_or_missing_refs.append(
                {
                    "ref_type": "simulated_alert_evaluation_rule",
                    "missing_alert_rule_id": rule_id,
                }
            )
        if not bool(evaluation.get("alert_fired", False)):
            stale_or_missing_refs.append(
                {
                    "ref_type": "simulated_alert_evaluation",
                    "alert_rule_id": rule_id,
                    "missing_alert_fired": True,
                }
            )
    for rule_id in sorted(alert_rule_ids - evaluation_rule_ids):
        stale_or_missing_refs.append(
            {
                "ref_type": "alert_rule_without_simulated_evaluation",
                "missing_alert_rule_id": rule_id,
            }
        )

    covered_families = {
        str(family)
        for rule in alert_rules
        for family in list(rule.get("failure_families", []))
        if str(family)
    }
    for required_family in _REQUIRED_FAILURE_FAMILIES:
        if required_family not in covered_families:
            stale_or_missing_refs.append(
                {
                    "ref_type": "alert_failure_family_coverage",
                    "missing_failure_family": required_family,
                }
            )

    incident_runbook = _mapping(payload.get("incident_runbook_carrier"))
    runbook_steps = {
        str(step.get("step_id"))
        for step in _list_of_mappings(incident_runbook.get("runbook_steps"))
        if step.get("step_id") not in (None, "")
    }
    for step_id in _REQUIRED_RUNBOOK_STEPS:
        if step_id not in runbook_steps:
            stale_or_missing_refs.append(
                {
                    "ref_type": "incident_runbook_step",
                    "missing_step_id": step_id,
                }
            )

    suspended_state = _mapping(payload.get("suspended_state_operation_readback"))
    for field_name in (
        "suspension_reason",
        "affected_capability",
        "owner_action_required",
        "manual_resume_required",
        "resume_readiness_state",
        "audit_refs",
    ):
        value = suspended_state.get(field_name)
        if value in (None, "", []) or (field_name.endswith("required") and value is not True):
            stale_or_missing_refs.append(
                {
                    "ref_type": "suspended_state_operation",
                    "missing_field": field_name,
                }
            )

    for drill_name in ("backup_restore_drill_evidence", "rollback_drill_evidence"):
        drill = _mapping(payload.get(drill_name))
        if not drill:
            stale_or_missing_refs.append(
                {"ref_type": "drill_evidence", "missing_drill": drill_name}
            )
            continue
        if str(drill.get("drill_mode")) != "DRY_RUN_ONLY":
            stale_or_missing_refs.append(
                {"ref_type": "drill_mode", "drill": drill_name}
            )
        for flag_name in (
            "destructive_restore_enabled",
            "restore_execution_enabled",
            "rollback_execution_enabled",
            "active_storage_mutation_enabled",
        ):
            if bool(drill.get(flag_name, False)):
                stale_or_missing_refs.append(
                    {
                        "ref_type": "drill_controlled_opening_requirement",
                        "drill": drill_name,
                        "flag": flag_name,
                    }
                )

    live_controlled_opening_requirement_violations = _live_controlled_opening_requirement_violations(payload)
    valid = not missing_fields and not stale_or_missing_refs and not live_controlled_opening_requirement_violations
    return {
        "valid": valid,
        "readback_state": PRODUCTION_READINESS_READY if valid else PRODUCTION_READINESS_FAIL_CLOSED,
        "missing_fields": missing_fields,
        "stale_or_missing_refs": stale_or_missing_refs,
        "live_controlled_opening_requirement_violations": live_controlled_opening_requirement_violations,
        "fail_closed": not valid,
        "no_broad_fallback": True,
    }


def production_slo_incident_readback_failure(readiness_id: str) -> dict[str, Any]:
    return {
        "readiness_id": readiness_id,
        "payload_present": False,
        "readback_state": PRODUCTION_READINESS_MISSING,
        "target_capability_state": PRODUCTION_READINESS_READY,
        "replayable_readback": False,
        "fail_closed": True,
        "no_broad_fallback": True,
        "notification_enabled": False,
        "live_dispatch_enabled": False,
        "real_alert_dispatch_enabled": False,
        "external_paging_enabled": False,
        "external_apm_enabled": False,
        "incident_automation_enabled": False,
        "destructive_restore_enabled": False,
        "restore_execution_enabled": False,
        "rollback_execution_enabled": False,
        "blocking_reasons": ["production_slo_incident_readiness_record_missing"],
    }


def production_slo_incident_controlled_opening_requirements() -> dict[str, bool]:
    return {
        "external_software_release_enabled": False,
        "production_release_enabled": False,
        "go_live_enabled": False,
        "notification_enabled": False,
        "live_alert_dispatch_enabled": False,
        "real_alert_dispatch_enabled": False,
        "external_observability_provider_enabled": False,
        "external_apm_enabled": False,
        "external_paging_enabled": False,
        "incident_automation_enabled": False,
        "external_backup_service_enabled": False,
        "destructive_restore_enabled": False,
        "restore_execution_enabled": False,
        "rollback_execution_enabled": False,
        "active_storage_mutation_enabled": False,
        "migration_execution_enabled": False,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "real_sales_outreach_enabled": False,
        "real_payment_enabled": False,
        "real_charge_enabled": False,
        "real_delivery_enabled": False,
        "real_refund_enabled": False,
        "automated_refund_enabled": False,
    }


def _build_approved_production_live_dependency_drill(
    *,
    platform: Mapping[str, Any],
    provider: Mapping[str, Any],
    alert_evaluations: list[Mapping[str, Any]],
    backup_drill: Mapping[str, Any],
    rollback_drill: Mapping[str, Any],
    incident_runbook: Mapping[str, Any],
    suspended_state: Mapping[str, Any],
    approval_inputs: Mapping[str, Any] | None,
) -> dict[str, Any]:
    inputs = dict(approval_inputs or {})
    request_flags = {
        "approved_production_live_dependency_drill_requested": bool(
            inputs.get("approved_production_live_dependency_drill_requested", False)
        ),
        "approved_container_stack_drill_requested": bool(
            inputs.get("approved_container_stack_drill_requested", False)
        ),
        "approved_alert_dispatch_drill_requested": bool(
            inputs.get("approved_alert_dispatch_drill_requested", False)
        ),
        "approved_backup_restore_drill_requested": bool(
            inputs.get("approved_backup_restore_drill_requested", False)
        ),
        "approved_rollback_drill_requested": bool(
            inputs.get("approved_rollback_drill_requested", False)
        ),
        "approved_incident_manual_execution_requested": bool(
            inputs.get("approved_incident_manual_execution_requested", False)
        ),
    }
    requested = any(request_flags.values())
    owner_approval_state = str(inputs.get("owner_approval_state") or "MISSING")
    dependency_provider_approval_state = str(
        inputs.get("external_dependency_provider_approval_state") or "MISSING"
    )
    alert_dispatch_approval_state = str(
        inputs.get("alert_dispatch_approval_state") or "MISSING"
    )
    restore_drill_approval_state = str(
        inputs.get("restore_drill_approval_state") or "MISSING"
    )
    rollback_drill_approval_state = str(
        inputs.get("rollback_drill_approval_state") or "MISSING"
    )
    incident_owner_approval_state = str(
        inputs.get("incident_owner_approval_state") or "MISSING"
    )
    operator_action_audit_refs = [
        str(ref)
        for ref in list(inputs.get("operator_action_audit_refs", []))
        if str(ref)
    ]
    compose = _mapping(platform.get("compose_readiness"))
    local_stack_ready = all(
        bool(compose.get(flag, False))
        for flag in (
            "dockerfile_present",
            "compose_file_present",
            "docker_compose_config_present",
        )
    )
    provider_suspended = bool(provider.get("provider_adapter_suspended", False)) or str(
        provider.get("provider_circuit_breaker_state") or ""
    ).upper() == "OPEN"
    backup_ready = (
        str(backup_drill.get("drill_mode")) == "DRY_RUN_ONLY"
        and bool(backup_drill.get("audit_refs"))
        and not bool(backup_drill.get("destructive_restore_enabled", False))
        and not bool(backup_drill.get("restore_execution_enabled", False))
    )
    rollback_ready = (
        str(rollback_drill.get("drill_mode")) == "DRY_RUN_ONLY"
        and bool(rollback_drill.get("audit_refs"))
        and not bool(rollback_drill.get("rollback_execution_enabled", False))
    )
    alert_evaluations_ready = bool(alert_evaluations) and all(
        bool(evaluation.get("alert_fired", False))
        and not bool(evaluation.get("real_alert_dispatch_enabled", False))
        for evaluation in alert_evaluations
    )
    incident_ready = (
        str(incident_runbook.get("runbook_state")) == PRODUCTION_READINESS_READY
        and bool(incident_runbook.get("audit_refs"))
        and not bool(incident_runbook.get("incident_automation_enabled", False))
    )
    blocked_reasons: list[str] = []
    if requested:
        if owner_approval_state != "APPROVED":
            blocked_reasons.append("owner_approval_missing")
        if dependency_provider_approval_state != "APPROVED":
            blocked_reasons.append("external_dependency_provider_approval_missing")
        if alert_dispatch_approval_state != "APPROVED":
            blocked_reasons.append("alert_dispatch_approval_missing")
        if restore_drill_approval_state != "APPROVED":
            blocked_reasons.append("restore_drill_approval_missing")
        if rollback_drill_approval_state != "APPROVED":
            blocked_reasons.append("rollback_drill_approval_missing")
        if incident_owner_approval_state != "APPROVED":
            blocked_reasons.append("incident_owner_approval_missing")
        if not operator_action_audit_refs:
            blocked_reasons.append("operator_action_audit_refs_missing")
        if not local_stack_ready:
            blocked_reasons.append("local_stack_runbook_not_ready")
        if not backup_ready:
            blocked_reasons.append("backup_restore_dry_run_not_ready")
        if not rollback_ready:
            blocked_reasons.append("rollback_dry_run_not_ready")
        if not alert_evaluations_ready:
            blocked_reasons.append("alert_simulation_readback_not_ready")
        if not incident_ready:
            blocked_reasons.append("incident_manual_runbook_not_ready")
    suspension_reasons = ["provider_adapter_suspended"] if requested and provider_suspended else []
    approved = requested and not blocked_reasons and not suspension_reasons
    if not requested:
        drill_state = "NOT_REQUESTED"
    elif suspension_reasons:
        drill_state = "SUSPENDED"
    elif approved:
        drill_state = "APPROVED_CONTROLLED_DRILL_RECORDED"
    else:
        drill_state = "BLOCKED"
    return {
        "drill_id": "PTL-I100-126-APPROVED-PRODUCTION-LIVE-DEPENDENCY-DRILL",
        "task_packet": "PTL-I100-126-production-live-dependency-and-drill-approval",
        **request_flags,
        "approved_production_live_dependency_drill_enabled": approved,
        "execution_request_state": "REQUESTED" if requested else "NOT_REQUESTED",
        "controlled_drill_state": drill_state,
        "owner_approval_state": owner_approval_state,
        "external_dependency_provider_approval_state": dependency_provider_approval_state,
        "alert_dispatch_approval_state": alert_dispatch_approval_state,
        "restore_drill_approval_state": restore_drill_approval_state,
        "rollback_drill_approval_state": rollback_drill_approval_state,
        "incident_owner_approval_state": incident_owner_approval_state,
        "operator_action_audit_refs": operator_action_audit_refs,
        "provider_adapter_readiness_summary": dict(provider),
        "controlled_execution_scope": "LOCAL_CONTROLLED_DRILL_READBACK",
        "container_stack_drill_record": {
            "runbook_validation_recorded": approved,
            "dockerfile_present": bool(compose.get("dockerfile_present", False)),
            "compose_file_present": bool(compose.get("compose_file_present", False)),
            "docker_compose_config_present": bool(
                compose.get("docker_compose_config_present", False)
            ),
            "container_execution_enabled": False,
            "docker_compose_up_executed": False,
            "migration_execution_enabled": False,
            "external_service_connection_enabled": False,
        },
        "alert_dispatch_drill_record": {
            "controlled_dispatch_simulation_recorded": approved,
            "simulated_alert_count": len(alert_evaluations),
            "alert_rule_ids": [
                str(evaluation.get("alert_rule_id"))
                for evaluation in alert_evaluations
            ],
            "notification_enabled": False,
            "live_dispatch_enabled": False,
            "real_alert_dispatch_enabled": False,
            "external_apm_enabled": False,
            "external_paging_enabled": False,
        },
        "backup_restore_drill_record": {
            "controlled_restore_dry_run_recorded": approved,
            "source_drill_id": backup_drill.get("drill_id"),
            "drill_mode": backup_drill.get("drill_mode"),
            "safe_to_restore": False,
            "destructive_restore_enabled": False,
            "restore_execution_enabled": False,
            "active_storage_mutation_enabled": False,
            "external_backup_service_enabled": False,
        },
        "rollback_drill_record": {
            "controlled_rollback_dry_run_recorded": approved,
            "source_drill_id": rollback_drill.get("drill_id"),
            "drill_mode": rollback_drill.get("drill_mode"),
            "rollback_execution_enabled": False,
            "destructive_restore_enabled": False,
            "active_storage_mutation_enabled": False,
        },
        "incident_manual_execution_record": {
            "manual_owner_action_recorded": approved,
            "source_runbook_id": incident_runbook.get("runbook_id"),
            "suspended_state_ref": suspended_state.get("suspension_id"),
            "owner_action_required": True,
            "manual_resume_required": True,
            "incident_automation_enabled": False,
            "external_paging_enabled": False,
        },
        "external_release_enabled": False,
        "production_release_enabled": False,
        "go_live_enabled": False,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "real_sales_outreach_enabled": False,
        "real_payment_enabled": False,
        "real_charge_enabled": False,
        "real_delivery_enabled": False,
        "real_refund_enabled": False,
        "automated_refund_enabled": False,
        "blocked_reasons": blocked_reasons,
        "suspension_reasons": suspension_reasons,
        "replay_state": {
            "state": "REPLAYABLE",
            "repository_backed": True,
            "controlled_drill_readback_replayable": True,
            "no_broad_fallback": True,
        },
    }


def _build_slo_readiness_carrier(
    *,
    platform: Mapping[str, Any],
    monitoring: Mapping[str, Any],
    backup_restore: Mapping[str, Any],
    rollback: Mapping[str, Any],
    provider: Mapping[str, Any],
) -> dict[str, Any]:
    capability_targets = [
        ("source_fetch", "public source adapter health, timeout, retry, and degrade readback"),
        ("parser", "Stage3 parser completion/error readback"),
        ("verification", "Stage4 public verification review/block readback"),
        ("rule_factory", "Stage5 rule/evidence dual gate readback"),
        ("stage6_product_package", "Stage6 product package readiness and artifact audit readback"),
        ("stage8_outreach_pilot", "121A outreach execution outbox and pilot suspension readback"),
        ("stage9_payment_delivery_pilot", "121B payment/delivery pilot ledger and rollback readback"),
        ("provider_reliability", "provider health/rate limit/timeout/circuit breaker readback"),
        ("backup_restore", "local backup manifest and restore dry-run readback"),
        ("rollback", "manual rollback dry-run readiness readback"),
        ("audit_replay", "repository-backed audit replay readback"),
    ]
    return {
        "slo_id": "PTL-I100-121C-PRODUCTION-SLO",
        "readiness_state": PRODUCTION_READINESS_READY,
        "capability_state": PRODUCTION_READINESS_READY,
        "readiness_only": True,
        "repository_backed_readback": True,
        "measurement_window": "readback_snapshot",
        "objective_count": len(capability_targets),
        "objectives": [
            {
                "capability": capability,
                "objective_summary": summary,
                "measurement_source": "repository_readback_or_simulated_failure_input",
                "latency_readback_visible": True,
                "error_readback_visible": True,
                "throughput_readback_visible": True,
                "failure_counter_visible": True,
                "suspension_state_visible": True,
                "owner_action_ref_required": True,
                "audit_ref_required": True,
                "live_execution_enabled": False,
            }
            for capability, summary in capability_targets
        ],
        "source_readiness_refs": {
            "platform_active_backend": str(platform.get("active_backend", "")),
            "monitoring_readiness_state": _mapping(
                monitoring.get("monitoring_readiness")
            ).get("readiness_state"),
            "backup_manifest_enabled": bool(backup_restore.get("backup_manifest_enabled", False)),
            "restore_dry_run_enabled": bool(backup_restore.get("restore_dry_run_enabled", False)),
            "rollback_state": rollback.get("rollback_state"),
            "provider_reliability_state": provider.get("provider_reliability_state"),
            "provider_circuit_breaker_state": provider.get("provider_circuit_breaker_state"),
        },
        "external_release_enabled": False,
        "go_live_enabled": False,
    }


def _build_monitoring_dashboard_readback(
    *,
    monitoring: Mapping[str, Any],
    alert_evaluations: list[Mapping[str, Any]],
    suspended_state: Mapping[str, Any],
) -> dict[str, Any]:
    components = _list_of_mappings(monitoring.get("monitoring_components"))
    component_by_id = {
        str(component.get("component_id")): component
        for component in components
        if component.get("component_id") not in (None, "")
    }
    simulated_failure_count = sum(1 for item in alert_evaluations if item.get("alert_fired"))
    panels = [
        _dashboard_panel(
            "source_fetch",
            ["source.fetch.readback", "stage2.public_source_adapters"],
            simulated_failure_count,
            suspended_state,
        ),
        _dashboard_panel(
            "provider_reliability",
            ["provider.controlled_opening_requirement"],
            simulated_failure_count,
            suspended_state,
            component_by_id=component_by_id,
        ),
        _dashboard_panel(
            "stage8_outreach_pilot",
            ["stage8.outreach_execution_outbox_snapshot"],
            simulated_failure_count,
            suspended_state,
        ),
        _dashboard_panel(
            "stage9_payment_delivery_pilot",
            ["stage9.payment_delivery_live_pilot"],
            simulated_failure_count,
            suspended_state,
        ),
        _dashboard_panel(
            "backup_restore",
            ["backup_restore.local_manifest"],
            simulated_failure_count,
            suspended_state,
            component_by_id=component_by_id,
        ),
        _dashboard_panel(
            "rollback",
            ["rollback.manual_review"],
            simulated_failure_count,
            suspended_state,
            component_by_id=component_by_id,
        ),
        _dashboard_panel(
            "audit_replay",
            ["storage.backend", "queue.worker"],
            simulated_failure_count,
            suspended_state,
            component_by_id=component_by_id,
        ),
    ]
    return {
        "dashboard_id": "PTL-I100-121C-PRODUCTION-MONITORING-DASHBOARD",
        "dashboard_state": PRODUCTION_READINESS_READY,
        "readback_only": True,
        "repository_backed_readback": True,
        "panel_count": len(panels),
        "panels": panels,
        "last_observed_at_optional": _mapping(monitoring.get("monitoring_readiness")).get(
            "last_observed_at_optional"
        ),
        "notification_enabled": False,
        "external_apm_enabled": False,
        "external_paging_enabled": False,
    }


def _dashboard_panel(
    capability: str,
    signal_refs: list[str],
    simulated_failure_count: int,
    suspended_state: Mapping[str, Any],
    *,
    component_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    components = component_by_id or {}
    component_states = [
        _mapping(components.get(ref)).get("health_state", "READBACK_ONLY")
        for ref in signal_refs
        if ref in components
    ]
    health_state = "DEGRADED_SIMULATED" if simulated_failure_count else (
        component_states[0] if component_states else "READBACK_ONLY"
    )
    return {
        "panel_id": f"panel.{capability}",
        "capability": capability,
        "health_state": health_state,
        "signal_refs": list(signal_refs),
        "latency_ms_p95_readback": None,
        "error_rate_readback": None,
        "throughput_per_minute_readback": None,
        "failure_counter": simulated_failure_count,
        "suspension_state": suspended_state.get("suspension_state", "SUSPENDED"),
        "last_observed_at_optional": None,
        "owner_action_refs": list(suspended_state.get("owner_action_refs", [])),
        "audit_refs": list(suspended_state.get("audit_refs", [])),
        "readback_only": True,
    }


def _build_alert_rule_catalog(monitoring: Mapping[str, Any]) -> list[dict[str, Any]]:
    base_rule_ids = [
        str(rule.get("alert_rule_id"))
        for rule in _list_of_mappings(monitoring.get("alert_rule_catalog"))
        if rule.get("alert_rule_id") not in (None, "")
    ]
    return [
        _alert_rule(
            "source_fetch_failure_alert",
            "source",
            "critical",
            "source fetch timeout, rate limit, source health degrade, or missing snapshot readback",
            "source_owner",
            ["stage2.public_source_adapters", "source_health", "failure_degrade"],
            base_rule_ids,
        ),
        _alert_rule(
            "provider_failure_alert",
            "provider",
            "critical",
            "provider health unhealthy, rate limit, timeout, failure taxonomy, or circuit open",
            "provider_owner",
            ["provider_adapter_readiness_summary", "provider.controlled_opening_requirement"],
            base_rule_ids,
        ),
        _alert_rule(
            "outreach_failure_alert",
            "outreach",
            "high",
            "Stage8 outreach provider result, bounce, failure threshold, complaint, or suspension readback",
            "sales_user",
            ["stage8.outreach_execution_outbox_snapshot", "stage8.live_pilot_readiness_summary"],
            base_rule_ids,
        ),
        _alert_rule(
            "payment_failure_alert",
            "payment",
            "critical",
            "Stage9 payment provider result, callback, settlement, or finance reconciliation failure readback",
            "delivery_governance_user",
            ["stage9.payment_delivery_live_pilot", "payment_sandbox_records"],
            base_rule_ids,
        ),
        _alert_rule(
            "delivery_failure_alert",
            "delivery",
            "critical",
            "Stage9 delivery provider result, artifact version lock, download audit, or fulfillment failure readback",
            "delivery_governance_user",
            ["stage9.payment_delivery_live_pilot", "delivery_sandbox_records"],
            base_rule_ids,
        ),
        _alert_rule(
            "backup_restore_failure_alert",
            "backup_restore",
            "critical",
            "backup manifest validation or restore dry-run reports missing refs/hash mismatch",
            "storage_owner",
            ["backup_restore.local_manifest", "storage.backup_restore"],
            base_rule_ids,
        ),
        _alert_rule(
            "rollback_failure_alert",
            "rollback",
            "critical",
            "rollback dry-run readiness requires manual review or missing backup manifest",
            "governance_owner",
            ["rollback.manual_review", "platform_infra_readiness.rollback_readiness"],
            base_rule_ids,
        ),
    ]


def _alert_rule(
    alert_rule_id: str,
    failure_family: str,
    severity: str,
    threshold_summary: str,
    owner_role: str,
    signal_refs: list[str],
    base_rule_ids: list[str],
) -> dict[str, Any]:
    return {
        "alert_rule_id": alert_rule_id,
        "failure_families": [failure_family],
        "severity": severity,
        "threshold_summary": threshold_summary,
        "owner_role": owner_role,
        "signal_refs": list(signal_refs),
        "base_monitoring_alert_rule_refs": list(base_rule_ids),
        "notification_enabled": False,
        "live_dispatch_enabled": False,
        "real_alert_dispatch_enabled": False,
        "external_paging_enabled": False,
        "external_apm_enabled": False,
        "incident_automation_enabled": False,
        "approval_required": True,
        "audit_required": True,
        "readiness_only": True,
        "dispatch_mode": "SIMULATED_READBACK_ONLY",
    }


def _default_simulated_failures() -> list[dict[str, Any]]:
    return [
        _simulated_failure("source_fetch_timeout", "source", "source_fetch"),
        _simulated_failure("provider_circuit_open", "provider", "provider_adapter"),
        _simulated_failure("outreach_failure_threshold", "outreach", "stage8_outreach_pilot"),
        _simulated_failure("payment_provider_failure", "payment", "stage9_payment_collection"),
        _simulated_failure("delivery_provider_failure", "delivery", "stage9_delivery_fulfillment"),
        _simulated_failure("backup_manifest_hash_mismatch", "backup_restore", "backup_restore"),
        _simulated_failure("rollback_manifest_missing", "rollback", "rollback"),
    ]


def _simulated_failure(failure_id: str, failure_family: str, affected_capability: str) -> dict[str, Any]:
    return {
        "failure_id": failure_id,
        "failure_family": failure_family,
        "affected_capability": affected_capability,
        "simulation_only": True,
        "fail_closed": True,
        "no_broad_fallback": True,
        "audit_refs": [f"simulated_failure:{failure_id}"],
    }


def _build_incident_runbook(
    *,
    backup_drill: Mapping[str, Any],
    rollback_drill: Mapping[str, Any],
    suspended_state: Mapping[str, Any],
) -> dict[str, Any]:
    steps = [
        ("detection", "match simulated alert evaluation and record alert_fired readback"),
        ("triage", "classify source/provider/outreach/payment/delivery/backup/rollback failure family"),
        ("suspend", "hold affected capability and require manual owner action"),
        ("rollback_dry_run", "review rollback dry-run evidence before any future rollback window"),
        ("restore_dry_run", "review restore dry-run evidence before any future destructive restore window"),
        ("manual_owner_action", "record owner decision, approval, and audit refs"),
        ("resume_readiness", "verify manual resume prerequisites without live dispatch"),
        ("post_incident_audit", "replay repository record and audit refs"),
    ]
    return {
        "runbook_id": "PTL-I100-121C-INCIDENT-RUNBOOK",
        "runbook_state": PRODUCTION_READINESS_READY,
        "manual_owner_action_required": True,
        "manual_resume_required": True,
        "incident_automation_enabled": False,
        "external_paging_enabled": False,
        "notification_enabled": False,
        "live_dispatch_enabled": False,
        "runbook_steps": [
            {
                "step_id": step_id,
                "step_summary": summary,
                "owner_role": "governance_owner" if "dry_run" in step_id else "incident_owner",
                "evidence_refs": [
                    f"incident_runbook:{step_id}",
                    str(backup_drill.get("drill_id")),
                    str(rollback_drill.get("drill_id")),
                ],
                "approval_required": True,
                "audit_required": True,
                "automation_enabled": False,
            }
            for step_id, summary in steps
        ],
        "suspended_state_ref": suspended_state.get("suspension_id"),
        "resume_readiness_state": suspended_state.get("resume_readiness_state"),
        "audit_refs": [
            *list(backup_drill.get("audit_refs", [])),
            *list(rollback_drill.get("audit_refs", [])),
            *list(suspended_state.get("audit_refs", [])),
        ],
    }


def _build_backup_restore_drill_evidence(backup_restore: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "drill_id": "PTL-I100-121C-BACKUP-RESTORE-DRY-RUN",
        "drill_mode": "DRY_RUN_ONLY",
        "drill_state": PRODUCTION_READINESS_READY,
        "backup_manifest_enabled": bool(backup_restore.get("backup_manifest_enabled", False)),
        "manifest_hash_enabled": bool(backup_restore.get("manifest_hash_enabled", False)),
        "restore_dry_run_enabled": bool(backup_restore.get("restore_dry_run_enabled", False)),
        "safe_to_restore": False,
        "destructive_restore_enabled": False,
        "restore_execution_enabled": False,
        "rollback_execution_enabled": False,
        "active_storage_mutation_enabled": False,
        "current_active_storage_mutation_enabled": False,
        "active_storage_write_enabled": False,
        "external_backup_service_enabled": False,
        "external_service_connection_enabled": False,
        "migration_execution_enabled": False,
        "approval_required": True,
        "audit_required": True,
        "evidence_refs": [
            "storage.backup_restore.build_backup_manifest",
            "storage.backup_restore.build_restore_dry_run",
            "platform_infra_readiness.backup_restore_readiness",
        ],
        "audit_refs": ["backup_restore_dry_run_audit_ref"],
    }


def _build_rollback_drill_evidence(rollback: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "drill_id": "PTL-I100-121C-ROLLBACK-DRY-RUN",
        "drill_mode": "DRY_RUN_ONLY",
        "drill_state": PRODUCTION_READINESS_READY,
        "rollback_point": rollback.get("rollback_point", "BACKUP_MANIFEST_REQUIRED"),
        "rollback_state": rollback.get("rollback_state", "REVIEW_REQUIRED"),
        "safe_to_restore": False,
        "destructive_restore_enabled": False,
        "restore_execution_enabled": False,
        "rollback_execution_enabled": False,
        "active_storage_mutation_enabled": False,
        "current_active_storage_mutation_enabled": False,
        "active_storage_write_enabled": False,
        "external_service_connection_enabled": False,
        "migration_execution_enabled": False,
        "approval_required": True,
        "audit_required": True,
        "evidence_refs": [
            "storage.backup_restore.build_rollback_readiness",
            "platform_infra_readiness.rollback_readiness",
        ],
        "audit_refs": ["rollback_dry_run_audit_ref"],
    }


def _build_suspended_state_operation_readback(
    *,
    alert_evaluations: list[Mapping[str, Any]],
    provider_adapter_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    fired_evaluations = [
        dict(evaluation)
        for evaluation in alert_evaluations
        if bool(evaluation.get("alert_fired", False))
    ]
    affected = sorted(
        {
            family
            for evaluation in fired_evaluations
            for family in list(evaluation.get("failure_families", []))
        }
    )
    return {
        "suspension_id": "PTL-I100-121C-SUSPENDED-STATE-READBACK",
        "suspension_state": "SUSPENDED",
        "suspension_reason": "simulated_source_provider_outreach_payment_delivery_backup_rollback_failure",
        "affected_capability": affected,
        "owner_action_required": True,
        "owner_action_refs": [
            "incident_owner_ack_required",
            "governance_owner_resume_review_required",
        ],
        "manual_resume_required": True,
        "resume_readiness_state": "MANUAL_REVIEW_REQUIRED",
        "fail_closed": True,
        "no_broad_fallback": True,
        "replayable_readback": True,
        "provider_adapter_suspended": bool(
            provider_adapter_readiness.get("provider_adapter_suspended", False)
        ),
        "provider_circuit_breaker_state": provider_adapter_readiness.get(
            "provider_circuit_breaker_state"
        ),
        "live_execution_enabled": False,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "real_sales_outreach_enabled": False,
        "real_payment_enabled": False,
        "real_delivery_enabled": False,
        "real_refund_enabled": False,
        "automated_refund_enabled": False,
        "audit_refs": [
            "suspended_state_operation_readback_audit_ref",
            *[
                f"alert_evaluation:{evaluation.get('evaluation_id')}"
                for evaluation in fired_evaluations
            ],
        ],
    }


def _build_source_refs(
    *,
    monitoring: Mapping[str, Any],
    backup_restore: Mapping[str, Any],
    rollback: Mapping[str, Any],
    provider: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "monitoring_alerting_readiness_id": monitoring.get("readiness_id"),
        "monitoring_alert_rule_ids": [
            str(rule.get("alert_rule_id"))
            for rule in _list_of_mappings(monitoring.get("alert_rule_catalog"))
            if rule.get("alert_rule_id") not in (None, "")
        ],
        "backup_restore_readiness_ref": "platform_infra_readiness.backup_restore_readiness"
        if backup_restore
        else "",
        "rollback_readiness_ref": "platform_infra_readiness.rollback_readiness"
        if rollback
        else "",
        "provider_adapter_readiness_ref": "provider_adapter_readiness_summary"
        if provider
        else "",
        "stage8_outreach_execution_outbox_ref": "stage8.outreach_execution_outbox_snapshot",
        "stage9_payment_delivery_live_pilot_ref": "stage9.payment_delivery_live_pilot",
        "api_bootstrap_ref": "api.main.create_app.transport_bootstrap",
        "repository_replay_ref": "storage.repositories.production_slo_incident_repo.ProductionSloIncidentRepository.replay",
    }


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _live_controlled_opening_requirement_violations(value: Any, *, path: str = "$") -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _LIVE_OR_DESTRUCTIVE_FIELDS and bool(child):
                violations.append({"path": child_path, "field": str(key)})
            violations.extend(_live_controlled_opening_requirement_violations(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_live_controlled_opening_requirement_violations(child, path=f"{path}[{index}]"))
    return violations


__all__ = [
    "APPROVED_PRODUCTION_LIVE_DEPENDENCY_DRILL_KEY",
    "PRODUCTION_READINESS_FAIL_CLOSED",
    "PRODUCTION_READINESS_MISSING",
    "PRODUCTION_READINESS_READY",
    "PRODUCTION_SLO_INCIDENT_READINESS_OBJECT_TYPE",
    "PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID",
    "build_production_slo_incident_readiness",
    "evaluate_production_alert_rules",
    "production_slo_incident_readback_failure",
    "production_slo_incident_controlled_opening_requirements",
    "validate_production_slo_incident_readiness",
]
