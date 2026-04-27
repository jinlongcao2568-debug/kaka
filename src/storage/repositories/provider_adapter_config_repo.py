from __future__ import annotations

from typing import Any, Mapping

from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_CONFIG_OBJECT_TYPE,
    PROVIDER_ADAPTER_CONFIG_RECORD_ID,
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
)
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


class ProviderAdapterConfigRepository:
    object_type = PROVIDER_ADAPTER_CONFIG_OBJECT_TYPE
    record_id = PROVIDER_ADAPTER_CONFIG_RECORD_ID

    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def save(self, payload: Mapping[str, Any]) -> PersistedRecord:
        payload_dict = dict(payload)
        readiness_summary = payload_dict.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY)
        if isinstance(readiness_summary, Mapping):
            payload_dict = dict(readiness_summary)
        return self.session.upsert_record(
            PersistedRecord(
                object_type=self.object_type,
                record_id=self.record_id,
                stage_scope=0,
                project_id=None,
                object_refs={},
                decision_states={},
                trace_refs={"config_source_ref": str(payload_dict.get("config_source_ref", ""))},
                audit_refs={},
                governed_state={
                    "mode": payload_dict.get("mode"),
                    "config_source": payload_dict.get("config_source"),
                    "readback_only": bool(payload_dict.get("readback_only", True)),
                    "provider_reliability_state": payload_dict.get("provider_reliability_state"),
                    "provider_circuit_breaker_state": payload_dict.get("provider_circuit_breaker_state"),
                    "provider_adapter_suspended": bool(payload_dict.get("provider_adapter_suspended", False)),
                    "provider_status_replayable": bool(payload_dict.get("provider_status_replayable", True)),
                    "provider_binding_mode": payload_dict.get("provider_binding_mode"),
                    "provider_binding_summary": dict(payload_dict.get("provider_binding_summary", {})),
                    "live_execution_enabled": False,
                    "provider_call_enabled": False,
                    "real_provider_call_enabled": False,
                    "automated_refund_enabled": False,
                },
                writeback_state={},
                payload=payload_dict,
                persisted_at=build_persisted_at(),
            )
        )

    def get_active(self) -> PersistedRecord | None:
        return self.session.get_record(self.object_type, self.record_id)

    def get_active_payload(self) -> dict[str, Any] | None:
        record = self.get_active()
        if record is None:
            return None
        return record.as_payload()


__all__ = ["ProviderAdapterConfigRepository"]
