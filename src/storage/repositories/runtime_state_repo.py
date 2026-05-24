from __future__ import annotations

import json
from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord


RUNTIME_RUN_STATE_OBJECT_TYPE = "runtime_run_state"
RUNTIME_AUDIT_EVENT_OBJECT_TYPE = "runtime_audit_event"
RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE = "runtime_operator_projection"
RUNTIME_WORKER_RESULT_OBJECT_TYPE = "runtime_worker_result"


class RuntimeStateRepository:
    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def save_controller_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        run_state = dict(result.get("run_state") or {})
        run_id = str(run_state.get("run_id") or "")
        if not run_id:
            raise ValueError("runtime_run_state_missing_run_id")
        entrypoint_id = str(run_state.get("entrypoint_id") or "")
        project_id = str(run_state.get("project_id") or "")
        persisted_at = utc_now_iso()
        audit = dict(result.get("audit_ledger") or {})
        projection = _operator_projection(result)
        projection = self._merge_existing_gdcic_worker_stage5_calibration(
            projection,
            project_id=project_id,
        )
        self.session.upsert_record(
            PersistedRecord(
                object_type=RUNTIME_RUN_STATE_OBJECT_TYPE,
                record_id=run_id,
                stage_scope=_stage_scope(run_state),
                project_id=project_id or None,
                object_refs={
                    "run_id": run_id,
                    "project_id": project_id,
                    "entrypoint_id": entrypoint_id,
                },
                decision_states={
                    "runtime_controller_mode": str(result.get("runtime_controller_mode") or ""),
                    "current_stage_id": str(run_state.get("current_stage_id") or ""),
                    "run_state": str(run_state.get("run_state") or ""),
                    "next_action_type": str(dict(run_state.get("next_action") or {}).get("action_type") or ""),
                    "next_action_entrypoint_id": str(dict(run_state.get("next_action") or {}).get("entrypoint_id") or ""),
                },
                trace_refs=_runtime_trace_refs(run_state, audit=audit),
                audit_refs={event["event_id"]: event["event_type"] for event in audit.get("events", []) if isinstance(event, Mapping)},
                governed_state={
                    "customer_visible_allowed": bool(result.get("customer_visible_allowed")),
                    "external_customer_action_enabled": bool(dict(run_state.get("safety") or {}).get("external_customer_action_enabled")),
                    "real_payment_enabled": bool(dict(run_state.get("safety") or {}).get("real_payment_enabled")),
                    "real_delivery_enabled": bool(dict(run_state.get("safety") or {}).get("real_delivery_enabled")),
                    "automatic_refund_enabled": bool(dict(run_state.get("safety") or {}).get("automatic_refund_enabled")),
                },
                writeback_state={},
                payload=dict(result),
                persisted_at=persisted_at,
            )
        )
        audit_records = [self._save_audit_event(run_id=run_id, project_id=project_id, event=event) for event in audit.get("events", []) if isinstance(event, Mapping)]
        projection_record = self._save_operator_projection(run_id=run_id, project_id=project_id, projection=projection)
        return {
            "runtime_persistence_state": "PERSISTED",
            "run_state_object_type": RUNTIME_RUN_STATE_OBJECT_TYPE,
            "run_id": run_id,
            "project_id": project_id,
            "entrypoint_id": entrypoint_id,
            "audit_event_count": len(audit_records),
            "operator_projection_record_id": projection_record.record_id,
            "persisted_at": persisted_at,
        }

    def _merge_existing_gdcic_worker_stage5_calibration(
        self,
        projection: Mapping[str, Any],
        *,
        project_id: str,
    ) -> dict[str, Any]:
        worker_results = self.list_worker_results(worker_id="gdcic_browser_authorized_readback_worker")
        if project_id:
            worker_results = [
                result for result in worker_results if str(result.get("project_id") or "") == project_id
            ]
        if not worker_results:
            return dict(projection)
        worker_calibration = _gdcic_worker_stage5_calibration_summary(worker_results[0])
        if not worker_calibration:
            return dict(projection)
        out = dict(projection)
        cycle_calibration = dict(out.get("stage5_calibration_summary") or {})
        out["stage5_calibration_summary"] = _merge_stage5_calibration_summaries(
            cycle_calibration,
            worker_calibration,
        )
        out["stage5_calibration_source_summaries"] = _stage5_calibration_source_summaries(
            cycle_calibration=cycle_calibration,
            gdcic_worker_calibration=worker_calibration,
            existing=out.get("stage5_calibration_source_summaries"),
        )
        return out

    def get_run(self, run_id: str) -> dict[str, Any]:
        record = self.session.get_record(RUNTIME_RUN_STATE_OBJECT_TYPE, run_id)
        if record is None:
            raise ValueError(f"runtime run {run_id!r} not found")
        return dict(record.payload)

    def list_by_project(self, project_id: str) -> list[dict[str, Any]]:
        return [dict(record.payload) for record in self.session.find_records(RUNTIME_RUN_STATE_OBJECT_TYPE, project_id=project_id)]

    def list_by_entrypoint(self, entrypoint_id: str) -> list[dict[str, Any]]:
        return [
            dict(record.payload)
            for record in self.session.find_records(RUNTIME_RUN_STATE_OBJECT_TYPE, entrypoint_id=entrypoint_id)
        ]

    def list_operator_projections(self) -> list[dict[str, Any]]:
        records = self.session.list_records(RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE)
        return [
            {
                **dict(record.payload),
                "persisted_at": record.persisted_at,
                "object_refs": dict(record.object_refs),
                "decision_states": dict(record.decision_states),
                "trace_refs": dict(record.trace_refs),
                "governed_state": dict(record.governed_state),
            }
            for record in sorted(records, key=lambda item: item.persisted_at, reverse=True)
        ]

    def list_operator_projections_by_trace(self, **criteria: str) -> list[dict[str, Any]]:
        records = self.session.find_records(RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE, **criteria)
        return [
            {
                **dict(record.payload),
                "persisted_at": record.persisted_at,
                "object_refs": dict(record.object_refs),
                "decision_states": dict(record.decision_states),
                "trace_refs": dict(record.trace_refs),
                "governed_state": dict(record.governed_state),
            }
            for record in sorted(records, key=lambda item: item.persisted_at, reverse=True)
        ]

    def list_audit_events(self, *, run_id: str = "") -> list[dict[str, Any]]:
        records = self.session.list_records(RUNTIME_AUDIT_EVENT_OBJECT_TYPE)
        if run_id:
            records = [record for record in records if str(record.object_refs.get("run_id") or "") == run_id]
        return [
            {
                **dict(record.payload),
                "persisted_at": record.persisted_at,
                "object_refs": dict(record.object_refs),
                "decision_states": dict(record.decision_states),
                "trace_refs": dict(record.trace_refs),
                "governed_state": dict(record.governed_state),
            }
            for record in sorted(records, key=lambda item: item.record_id)
        ]

    def save_worker_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        worker_id = str(result.get("worker_id") or "")
        if not worker_id:
            raise ValueError("runtime_worker_result_missing_worker_id")
        created_at = str(result.get("created_at") or utc_now_iso())
        record_id = str(result.get("worker_result_id") or f"{worker_id}:{created_at}")
        persisted_at = utc_now_iso()
        self.session.upsert_record(
            PersistedRecord(
                object_type=RUNTIME_WORKER_RESULT_OBJECT_TYPE,
                record_id=record_id,
                stage_scope=3 if worker_id == "stage1_3_repair_worker" else 0,
                project_id=str(result.get("project_id") or "") or None,
                object_refs={
                    "worker_id": worker_id,
                    "worker_result_id": record_id,
                },
                decision_states={
                    "worker_mode": str(result.get("worker_mode") or ""),
                    "repair_worker_state": str(result.get("repair_worker_state") or ""),
                },
                trace_refs=_worker_result_trace_refs(result),
                audit_refs={},
                governed_state={
                    "customer_visible_allowed": bool(result.get("customer_visible_allowed")),
                    "external_customer_action_enabled": bool(result.get("external_customer_action_enabled")),
                    "live_execution_enabled": bool(result.get("live_execution_enabled")),
                    "real_payment_enabled": bool(result.get("real_payment_enabled")),
                    "real_delivery_enabled": bool(result.get("real_delivery_enabled")),
                    "automatic_refund_enabled": bool(result.get("automatic_refund_enabled")),
                },
                writeback_state={},
                payload=dict(result),
                persisted_at=persisted_at,
            )
        )
        if worker_id == "gdcic_browser_authorized_readback_worker":
            self._refresh_latest_operator_projection_stage5_calibration(result)
        return {
            "runtime_worker_result_persistence_state": "PERSISTED",
            "worker_result_object_type": RUNTIME_WORKER_RESULT_OBJECT_TYPE,
            "worker_result_id": record_id,
            "worker_id": worker_id,
            "persisted_at": persisted_at,
        }

    def list_worker_results(self, *, worker_id: str = "") -> list[dict[str, Any]]:
        records = self.session.list_records(RUNTIME_WORKER_RESULT_OBJECT_TYPE)
        if worker_id:
            records = [record for record in records if str(record.object_refs.get("worker_id") or "") == worker_id]
        return [
            {
                **dict(record.payload),
                "persisted_at": record.persisted_at,
                "object_refs": dict(record.object_refs),
                "decision_states": dict(record.decision_states),
                "trace_refs": dict(record.trace_refs),
                "governed_state": dict(record.governed_state),
            }
            for record in sorted(records, key=lambda item: item.persisted_at, reverse=True)
        ]

    def latest_worker_result(self, *, worker_id: str = "") -> dict[str, Any]:
        results = self.list_worker_results(worker_id=worker_id)
        if not results:
            return {}
        return dict(results[0])

    def audit_replay(self, run_id: str) -> dict[str, Any]:
        events = self.list_audit_events(run_id=run_id)
        return {
            "replay_state": "REPLAY_READY" if events else "NO_RUNTIME_AUDIT_EVENTS_RECORDED",
            "run_id": str(run_id or ""),
            "event_count": len(events),
            "event_type_counts": _counts(event.get("event_type") for event in events),
            "stage_id_counts": _counts(event.get("stage_id") for event in events),
            "events": events,
            "repository_backed_replay": True,
            "customer_visible_allowed": False,
            "external_customer_action_enabled": False,
            "real_payment_enabled": False,
            "real_delivery_enabled": False,
            "automatic_refund_enabled": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }

    def latest_operator_projection(self) -> dict[str, Any]:
        projections = self.list_operator_projections()
        if not projections:
            return _empty_operator_projection()
        latest = dict(projections[0])
        latest.setdefault("runtime_projection_state", "RUNTIME_CONTROLLER_RUN_STATE_READY")
        latest.setdefault("customer_visible_allowed", False)
        latest.setdefault("no_legal_conclusion", True)
        latest.setdefault("query_miss_is_not_clearance", True)
        return latest

    def _save_audit_event(self, *, run_id: str, project_id: str, event: Mapping[str, Any]) -> PersistedRecord:
        event_id = str(event.get("event_id") or "")
        return self.session.upsert_record(
            PersistedRecord(
                object_type=RUNTIME_AUDIT_EVENT_OBJECT_TYPE,
                record_id=f"{run_id}:{event_id}",
                stage_scope=0,
                project_id=project_id or None,
                object_refs={"run_id": run_id, "project_id": project_id, "event_id": event_id},
                decision_states={
                    "event_type": str(event.get("event_type") or ""),
                    "stage_id": str(event.get("stage_id") or ""),
                },
                trace_refs=_audit_event_trace_refs(event),
                audit_refs={"event_id": event_id},
                governed_state={"customer_visible_allowed": False},
                writeback_state={},
                payload=dict(event),
                persisted_at=utc_now_iso(),
            )
        )

    def _refresh_latest_operator_projection_stage5_calibration(self, worker_result: Mapping[str, Any]) -> None:
        worker_calibration = _gdcic_worker_stage5_calibration_summary(worker_result)
        if not worker_calibration:
            return
        project_id = str(worker_result.get("project_id") or "")
        records = self.session.list_records(RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE)
        if project_id:
            records = [record for record in records if str(record.project_id or "") == project_id]
        if not records:
            return
        latest = sorted(records, key=lambda item: item.persisted_at, reverse=True)[0]
        projection = dict(latest.payload)
        cycle_calibration = dict(projection.get("stage5_calibration_summary") or {})
        merged_calibration = _merge_stage5_calibration_summaries(cycle_calibration, worker_calibration)
        projection["stage5_calibration_summary"] = merged_calibration
        projection["stage5_calibration_source_summaries"] = _stage5_calibration_source_summaries(
            cycle_calibration=cycle_calibration,
            gdcic_worker_calibration=worker_calibration,
            existing=projection.get("stage5_calibration_source_summaries"),
        )
        self._save_operator_projection(
            run_id=str(latest.object_refs.get("run_id") or latest.record_id),
            project_id=str(latest.project_id or ""),
            projection=projection,
        )

    def _save_operator_projection(
        self,
        *,
        run_id: str,
        project_id: str,
        projection: Mapping[str, Any],
    ) -> PersistedRecord:
        return self.session.upsert_record(
            PersistedRecord(
                object_type=RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE,
                record_id=run_id,
                stage_scope=0,
                project_id=project_id or None,
                object_refs={
                    "run_id": run_id,
                    "project_id": project_id,
                    "entrypoint_id": str(projection.get("entrypoint_id") or ""),
                },
                decision_states={
                    "runtime_projection_state": str(projection.get("runtime_projection_state") or ""),
                    "next_action_type": str(projection.get("next_action_type") or ""),
                    "next_action_entrypoint_id": str(projection.get("next_action_entrypoint_id") or ""),
                },
                trace_refs=_operator_projection_trace_refs(projection),
                audit_refs={},
                governed_state={"customer_visible_allowed": False},
                writeback_state={},
                payload=dict(projection),
                persisted_at=utc_now_iso(),
            )
        )


def _operator_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    run_state = dict(result.get("run_state") or {})
    next_action = dict(run_state.get("next_action") or {})
    dispatch_queue = _controller_dispatch_queue(result.get("dispatch_queue"))
    stage5_calibration = _stage5_calibration_summary(run_state)
    return {
        "runtime_projection_state": "RUNTIME_CONTROLLER_RUN_STATE_READY",
        "run_id": str(run_state.get("run_id") or ""),
        "project_id": str(run_state.get("project_id") or ""),
        "entrypoint_id": str(run_state.get("entrypoint_id") or ""),
        "current_stage_id": str(run_state.get("current_stage_id") or ""),
        "run_state": str(run_state.get("run_state") or ""),
        "next_action_type": str(next_action.get("action_type") or ""),
        "next_action_entrypoint_id": str(next_action.get("entrypoint_id") or ""),
        "next_action_reason": str(next_action.get("reason") or ""),
        "next_action_blocking_reasons": _string_list(next_action.get("blocking_reasons")),
        "stage123_front_chain_summary": dict(run_state.get("stage123_front_chain_summary") or {}),
        "stage1_6_readiness_summary": dict(run_state.get("stage1_6_readiness_summary") or {}),
        "stage4_release_field_query_summary": dict(run_state.get("stage4_release_field_query_summary") or {}),
        "stage4_release_chain_bootstrap_summary": dict(
            run_state.get("stage4_release_chain_bootstrap_summary") or {}
        ),
        "stage5_calibration_summary": stage5_calibration,
        "stage5_calibration_source_summaries": _stage5_calibration_source_summaries(
            cycle_calibration=stage5_calibration,
            gdcic_worker_calibration={},
        ),
        "runtime_blocker_controller_summary": dict(run_state.get("runtime_blocker_controller_summary") or {}),
        "controller_dispatch_queue": dispatch_queue,
        "stage45_replay_summary": dict(run_state.get("stage45_replay_summary") or {}),
        "controlled_boundary_summary": dict(run_state.get("controlled_boundary") or {}),
        "operator_action_required": str(next_action.get("action_type") or "") in {"REVIEW", "OPERATOR_ACTION"},
        "safety": dict(run_state.get("safety") or {}),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _empty_operator_projection() -> dict[str, Any]:
    return {
        "runtime_projection_state": "EMPTY",
        "run_id": "",
        "project_id": "",
        "entrypoint_id": "",
        "current_stage_id": "",
        "run_state": "NO_RUNTIME_RUN_RECORDED",
        "next_action_type": "",
        "next_action_entrypoint_id": "",
        "next_action_reason": "",
        "next_action_blocking_reasons": [],
        "stage123_front_chain_summary": {},
        "stage1_6_readiness_summary": {},
        "stage4_release_field_query_summary": {},
        "stage4_release_chain_bootstrap_summary": {},
        "stage5_calibration_summary": {},
        "runtime_blocker_controller_summary": {},
        "controller_dispatch_queue": {"records": [], "summary": {"dispatch_record_count": 0}},
        "stage45_replay_summary": {},
        "controlled_boundary_summary": {
            "stage8_outreach_boundary_state": "CONTROLLED_OPENING_PREREQUISITES_ONLY",
            "stage9_payment_delivery_refund_boundary_state": "CONTROLLED_OPENING_PREREQUISITES_ONLY",
            "automatic_refund_policy_state": "EXCLUDED",
            "external_customer_action_enabled": False,
            "real_outreach_enabled": False,
            "real_payment_enabled": False,
            "real_delivery_enabled": False,
            "real_refund_enabled": False,
            "automatic_refund_enabled": False,
            "customer_visible_allowed": False,
        },
        "operator_action_required": False,
        "safety": {
            "external_customer_action_enabled": False,
            "real_payment_enabled": False,
            "real_delivery_enabled": False,
            "automatic_refund_enabled": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _audit_event_trace_refs(event: Mapping[str, Any]) -> dict[str, str]:
    details = dict(event.get("details") or {}) if isinstance(event.get("details"), Mapping) else {}
    trace_refs: dict[str, str] = {
        "event_type": str(event.get("event_type") or ""),
        "stage_id": str(event.get("stage_id") or ""),
    }
    for key, value in details.items():
        name = str(key or "").strip()
        if not name:
            continue
        if isinstance(value, Mapping) or isinstance(value, list):
            trace_refs[f"{name}_json"] = _json_string(value)
        elif value not in (None, ""):
            trace_refs[name] = str(value)
    return {key: value for key, value in trace_refs.items() if str(value).strip() not in {"", "[]", "{}"}}


def _worker_result_trace_refs(result: Mapping[str, Any]) -> dict[str, str]:
    repair_tasks = result.get("repair_tasks") if isinstance(result.get("repair_tasks"), list) else []
    trace_refs = {
        "worker_id": str(result.get("worker_id") or ""),
        "worker_mode": str(result.get("worker_mode") or ""),
        "repair_worker_state": str(result.get("repair_worker_state") or ""),
        "worker_result_state": str(result.get("worker_result_state") or ""),
        "repair_task_count": str(result.get("repair_task_count") or 0),
        "repair_metric_counts_json": _json_string(result.get("repair_metric_counts") or {}),
        "repair_worker_family_counts_json": _json_string(result.get("repair_worker_family_counts") or {}),
        "repair_review_family_counts_json": _json_string(result.get("repair_review_family_counts") or {}),
        "repair_source_dispatch_task_ids_json": _json_string(
            [
                str(task.get("source_dispatch_task_id") or "")
                for task in repair_tasks
                if isinstance(task, Mapping) and str(task.get("source_dispatch_task_id") or "").strip()
            ]
        ),
        "gdcic_browser_readback_task_count": str(result.get("gdcic_browser_readback_task_count") or 0),
        "gdcic_browser_readback_record_count": str(result.get("gdcic_browser_readback_record_count") or 0),
        "gdcic_browser_readback_ready_count": str(result.get("gdcic_browser_readback_ready_count") or 0),
        "project_manager_change_ready_count": str(result.get("project_manager_change_ready_count") or 0),
        "project_manager_change_interpretation_counts_json": _json_string(
            result.get("project_manager_change_interpretation_counts") or {}
        ),
        "authorization_readiness_state": str(result.get("authorization_readiness_state") or ""),
        "authorized_session_input_state": str(result.get("authorized_session_input_state") or ""),
        "operator_next_action_counts_json": _json_string(result.get("operator_next_action_counts") or {}),
        "stage5_calibration_sample_count": str(result.get("stage5_calibration_sample_count") or 0),
        "stage5_calibration_truth_label_required_count": str(
            result.get("stage5_calibration_truth_label_required_count") or 0
        ),
        "stage5_abcd_calibration_counts_json": _json_string(result.get("stage5_abcd_calibration_counts") or {}),
        "stage5_calibration_review_bucket_counts_json": _json_string(
            result.get("stage5_calibration_review_bucket_counts") or {}
        ),
        "stage5_calibration_evidence_strength_counts_json": _json_string(
            result.get("stage5_calibration_evidence_strength_counts") or {}
        ),
        "stage5_calibration_review_family_counts_json": _json_string(
            result.get("stage5_calibration_review_family_counts") or {}
        ),
    }
    return {key: value for key, value in trace_refs.items() if str(value).strip() not in {"", "[]", "{}"}}


def _stage_scope(run_state: Mapping[str, Any]) -> int:
    current = str(run_state.get("current_stage_id") or "")
    if current.startswith("stage"):
        digits = "".join(ch for ch in current[5:] if ch.isdigit())
        if digits:
            return int(digits)
    return 0


def _runtime_trace_refs(run_state: Mapping[str, Any], *, audit: Mapping[str, Any]) -> dict[str, str]:
    stage123_summary = dict(run_state.get("stage123_front_chain_summary") or {})
    stage123_stability = dict(stage123_summary.get("stage123_stability_summary") or {})
    stage1_6_summary = dict(run_state.get("stage1_6_readiness_summary") or {})
    stage1_6_stability = dict(stage1_6_summary.get("stage1_3_stability_summary") or {})
    stage4_project_code_recall = _stage4_project_code_recall_summary(stage1_6_summary)
    stage4_field_summary = dict(run_state.get("stage4_release_field_query_summary") or {})
    stage4_chain_summary = dict(run_state.get("stage4_release_chain_bootstrap_summary") or {})
    stage4_release_adapter_plan_recall = dict(
        stage4_chain_summary.get("stage4_release_adapter_plan_project_code_recall_summary") or {}
    )
    stage4_gdcic_authorized_readback = dict(stage4_chain_summary.get("stage4_gdcic_authorized_readback_summary") or {})
    stage5_summary = _stage5_calibration_summary(run_state)
    stage45_replay_summary = dict(run_state.get("stage45_replay_summary") or {})
    runtime_blocker_summary = dict(run_state.get("runtime_blocker_controller_summary") or {})
    controlled_boundary = dict(run_state.get("controlled_boundary") or {})

    input_refs = _string_list(run_state.get("input_refs"))
    output_refs = _string_list(run_state.get("output_artifact_refs"))
    stage4_chain_input_refs = {
        str(key): str(value)
        for key, value in dict(stage4_chain_summary.get("stage4_release_chain_input_refs") or {}).items()
        if str(value or "").strip()
    }
    trace_refs = {
        "audit_event_count": str(len(audit.get("events") or [])),
        "input_ref_count": str(len(input_refs)),
        "output_artifact_ref_count": str(len(output_refs)),
        "input_refs_json": _json_string(input_refs),
        "output_artifact_refs_json": _json_string(output_refs),
        "stage123_front_chain_state": str(stage123_summary.get("stage123_front_chain_state") or ""),
        "stage123_attachment_snapshot_missing_count": str(
            stage123_stability.get("stage2_attachment_snapshot_missing_count") or 0
        ),
        "stage123_attachment_snapshot_readback_missing_count": str(
            stage123_stability.get("attachment_snapshot_readback_missing_count") or 0
        ),
        "stage123_attachment_ocr_pending_count": str(
            stage123_stability.get("stage3_attachment_ocr_pending_count") or 0
        ),
        "stage123_responsible_role_gap_count": str(
            stage123_stability.get("stage3_responsible_role_gap_count") or 0
        ),
        "stage1_6_readiness_record_count": str(stage1_6_summary.get("stage1_6_readiness_record_count") or 0),
        "stage1_6_gap_summary_record_count": str(stage1_6_summary.get("stage1_6_gap_summary_record_count") or 0),
        "stage1_6_readiness_json": str(stage1_6_summary.get("stage1_6_readiness_json") or ""),
        "stage1_6_gap_summary_json": str(stage1_6_summary.get("stage1_6_gap_summary_json") or ""),
        "stage1_6_real_public_pressure_report_json": str(
            stage1_6_summary.get("stage1_6_real_public_pressure_report_json") or ""
        ),
        "stage1_6_pressure_coverage_state": str(stage1_6_summary.get("stage1_6_pressure_coverage_state") or ""),
        "stage1_6_pressure_candidate_count": str(stage1_6_summary.get("stage1_6_pressure_candidate_count") or 0),
        "stage1_6_pressure_closed_loop_results_count": str(
            stage1_6_summary.get("stage1_6_pressure_closed_loop_results_count") or 0
        ),
        "stage1_6_pressure_stage5_calibration_sample_count": str(
            stage1_6_summary.get("stage1_6_pressure_stage5_calibration_sample_count") or 0
        ),
        "stage1_6_next_action_counts_json": _json_string(stage1_6_summary.get("stage1_6_next_action_counts") or {}),
        "stage1_6_gap_next_action_counts_json": _json_string(
            stage1_6_summary.get("stage1_6_gap_next_action_counts") or {}
        ),
        "stage1_6_attachment_snapshot_missing_count": str(
            stage1_6_stability.get("stage2_attachment_snapshot_missing_count") or 0
        ),
        "stage1_6_attachment_snapshot_readback_missing_count": str(
            stage1_6_stability.get("attachment_snapshot_readback_missing_count") or 0
        ),
        "stage1_6_attachment_ocr_pending_count": str(
            stage1_6_stability.get("stage3_attachment_ocr_pending_count") or 0
        ),
        "stage1_6_responsible_role_gap_count": str(
            stage1_6_stability.get("stage3_responsible_role_gap_count") or 0
        ),
        "stage4_release_adapter_bridge_project_code_recall_state": str(
            stage4_project_code_recall.get("project_code_recall_state") or ""
        ),
        "stage4_release_adapter_bridge_gdcic_project_code_variant_task_count": str(
            stage4_project_code_recall.get("with_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_bridge_missing_gdcic_project_code_variant_task_count": str(
            stage4_project_code_recall.get("missing_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_bridge_project_code_recall_summary_json": _json_string(
            stage4_project_code_recall
        ),
        "stage4_release_field_query_project_count": str(
            stage4_field_summary.get("release_field_query_project_count") or 0
        ),
        "stage4_release_field_query_state_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_state_counts") or {}
        ),
        "stage4_release_field_query_authorization_state_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_authorization_state_counts") or {}
        ),
        "stage4_release_field_query_authorized_session_input_state_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_authorized_session_input_state_counts") or {}
        ),
        "stage4_release_field_query_operator_next_action_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_operator_next_action_counts") or {}
        ),
        "stage4_release_field_query_project_manager_change_ready_count": str(
            stage4_field_summary.get("release_field_query_project_manager_change_ready_count") or 0
        ),
        "stage4_release_field_query_project_manager_change_interpretation_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_project_manager_change_interpretation_counts") or {}
        ),
        "stage4_release_chain_source_kind": str(
            stage4_chain_summary.get("stage4_release_chain_bootstrap_source_kind") or ""
        ),
        "stage4_release_chain_input_refs_json": _json_string(stage4_chain_input_refs),
        "stage4_release_adapter_plan_project_code_recall_state": str(
            stage4_release_adapter_plan_recall.get("project_code_recall_state") or ""
        ),
        "stage4_release_adapter_plan_gdcic_project_code_variant_task_count": str(
            stage4_release_adapter_plan_recall.get("with_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_plan_missing_gdcic_project_code_variant_task_count": str(
            stage4_release_adapter_plan_recall.get("missing_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_plan_project_code_recall_summary_json": _json_string(
            stage4_release_adapter_plan_recall
        ),
        "stage4_gdcic_authorized_readback_source_json": str(
            stage4_gdcic_authorized_readback.get("source_gdcic_browser_readback_json") or ""
        ),
        "stage4_gdcic_authorized_readback_ready_count": str(
            stage4_gdcic_authorized_readback.get("gdcic_browser_readback_ready_count") or 0
        ),
        "stage4_gdcic_authorized_readback_project_manager_change_ready_count": str(
            stage4_gdcic_authorized_readback.get("project_manager_change_ready_count") or 0
        ),
        "stage4_gdcic_authorized_readback_project_manager_change_interpretation_counts_json": _json_string(
            stage4_gdcic_authorized_readback.get("project_manager_change_interpretation_counts") or {}
        ),
        "stage4_gdcic_authorized_readback_summary_json": _json_string(stage4_gdcic_authorized_readback),
        "stage4_release_chain_project_count": str(stage4_chain_summary.get("stage4_release_chain_project_count") or 0),
        "stage4_release_chain_runtime_blocker_ledger_count": str(
            stage4_chain_summary.get("stage4_release_chain_runtime_blocker_ledger_count") or 0
        ),
        "stage4_release_chain_next_action_counts_json": _json_string(
            stage4_chain_summary.get("stage4_release_chain_next_action_counts") or {}
        ),
        "stage4_release_chain_manual_action_family_counts_json": _json_string(
            stage4_chain_summary.get("stage4_release_chain_manual_action_family_counts") or {}
        ),
        "stage4_release_chain_runtime_blocker_state_counts_json": _json_string(
            stage4_chain_summary.get("stage4_release_chain_runtime_blocker_state_counts") or {}
        ),
        "stage5_calibration_sample_count": str(stage5_summary.get("stage5_calibration_sample_count") or 0),
        "stage5_calibration_truth_label_required_count": str(
            stage5_summary.get("stage5_calibration_truth_label_required_count") or 0
        ),
        "stage5_abcd_calibration_counts_json": _json_string(
            stage5_summary.get("stage5_abcd_calibration_counts") or {}
        ),
        "stage5_calibration_evidence_strength_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_evidence_strength_counts") or {}
        ),
        "stage5_calibration_review_bucket_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_review_bucket_counts") or {}
        ),
        "stage5_calibration_review_family_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_review_family_counts") or {}
        ),
        "stage5_calibration_suggested_action_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_suggested_action_counts") or {}
        ),
        "stage45_replay_stage4_probe_replay_count": str(
            stage45_replay_summary.get("stage4_probe_replay_count") or 0
        ),
        "stage45_replay_stage4_blocker_ledger_count": str(
            stage45_replay_summary.get("stage4_blocker_ledger_count") or 0
        ),
        "stage45_replay_operator_action_count": str(stage45_replay_summary.get("operator_action_count") or 0),
        "stage45_replay_runtime_blocker_subqueue_route_counts_json": _json_string(
            stage45_replay_summary.get("runtime_blocker_subqueue_route_counts") or {}
        ),
        "stage45_replay_stage5_executed_rule_codes_json": _json_string(
            stage45_replay_summary.get("stage5_executed_rule_codes") or []
        ),
        "stage45_replay_stage5_skipped_rule_codes_json": _json_string(
            stage45_replay_summary.get("stage5_skipped_rule_codes") or []
        ),
        "stage45_replay_stage5_missing_readback_count": str(
            stage45_replay_summary.get("stage5_missing_readback_count") or 0
        ),
        "stage45_replay_stage5_calibration_sample_count": str(
            stage45_replay_summary.get("stage5_calibration_sample_count") or 0
        ),
        "stage45_replay_stage5_calibration_truth_label_required_count": str(
            stage45_replay_summary.get("stage5_calibration_truth_label_required_count") or 0
        ),
        "stage45_replay_stage5_abcd_calibration_counts_json": _json_string(
            stage45_replay_summary.get("stage5_abcd_calibration_counts") or {}
        ),
        "stage45_replay_stage5_calibration_evidence_strength_counts_json": _json_string(
            stage45_replay_summary.get("stage5_calibration_evidence_strength_counts") or {}
        ),
        "stage45_replay_stage5_calibration_review_family_counts_json": _json_string(
            stage45_replay_summary.get("stage5_calibration_review_family_counts") or {}
        ),
        "stage45_replay_stage5_calibration_suggested_action_counts_json": _json_string(
            stage45_replay_summary.get("stage5_calibration_suggested_action_counts") or {}
        ),
        "runtime_blocker_next_subqueue_input_state": str(
            runtime_blocker_summary.get("next_subqueue_input_state") or ""
        ),
        "runtime_blocker_controller_dispatch_task_count": str(
            runtime_blocker_summary.get("controller_dispatch_task_count") or 0
        ),
        "runtime_controller_derived_dispatch_task_count": str(
            runtime_blocker_summary.get("controller_derived_dispatch_task_count") or 0
        ),
        "runtime_controller_derived_dispatch_ready_count": str(
            runtime_blocker_summary.get("controller_derived_dispatch_ready_count") or 0
        ),
        "runtime_controller_derived_dispatch_state_counts_json": _json_string(
            runtime_blocker_summary.get("controller_derived_dispatch_state_counts") or {}
        ),
        "runtime_controller_derived_dispatch_entrypoint_counts_json": _json_string(
            runtime_blocker_summary.get("controller_derived_dispatch_entrypoint_counts") or {}
        ),
        "runtime_controller_derived_dispatch_review_family_counts_json": _json_string(
            runtime_blocker_summary.get("controller_derived_dispatch_review_family_counts") or {}
        ),
        "stage1_3_repair_task_count": str(runtime_blocker_summary.get("stage1_3_repair_task_count") or 0),
        "stage1_3_repair_metric_counts_json": _json_string(
            runtime_blocker_summary.get("stage1_3_repair_metric_counts") or {}
        ),
        "stage1_3_repair_review_family_counts_json": _json_string(
            runtime_blocker_summary.get("stage1_3_repair_review_family_counts") or {}
        ),
        "stage8_outreach_boundary_state": str(
            controlled_boundary.get("stage8_outreach_boundary_state") or ""
        ),
        "stage9_payment_delivery_refund_boundary_state": str(
            controlled_boundary.get("stage9_payment_delivery_refund_boundary_state") or ""
        ),
        "automatic_refund_policy_state": str(controlled_boundary.get("automatic_refund_policy_state") or ""),
        "controlled_boundary_blocked_action_families_json": _json_string(
            controlled_boundary.get("blocked_action_families") or []
        ),
        "controlled_boundary_required_before_live_execution_json": _json_string(
            controlled_boundary.get("required_before_live_execution") or []
        ),
        "controlled_boundary_required_before_live_execution_count": str(
            len(_string_list(controlled_boundary.get("required_before_live_execution")))
        ),
        "controlled_boundary_operator_next_action": str(controlled_boundary.get("operator_next_action") or ""),
    }
    return {key: value for key, value in trace_refs.items() if str(value).strip() not in {"", "[]", "{}"}}


def _operator_projection_trace_refs(projection: Mapping[str, Any]) -> dict[str, str]:
    stage1_6_summary = dict(projection.get("stage1_6_readiness_summary") or {})
    stage1_6_stability = dict(stage1_6_summary.get("stage1_3_stability_summary") or {})
    stage4_project_code_recall = _stage4_project_code_recall_summary(stage1_6_summary)
    stage123_summary = dict(projection.get("stage123_front_chain_summary") or {})
    stage123_stability = dict(stage123_summary.get("stage123_stability_summary") or {})
    stage4_field_summary = dict(projection.get("stage4_release_field_query_summary") or {})
    stage4_chain_summary = dict(projection.get("stage4_release_chain_bootstrap_summary") or {})
    stage4_release_adapter_plan_recall = dict(
        stage4_chain_summary.get("stage4_release_adapter_plan_project_code_recall_summary") or {}
    )
    stage4_gdcic_authorized_readback = dict(stage4_chain_summary.get("stage4_gdcic_authorized_readback_summary") or {})
    stage5_summary = dict(projection.get("stage5_calibration_summary") or {})
    stage5_source_summaries = dict(projection.get("stage5_calibration_source_summaries") or {})
    stage45_replay_summary = dict(projection.get("stage45_replay_summary") or {})
    runtime_blocker_summary = dict(projection.get("runtime_blocker_controller_summary") or {})
    controlled_boundary = dict(projection.get("controlled_boundary_summary") or {})
    trace_refs = {
        "stage1_6_readiness_record_count": str(stage1_6_summary.get("stage1_6_readiness_record_count") or 0),
        "stage1_6_gap_summary_record_count": str(stage1_6_summary.get("stage1_6_gap_summary_record_count") or 0),
        "stage1_6_real_public_pressure_report_json": str(
            stage1_6_summary.get("stage1_6_real_public_pressure_report_json") or ""
        ),
        "stage1_6_pressure_coverage_state": str(stage1_6_summary.get("stage1_6_pressure_coverage_state") or ""),
        "stage1_6_pressure_candidate_count": str(stage1_6_summary.get("stage1_6_pressure_candidate_count") or 0),
        "stage1_6_pressure_closed_loop_results_count": str(
            stage1_6_summary.get("stage1_6_pressure_closed_loop_results_count") or 0
        ),
        "stage1_6_pressure_stage5_calibration_sample_count": str(
            stage1_6_summary.get("stage1_6_pressure_stage5_calibration_sample_count") or 0
        ),
        "stage1_6_next_action_counts_json": _json_string(stage1_6_summary.get("stage1_6_next_action_counts") or {}),
        "stage1_6_gap_next_action_counts_json": _json_string(
            stage1_6_summary.get("stage1_6_gap_next_action_counts") or {}
        ),
        "stage1_6_attachment_snapshot_missing_count": str(
            stage1_6_stability.get("stage2_attachment_snapshot_missing_count") or 0
        ),
        "stage1_6_attachment_snapshot_readback_missing_count": str(
            stage1_6_stability.get("attachment_snapshot_readback_missing_count") or 0
        ),
        "stage1_6_attachment_ocr_pending_count": str(
            stage1_6_stability.get("stage3_attachment_ocr_pending_count") or 0
        ),
        "stage1_6_responsible_role_gap_count": str(
            stage1_6_stability.get("stage3_responsible_role_gap_count") or 0
        ),
        "stage4_release_adapter_bridge_project_code_recall_state": str(
            stage4_project_code_recall.get("project_code_recall_state") or ""
        ),
        "stage4_release_adapter_bridge_gdcic_project_code_variant_task_count": str(
            stage4_project_code_recall.get("with_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_bridge_missing_gdcic_project_code_variant_task_count": str(
            stage4_project_code_recall.get("missing_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_bridge_project_code_recall_summary_json": _json_string(
            stage4_project_code_recall
        ),
        "stage123_attachment_snapshot_missing_count": str(
            stage123_stability.get("stage2_attachment_snapshot_missing_count") or 0
        ),
        "stage123_attachment_snapshot_readback_missing_count": str(
            stage123_stability.get("attachment_snapshot_readback_missing_count") or 0
        ),
        "stage123_attachment_ocr_pending_count": str(
            stage123_stability.get("stage3_attachment_ocr_pending_count") or 0
        ),
        "stage123_responsible_role_gap_count": str(
            stage123_stability.get("stage3_responsible_role_gap_count") or 0
        ),
        "stage4_release_field_query_project_count": str(
            stage4_field_summary.get("release_field_query_project_count") or 0
        ),
        "stage4_release_field_query_authorization_state_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_authorization_state_counts") or {}
        ),
        "stage4_release_field_query_authorized_session_input_state_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_authorized_session_input_state_counts") or {}
        ),
        "stage4_release_field_query_operator_next_action_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_operator_next_action_counts") or {}
        ),
        "stage4_release_field_query_project_manager_change_ready_count": str(
            stage4_field_summary.get("release_field_query_project_manager_change_ready_count") or 0
        ),
        "stage4_release_field_query_project_manager_change_interpretation_counts_json": _json_string(
            stage4_field_summary.get("release_field_query_project_manager_change_interpretation_counts") or {}
        ),
        "stage4_release_chain_source_kind": str(
            stage4_chain_summary.get("stage4_release_chain_bootstrap_source_kind") or ""
        ),
        "stage4_release_chain_input_refs_json": _json_string(
            stage4_chain_summary.get("stage4_release_chain_input_refs") or {}
        ),
        "stage4_release_adapter_plan_project_code_recall_state": str(
            stage4_release_adapter_plan_recall.get("project_code_recall_state") or ""
        ),
        "stage4_release_adapter_plan_gdcic_project_code_variant_task_count": str(
            stage4_release_adapter_plan_recall.get("with_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_plan_missing_gdcic_project_code_variant_task_count": str(
            stage4_release_adapter_plan_recall.get("missing_gdcic_project_code_variant_task_count") or 0
        ),
        "stage4_release_adapter_plan_project_code_recall_summary_json": _json_string(
            stage4_release_adapter_plan_recall
        ),
        "stage4_gdcic_authorized_readback_source_json": str(
            stage4_gdcic_authorized_readback.get("source_gdcic_browser_readback_json") or ""
        ),
        "stage4_gdcic_authorized_readback_ready_count": str(
            stage4_gdcic_authorized_readback.get("gdcic_browser_readback_ready_count") or 0
        ),
        "stage4_gdcic_authorized_readback_project_manager_change_ready_count": str(
            stage4_gdcic_authorized_readback.get("project_manager_change_ready_count") or 0
        ),
        "stage4_gdcic_authorized_readback_project_manager_change_interpretation_counts_json": _json_string(
            stage4_gdcic_authorized_readback.get("project_manager_change_interpretation_counts") or {}
        ),
        "stage4_gdcic_authorized_readback_summary_json": _json_string(stage4_gdcic_authorized_readback),
        "stage4_release_chain_project_count": str(stage4_chain_summary.get("stage4_release_chain_project_count") or 0),
        "stage4_release_chain_next_action_counts_json": _json_string(
            stage4_chain_summary.get("stage4_release_chain_next_action_counts") or {}
        ),
        "stage4_release_chain_manual_action_family_counts_json": _json_string(
            stage4_chain_summary.get("stage4_release_chain_manual_action_family_counts") or {}
        ),
        "stage4_release_chain_runtime_blocker_state_counts_json": _json_string(
            stage4_chain_summary.get("stage4_release_chain_runtime_blocker_state_counts") or {}
        ),
        "stage5_calibration_sample_count": str(stage5_summary.get("stage5_calibration_sample_count") or 0),
        "stage5_calibration_truth_label_required_count": str(
            stage5_summary.get("stage5_calibration_truth_label_required_count") or 0
        ),
        "stage5_abcd_calibration_counts_json": _json_string(
            stage5_summary.get("stage5_abcd_calibration_counts") or {}
        ),
        "stage5_calibration_evidence_strength_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_evidence_strength_counts") or {}
        ),
        "stage5_calibration_review_bucket_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_review_bucket_counts") or {}
        ),
        "stage5_calibration_review_family_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_review_family_counts") or {}
        ),
        "stage5_calibration_suggested_action_counts_json": _json_string(
            stage5_summary.get("stage5_calibration_suggested_action_counts") or {}
        ),
        "stage5_calibration_merged_source_count": str(stage5_summary.get("merged_source_count") or 0),
        "stage5_calibration_source_summaries_json": _json_string(stage5_source_summaries),
        "stage45_replay_stage4_probe_replay_count": str(
            stage45_replay_summary.get("stage4_probe_replay_count") or 0
        ),
        "stage45_replay_stage4_blocker_ledger_count": str(
            stage45_replay_summary.get("stage4_blocker_ledger_count") or 0
        ),
        "stage45_replay_operator_action_count": str(stage45_replay_summary.get("operator_action_count") or 0),
        "stage45_replay_runtime_blocker_subqueue_route_counts_json": _json_string(
            stage45_replay_summary.get("runtime_blocker_subqueue_route_counts") or {}
        ),
        "stage45_replay_stage5_executed_rule_codes_json": _json_string(
            stage45_replay_summary.get("stage5_executed_rule_codes") or []
        ),
        "stage45_replay_stage5_skipped_rule_codes_json": _json_string(
            stage45_replay_summary.get("stage5_skipped_rule_codes") or []
        ),
        "stage45_replay_stage5_missing_readback_count": str(
            stage45_replay_summary.get("stage5_missing_readback_count") or 0
        ),
        "stage45_replay_stage5_calibration_sample_count": str(
            stage45_replay_summary.get("stage5_calibration_sample_count") or 0
        ),
        "stage45_replay_stage5_calibration_truth_label_required_count": str(
            stage45_replay_summary.get("stage5_calibration_truth_label_required_count") or 0
        ),
        "stage45_replay_stage5_abcd_calibration_counts_json": _json_string(
            stage45_replay_summary.get("stage5_abcd_calibration_counts") or {}
        ),
        "stage45_replay_stage5_calibration_evidence_strength_counts_json": _json_string(
            stage45_replay_summary.get("stage5_calibration_evidence_strength_counts") or {}
        ),
        "stage45_replay_stage5_calibration_review_family_counts_json": _json_string(
            stage45_replay_summary.get("stage5_calibration_review_family_counts") or {}
        ),
        "stage45_replay_stage5_calibration_suggested_action_counts_json": _json_string(
            stage45_replay_summary.get("stage5_calibration_suggested_action_counts") or {}
        ),
        "runtime_blocker_next_subqueue_input_state": str(
            runtime_blocker_summary.get("next_subqueue_input_state") or ""
        ),
        "runtime_controller_derived_dispatch_task_count": str(
            runtime_blocker_summary.get("controller_derived_dispatch_task_count") or 0
        ),
        "runtime_controller_derived_dispatch_ready_count": str(
            runtime_blocker_summary.get("controller_derived_dispatch_ready_count") or 0
        ),
        "runtime_controller_derived_dispatch_state_counts_json": _json_string(
            runtime_blocker_summary.get("controller_derived_dispatch_state_counts") or {}
        ),
        "runtime_controller_derived_dispatch_entrypoint_counts_json": _json_string(
            runtime_blocker_summary.get("controller_derived_dispatch_entrypoint_counts") or {}
        ),
        "runtime_controller_derived_dispatch_review_family_counts_json": _json_string(
            runtime_blocker_summary.get("controller_derived_dispatch_review_family_counts") or {}
        ),
        "stage1_3_repair_task_count": str(runtime_blocker_summary.get("stage1_3_repair_task_count") or 0),
        "stage1_3_repair_metric_counts_json": _json_string(
            runtime_blocker_summary.get("stage1_3_repair_metric_counts") or {}
        ),
        "stage1_3_repair_review_family_counts_json": _json_string(
            runtime_blocker_summary.get("stage1_3_repair_review_family_counts") or {}
        ),
        "stage8_outreach_boundary_state": str(
            controlled_boundary.get("stage8_outreach_boundary_state") or ""
        ),
        "stage9_payment_delivery_refund_boundary_state": str(
            controlled_boundary.get("stage9_payment_delivery_refund_boundary_state") or ""
        ),
        "automatic_refund_policy_state": str(controlled_boundary.get("automatic_refund_policy_state") or ""),
        "controlled_boundary_blocked_action_families_json": _json_string(
            controlled_boundary.get("blocked_action_families") or []
        ),
        "controlled_boundary_required_before_live_execution_json": _json_string(
            controlled_boundary.get("required_before_live_execution") or []
        ),
        "controlled_boundary_required_before_live_execution_count": str(
            len(_string_list(controlled_boundary.get("required_before_live_execution")))
        ),
        "controlled_boundary_operator_next_action": str(controlled_boundary.get("operator_next_action") or ""),
        "next_action_type": str(projection.get("next_action_type") or ""),
        "next_action_entrypoint_id": str(projection.get("next_action_entrypoint_id") or ""),
        "next_action_blocking_reasons_json": _json_string(
            projection.get("next_action_blocking_reasons") or []
        ),
    }
    return {key: value for key, value in trace_refs.items() if str(value).strip() not in {"", "[]", "{}"}}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _json_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        out[text] = out.get(text, 0) + 1
    return out


def _sum_by_key(records: list[Mapping[str, Any]], *, key_field: str, value_field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in records:
        key = str(record.get(key_field) or record.get("reason") or "").strip()
        if not key:
            continue
        out[key] = out.get(key, 0) + int(record.get(value_field) or 0)
    return out


def _stage4_project_code_recall_summary(stage1_6_summary: Mapping[str, Any]) -> dict[str, Any]:
    value = stage1_6_summary.get("stage4_release_adapter_bridge_project_code_recall_summary")
    return dict(value) if isinstance(value, Mapping) else {}


def _stage5_calibration_summary(run_state: Mapping[str, Any]) -> dict[str, Any]:
    cycle_summary = run_state.get("stage6_cycle_summary")
    if not isinstance(cycle_summary, Mapping):
        return {}
    sample_count = int(cycle_summary.get("stage5_calibration_sample_count") or 0)
    truth_label_required_count = int(cycle_summary.get("stage5_calibration_truth_label_required_count") or 0)
    if sample_count <= 0 and truth_label_required_count <= 0:
        return {}
    return {
        "stage5_calibration_sample_count": sample_count,
        "stage5_calibration_truth_label_required_count": truth_label_required_count,
        "stage5_abcd_calibration_counts": dict(
            cycle_summary.get("stage5_abcd_calibration_counts")
            if isinstance(cycle_summary.get("stage5_abcd_calibration_counts"), Mapping)
            else {}
        ),
        "stage5_calibration_review_bucket_counts": dict(
            cycle_summary.get("stage5_calibration_review_bucket_counts")
            if isinstance(cycle_summary.get("stage5_calibration_review_bucket_counts"), Mapping)
            else {}
        ),
        "stage5_calibration_evidence_strength_counts": dict(
            cycle_summary.get("stage5_calibration_evidence_strength_counts")
            if isinstance(cycle_summary.get("stage5_calibration_evidence_strength_counts"), Mapping)
            else {}
        ),
        "stage5_calibration_review_family_counts": dict(
            cycle_summary.get("stage5_calibration_review_family_counts")
            if isinstance(cycle_summary.get("stage5_calibration_review_family_counts"), Mapping)
            else {}
        ),
        "stage5_calibration_suggested_action_counts": dict(
            cycle_summary.get("stage5_calibration_suggested_action_counts")
            if isinstance(cycle_summary.get("stage5_calibration_suggested_action_counts"), Mapping)
            else {}
        ),
    }


def _gdcic_worker_stage5_calibration_summary(worker_result: Mapping[str, Any]) -> dict[str, Any]:
    sample_count = int(worker_result.get("stage5_calibration_sample_count") or 0)
    truth_label_required_count = int(worker_result.get("stage5_calibration_truth_label_required_count") or 0)
    if sample_count <= 0 and truth_label_required_count <= 0:
        return {}
    return {
        "stage5_calibration_sample_count": sample_count,
        "stage5_calibration_truth_label_required_count": truth_label_required_count,
        "stage5_abcd_calibration_counts": _int_mapping(worker_result.get("stage5_abcd_calibration_counts")),
        "stage5_calibration_review_bucket_counts": _int_mapping(
            worker_result.get("stage5_calibration_review_bucket_counts")
            or worker_result.get("stage5_abcd_calibration_counts")
        ),
        "stage5_calibration_evidence_strength_counts": _int_mapping(
            worker_result.get("stage5_calibration_evidence_strength_counts")
        ),
        "stage5_calibration_review_family_counts": _int_mapping(
            worker_result.get("stage5_calibration_review_family_counts")
        ),
        "stage5_calibration_suggested_action_counts": _int_mapping(
            worker_result.get("stage5_calibration_suggested_action_counts")
        ),
    }


def _stage5_calibration_source_summaries(
    *,
    cycle_calibration: Mapping[str, Any],
    gdcic_worker_calibration: Mapping[str, Any],
    existing: Any = None,
) -> dict[str, Any]:
    sources = dict(existing) if isinstance(existing, Mapping) else {}
    if _has_stage5_calibration(cycle_calibration):
        sources["stage6_cycle_summary"] = dict(cycle_calibration)
    if _has_stage5_calibration(gdcic_worker_calibration):
        sources["gdcic_authorized_readback_worker"] = dict(gdcic_worker_calibration)
    return sources


def _merge_stage5_calibration_summaries(*summaries: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "stage5_calibration_sample_count": 0,
        "stage5_calibration_truth_label_required_count": 0,
        "stage5_abcd_calibration_counts": {},
        "stage5_calibration_review_bucket_counts": {},
        "stage5_calibration_evidence_strength_counts": {},
        "stage5_calibration_review_family_counts": {},
        "stage5_calibration_suggested_action_counts": {},
        "merged_source_count": 0,
    }
    for summary in summaries:
        if not _has_stage5_calibration(summary):
            continue
        merged["merged_source_count"] += 1
        merged["stage5_calibration_sample_count"] += int(summary.get("stage5_calibration_sample_count") or 0)
        merged["stage5_calibration_truth_label_required_count"] += int(
            summary.get("stage5_calibration_truth_label_required_count") or 0
        )
        for key in (
            "stage5_abcd_calibration_counts",
            "stage5_calibration_review_bucket_counts",
            "stage5_calibration_evidence_strength_counts",
            "stage5_calibration_review_family_counts",
            "stage5_calibration_suggested_action_counts",
        ):
            merged[key] = _merge_count_maps(merged[key], summary.get(key))
    if merged["merged_source_count"] <= 0:
        return {}
    return merged


def _has_stage5_calibration(summary: Mapping[str, Any]) -> bool:
    return int(summary.get("stage5_calibration_sample_count") or 0) > 0 or int(
        summary.get("stage5_calibration_truth_label_required_count") or 0
    ) > 0


def _merge_count_maps(left: Any, right: Any) -> dict[str, int]:
    merged = _int_mapping(left)
    for key, value in _int_mapping(right).items():
        merged[key] = merged.get(key, 0) + int(value or 0)
    return merged


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): int(count or 0) for key, count in value.items() if str(key or "").strip()}


def _controller_dispatch_queue(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"records": [], "summary": {"dispatch_record_count": 0}}
    records = [dict(record) for record in value.get("records", []) if isinstance(record, Mapping)]
    summary = dict(value.get("summary") or {})
    summary.setdefault("dispatch_record_count", len(records))
    repair_records = [
        record for record in records if str(record.get("review_family") or "").startswith("stage1_3_")
    ]
    summary.setdefault("stage1_3_repair_task_count", len(repair_records))
    summary.setdefault(
        "stage1_3_repair_metric_counts",
        _sum_by_key(repair_records, key_field="source_metric", value_field="metric_count"),
    )
    summary.setdefault(
        "stage1_3_repair_review_family_counts",
        _counts(record.get("review_family") for record in repair_records),
    )
    return {
        **dict(value),
        "records": records,
        "summary": summary,
        "customer_visible_allowed": False,
        "external_customer_action_enabled": False,
    }


__all__ = [
    "RUNTIME_AUDIT_EVENT_OBJECT_TYPE",
    "RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE",
    "RUNTIME_RUN_STATE_OBJECT_TYPE",
    "RUNTIME_WORKER_RESULT_OBJECT_TYPE",
    "RuntimeStateRepository",
]
