from __future__ import annotations

from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord


MARKET_SCAN_OBJECT_TYPE = "stage1_market_scan_run"


class Stage1MarketScanRepository:
    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def save(self, scan: Mapping[str, Any]) -> PersistedRecord:
        payload = dict(scan)
        scan_run_id = str(payload["scan_run_id"])
        audit_refs = {
            key: str(value)
            for key, value in dict(payload.get("audit_refs", {})).items()
            if value not in (None, "")
        }
        object_refs = {
            "scan_run_id": scan_run_id,
            "task_id": str(payload.get("task_id", "")),
            "batch_id": str(payload.get("batch_id", "")),
        }
        selected_ids = [
            str(candidate.get("opportunity_candidate_id"))
            for candidate in payload.get("opportunity_candidates", [])
            if candidate.get("opportunity_candidate_id")
        ]
        if selected_ids:
            object_refs["selected_opportunity_candidate_ids"] = ",".join(selected_ids)
        trace_refs = {
            "run_controller_id": str(dict(payload.get("run_controller", {})).get("run_controller_id", "")),
            "state_machine_id": str(dict(payload.get("stage_state_machine", {})).get("state_machine_id", "")),
        }
        return self.session.upsert_record(
            PersistedRecord(
                object_type=MARKET_SCAN_OBJECT_TYPE,
                record_id=scan_run_id,
                stage_scope=1,
                project_id=None,
                object_refs={key: value for key, value in object_refs.items() if value},
                decision_states={
                    "capability_state": str(payload.get("capability_state", "INTERNAL_READY")),
                    "next_action": str(payload.get("next_action", "")),
                },
                trace_refs={key: value for key, value in trace_refs.items() if value},
                audit_refs=audit_refs,
                governed_state={
                    "internal_only": bool(payload.get("internal_only", True)),
                    "customer_visible": bool(payload.get("customer_visible", False)),
                    "live_execution_enabled": bool(payload.get("live_execution_enabled", False)),
                    "real_external_fetch_enabled": bool(payload.get("real_external_fetch_enabled", False)),
                    "crawler_enabled": bool(payload.get("crawler_enabled", False)),
                    "manual_url_picker_primary_flow": bool(
                        payload.get("manual_url_picker_primary_flow", False)
                    ),
                    "autonomous_decision": bool(payload.get("autonomous_decision", True)),
                    "selected_candidate_count": int(payload.get("selected_candidate_count", 0)),
                    "review_candidate_count": int(payload.get("review_candidate_count", 0)),
                    "skipped_candidate_count": int(payload.get("skipped_candidate_count", 0)),
                },
                writeback_state={},
                payload=payload,
                persisted_at=utc_now_iso(),
            )
        )

    def get(self, scan_run_id: str) -> PersistedRecord | None:
        return self.session.get_record(MARKET_SCAN_OBJECT_TYPE, scan_run_id)

    def list(self) -> list[PersistedRecord]:
        return self.session.list_records(MARKET_SCAN_OBJECT_TYPE)

    def readback(self, scan_run_id: str) -> dict[str, Any]:
        record = self._require(scan_run_id)
        payload = dict(record.payload)
        return {
            "readback_state": "READBACK_READY",
            "repository_backed": True,
            "replayable": True,
            "scan_run_id": scan_run_id,
            "market_scan": payload,
            "readback_summary": dict(payload.get("readback_summary", {})),
            "run_controller": dict(payload.get("run_controller", {})),
            "stage_state_machine": dict(payload.get("stage_state_machine", {})),
            "opportunity_candidates": list(payload.get("opportunity_candidates", [])),
            "review_candidates": list(payload.get("review_candidates", [])),
            "skipped_candidates": list(payload.get("skipped_candidates", [])),
            "governed_state": dict(record.governed_state),
            "audit_refs": dict(record.audit_refs),
        }

    def replay(self, scan_run_id: str) -> dict[str, Any]:
        readback = self.readback(scan_run_id)
        return {
            "replay_state": "REPLAY_READY",
            "scan_run_id": scan_run_id,
            "market_scan_readback": readback,
            "stage2_fetch_executed": False,
            "crawler_executed": False,
            "customer_visible_claim_generated": False,
        }

    def _require(self, scan_run_id: str) -> PersistedRecord:
        record = self.get(scan_run_id)
        if record is None:
            raise ValueError(f"market scan run {scan_run_id!r} not found")
        return record


__all__ = ["MARKET_SCAN_OBJECT_TYPE", "Stage1MarketScanRepository"]
