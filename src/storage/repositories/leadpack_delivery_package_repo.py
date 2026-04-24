from __future__ import annotations

from typing import Any, Mapping

from stage7_sales.leadpack_delivery_package import LEADPACK_DELIVERY_PACKAGE_OBJECT_TYPE
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at


class LeadpackDeliveryPackageRepository:
    object_type = LEADPACK_DELIVERY_PACKAGE_OBJECT_TYPE
    id_field = "package_id"

    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def get_by_id(self, record_id: str) -> PersistedRecord | None:
        return self.session.get_record(self.object_type, record_id)

    def find_one_by_field(self, field_name: str, value: str) -> PersistedRecord | None:
        rows = self.session.find_records(self.object_type, **{field_name: value})
        return rows[0] if rows else None

    def get_by_evidence_pack_id(self, evidence_pack_id: str) -> PersistedRecord | None:
        return self.find_one_by_field("evidence_pack_id", evidence_pack_id)

    def get_by_page_draft_id(self, page_draft_id: str) -> PersistedRecord | None:
        return self.find_one_by_field("page_draft_id", page_draft_id)

    def get_by_artifact_manifest_id(self, artifact_manifest_id: str) -> PersistedRecord | None:
        return self.find_one_by_field("artifact_manifest_id", artifact_manifest_id)

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
        source_object_refs = payload.get("source_object_refs")
        if isinstance(source_object_refs, Mapping):
            for source in source_object_refs.values():
                if not isinstance(source, Mapping):
                    continue
                object_id = source.get("object_id")
                object_type = source.get("object_type")
                if object_id not in (None, "", "UNKNOWN") and object_type:
                    refs[f"{object_type}_id"] = str(object_id)
        return refs

    def _collect_named_values(self, payload: Mapping[str, Any], *, include_token: str) -> dict[str, str]:
        refs: dict[str, str] = {}
        for key, value in payload.items():
            if include_token in key.lower() and value not in (None, "", "UNKNOWN"):
                refs[key] = str(value)
        for nested_key in (
            "package_manifest",
            "evidence_item_manifest",
            "approval_audit_prerequisites",
            "delivery_readiness_summary",
            "readiness_summary",
        ):
            nested = payload.get(nested_key)
            if isinstance(nested, Mapping):
                for key, value in nested.items():
                    if include_token in key.lower() and value not in (None, "", "UNKNOWN"):
                        refs[key] = str(value)
        return refs

    def _collect_governed_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "masking_state": payload.get("masking_state"),
            "approval_state": payload.get("approval_state"),
            "audit_state": payload.get("audit_state"),
            "package_state": payload.get("package_state"),
            "page_state": payload.get("page_state"),
            "delivery_state": payload.get("delivery_state"),
            "customer_visible_enabled": bool(payload.get("customer_visible_enabled", False)),
            "external_delivery_enabled": bool(payload.get("external_delivery_enabled", False)),
            "external_release_enabled": bool(payload.get("external_release_enabled", False)),
            "page_publication_enabled": bool(payload.get("page_publication_enabled", False)),
            "readiness_summary": dict(payload.get("readiness_summary", {})),
        }

    def _coerce_optional(self, value: Any) -> str | None:
        if value in (None, "", "UNKNOWN"):
            return None
        return str(value)


__all__ = ["LeadpackDeliveryPackageRepository"]
