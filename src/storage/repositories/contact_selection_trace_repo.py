from __future__ import annotations

from typing import Any, Mapping

from storage.db import PersistedRecord, build_persisted_at
from storage.repositories._base import ContractRepository


class ContactSelectionTraceRepository(ContractRepository):
    object_type = "contact_selection_trace"
    id_field = "contact_selection_trace_id"

    def save(self, payload: Mapping[str, Any]) -> PersistedRecord:
        payload_dict = dict(payload)
        self.store.validate_record(self.object_type, payload_dict)
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


__all__ = ["ContactSelectionTraceRepository"]
