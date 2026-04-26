from __future__ import annotations

from typing import Any, Mapping

from stage8_outreach.execution_outbox import OUTBOX_OBJECT_TYPE
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


class OutreachExecutionOutboxRepository:
    object_type = OUTBOX_OBJECT_TYPE
    id_field = "outbox_id"

    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def get_by_id(self, record_id: str) -> PersistedRecord | None:
        return self.session.get_record(self.object_type, record_id)

    def save(self, payload: Mapping[str, Any]) -> PersistedRecord:
        payload_dict = dict(payload)
        record_id = str(payload_dict[self.id_field])
        project_id = self._coerce_optional(payload_dict.get("project_id"))
        return self.session.upsert_record(
            PersistedRecord(
                object_type=self.object_type,
                record_id=record_id,
                stage_scope=8,
                project_id=project_id,
                object_refs=self._collect_object_refs(payload_dict),
                decision_states={},
                trace_refs=self._collect_named_values(payload_dict, include_token="trace"),
                audit_refs=self._collect_named_values(payload_dict, include_token="audit"),
                governed_state=self._collect_governed_state(payload_dict),
                writeback_state={},
                payload=payload_dict,
                persisted_at=build_persisted_at(),
            )
        )

    def find_one_by_field(self, field_name: str, value: str) -> PersistedRecord | None:
        rows = self.session.find_records(self.object_type, **{field_name: value})
        return rows[0] if rows else None

    def _collect_object_refs(self, payload: Mapping[str, Any]) -> dict[str, str]:
        refs: dict[str, str] = {}
        for key, value in payload.items():
            if key == self.id_field:
                continue
            if key.endswith("_id") or key.endswith("_id_optional"):
                if value not in (None, "", "UNKNOWN"):
                    refs[key] = str(value)
        return refs

    def _collect_named_values(self, payload: Mapping[str, Any], *, include_token: str) -> dict[str, str]:
        refs: dict[str, str] = {}
        for key, value in payload.items():
            if include_token in key.lower() and value not in (None, "", "UNKNOWN"):
                refs[key] = str(value)
        vendor_state = payload.get("vendor_adapter_state")
        if isinstance(vendor_state, Mapping):
            for key, value in vendor_state.items():
                if include_token in key.lower() and value not in (None, "", "UNKNOWN"):
                    refs[key] = str(value)
        return refs

    def _collect_governed_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "execution_id": payload.get("execution_id"),
            "governed_execution_mode": payload.get("governed_execution_mode"),
            "adapter_family": payload.get("adapter_family"),
            "pilot_id": payload.get("pilot_id"),
            "pilot_scope": payload.get("pilot_scope"),
            "approved_sample_size": payload.get("approved_sample_size"),
            "requested_sample_size": payload.get("requested_sample_size"),
            "batch_send_enabled": bool(payload.get("batch_send_enabled", False)),
            "provider_family": payload.get("provider_family"),
            "provider_config_ref": dict(payload.get("provider_config_ref", {})),
            "provider_config_state": payload.get("provider_config_state"),
            "provider_adapter_readiness_summary": dict(
                payload.get("provider_adapter_readiness_summary", {})
            ),
            "sandbox_execution_state": payload.get("sandbox_execution_state"),
            "sandbox_pass_state": payload.get("sandbox_pass_state"),
            "approval_state": payload.get("approval_state"),
            "audit_state": payload.get("audit_state"),
            "template_approval_state": payload.get("template_approval_state"),
            "contact_source_audit_state": payload.get("contact_source_audit_state"),
            "operator_approval_state": payload.get("operator_approval_state"),
            "operator_action_audit_refs": list(payload.get("operator_action_audit_refs", [])),
            "frequency_control_state": payload.get("frequency_control_state"),
            "quiet_hours_state": payload.get("quiet_hours_state"),
            "opt_out_state": payload.get("opt_out_state"),
            "unsubscribe_state": payload.get("unsubscribe_state"),
            "live_pilot_readiness_state": payload.get("live_pilot_readiness_state"),
            "live_execution_requested": bool(payload.get("live_execution_requested", False)),
            "approved_provider_execution_requested": bool(
                payload.get("approved_provider_execution_requested", False)
            ),
            "approved_provider_execution_enabled": bool(
                payload.get("approved_provider_execution_enabled", False)
            ),
            "execution_request_state": payload.get("execution_request_state"),
            "provider_execution_state": payload.get("provider_execution_state"),
            "approved_provider_execution_summary": dict(
                payload.get("approved_provider_execution_summary", {})
            ),
            "bounce_state": payload.get("bounce_state"),
            "failure_state": dict(payload.get("failure_state", {})),
            "complaint_state": payload.get("complaint_state"),
            "bounce_taxonomy": dict(payload.get("bounce_taxonomy", {})),
            "failure_taxonomy": dict(payload.get("failure_taxonomy", {})),
            "failure_threshold_state": dict(payload.get("failure_threshold_state", {})),
            "complaint_taxonomy": dict(payload.get("complaint_taxonomy", {})),
            "provider_result_readback": dict(payload.get("provider_result_readback", {})),
            "retry_state": dict(payload.get("retry_state", {})),
            "stop_state": dict(payload.get("stop_state", {})),
            "suspension_state": dict(payload.get("suspension_state", {})),
            "live_pilot_readiness_summary": dict(payload.get("live_pilot_readiness_summary", {})),
            "live_execution_enabled": bool(payload.get("live_execution_enabled", False)),
            "controlled_provider_adapter_scope": payload.get("controlled_provider_adapter_scope"),
            "controlled_provider_execution_executed": bool(
                payload.get("controlled_provider_execution_executed", False)
            ),
            "real_send_attempted": bool(payload.get("real_send_attempted", False)),
            "external_delivery_enabled": bool(payload.get("external_delivery_enabled", False)),
            "blocked_reasons": list(payload.get("blocked_reasons", [])),
            "execution_timeline": list(payload.get("execution_timeline", [])),
            "replay_state": dict(payload.get("replay_state", {})),
            "outbox_readiness_summary": dict(payload.get("outbox_readiness_summary", {})),
        }

    def _coerce_optional(self, value: Any) -> str | None:
        if value in (None, "", "UNKNOWN"):
            return None
        return str(value)


__all__ = ["OutreachExecutionOutboxRepository"]
