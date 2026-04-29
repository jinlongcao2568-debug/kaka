from __future__ import annotations

from typing import Any, Mapping

from shared.settings import Settings
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.production_slo_incident_readiness import (
    APPROVED_PRODUCTION_LIVE_DEPENDENCY_DRILL_KEY,
    PRODUCTION_SLO_INCIDENT_READINESS_OBJECT_TYPE,
    PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID,
    build_production_slo_incident_readiness,
    production_slo_incident_readback_failure,
    validate_production_slo_incident_readiness,
)


class ProductionSloIncidentRepository:
    object_type = PRODUCTION_SLO_INCIDENT_READINESS_OBJECT_TYPE
    default_record_id = PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID

    def __init__(
        self,
        *,
        session: DatabaseSession | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.session = session or DatabaseSession.default(settings=self.settings)

    def build_current_payload(self) -> dict[str, Any]:
        platform_readiness = self.settings.platform_infra_readiness()
        production_readiness = platform_readiness.get("production_slo_incident_readiness")
        if isinstance(production_readiness, Mapping):
            return dict(production_readiness)
        return build_production_slo_incident_readiness(
            platform_infra_readiness=platform_readiness,
            monitoring_alerting_readiness=dict(
                platform_readiness.get("monitoring_alerting_readiness", {})
            ),
            provider_adapter_readiness=self.settings.provider_adapter_readiness_summary(),
        )

    def save_current(self) -> PersistedRecord:
        return self.save(self.build_current_payload())

    def save(self, payload: Mapping[str, Any]) -> PersistedRecord:
        payload_dict = dict(payload)
        validation = validate_production_slo_incident_readiness(payload_dict)
        if validation["live_controlled_opening_boundary_violations"]:
            raise ValueError(
                "production SLO incident readiness live dispatch, automation, restore, or rollback flags must remain false"
            )
        payload_dict["validation"] = validation
        readiness_id = str(payload_dict.get("readiness_id") or self.default_record_id)
        alert_rule_ids = [
            str(rule.get("alert_rule_id"))
            for rule in payload_dict.get("alert_rule_catalog", [])
            if isinstance(rule, Mapping) and rule.get("alert_rule_id") not in (None, "")
        ]
        incident_runbook = dict(payload_dict.get("incident_runbook_carrier", {}))
        backup_drill = dict(payload_dict.get("backup_restore_drill_evidence", {}))
        rollback_drill = dict(payload_dict.get("rollback_drill_evidence", {}))
        suspended_state = dict(payload_dict.get("suspended_state_operation_readback", {}))
        approved_drill = dict(
            payload_dict.get(APPROVED_PRODUCTION_LIVE_DEPENDENCY_DRILL_KEY, {})
        )

        return self.session.upsert_record(
            PersistedRecord(
                object_type=self.object_type,
                record_id=readiness_id,
                stage_scope=0,
                project_id=None,
                object_refs={
                    "readiness_id": readiness_id,
                    "alert_rule_ids": ",".join(alert_rule_ids),
                    "incident_runbook_id": str(incident_runbook.get("runbook_id", "")),
                    "backup_restore_drill_id": str(backup_drill.get("drill_id", "")),
                    "rollback_drill_id": str(rollback_drill.get("drill_id", "")),
                    "suspension_id": str(suspended_state.get("suspension_id", "")),
                    "approved_dependency_drill_id": str(approved_drill.get("drill_id", "")),
                },
                decision_states={
                    "target_capability_state": str(
                        payload_dict.get("target_capability_state", "")
                    ),
                    "readiness_state": str(payload_dict.get("readiness_state", "")),
                    "readback_state": str(validation["readback_state"]),
                    "incident_runbook_state": str(incident_runbook.get("runbook_state", "")),
                    "suspension_state": str(suspended_state.get("suspension_state", "")),
                    "approved_dependency_drill_state": str(
                        approved_drill.get("controlled_drill_state", "")
                    ),
                },
                trace_refs={
                    "source": "storage.production_slo_incident_readiness",
                    "task_packet": "PTL-I100-121C-production-slo-monitoring-incident-readiness",
                },
                audit_refs={
                    "audit_required": "True",
                    "approval_required": "True",
                    "backup_restore_drill_id": str(backup_drill.get("drill_id", "")),
                    "rollback_drill_id": str(rollback_drill.get("drill_id", "")),
                },
                governed_state={
                    "readback_only": True,
                    "repository_backed_readback": True,
                    "replayable_readback": bool(payload_dict.get("replayable_readback", True)),
                    "notification_enabled": False,
                    "live_dispatch_enabled": False,
                    "real_alert_dispatch_enabled": False,
                    "external_paging_enabled": False,
                    "external_apm_enabled": False,
                    "incident_automation_enabled": False,
                    "destructive_restore_enabled": False,
                    "restore_execution_enabled": False,
                    "rollback_execution_enabled": False,
                    "active_storage_mutation_enabled": False,
                    "external_release_enabled": False,
                    "approved_production_live_dependency_drill_enabled": bool(
                        approved_drill.get(
                            "approved_production_live_dependency_drill_enabled", False
                        )
                    ),
                    "approved_production_live_dependency_drill_summary": {
                        "drill_id": approved_drill.get("drill_id"),
                        "controlled_drill_state": approved_drill.get("controlled_drill_state"),
                        "controlled_execution_scope": approved_drill.get(
                            "controlled_execution_scope"
                        ),
                        "container_execution_enabled": False,
                        "real_alert_dispatch_enabled": False,
                        "destructive_restore_enabled": False,
                        "rollback_execution_enabled": False,
                        "incident_automation_enabled": False,
                        "external_release_enabled": False,
                    },
                    "fail_closed": bool(validation["fail_closed"]),
                },
                writeback_state={
                    "alert_dispatch_state": "DISABLED_READBACK_ONLY",
                    "incident_automation_state": "DISABLED_MANUAL_OWNER_ACTION_REQUIRED",
                    "restore_execution_state": "DISABLED_DRY_RUN_ONLY",
                    "rollback_execution_state": "DISABLED_DRY_RUN_ONLY",
                    "resume_state": "MANUAL_REVIEW_REQUIRED",
                    "approved_dependency_drill_state": str(
                        approved_drill.get("controlled_drill_state", "NOT_REQUESTED")
                    ),
                },
                payload=payload_dict,
                persisted_at=build_persisted_at(),
            )
        )

    def get(
        self,
        readiness_id: str = PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID,
    ) -> PersistedRecord | None:
        return self.session.get_record(self.object_type, readiness_id)

    def readback(
        self,
        readiness_id: str = PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID,
    ) -> dict[str, Any]:
        record = self.get(readiness_id)
        if record is None:
            return production_slo_incident_readback_failure(readiness_id)
        validation = validate_production_slo_incident_readiness(record.payload)
        payload = record.payload
        return {
            "readiness_id": readiness_id,
            "payload_present": True,
            "target_capability_state": payload.get("target_capability_state"),
            "readiness_state": payload.get("readiness_state"),
            "readback_state": validation["readback_state"],
            "validation": validation,
            "persisted_at": record.persisted_at,
            "source_refs": dict(payload.get("source_refs", {})),
            "slo_readiness_carrier": dict(payload.get("slo_readiness_carrier", {})),
            "monitoring_dashboard_readback": dict(
                payload.get("monitoring_dashboard_readback", {})
            ),
            "alert_rule_catalog": list(payload.get("alert_rule_catalog", [])),
            "simulated_alert_evaluation_readback": list(
                payload.get("simulated_alert_evaluation_readback", [])
            ),
            "incident_runbook_carrier": dict(payload.get("incident_runbook_carrier", {})),
            "backup_restore_drill_evidence": dict(
                payload.get("backup_restore_drill_evidence", {})
            ),
            "rollback_drill_evidence": dict(payload.get("rollback_drill_evidence", {})),
            "suspended_state_operation_readback": dict(
                payload.get("suspended_state_operation_readback", {})
            ),
            APPROVED_PRODUCTION_LIVE_DEPENDENCY_DRILL_KEY: dict(
                payload.get(APPROVED_PRODUCTION_LIVE_DEPENDENCY_DRILL_KEY, {})
            ),
            "controlled_opening_boundaries": dict(payload.get("controlled_opening_boundaries", {})),
            "replayable_readback": bool(payload.get("replayable_readback", True)),
            "notification_enabled": False,
            "live_dispatch_enabled": False,
            "real_alert_dispatch_enabled": False,
            "external_paging_enabled": False,
            "external_apm_enabled": False,
            "incident_automation_enabled": False,
            "destructive_restore_enabled": False,
            "restore_execution_enabled": False,
            "rollback_execution_enabled": False,
            "active_storage_mutation_enabled": False,
            "no_broad_fallback": True,
            "fail_closed": bool(validation["fail_closed"]),
        }

    def replay(
        self,
        readiness_id: str = PRODUCTION_SLO_INCIDENT_READINESS_RECORD_ID,
    ) -> dict[str, Any]:
        readback = self.readback(readiness_id)
        if not readback.get("payload_present", False):
            return readback
        validation = dict(readback["validation"])
        return {
            **readback,
            "replay_state": validation["readback_state"],
            "replayable": bool(readback.get("replayable_readback", False))
            and not validation["fail_closed"],
            "fail_closed": bool(validation["fail_closed"]),
            "no_broad_fallback": True,
        }


__all__ = ["ProductionSloIncidentRepository"]
