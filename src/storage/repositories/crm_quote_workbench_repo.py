from __future__ import annotations

from typing import Any, Mapping

from stage7_sales.crm_quote_workbench import CRM_QUOTE_WORKBENCH_OBJECT_TYPE
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


class CRMQuoteWorkbenchRepository:
    object_type = CRM_QUOTE_WORKBENCH_OBJECT_TYPE
    id_field = "crm_action_id"

    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def get_by_id(self, record_id: str) -> PersistedRecord | None:
        return self.session.get_record(self.object_type, record_id)

    def find_one_by_field(self, field_name: str, value: str) -> PersistedRecord | None:
        rows = self.session.find_records(self.object_type, **{field_name: value})
        return rows[0] if rows else None

    def get_by_quote_draft_id(self, quote_draft_id: str) -> PersistedRecord | None:
        return self.find_one_by_field("quote_draft_id", quote_draft_id)

    def get_by_provider_execution_id(self, provider_execution_id: str) -> PersistedRecord | None:
        return self.find_one_by_field("provider_execution_id", provider_execution_id)

    def save(self, payload: Mapping[str, Any]) -> PersistedRecord:
        payload_dict = dict(payload)
        record_id = str(payload_dict[self.id_field])
        project_id = self._coerce_optional(payload_dict.get("project_id"))
        return self.session.upsert_record(
            PersistedRecord(
                object_type=self.object_type,
                record_id=record_id,
                stage_scope=7,
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

    def _collect_object_refs(self, payload: Mapping[str, Any]) -> dict[str, str]:
        refs: dict[str, str] = {}
        for key, value in payload.items():
            if key == self.id_field:
                continue
            if key.endswith("_id") or key.endswith("_id_optional"):
                if value not in (None, "", "UNKNOWN"):
                    refs[key] = str(value)
        quote_draft = payload.get("quote_draft")
        if isinstance(quote_draft, Mapping):
            for key, value in quote_draft.items():
                if key.endswith("_id") or key.endswith("_id_optional"):
                    if value not in (None, "", "UNKNOWN"):
                        refs[key] = str(value)
        for nested_key in (
            "quote_sandbox_record",
            "quote_send_record",
            "deal_tracking_record",
            "sales_followup_record",
            "sales_note_record",
            "sales_callback_record",
            "sandbox_adapter_execution",
            "provider_result_readback",
            "approved_crm_quote_execution_summary",
        ):
            nested = payload.get(nested_key)
            if isinstance(nested, Mapping):
                for key, value in nested.items():
                    if key.endswith("_id") or key.endswith("_id_optional"):
                        if value not in (None, "", "UNKNOWN"):
                            refs[key] = str(value)
        crm_records = payload.get("crm_sandbox_sync_records")
        if isinstance(crm_records, Mapping):
            for target, record in crm_records.items():
                if not isinstance(record, Mapping):
                    continue
                record_id = record.get("sandbox_sync_record_id")
                if record_id not in (None, "", "UNKNOWN"):
                    refs[f"crm_{target}_sandbox_sync_record_id"] = str(record_id)
        return refs

    def _collect_named_values(self, payload: Mapping[str, Any], *, include_token: str) -> dict[str, str]:
        refs: dict[str, str] = {}
        for key, value in payload.items():
            if include_token in key.lower() and value not in (None, "", "UNKNOWN"):
                refs[key] = str(value)
        for nested_key in ("vendor_adapter_state", "audit_readiness_summary", "readiness_summary"):
            nested = payload.get(nested_key)
            if isinstance(nested, Mapping):
                for key, value in nested.items():
                    if include_token in key.lower() and value not in (None, "", "UNKNOWN"):
                        refs[key] = str(value)
        return refs

    def _collect_governed_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "governed_execution_mode": payload.get("governed_execution_mode"),
            "owner_action_state": payload.get("owner_action_state"),
            "approval_state": payload.get("approval_state"),
            "audit_state": payload.get("audit_state"),
            "quote_surface_state": payload.get("quote_surface_state"),
            "dry_run_state": payload.get("dry_run_state"),
            "live_execution_enabled": bool(payload.get("live_execution_enabled", False)),
            "external_quote_sent": bool(payload.get("external_quote_sent", False)),
            "real_external_quote_sent": bool(payload.get("real_external_quote_sent", False)),
            "provider_execution_id": payload.get("provider_execution_id"),
            "execution_request_state": payload.get("execution_request_state"),
            "provider_execution_state": payload.get("provider_execution_state"),
            "approved_crm_quote_execution_enabled": bool(
                payload.get("approved_crm_quote_execution_enabled", False)
            ),
            "controlled_provider_adapter_scope": payload.get("controlled_provider_adapter_scope"),
            "controlled_provider_execution_executed": bool(
                payload.get("controlled_provider_execution_executed", False)
            ),
            "blocked_reasons": list(payload.get("blocked_reasons", [])),
            "suspension_reasons": list(payload.get("suspension_reasons", [])),
            "readiness_summary": dict(payload.get("readiness_summary", {})),
            "sandbox_adapter_execution": dict(payload.get("sandbox_adapter_execution", {})),
            "provider_config_ref": dict(payload.get("provider_config_ref", {})),
            "provider_result_readback": dict(payload.get("provider_result_readback", {})),
            "approved_crm_quote_execution_summary": dict(
                payload.get("approved_crm_quote_execution_summary", {})
            ),
            "deal_tracking_timeline": list(payload.get("deal_tracking_timeline", [])),
            "replay_state": dict(payload.get("replay_state", {})),
            "quote_send_record": dict(payload.get("quote_send_record", {})),
            "quote_sandbox_record": dict(payload.get("quote_sandbox_record", {})),
            "deal_tracking_record": dict(payload.get("deal_tracking_record", {})),
            "sales_followup_record": dict(payload.get("sales_followup_record", {})),
            "sales_note_record": dict(payload.get("sales_note_record", {})),
            "sales_callback_record": dict(payload.get("sales_callback_record", {})),
        }

    def _coerce_optional(self, value: Any) -> str | None:
        if value in (None, "", "UNKNOWN"):
            return None
        return str(value)


__all__ = ["CRMQuoteWorkbenchRepository"]
