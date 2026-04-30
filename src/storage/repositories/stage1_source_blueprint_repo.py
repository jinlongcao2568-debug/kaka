from __future__ import annotations

from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord


SOURCE_BLUEPRINT_OBJECT_TYPE = "stage1_source_blueprint_plan"


class Stage1SourceBlueprintRepository:
    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def save(self, plan: Mapping[str, Any]) -> PersistedRecord:
        payload = dict(plan)
        plan_id = str(payload["source_blueprint_plan_id"])
        opportunity = dict(payload.get("opportunity_candidate") or {})
        stage2_plan = dict(payload.get("stage2_capture_plan") or {})
        audit_refs = {
            key: str(value)
            for key, value in dict(payload.get("audit_refs", {})).items()
            if value not in (None, "")
        }
        object_refs = {
            "source_blueprint_plan_id": plan_id,
            "scan_run_id": str(payload.get("scan_run_id", "")),
            "opportunity_candidate_id": str(opportunity.get("opportunity_candidate_id", "")),
            "project_id": str(opportunity.get("project_id", "")),
            "capture_plan_id": str(stage2_plan.get("capture_plan_id", "")),
        }
        selected_registry_ids = [
            str(step.get("source_registry_id"))
            for step in stage2_plan.get("capture_steps", [])
            if step.get("source_registry_id")
        ]
        if selected_registry_ids:
            object_refs["selected_source_registry_ids"] = ",".join(selected_registry_ids)
        return self.session.upsert_record(
            PersistedRecord(
                object_type=SOURCE_BLUEPRINT_OBJECT_TYPE,
                record_id=plan_id,
                stage_scope=1,
                project_id=object_refs.get("project_id") or None,
                object_refs={key: value for key, value in object_refs.items() if value},
                decision_states={
                    "capability_state": str(payload.get("capability_state", "INTERNAL_READY")),
                    "plan_state": str(payload.get("plan_state", "")),
                    "next_action": str(payload.get("next_action", "")),
                },
                trace_refs={
                    "source_blueprint_orchestrator_id": str(
                        payload.get("source_blueprint_orchestrator_id", "")
                    ),
                    "capture_plan_id": str(stage2_plan.get("capture_plan_id", "")),
                },
                audit_refs=audit_refs,
                governed_state={
                    "internal_only": bool(payload.get("internal_only", True)),
                    "customer_visible": bool(payload.get("customer_visible", False)),
                    "stage2_fetch_executed": bool(payload.get("stage2_fetch_executed", False)),
                    "real_external_fetch_enabled": bool(payload.get("real_external_fetch_enabled", False)),
                    "capture_execution_enabled": bool(payload.get("capture_execution_enabled", False)),
                    "unapproved_source_selected": bool(
                        dict(payload.get("source_approval_summary") or {}).get(
                            "unapproved_source_selected", False
                        )
                    ),
                    "city_adapter_triggered_by_gap": bool(
                        dict(payload.get("coverage_gap_policy") or {}).get(
                            "city_adapter_triggered", False
                        )
                    ),
                    "beijing_first_batch_commercial_pilot": bool(
                        dict(payload.get("commercial_pilot_policy") or {}).get(
                            "beijing_first_batch_commercial_pilot", False
                        )
                    ),
                },
                writeback_state={},
                payload=payload,
                persisted_at=utc_now_iso(),
            )
        )

    def get(self, plan_id: str) -> PersistedRecord | None:
        return self.session.get_record(SOURCE_BLUEPRINT_OBJECT_TYPE, plan_id)

    def list(self) -> list[PersistedRecord]:
        return self.session.list_records(SOURCE_BLUEPRINT_OBJECT_TYPE)

    def readback(self, plan_id: str) -> dict[str, Any]:
        record = self._require(plan_id)
        payload = dict(record.payload)
        return {
            "readback_state": "READBACK_READY",
            "repository_backed": True,
            "replayable": True,
            "source_blueprint_plan_id": plan_id,
            "source_blueprint_plan": payload,
            "source_mix": list(payload.get("source_mix", [])),
            "stage2_capture_plan": dict(payload.get("stage2_capture_plan", {})),
            "readback_summary": dict(payload.get("readback_summary", {})),
            "governed_state": dict(record.governed_state),
            "audit_refs": dict(record.audit_refs),
        }

    def replay(self, plan_id: str) -> dict[str, Any]:
        readback = self.readback(plan_id)
        return {
            "replay_state": "REPLAY_READY",
            "source_blueprint_plan_id": plan_id,
            "source_blueprint_readback": readback,
            "stage2_fetch_executed": False,
            "real_external_fetch_executed": False,
            "customer_visible_claim_generated": False,
        }

    def _require(self, plan_id: str) -> PersistedRecord:
        record = self.get(plan_id)
        if record is None:
            raise ValueError(f"source blueprint plan {plan_id!r} not found")
        return record


__all__ = ["SOURCE_BLUEPRINT_OBJECT_TYPE", "Stage1SourceBlueprintRepository"]
