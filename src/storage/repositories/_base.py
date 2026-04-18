from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import ContractStore

from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


PRIMARY_STATUS_FIELDS = {
    "saleable_opportunity": ("saleability_status", "opportunity_grade"),
    "offer_recommendation": ("offer_recommendation_state", "recommended_delivery_form"),
    "buyer_fit": ("buyer_type",),
    "legal_action_actor_profile": ("actionability_state",),
    "procurement_decision_actor_profile": ("reachable_state",),
    "contact_target": ("contact_target_status", "contact_validity_status"),
    "outreach_plan": ("plan_status", "approval_state"),
    "touch_record": ("touch_record_state", "response_status"),
    "order_record": ("order_status", "commercial_status"),
    "payment_record": ("payment_status", "refund_state"),
    "delivery_record": ("delivery_status", "archival_status"),
    "opportunity_outcome_event": ("outcome_family",),
    "governance_feedback_event": ("trigger_type",),
    "project_fact": ("sale_gate_status",),
    "legal_action_recommendation": ("window_status",),
}

STAGE_SCOPE_BY_OBJECT = {
    "project_fact": 6,
    "legal_action_recommendation": 6,
    "legal_action_actor_profile": 7,
    "procurement_decision_actor_profile": 7,
    "buyer_fit": 7,
    "offer_recommendation": 7,
    "saleable_opportunity": 7,
    "contact_target": 8,
    "outreach_plan": 8,
    "touch_record": 8,
    "order_record": 9,
    "payment_record": 9,
    "delivery_record": 9,
    "opportunity_outcome_event": 9,
    "governance_feedback_event": 9,
}

DECISION_FIELDS = (
    "permission_decision_state",
    "governance_decision_state",
    "semantic_decision_state",
    "policy_decision_state",
)

GOVERNED_STATE_FIELDS = (
    "projection_mode",
    "run_mode",
    "governed_execution_mode",
    "approval_state",
    "plan_status",
    "requested_delivery_surface",
)

WRITEBACK_FIELDS = (
    "written_back_at",
    "written_back_at_optional",
    "writeback_targets",
    "writeback_target_optional",
)


class ContractRepository:
    object_type: str = ""
    id_field: str = ""

    def __init__(
        self,
        *,
        session: DatabaseSession | None = None,
        store: ContractStore | None = None,
    ) -> None:
        self.session = session or DatabaseSession.default()
        self.store = store or ContractStore.default()

    def get_by_id(self, record_id: str) -> PersistedRecord | None:
        return self.session.get_record(self.object_type, record_id)

    def save(self, payload: Mapping[str, Any]) -> PersistedRecord:
        payload_dict = dict(payload)
        self.store.validate_record(self.object_type, payload_dict)
        record_id = str(payload_dict[self.id_field])
        project_id = self._coerce_optional(payload_dict.get("project_id"))
        return self.session.upsert_record(
            PersistedRecord(
                object_type=self.object_type,
                record_id=record_id,
                stage_scope=STAGE_SCOPE_BY_OBJECT[self.object_type],
                project_id=project_id,
                object_refs=self._collect_object_refs(payload_dict),
                decision_states=self._collect_values(payload_dict, DECISION_FIELDS),
                trace_refs=self._collect_named_values(payload_dict, include_token="trace"),
                audit_refs=self._collect_named_values(payload_dict, include_token="audit"),
                governed_state=self._collect_governed_state(payload_dict),
                writeback_state=self._collect_values(payload_dict, WRITEBACK_FIELDS),
                payload=payload_dict,
                persisted_at=build_persisted_at(),
            )
        )

    def list_by_project_id(self, project_id: str) -> list[PersistedRecord]:
        return self.session.find_records(self.object_type, project_id=project_id)

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

    def _collect_values(self, payload: Mapping[str, Any], field_names: tuple[str, ...]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field_name in field_names:
            if payload.get(field_name) not in (None, ""):
                values[field_name] = payload[field_name]
        return values

    def _collect_named_values(self, payload: Mapping[str, Any], *, include_token: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, value in payload.items():
            if include_token in key.lower() and value not in (None, "", "UNKNOWN"):
                values[key] = str(value)
        return values

    def _collect_governed_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        state = self._collect_values(payload, GOVERNED_STATE_FIELDS)
        primary_status = self._primary_status(payload)
        if primary_status:
            state["primary_status"] = primary_status
        return state

    def _primary_status(self, payload: Mapping[str, Any]) -> str | None:
        for field_name in PRIMARY_STATUS_FIELDS.get(self.object_type, ()):
            value = payload.get(field_name)
            if value not in (None, ""):
                return str(value)
        return None

    def _coerce_optional(self, value: Any) -> str | None:
        if value in (None, "", "UNKNOWN"):
            return None
        return str(value)


__all__ = ["ContractRepository"]
