from __future__ import annotations

from typing import Any, Mapping

from shared.settings import Settings
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.monitoring_alerting import (
    MONITORING_ALERTING_READINESS_OBJECT_TYPE,
    MONITORING_ALERTING_READINESS_RECORD_ID,
    build_monitoring_alerting_readiness,
    monitoring_alerting_readback_failure,
    validate_monitoring_alerting_readiness,
)


class MonitoringAlertingRepository:
    object_type = MONITORING_ALERTING_READINESS_OBJECT_TYPE
    default_record_id = MONITORING_ALERTING_READINESS_RECORD_ID

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
        return build_monitoring_alerting_readiness(
            platform_infra_readiness=platform_readiness,
            provider_adapter_readiness=self.settings.provider_adapter_readiness_summary(),
        )

    def save_current(self) -> PersistedRecord:
        return self.save(self.build_current_payload())

    def save(self, payload: Mapping[str, Any]) -> PersistedRecord:
        payload_dict = dict(payload)
        validation = validate_monitoring_alerting_readiness(payload_dict)
        if validation["live_controlled_opening_boundary_violations"]:
            raise ValueError("monitoring alerting readiness live dispatch flags must remain false")
        payload_dict["validation"] = validation
        readiness_id = str(payload_dict.get("readiness_id") or self.default_record_id)
        monitoring_readiness = dict(payload_dict.get("monitoring_readiness", {}))
        alert_readiness = dict(payload_dict.get("alert_readiness", {}))
        incident_readiness = dict(payload_dict.get("incident_readiness", {}))
        component_ids = [
            str(component.get("component_id"))
            for component in payload_dict.get("monitoring_components", [])
            if isinstance(component, Mapping) and component.get("component_id") not in (None, "")
        ]
        alert_rule_ids = [
            str(rule.get("alert_rule_id"))
            for rule in payload_dict.get("alert_rule_catalog", [])
            if isinstance(rule, Mapping) and rule.get("alert_rule_id") not in (None, "")
        ]
        return self.session.upsert_record(
            PersistedRecord(
                object_type=self.object_type,
                record_id=readiness_id,
                stage_scope=0,
                project_id=None,
                object_refs={
                    "readiness_id": readiness_id,
                    "component_ids": ",".join(component_ids),
                    "alert_rule_ids": ",".join(alert_rule_ids),
                },
                decision_states={
                    "monitoring_readiness_state": str(monitoring_readiness.get("readiness_state", "")),
                    "monitoring_health_state": str(monitoring_readiness.get("health_state", "")),
                    "alert_readiness_state": str(alert_readiness.get("readiness_state", "")),
                    "incident_state": str(incident_readiness.get("incident_state", "")),
                    "readback_state": str(validation["readback_state"]),
                },
                trace_refs={
                    "source": "storage.monitoring_alerting",
                    "task_packet": "PTL-I100-112F-monitoring-alerting-readiness",
                },
                audit_refs={
                    "audit_required": str(alert_readiness.get("audit_required", True)),
                    "approval_required": str(alert_readiness.get("approval_required", True)),
                },
                governed_state={
                    "readback_only": True,
                    "replayable_readback": bool(payload_dict.get("replayable_readback", True)),
                    "notification_enabled": False,
                    "live_dispatch_enabled": False,
                    "incident_automation_enabled": False,
                    "external_paging_enabled": False,
                    "fail_closed": bool(validation["fail_closed"]),
                },
                writeback_state={
                    "alert_dispatch_state": "DISABLED_READBACK_ONLY",
                    "incident_automation_state": "DISABLED_MANUAL_OWNER_ACTION_REQUIRED",
                },
                payload=payload_dict,
                persisted_at=build_persisted_at(),
            )
        )

    def get(self, readiness_id: str = MONITORING_ALERTING_READINESS_RECORD_ID) -> PersistedRecord | None:
        return self.session.get_record(self.object_type, readiness_id)

    def readback(self, readiness_id: str = MONITORING_ALERTING_READINESS_RECORD_ID) -> dict[str, Any]:
        record = self.get(readiness_id)
        if record is None:
            return monitoring_alerting_readback_failure(readiness_id)
        validation = validate_monitoring_alerting_readiness(record.payload)
        return {
            "readiness_id": readiness_id,
            "payload_present": True,
            "readback_state": validation["readback_state"],
            "validation": validation,
            "persisted_at": record.persisted_at,
            "monitoring_readiness": dict(record.payload.get("monitoring_readiness", {})),
            "monitoring_components": list(record.payload.get("monitoring_components", [])),
            "alert_readiness": dict(record.payload.get("alert_readiness", {})),
            "alert_rule_catalog": list(record.payload.get("alert_rule_catalog", [])),
            "incident_readiness": dict(record.payload.get("incident_readiness", {})),
            "controlled_opening_boundaries": dict(record.payload.get("controlled_opening_boundaries", {})),
            "replayable_readback": bool(record.payload.get("replayable_readback", True)),
            "notification_enabled": False,
            "live_dispatch_enabled": False,
            "incident_automation_enabled": False,
            "external_paging_enabled": False,
            "no_broad_fallback": True,
            "fail_closed": bool(validation["fail_closed"]),
        }

    def replay(self, readiness_id: str = MONITORING_ALERTING_READINESS_RECORD_ID) -> dict[str, Any]:
        readback = self.readback(readiness_id)
        if not readback.get("payload_present", False):
            return readback
        validation = dict(readback["validation"])
        return {
            **readback,
            "replay_state": validation["readback_state"],
            "replayable": bool(readback.get("replayable_readback", False)) and not validation["fail_closed"],
            "fail_closed": bool(validation["fail_closed"]),
            "no_broad_fallback": True,
        }


__all__ = ["MonitoringAlertingRepository"]
