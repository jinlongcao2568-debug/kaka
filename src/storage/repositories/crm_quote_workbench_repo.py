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
            "real_external_quote_sent": bool(payload.get("real_external_quote_sent", False)),
            "blocked_reasons": list(payload.get("blocked_reasons", [])),
            "readiness_summary": dict(payload.get("readiness_summary", {})),
        }

    def _coerce_optional(self, value: Any) -> str | None:
        if value in (None, "", "UNKNOWN"):
            return None
        return str(value)


__all__ = ["CRMQuoteWorkbenchRepository"]
