from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from runtime.audit_ledger import AuditReplayLedger
from runtime.dispatcher import WorkQueueDispatcher
from runtime.entrypoint_registry import RuntimeEntrypointRegistry
from runtime.stage123_front_chain import build_stage123_runtime_front_chain, has_stage123_front_chain_input
from runtime.stage45_replay import build_stage45_runtime_sample_replay
from runtime.stage_state_machine import StageStateMachine
from runtime.transition_guard import TransitionGuard
from storage.repositories.runtime_state_repo import RuntimeStateRepository


Stage6PreviewExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
Stage6CycleRunner = Callable[..., Mapping[str, Any]]


class RunController:
    def __init__(
        self,
        *,
        stage6_preview_executor: Stage6PreviewExecutor,
        stage6_cycle_runner: Stage6CycleRunner | None = None,
        entrypoint_registry: RuntimeEntrypointRegistry | None = None,
        stage_state_machine: StageStateMachine | None = None,
        transition_guard: TransitionGuard | None = None,
        runtime_state_repository: RuntimeStateRepository | None = None,
    ) -> None:
        self.stage6_preview_executor = stage6_preview_executor
        self.stage6_cycle_runner = stage6_cycle_runner
        self.entrypoint_registry = entrypoint_registry or RuntimeEntrypointRegistry.default()
        self.stage_state_machine = stage_state_machine or StageStateMachine.default()
        self.transition_guard = transition_guard or TransitionGuard()
        self.runtime_state_repository = runtime_state_repository or RuntimeStateRepository()

    def start_stage1_6_preview_run(
        self,
        payload: Mapping[str, Any],
        *,
        created_at: str,
    ) -> dict[str, Any]:
        project_id = str(payload.get("project_id") or "").strip()
        if not project_id:
            raise ValueError("project_id_required")
        entrypoint_id = str(payload.get("entrypoint_id") or "stage1_6_internal_http_orchestration_preview")
        run_id = f"RUN-{project_id}-stage1-6-preview"
        ledger = AuditReplayLedger()
        ledger.record(
            event_type="RUN_STARTED",
            run_id=run_id,
            created_at=created_at,
            details={
                "entrypoint_id": entrypoint_id,
                "project_id": project_id,
                "source_mode": payload.get("source_mode"),
            },
        )

        stage_result = dict(self.stage6_preview_executor(payload))
        current_stage_id = str(stage_result.get("stage_id") or "stage6_fact_review")
        if current_stage_id != "stage6_fact_review":
            self.stage_state_machine.next_stage_id(current_stage_id)
        next_action = self.transition_guard.guarded_next_action(stage_result.get("next_action"))
        blocking_reasons = [str(reason) for reason in stage_result.get("blocking_reasons", []) if reason]
        output_refs = [str(ref) for ref in stage_result.get("output_artifact_refs", []) if ref]
        input_refs = [str(ref) for ref in payload.get("input_refs", []) if ref]

        ledger.record(
            event_type="STAGE_RESULT_RECORDED",
            run_id=run_id,
            stage_id=current_stage_id,
            created_at=created_at,
            details={
                "stage_state": stage_result.get("stage_state"),
                "blocking_reasons": blocking_reasons,
                "next_action": next_action,
                "output_artifact_refs": output_refs,
            },
        )

        dispatcher = WorkQueueDispatcher(created_at=created_at)
        dispatch_task = dispatcher.enqueue_next_action(
            run_id=run_id,
            project_id=project_id,
            current_stage_id=current_stage_id,
            next_action=next_action,
            input_refs=output_refs,
        )
        ledger.record(
            event_type="DISPATCH_TASK_ENQUEUED",
            run_id=run_id,
            stage_id=current_stage_id,
            created_at=created_at,
            details={
                "dispatch_task_id": dispatch_task["dispatch_task_id"],
                "entrypoint_id": dispatch_task["entrypoint_id"],
                "dispatch_state": dispatch_task["dispatch_state"],
            },
        )

        controlled_boundary = self.transition_guard.controlled_boundary_projection()
        ledger.record(
            event_type="RUNTIME_CONTROLLED_BOUNDARY_RECORDED",
            run_id=run_id,
            stage_id="stage8_outreach",
            created_at=created_at,
            details=dict(controlled_boundary),
        )
        audit = ledger.to_dict()
        run_state = {
            "run_id": run_id,
            "entrypoint_id": entrypoint_id,
            "project_id": project_id,
            "current_stage_id": current_stage_id,
            "visited_stage_ids": self.stage_state_machine.stage_order_until(current_stage_id),
            "run_state": str(stage_result.get("stage_state") or "REVIEW_REQUIRED"),
            "next_action": next_action,
            "blocking_reasons": blocking_reasons,
            "input_refs": input_refs,
            "output_artifact_refs": output_refs,
            "audit_refs": [event["event_id"] for event in audit["events"]],
            "safety": self.transition_guard.safety_envelope(),
            "controlled_boundary": controlled_boundary,
            "created_at": created_at,
        }
        result = {
            "runtime_controller_mode": "STAGE1_6_PREVIEW_WRAPPED",
            "run_state": run_state,
            "dispatch_queue": {"records": dispatcher.pending_tasks()},
            "audit_ledger": audit,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        result["runtime_persistence"] = self.runtime_state_repository.save_controller_result(result)
        return result

    def start_stage1_6_runtime_cycle(
        self,
        payload: Mapping[str, Any],
        *,
        created_at: str,
    ) -> dict[str, Any]:
        focus_path = Path(
            str(payload.get("stage1_6_priority_execution_plan") or "control/stage1_6_priority_execution_plan.yaml")
        )
        focus_payload = _load_yaml_mapping(focus_path)
        current_focus = (
            focus_payload.get("current_focus") if isinstance(focus_payload.get("current_focus"), Mapping) else {}
        )
        priority_id = str(current_focus.get("priority_id") or "stage1_6_runtime_cycle")
        project_id = str(payload.get("project_id") or priority_id).strip()
        if not project_id:
            raise ValueError("project_id_or_current_focus_required")

        entrypoint_id = str(payload.get("entrypoint_id") or "stage6_review_cycle_runner")
        self.entrypoint_registry.require_registered_entrypoint(entrypoint_id)
        run_id = f"RUN-{project_id}-stage1-6-runtime-cycle"
        ledger = AuditReplayLedger()
        ledger.record(
            event_type="RUN_STARTED",
            run_id=run_id,
            created_at=created_at,
            details={
                "entrypoint_id": entrypoint_id,
                "project_id": project_id,
                "runtime_controller_mode": "STAGE1_6_RUNTIME_CYCLE",
            },
        )
        ledger.record(
            event_type="CONTROL_FOCUS_LOADED",
            run_id=run_id,
            stage_id="stage1_tasking",
            created_at=created_at,
            details={
                "focus_ref": f"{focus_path.as_posix()}#current_focus",
                "priority_id": priority_id,
                "current_focus": dict(current_focus),
            },
        )

        runtime_input_artifact_diagnostics = _runtime_input_artifact_diagnostics(payload)
        if runtime_input_artifact_diagnostics:
            ledger.record(
                event_type="RUNTIME_INPUT_ARTIFACT_BLOCKER_RECORDED",
                run_id=run_id,
                stage_id="stage1_tasking",
                created_at=created_at,
                details={
                    "input_artifact_diagnostics": runtime_input_artifact_diagnostics,
                    "blocking_reasons": [
                        diagnostic["blocking_reason"]
                        for diagnostic in runtime_input_artifact_diagnostics
                        if diagnostic.get("blocking_reason")
                    ],
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
            )

        stage1_6_readiness_summary = _stage1_6_readiness_summary(payload)
        if stage1_6_readiness_summary:
            ledger.record(
                event_type="STAGE1_6_BATCH_READINESS_LEDGER_RECORDED",
                run_id=run_id,
                stage_id="stage1_tasking",
                created_at=created_at,
                details={
                    **stage1_6_readiness_summary,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
            )

        stage123_front_chain = _stage123_front_chain_result(payload, created_at=created_at)
        if stage123_front_chain:
            stage123_summary = (
                stage123_front_chain.get("summary")
                if isinstance(stage123_front_chain.get("summary"), Mapping)
                else {}
            )
            stage123_stability_summary = (
                stage123_summary.get("stage123_stability_summary")
                if isinstance(stage123_summary.get("stage123_stability_summary"), Mapping)
                else {}
            )
            ledger.record(
                event_type="STAGE123_FRONT_CHAIN_RECORDED",
                run_id=run_id,
                stage_id="stage3_parsing",
                created_at=created_at,
                details={
                    "summary": dict(stage123_summary),
                    "stage123_stability_summary": dict(stage123_stability_summary),
                    "customer_visible_allowed": False,
                    "live_execution_enabled": False,
                },
            )

        cycle_result = dict(self._stage6_cycle_runner()(**_stage6_cycle_kwargs(payload, created_at=created_at)))
        stage45_replay = _stage45_replay_result(payload, created_at=created_at)
        cycle_summary = (
            cycle_result.get("summary") if isinstance(cycle_result.get("summary"), Mapping) else {}
        )
        cycle_manifest = (
            cycle_result.get("manifest") if isinstance(cycle_result.get("manifest"), Mapping) else {}
        )
        stage4_release_field_query_summary = _stage4_release_field_query_summary(cycle_summary, cycle_manifest)
        stage4_release_chain_bootstrap_summary = _stage4_release_chain_bootstrap_summary(cycle_summary, cycle_manifest)
        output_refs = [
            *_stage123_output_refs(stage123_front_chain),
            *_stage6_cycle_output_refs(cycle_manifest),
        ]
        stage123_blocking_reasons = (
            list((stage123_front_chain.get("summary") or {}).get("blocking_reasons") or [])
            if stage123_front_chain
            else []
        )
        blocking_reasons = [
            str(reason)
            for reason in [
                *(diagnostic.get("blocking_reason") for diagnostic in runtime_input_artifact_diagnostics),
                *stage123_blocking_reasons,
                *list(cycle_result.get("blocking_reasons") or []),
                *list(cycle_summary.get("blocking_reasons") or []),
            ]
            if str(reason or "").strip()
        ]
        run_state_value = "REVIEW_REQUIRED" if cycle_result.get("safe_to_execute") else "BLOCKED"
        next_action = _stage6_cycle_next_action(
            cycle_summary,
            stage4_release_field_query_summary=stage4_release_field_query_summary,
            stage4_release_chain_bootstrap_summary=stage4_release_chain_bootstrap_summary,
            stage1_6_readiness_summary=stage1_6_readiness_summary,
        )
        dispatcher = WorkQueueDispatcher(created_at=created_at, entrypoint_registry=self.entrypoint_registry)
        dispatch_task = dispatcher.enqueue_next_action(
            run_id=run_id,
            project_id=project_id,
            current_stage_id="stage6_fact_review",
            next_action=next_action,
            input_refs=output_refs,
        )
        stage5_review_action = _stage5_calibration_review_action(cycle_summary)
        stage5_review_dispatch_task = None
        if stage5_review_action:
            stage5_review_dispatch_task = dispatcher.enqueue_next_action(
                run_id=run_id,
                project_id=project_id,
                current_stage_id="stage5_rules_evidence",
                next_action=stage5_review_action,
                input_refs=[str(payload.get("stage5_calibration_sample_json") or "")]
                if str(payload.get("stage5_calibration_sample_json") or "").strip()
                else [],
            )
        stage1_3_stability_dispatch_tasks = [
            dispatcher.enqueue_next_action(
                run_id=run_id,
                project_id=project_id,
                current_stage_id=str(action.get("current_stage_id") or "stage3_parsing"),
                next_action=action,
                input_refs=_stage1_3_stability_input_refs(payload),
            )
            for action in _stage1_3_stability_review_actions(stage1_6_readiness_summary, stage123_front_chain)
        ]
        dispatch_records = dispatcher.pending_tasks()
        ledger.record(
            event_type="STAGE6_RUNTIME_CYCLE_RECORDED",
            run_id=run_id,
            stage_id="stage6_fact_review",
            created_at=created_at,
            details={
                "safe_to_execute": bool(cycle_result.get("safe_to_execute")),
                "summary": dict(cycle_summary),
                "output_artifact_refs": output_refs,
            },
        )
        ledger.record(
            event_type="RUNTIME_BLOCKER_QUEUE_RECORDED",
            run_id=run_id,
            stage_id="stage6_fact_review",
            created_at=created_at,
            details={
                "runtime_blocker_next_subqueue_input_state": str(
                    cycle_summary.get("runtime_blocker_next_subqueue_input_state") or ""
                ),
                "runtime_blocker_controller_dispatch_task_count": int(
                    cycle_summary.get("runtime_blocker_controller_dispatch_task_count") or 0
                ),
                "runtime_blocker_dispatch_runner_followup_task_count": int(
                    cycle_summary.get("runtime_blocker_dispatch_runner_followup_task_count") or 0
                ),
            },
        )
        ledger.record(
            event_type="RUNTIME_CONTROLLER_DISPATCH_TASK_DERIVED",
            run_id=run_id,
            stage_id="stage6_fact_review",
            created_at=created_at,
            details={
                "dispatch_task_id": dispatch_task["dispatch_task_id"],
                "entrypoint_id": dispatch_task["entrypoint_id"],
                "dispatch_state": dispatch_task["dispatch_state"],
                "action_type": dispatch_task["action_type"],
                "blocking_reasons": list(dispatch_task.get("blocking_reasons") or []),
                "external_customer_action_enabled": False,
            },
        )
        if stage5_review_dispatch_task:
            ledger.record(
                event_type="STAGE5_CALIBRATION_REVIEW_TASK_DERIVED",
                run_id=run_id,
                stage_id="stage5_rules_evidence",
                created_at=created_at,
                details={
                    "dispatch_task_id": stage5_review_dispatch_task["dispatch_task_id"],
                    "dispatch_state": stage5_review_dispatch_task["dispatch_state"],
                    "action_type": stage5_review_dispatch_task["action_type"],
                    "review_family": stage5_review_dispatch_task["review_family"],
                    "review_state": stage5_review_dispatch_task["review_state"],
                    "reason": stage5_review_dispatch_task["reason"],
                    "external_customer_action_enabled": False,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
            )
        for stability_task in stage1_3_stability_dispatch_tasks:
            ledger.record(
                event_type="STAGE1_3_STABILITY_REPAIR_TASK_DERIVED",
                run_id=run_id,
                stage_id=str(stability_task.get("current_stage_id") or "stage3_parsing"),
                created_at=created_at,
                details={
                    "dispatch_task_id": stability_task["dispatch_task_id"],
                    "dispatch_state": stability_task["dispatch_state"],
                    "action_type": stability_task["action_type"],
                    "review_family": stability_task["review_family"],
                    "review_state": stability_task["review_state"],
                    "reason": stability_task["reason"],
                    "source_metric": stability_task.get("source_metric", ""),
                    "metric_count": int(stability_task.get("metric_count") or 0),
                    "operator_next_action": stability_task.get("operator_next_action", ""),
                    "stability_metric_counts": dict(stability_task.get("stability_metric_counts") or {}),
                    "external_customer_action_enabled": False,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
            )
        if int(cycle_summary.get("stage5_calibration_sample_count") or 0) > 0:
            ledger.record(
                event_type="STAGE5_CALIBRATION_LEDGER_RECORDED",
                run_id=run_id,
                stage_id="stage5_rules_evidence",
                created_at=created_at,
                details={
                    "stage5_calibration_sample_count": int(
                        cycle_summary.get("stage5_calibration_sample_count") or 0
                    ),
                    "stage5_calibration_truth_label_required_count": int(
                        cycle_summary.get("stage5_calibration_truth_label_required_count") or 0
                    ),
                    "stage5_calibration_review_bucket_counts": dict(
                        cycle_summary.get("stage5_calibration_review_bucket_counts")
                        if isinstance(cycle_summary.get("stage5_calibration_review_bucket_counts"), Mapping)
                        else {}
                    ),
                    "stage5_abcd_calibration_counts": dict(
                        cycle_summary.get("stage5_abcd_calibration_counts")
                        if isinstance(cycle_summary.get("stage5_abcd_calibration_counts"), Mapping)
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
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
            )
        if int(stage4_release_field_query_summary.get("release_field_query_project_count") or 0) > 0:
            ledger.record(
                event_type="STAGE4_RELEASE_FIELD_QUERY_LEDGER_RECORDED",
                run_id=run_id,
                stage_id="stage4_verification",
                created_at=created_at,
                details={
                    "release_field_query_project_count": int(
                        stage4_release_field_query_summary.get("release_field_query_project_count") or 0
                    ),
                    "release_field_query_state_counts": dict(
                        stage4_release_field_query_summary.get("release_field_query_state_counts") or {}
                    ),
                    "release_field_query_authorized_session_input_state_counts": dict(
                        stage4_release_field_query_summary.get(
                            "release_field_query_authorized_session_input_state_counts"
                        )
                        or {}
                    ),
                    "release_field_query_authorization_state_counts": dict(
                        stage4_release_field_query_summary.get("release_field_query_authorization_state_counts") or {}
                    ),
                    "release_field_query_operator_next_action_counts": dict(
                        stage4_release_field_query_summary.get("release_field_query_operator_next_action_counts") or {}
                    ),
                    "release_field_query_project_manager_change_ready_count": int(
                        stage4_release_field_query_summary.get(
                            "release_field_query_project_manager_change_ready_count"
                        )
                        or 0
                    ),
                    "release_field_query_project_manager_change_interpretation_counts": dict(
                        stage4_release_field_query_summary.get(
                            "release_field_query_project_manager_change_interpretation_counts"
                        )
                        or {}
                    ),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
            )
        if stage4_release_chain_bootstrap_summary:
            ledger.record(
                event_type="STAGE4_RELEASE_CHAIN_BOOTSTRAP_LEDGER_RECORDED",
                run_id=run_id,
                stage_id="stage4_verification",
                created_at=created_at,
                details={
                    **stage4_release_chain_bootstrap_summary,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
            )
        if stage45_replay:
            replay_summary = (
                stage45_replay.get("summary") if isinstance(stage45_replay.get("summary"), Mapping) else {}
            )
            ledger.record(
                event_type="STAGE45_RUNTIME_REPLAY_RECORDED",
                run_id=run_id,
                stage_id="stage4_verification",
                created_at=created_at,
                details={
                    "summary": dict(replay_summary),
                    "query_miss_is_not_clearance": True,
                    "customer_visible_allowed": False,
                },
            )
        controlled_boundary = self.transition_guard.controlled_boundary_projection()
        ledger.record(
            event_type="RUNTIME_CONTROLLED_BOUNDARY_RECORDED",
            run_id=run_id,
            stage_id="stage8_outreach",
            created_at=created_at,
            details={
                **controlled_boundary,
                "stage9_payment_delivery_refund_boundary_state": controlled_boundary[
                    "stage9_payment_delivery_refund_boundary_state"
                ],
            },
        )
        audit = ledger.to_dict()
        run_state = {
            "run_id": run_id,
            "entrypoint_id": entrypoint_id,
            "project_id": project_id,
            "current_stage_id": "stage6_fact_review",
            "visited_stage_ids": self.stage_state_machine.stage_order_until("stage6_fact_review"),
            "run_state": run_state_value,
            "next_action": next_action,
            "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
            "input_refs": _stage6_cycle_input_refs(payload, focus_path=focus_path),
            "output_artifact_refs": output_refs,
            "audit_refs": [event["event_id"] for event in audit["events"]],
            "current_focus": dict(current_focus),
            "input_artifact_diagnostics": list(runtime_input_artifact_diagnostics),
            "stage1_6_readiness_summary": dict(stage1_6_readiness_summary),
            "stage123_front_chain_summary": dict(stage123_front_chain.get("summary") or {}) if stage123_front_chain else {},
            "stage4_release_field_query_summary": dict(stage4_release_field_query_summary),
            "stage4_release_chain_bootstrap_summary": dict(stage4_release_chain_bootstrap_summary),
            "stage6_cycle_summary": dict(cycle_summary),
            "stage45_replay_summary": dict(stage45_replay.get("summary") or {}) if stage45_replay else {},
            "runtime_blocker_controller_summary": {
                "next_subqueue_input_state": str(cycle_summary.get("runtime_blocker_next_subqueue_input_state") or ""),
                "controller_queue_record_count": int(cycle_summary.get("runtime_blocker_controller_queue_record_count") or 0),
                "controller_dispatch_task_count": int(cycle_summary.get("runtime_blocker_controller_dispatch_task_count") or 0),
                "dispatch_ready_count": int(cycle_summary.get("runtime_blocker_controller_dispatch_ready_count") or 0),
                "dispatch_runner_task_count": int(cycle_summary.get("runtime_blocker_dispatch_runner_task_count") or 0),
                "dispatch_runner_followup_task_count": int(
                    cycle_summary.get("runtime_blocker_dispatch_runner_followup_task_count") or 0
                ),
                "controller_derived_dispatch_task_count": len(dispatch_records),
                "controller_derived_dispatch_ready_count": sum(
                    1 for record in dispatch_records if record.get("dispatch_state") == "READY_FOR_INTERNAL_DISPATCH"
                ),
                "controller_derived_dispatch_state_counts": _counts(
                    record.get("dispatch_state") for record in dispatch_records
                ),
                "controller_derived_dispatch_entrypoint_counts": _counts(
                    record.get("entrypoint_id") for record in dispatch_records
                ),
                "controller_derived_dispatch_review_family_counts": _counts(
                    record.get("review_family") for record in dispatch_records
                ),
                "stage1_3_repair_task_count": sum(
                    1
                    for record in dispatch_records
                    if str(record.get("review_family") or "").startswith("stage1_3_")
                ),
                "stage1_3_repair_metric_counts": _stage1_3_repair_metric_counts(dispatch_records),
                "stage1_3_repair_review_family_counts": _counts(
                    record.get("review_family")
                    for record in dispatch_records
                    if str(record.get("review_family") or "").startswith("stage1_3_")
                ),
            },
            "safety": self.transition_guard.safety_envelope(),
            "controlled_boundary": controlled_boundary,
            "created_at": created_at,
        }
        result = {
            "runtime_controller_mode": "STAGE1_6_RUNTIME_CYCLE",
            "run_state": run_state,
            "stage123_front_chain_result": stage123_front_chain,
            "stage6_cycle_result": cycle_result,
            "stage45_replay_result": stage45_replay,
            "dispatch_queue": {"records": dispatch_records},
            "audit_ledger": audit,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
        result["runtime_persistence"] = self.runtime_state_repository.save_controller_result(result)
        return result

    def _stage6_cycle_runner(self) -> Stage6CycleRunner:
        if self.stage6_cycle_runner is not None:
            return self.stage6_cycle_runner
        from storage.stage6_review_cycle_runner import run_stage6_review_cycle_runner

        return run_stage6_review_cycle_runner


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"stage1_6_priority_execution_plan_missing:{path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"stage1_6_priority_execution_plan_not_mapping:{path}")
    return dict(loaded)


def _stage6_cycle_kwargs(payload: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    key_map = {
        "batch_closeout_json": "batch_closeout_json",
        "batch_closeout_root": "batch_closeout_root",
        "runtime_blocker_next_subqueue_json": "runtime_blocker_next_subqueue_json",
        "runtime_blocker_next_subqueue_root": "runtime_blocker_next_subqueue_root",
        "stage6_review_loop_json": "stage6_review_loop_json",
        "stage6_review_loop_root": "stage6_review_loop_root",
        "stage6_review_loop_status_json": "stage6_review_loop_status_json",
        "stage6_review_loop_status_root": "stage6_review_loop_status_root",
        "release_field_query_json": "release_field_query_json",
        "release_field_query_root": "release_field_query_root",
        "release_evidence_adapter_plan_json": "release_evidence_adapter_plan_json",
        "release_evidence_adapter_plan_root": "release_evidence_adapter_plan_root",
        "gdcic_browser_readback_json": "gdcic_browser_readback_json",
        "gdcic_browser_readback_root": "gdcic_browser_readback_root",
        "original_backtrace_continuation_json": "original_backtrace_continuation_json",
        "original_backtrace_continuation_root": "original_backtrace_continuation_root",
        "stage16_p13b_continuation_json": "stage16_p13b_continuation_json",
        "stage16_p13b_continuation_root": "stage16_p13b_continuation_root",
        "stage5_calibration_sample_json": "stage5_calibration_sample_json",
        "stage5_calibration_sample_root": "stage5_calibration_sample_root",
        "stage4_backfill_followup_queue_json": "stage4_backfill_followup_queue_json",
        "stage4_backfill_followup_queue_root": "stage4_backfill_followup_queue_root",
        "stage1_6_scoreboard_json": "stage1_6_scoreboard_json",
        "output_root": "output_root",
        "baseline_evidence_state_json": "baseline_evidence_state_json",
        "cwd": "cwd",
    }
    kwargs = {
        target: payload[source]
        for source, target in key_map.items()
        if str(payload.get(source) or "").strip()
    }
    for key in ("execute_dispatch", "execute_runtime_blocker_dispatch"):
        if key in payload:
            kwargs[key] = bool(payload.get(key))
    for key in ("dispatch_max_groups", "runtime_blocker_dispatch_max_tasks"):
        if payload.get(key) is not None:
            kwargs[key] = int(payload.get(key))
    if payload.get("project_ids") is not None:
        value = payload.get("project_ids")
        kwargs["project_ids"] = list(value) if isinstance(value, (list, tuple)) else [str(value)]
    kwargs["created_at"] = created_at
    return kwargs


def _stage123_front_chain_result(payload: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    if not has_stage123_front_chain_input(payload):
        return {}
    output_root = str(payload.get("stage123_front_chain_output_root") or "").strip() or None
    source_payload = payload.get("stage123_front_chain_payload")
    if not isinstance(source_payload, Mapping):
        source_payload = payload
    return build_stage123_runtime_front_chain(source_payload, created_at=created_at, output_root=output_root)


def _stage6_cycle_next_action(
    cycle_summary: Mapping[str, Any],
    *,
    stage4_release_field_query_summary: Mapping[str, Any] | None = None,
    stage4_release_chain_bootstrap_summary: Mapping[str, Any] | None = None,
    stage1_6_readiness_summary: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    followup_type_counts = (
        cycle_summary.get("runtime_blocker_dispatch_runner_followup_task_type_counts")
        if isinstance(cycle_summary.get("runtime_blocker_dispatch_runner_followup_task_type_counts"), Mapping)
        else {}
    )
    if int(followup_type_counts.get("RUN_GUANGDONG_LOCAL_FIELD_QUERY_WITH_GDCIC_BROWSER_READBACK") or 0) > 0:
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": "guangdong_local_field_query_probe",
            "reason": "runtime_blocker_field_query_followup_ready",
        }
    field_operator_counts = (
        stage4_release_field_query_summary.get("release_field_query_operator_next_action_counts")
        if isinstance(stage4_release_field_query_summary, Mapping)
        and isinstance(stage4_release_field_query_summary.get("release_field_query_operator_next_action_counts"), Mapping)
        else {}
    )
    field_authorization_counts = (
        stage4_release_field_query_summary.get("release_field_query_authorization_state_counts")
        if isinstance(stage4_release_field_query_summary, Mapping)
        and isinstance(stage4_release_field_query_summary.get("release_field_query_authorization_state_counts"), Mapping)
        else {}
    )
    field_state_counts = (
        stage4_release_field_query_summary.get("release_field_query_state_counts")
        if isinstance(stage4_release_field_query_summary, Mapping)
        and isinstance(stage4_release_field_query_summary.get("release_field_query_state_counts"), Mapping)
        else {}
    )
    if int(field_operator_counts.get("provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun") or 0) > 0 or int(
        field_authorization_counts.get("LOGIN_OR_SSO_REQUIRED") or 0
    ) > 0 or int(field_state_counts.get("NEEDS_BROWSER") or 0) > 0:
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": "guangdong_local_field_query_probe",
            "reason": "stage4_release_field_query_authorized_readback_required",
        }
    if int(followup_type_counts.get("RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT") or 0) > 0:
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": "stage6_review_cycle_runner",
            "reason": "runtime_blocker_retry_followup_waiting_for_reopen_input",
        }
    if int(followup_type_counts.get("BUILD_FALLBACK_SOURCE_ADAPTER_PLAN") or 0) > 0:
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": "stage4_release_evidence_bridge_builder",
            "reason": "runtime_blocker_fallback_source_plan_required",
        }
    chain_next_counts = (
        stage4_release_chain_bootstrap_summary.get("stage4_release_chain_next_action_counts")
        if isinstance(stage4_release_chain_bootstrap_summary, Mapping)
        and isinstance(stage4_release_chain_bootstrap_summary.get("stage4_release_chain_next_action_counts"), Mapping)
        else {}
    )
    if int(chain_next_counts.get("rerun_stage6_review_cycle_after_reopen_input_is_recorded") or 0) > 0:
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": "stage6_review_cycle_runner",
            "reason": "stage4_release_chain_reopen_input_then_rerun",
        }
    readiness_next_counts = (
        stage1_6_readiness_summary.get("stage1_6_next_action_counts")
        if isinstance(stage1_6_readiness_summary, Mapping)
        and isinstance(stage1_6_readiness_summary.get("stage1_6_next_action_counts"), Mapping)
        else {}
    )
    gap_next_counts = (
        stage1_6_readiness_summary.get("stage1_6_gap_next_action_counts")
        if isinstance(stage1_6_readiness_summary, Mapping)
        and isinstance(stage1_6_readiness_summary.get("stage1_6_gap_next_action_counts"), Mapping)
        else {}
    )
    if int(readiness_next_counts.get("run_stage4_release_evidence_bridge_builder") or 0) > 0 or int(
        gap_next_counts.get("run_stage4_release_evidence_bridge_builder") or 0
    ) > 0:
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": "stage4_release_evidence_bridge_builder",
            "reason": "stage1_6_readiness_release_evidence_bridge_required",
        }
    local_region_resolution_required = _local_authority_region_resolution_required_count(cycle_summary)
    if local_region_resolution_required > 0:
        return {
            "action_type": "REVIEW",
            "entrypoint_id": "",
            "reason": "local_authority_region_resolution_required_before_public_readback",
            "review_family": "stage4_local_authority_region_resolution_review",
            "review_state": "WAITING_FOR_LOCAL_AUTHORITY_REGION_RESOLUTION",
            "dispatch_task_id_suffix": "local-authority-region-resolution-review",
            "source_metric": "LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED",
            "metric_count": str(local_region_resolution_required),
            "operator_next_action": "resolve_local_authority_region_before_retrying_public_readback",
        }
    if int(cycle_summary.get("runtime_blocker_dispatch_runner_followup_task_count") or 0) > 0:
        return {
            "action_type": "REVIEW",
            "entrypoint_id": "",
            "reason": "runtime_blocker_non_executable_followup_requires_operator_review",
        }
    if int(cycle_summary.get("runtime_blocker_controller_dispatch_ready_count") or 0) > 0:
        return {
            "action_type": "ENTRYPOINT",
            "entrypoint_id": "stage6_review_cycle_runner",
            "reason": "runtime_blocker_controller_dispatch_ready",
        }
    return {
        "action_type": "REVIEW",
        "entrypoint_id": "",
        "reason": "stage1_6_runtime_cycle_operator_review_or_no_dispatch_ready",
    }


def _local_authority_region_resolution_required_count(cycle_summary: Mapping[str, Any]) -> int:
    primary = (
        cycle_summary.get("stage5_operational_primary_track_counts_from_scoreboard")
        if isinstance(cycle_summary.get("stage5_operational_primary_track_counts_from_scoreboard"), Mapping)
        else {}
    )
    review_buckets = (
        cycle_summary.get("stage5_operational_review_bucket_counts_from_scoreboard")
        if isinstance(cycle_summary.get("stage5_operational_review_bucket_counts_from_scoreboard"), Mapping)
        else {}
    )
    resolution = (
        cycle_summary.get("p13b_local_authority_resolution_state_counts_from_scoreboard")
        if isinstance(cycle_summary.get("p13b_local_authority_resolution_state_counts_from_scoreboard"), Mapping)
        else {}
    )
    return max(
        int(primary.get("local_authority_region_resolution_required") or 0),
        int(review_buckets.get("LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED_REVIEW") or 0),
        int(resolution.get("LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED") or 0),
    )


def _stage5_calibration_review_action(cycle_summary: Mapping[str, Any]) -> dict[str, str]:
    if int(cycle_summary.get("stage5_calibration_truth_label_required_count") or 0) <= 0:
        return {}
    review_family_counts = (
        cycle_summary.get("stage5_calibration_review_family_counts")
        if isinstance(cycle_summary.get("stage5_calibration_review_family_counts"), Mapping)
        else {}
    )
    primary_family = next((str(key) for key, count in review_family_counts.items() if int(count or 0) > 0), "")
    return {
        "action_type": "REVIEW",
        "entrypoint_id": "",
        "reason": "stage5_calibration_truth_label_required",
        "review_family": primary_family or "stage5_calibration_truth_label_review",
        "review_state": "WAITING_FOR_STAGE5_TRUTH_LABEL_REVIEW",
        "dispatch_task_id_suffix": "stage5-calibration-truth-label-review",
    }


def _stage1_3_stability_review_actions(
    stage1_6_readiness_summary: Mapping[str, Any],
    stage123_front_chain: Mapping[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    stability = dict(stage1_6_readiness_summary.get("stage1_3_stability_summary") or {})
    if not stability and stage123_front_chain:
        stage123_summary = (
            stage123_front_chain.get("summary")
            if isinstance(stage123_front_chain.get("summary"), Mapping)
            else {}
        )
        stability = dict(stage123_summary.get("stage123_stability_summary") or {})
    stability_metric_counts = {
        str(key): int(value or 0)
        for key, value in stability.items()
        if str(key or "").endswith("_count") and int(value or 0) > 0
    }
    specs = (
        (
            "stage2_attachment_snapshot_missing_count",
            "stage1_3_attachment_snapshot_repair",
            "WAITING_FOR_STAGE2_ATTACHMENT_SNAPSHOT_REPAIR",
            "stage2-attachment-snapshot-repair",
            "stage2_ingestion",
            "补齐附件 snapshot，并固化 URL、采集时间、hash 与 readback 线索。",
        ),
        (
            "attachment_snapshot_readback_missing_count",
            "stage1_3_attachment_snapshot_readback_repair",
            "WAITING_FOR_STAGE2_ATTACHMENT_READBACK_REPAIR",
            "stage2-attachment-readback-repair",
            "stage2_ingestion",
            "补齐附件 snapshot readback；缺读回只能保留证据不足，不得外推排除性结论。",
        ),
        (
            "stage3_attachment_ocr_pending_count",
            "stage1_3_attachment_ocr_repair",
            "WAITING_FOR_STAGE3_ATTACHMENT_OCR_REPAIR",
            "stage3-attachment-ocr-repair",
            "stage3_parsing",
            "对待处理附件执行 OCR/结构化回读，并回灌解析字段与审计链。",
        ),
        (
            "stage3_responsible_role_gap_count",
            "stage1_3_responsible_role_review",
            "WAITING_FOR_STAGE3_RESPONSIBLE_ROLE_REVIEW",
            "stage3-responsible-role-review",
            "stage3_parsing",
            "复核负责人角色字段；公开注册信息只能表述匹配/不匹配。",
        ),
        (
            "stage3_parse_blocker_count",
            "stage1_3_parse_blocker_review",
            "WAITING_FOR_STAGE3_PARSE_BLOCKER_REVIEW",
            "stage3-parse-blocker-review",
            "stage3_parsing",
            "定位解析阻断来源并生成可回放修复任务。",
        ),
    )
    for metric, family, state, suffix, stage_id, operator_next_action in specs:
        metric_count = int(stability.get(metric) or 0)
        if metric_count <= 0:
            continue
        actions.append(
            {
                "action_type": "REVIEW",
                "entrypoint_id": "stage1_3_repair_worker",
                "reason": metric,
                "review_family": family,
                "review_state": state,
                "dispatch_task_id_suffix": suffix,
                "current_stage_id": stage_id,
                "source_metric": metric,
                "metric_count": metric_count,
                "stability_metric_counts": dict(stability_metric_counts),
                "operator_next_action": operator_next_action,
            }
        )
    return actions


def _stage1_3_repair_metric_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if not str(record.get("review_family") or "").startswith("stage1_3_"):
            continue
        metric = str(record.get("source_metric") or record.get("reason") or "").strip()
        if not metric:
            continue
        counts[metric] = counts.get(metric, 0) + int(record.get("metric_count") or 0)
    return counts


def _stage1_3_stability_input_refs(payload: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in (
        "stage1_6_readiness_json",
        "stage1_6_gap_summary_json",
        "stage2_capture_json",
        "stage3_parse_json",
    ):
        text = str(payload.get(key) or "").strip()
        if text:
            refs.append(text)
    return refs


def _stage4_release_field_query_summary(
    cycle_summary: Mapping[str, Any],
    cycle_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    projection_records = _operator_projection_records(cycle_manifest)
    record_based_summary = _stage4_release_field_query_summary_from_records(projection_records)
    project_count = int(
        cycle_summary.get("release_field_query_project_count")
        or record_based_summary.get("release_field_query_project_count")
        or 0
    )
    if project_count <= 0:
        return {}
    return {
        "release_field_query_project_count": project_count,
        "release_field_query_state_counts": _summary_or_record_counts(
            cycle_summary,
            record_based_summary,
            "release_field_query_state_counts",
        ),
        "release_field_query_authorized_session_input_state_counts": _summary_or_record_counts(
            cycle_summary,
            record_based_summary,
            "release_field_query_authorized_session_input_state_counts",
        ),
        "release_field_query_authorization_state_counts": _summary_or_record_counts(
            cycle_summary,
            record_based_summary,
            "release_field_query_authorization_state_counts",
        ),
        "release_field_query_operator_next_action_counts": _summary_or_record_counts(
            cycle_summary,
            record_based_summary,
            "release_field_query_operator_next_action_counts",
        ),
        "release_field_query_project_manager_change_ready_count": int(
            cycle_summary.get("release_field_query_project_manager_change_ready_count")
            or record_based_summary.get("release_field_query_project_manager_change_ready_count")
            or 0
        ),
        "release_field_query_project_manager_change_interpretation_counts": _summary_or_record_counts(
            cycle_summary,
            record_based_summary,
            "release_field_query_project_manager_change_interpretation_counts",
        ),
        "query_miss_is_not_clearance": True,
    }


def _stage4_release_chain_bootstrap_summary(
    cycle_summary: Mapping[str, Any],
    cycle_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    source_refs = {
        "source_release_evidence_adapter_plan_json": str(
            cycle_manifest.get("source_release_evidence_adapter_plan_json") or ""
        ),
        "source_original_backtrace_continuation_json": str(
            cycle_manifest.get("source_original_backtrace_continuation_json") or ""
        ),
        "source_stage16_p13b_continuation_json": str(
            cycle_manifest.get("source_stage16_p13b_continuation_json") or ""
        ),
        "source_gdcic_browser_readback_json": str(
            cycle_manifest.get("source_gdcic_browser_readback_json") or ""
        ),
        "derived_release_field_query_from_gdcic_browser_readback_json": str(
            cycle_manifest.get("derived_release_field_query_from_gdcic_browser_readback_json") or ""
        ),
    }
    active_source_refs = {key: value for key, value in source_refs.items() if value}
    release_adapter_plan_summary = _release_adapter_plan_project_code_recall_summary(
        active_source_refs.get("source_release_evidence_adapter_plan_json")
    )
    gdcic_authorized_readback_summary = _gdcic_authorized_readback_summary(
        active_source_refs.get("source_gdcic_browser_readback_json")
    )
    records = _operator_projection_records(cycle_manifest)
    release_chain_records = _release_chain_projection_records(records)
    runtime_blockers = [
        blocker
        for record in release_chain_records
        for blocker in _as_list(record.get("runtime_blocker_ledger_records"))
        if isinstance(blocker, Mapping)
    ]
    if not active_source_refs and not release_chain_records and not runtime_blockers:
        return {}
    return {
        "stage4_release_chain_bootstrap_source_kind": str(
            cycle_summary.get("stage6_review_cycle_bootstrap_source_kind") or ""
        ),
        "stage4_release_chain_bootstrap_selected_handler_kind": str(
            cycle_summary.get("stage6_review_cycle_bootstrap_selected_handler_kind") or ""
        ),
        "stage4_release_chain_input_refs": active_source_refs,
        "stage4_release_adapter_plan_project_code_recall_summary": release_adapter_plan_summary,
        "stage4_gdcic_authorized_readback_summary": gdcic_authorized_readback_summary,
        "stage4_release_chain_project_count": len(
            {
                str(record.get("project_id") or "").strip()
                for record in release_chain_records
                if str(record.get("project_id") or "").strip()
            }
        ),
        "stage4_release_chain_dispatch_task_type_counts": _counts(
            record.get("dispatch_task_type") for record in release_chain_records
        ),
        "stage4_release_chain_next_action_counts": _counts(
            record.get("next_recommended_action") for record in release_chain_records
        ),
        "stage4_release_chain_manual_action_family_counts": _counts(
            record.get("next_cycle_manual_only_action_family") for record in release_chain_records
        ),
        "stage4_release_chain_loop_terminal_state_counts": _counts(
            record.get("loop_terminal_state") for record in release_chain_records
        ),
        "stage4_release_chain_runtime_blocker_ledger_count": len(runtime_blockers),
        "stage4_release_chain_runtime_blocker_state_counts": _counts(
            blocker.get("blocker_state") for blocker in runtime_blockers
        ),
        "query_miss_is_not_clearance": True,
    }


def _release_adapter_plan_project_code_recall_summary(path_value: Any) -> dict[str, Any]:
    payload = _json_payload(path_value)
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), Mapping) else payload.get("summary")
    if not isinstance(summary, Mapping):
        return {}
    recall = summary.get("stage4_release_adapter_plan_project_code_recall_summary")
    return dict(recall) if isinstance(recall, Mapping) else {}


def _gdcic_authorized_readback_summary(path_value: Any) -> dict[str, Any]:
    payload = _json_payload(path_value)
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), Mapping) else payload.get("summary")
    if not isinstance(summary, Mapping):
        return {}
    readback_records = [
        dict(record)
        for record in _as_list(manifest.get("browser_readback_records"))
        if isinstance(record, Mapping)
    ]
    project_manager_change_records = [
        source_record
        for record in readback_records
        if str(record.get("release_evidence_target_type") or "") == "project_manager_change_notice"
        and str(record.get("adapter_result_state") or "") == "MATCHED"
        for source_record in _as_list(record.get("records"))
        if isinstance(source_record, Mapping)
    ]
    return {
        "source_gdcic_browser_readback_json": str(path_value or ""),
        "authorized_session_input_state": str(summary.get("authorized_session_input_state") or ""),
        "gdcic_authorized_session_overall_state": str(
            summary.get("gdcic_authorized_session_overall_state") or ""
        ),
        "gdcic_browser_readback_task_count": int(summary.get("gdcic_browser_readback_task_count") or 0),
        "gdcic_browser_readback_record_count": int(summary.get("gdcic_browser_readback_record_count") or 0),
        "gdcic_browser_readback_ready_count": int(summary.get("gdcic_browser_readback_ready_count") or 0),
        "gdcic_browser_login_or_sso_required_count": int(
            summary.get("gdcic_browser_login_or_sso_required_count") or 0
        ),
        "project_manager_change_ready_count": int(
            summary.get("project_manager_change_ready_count") or len(project_manager_change_records)
        ),
        "project_manager_change_interpretation_counts": dict(
            summary.get("project_manager_change_interpretation_counts")
            if isinstance(summary.get("project_manager_change_interpretation_counts"), Mapping)
            else _counts(
                record.get("project_manager_change_release_window_interpretation")
                for record in project_manager_change_records
            )
        ),
        "project_manager_change_date_count": int(
            summary.get("project_manager_change_date_count")
            or sum(1 for record in project_manager_change_records if str(record.get("change_date") or "").strip())
        ),
        "project_manager_change_original_manager_matches_query_count": int(
            summary.get("project_manager_change_original_manager_matches_query_count")
            or sum(1 for record in project_manager_change_records if bool(record.get("original_project_manager_matches_query_person")))
        ),
        "project_manager_change_new_manager_matches_query_count": int(
            summary.get("project_manager_change_new_manager_matches_query_count")
            or sum(1 for record in project_manager_change_records if bool(record.get("new_project_manager_matches_query_person")))
        ),
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _release_chain_projection_records(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        task_type = str(record.get("dispatch_task_type") or "")
        action_family = str(record.get("next_cycle_manual_only_action_family") or "")
        next_task_type = str(record.get("next_task_type") or "")
        blocker_scopes = {
            str(blocker.get("ledger_scope") or "")
            for blocker in _as_list(record.get("runtime_blocker_ledger_records"))
            if isinstance(blocker, Mapping)
        }
        if (
            "P13B" in task_type
            or "P13B" in action_family
            or "ORIGINAL" in task_type
            or "original" in next_task_type
            or "p13b" in next_task_type
            or "p13b_continuation" in blocker_scopes
            or "p13b_original_readback" in blocker_scopes
        ):
            out.append(dict(record))
    return out


def _operator_projection_records(cycle_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    status_table = cycle_manifest.get("operator_projection_status_table")
    if not isinstance(status_table, Mapping):
        return []
    records = status_table.get("records")
    if not isinstance(records, list):
        return []
    return [dict(record) for record in records if isinstance(record, Mapping)]


def _stage4_release_field_query_summary_from_records(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    direct_records = [
        record for record in records if str(record.get("release_field_query_state") or "").strip()
    ]
    blocker_records = [
        dict(blocker)
        for record in records
        for blocker in _as_list(record.get("runtime_blocker_ledger_records"))
        if isinstance(blocker, Mapping)
        and str(blocker.get("ledger_scope") or "") == "stage4_release_evidence_query"
    ]
    if not direct_records and not blocker_records:
        return {}
    project_ids = {
        str(record.get("project_id") or "").strip()
        for record in [*direct_records, *blocker_records]
        if str(record.get("project_id") or "").strip()
    }
    return {
        "release_field_query_project_count": len(project_ids) if project_ids else len(direct_records) + len(blocker_records),
        "release_field_query_state_counts": _counts(
            [
                *(record.get("release_field_query_state") for record in direct_records),
                *(record.get("release_field_query_state") for record in blocker_records),
            ]
        ),
        "release_field_query_authorized_session_input_state_counts": _merge_count_mappings(
            record.get("release_field_query_authorized_session_input_state_counts")
            for record in direct_records
        )
        or _counts(
            _release_field_query_session_input_state_from_blocker(record) for record in blocker_records
        ),
        "release_field_query_authorization_state_counts": _merge_count_mappings(
            record.get("release_field_query_authorization_state_counts") for record in direct_records
        )
        or _counts(
            _release_field_query_authorization_state_from_blocker(record) for record in blocker_records
        ),
        "release_field_query_operator_next_action_counts": _counts(
            action
            for _, action in _dedupe_project_actions(
                [
                    *(
                        (record.get("project_id"), action)
                        for record in direct_records
                        for action in _as_list(record.get("release_field_query_operator_next_actions"))
                    ),
                    *((record.get("project_id"), record.get("operator_next_action")) for record in blocker_records),
                ]
            )
        ),
        "release_field_query_project_manager_change_ready_count": sum(
            1
            for record in direct_records
            for summary in _as_list(record.get("release_field_query_source_hit_summaries"))
            if isinstance(summary, Mapping)
            and _as_list(summary.get("project_manager_change_interpretations"))
        ),
        "release_field_query_project_manager_change_interpretation_counts": _counts(
            interpretation
            for record in direct_records
            for summary in _as_list(record.get("release_field_query_source_hit_summaries"))
            if isinstance(summary, Mapping)
            for interpretation in _as_list(summary.get("project_manager_change_interpretations"))
        ),
    }


def _dedupe_project_actions(actions: list[tuple[Any, Any]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for project_id, action in actions:
        item = (str(project_id or "").strip(), str(action or "").strip())
        if not item[1] or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _release_field_query_session_input_state_from_blocker(record: Mapping[str, Any]) -> str:
    required_input = [str(value) for value in _as_list(record.get("required_input"))]
    if "authorized_browser_storage_state_or_user_data_dir" in required_input:
        return "NO_AUTHORIZED_SESSION_INPUT"
    return ""


def _release_field_query_authorization_state_from_blocker(record: Mapping[str, Any]) -> str:
    blocker_reason = str(record.get("blocker_reason") or "").lower()
    blocker_state = str(record.get("blocker_state") or "").lower()
    if "login_or_sso_required" in blocker_reason or "authorization_hold" in blocker_state:
        return "LOGIN_OR_SSO_REQUIRED"
    return ""


def _summary_or_record_counts(
    cycle_summary: Mapping[str, Any],
    record_based_summary: Mapping[str, Any],
    key: str,
) -> dict[str, int]:
    summary_counts = cycle_summary.get(key)
    if isinstance(summary_counts, Mapping) and summary_counts:
        return {str(name): int(count or 0) for name, count in summary_counts.items()}
    record_counts = record_based_summary.get(key)
    if isinstance(record_counts, Mapping):
        return {str(name): int(count or 0) for name, count in record_counts.items()}
    return {}


def _merge_count_mappings(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key, count in value.items():
            text = str(key or "").strip()
            if not text:
                continue
            out[text] = out.get(text, 0) + int(count or 0)
    return out


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _stage45_replay_result(payload: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    samples = payload.get("stage45_replay_samples")
    sample_json = str(payload.get("stage45_replay_samples_json") or "").strip()
    if samples in (None, "", [], {}) and not sample_json:
        return {}
    output_root = str(payload.get("stage45_replay_output_root") or "").strip() or None
    return build_stage45_runtime_sample_replay(
        samples if samples not in (None, "", [], {}) else sample_json,
        created_at=created_at,
        output_root=output_root,
    )


def _stage6_cycle_input_refs(payload: Mapping[str, Any], *, focus_path: Path) -> list[str]:
    refs = [f"{focus_path.as_posix()}#current_focus"]
    for key in (
        "batch_closeout_json",
        "runtime_blocker_next_subqueue_json",
        "stage6_review_loop_json",
        "stage6_review_loop_status_json",
        "release_field_query_json",
        "release_evidence_adapter_plan_json",
        "gdcic_browser_readback_json",
        "original_backtrace_continuation_json",
        "stage16_p13b_continuation_json",
        "stage5_calibration_sample_json",
        "stage4_backfill_followup_queue_json",
        "stage45_replay_samples_json",
        "stage1_6_readiness_json",
        "stage1_6_gap_summary_json",
        "stage1_6_scoreboard_json",
        "stage1_6_real_public_pressure_report_json",
        "baseline_evidence_state_json",
        "stage1_market_scan_json",
        "stage1_source_blueprint_json",
        "stage2_capture_json",
        "stage3_parse_json",
    ):
        text = str(payload.get(key) or "").strip()
        if text:
            refs.append(text)
    return refs


def _stage1_6_readiness_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    readiness_payload = _stage1_6_table_payload(payload.get("stage1_6_readiness_json"))
    gap_payload = _stage1_6_table_payload(payload.get("stage1_6_gap_summary_json"))
    pressure_payload = _stage1_6_pressure_report_payload(payload.get("stage1_6_real_public_pressure_report_json"))
    pressure_manifest = (
        pressure_payload.get("manifest")
        if isinstance(pressure_payload.get("manifest"), Mapping)
        else {}
    )
    readiness_records = _stage1_6_table_records(payload.get("stage1_6_readiness_json"))
    gap_records = _stage1_6_table_records(payload.get("stage1_6_gap_summary_json"))
    if not readiness_records:
        readiness_records = [
            dict(record)
            for record in _as_list(pressure_manifest.get("stage1_6_readiness_records"))
            if isinstance(record, Mapping)
        ]
    if not gap_records:
        gap_records = [
            dict(record)
            for record in _as_list(pressure_manifest.get("stage1_6_gap_summary_records"))
            if isinstance(record, Mapping)
        ]
    if not readiness_records and not gap_records:
        return {}
    readiness_source_summary = (
        readiness_payload.get("summary") if isinstance(readiness_payload.get("summary"), Mapping) else {}
    )
    if not readiness_source_summary:
        readiness_source_summary = (
            pressure_manifest.get("summary")
            if isinstance(pressure_manifest.get("summary"), Mapping)
            else pressure_payload.get("summary")
            if isinstance(pressure_payload.get("summary"), Mapping)
            else {}
        )
    gap_source_summary = gap_payload.get("summary") if isinstance(gap_payload.get("summary"), Mapping) else {}
    readiness_state_counts = _counts(
        record.get("stage1_6_readiness_state") for record in readiness_records
    )
    bottleneck_stage_counts = _counts(record.get("bottleneck_stage") for record in readiness_records)
    gap_family_counts = _counts(record.get("gap_family") for record in gap_records)
    gap_state_counts = _counts(record.get("gap_state") for record in gap_records)
    gap_value_counts = _counts(record.get("gap_value") for record in gap_records)
    readiness_next_action_counts = _counts(
        record.get("next_recommended_action") or record.get("recommended_next_action")
        for record in readiness_records
    )
    gap_next_action_counts = _counts(record.get("next_action") for record in gap_records)
    stage1_3_stability = _stage1_3_stability_from_readiness_ledger(
        readiness_records,
        readiness_source_summary,
    )
    stage4_project_code_recall_summary = (
        readiness_source_summary.get("stage4_release_adapter_bridge_project_code_recall_summary")
        if isinstance(
            readiness_source_summary.get("stage4_release_adapter_bridge_project_code_recall_summary"),
            Mapping,
        )
        else {}
    )
    return {
        "stage1_6_readiness_json": str(payload.get("stage1_6_readiness_json") or ""),
        "stage1_6_gap_summary_json": str(payload.get("stage1_6_gap_summary_json") or ""),
        "stage1_6_real_public_pressure_report_json": str(
            payload.get("stage1_6_real_public_pressure_report_json") or ""
        ),
        "stage1_6_pressure_coverage_state": str(readiness_source_summary.get("coverage_state") or ""),
        "stage1_6_pressure_candidate_count": int(readiness_source_summary.get("candidate_count") or 0),
        "stage1_6_pressure_closed_loop_results_count": int(
            readiness_source_summary.get("closed_loop_results_count") or 0
        ),
        "stage1_6_pressure_stage5_calibration_sample_count": int(
            readiness_source_summary.get("stage5_calibration_sample_count") or 0
        ),
        "stage1_6_readiness_record_count": int(
            readiness_source_summary.get("stage1_6_readiness_record_count") or len(readiness_records)
        ),
        "stage1_6_gap_summary_record_count": int(
            gap_source_summary.get("stage1_6_gap_summary_record_count")
            or readiness_source_summary.get("stage1_6_gap_summary_record_count")
            or len(gap_records)
        ),
        "stage1_6_readiness_state_counts": readiness_state_counts,
        "stage1_6_bottleneck_stage_counts": bottleneck_stage_counts,
        "stage1_6_gap_family_counts": gap_family_counts,
        "stage1_6_gap_state_counts": gap_state_counts,
        "stage1_6_gap_value_counts": gap_value_counts,
        "stage1_6_next_action_counts": readiness_next_action_counts,
        "stage1_6_gap_next_action_counts": gap_next_action_counts,
        "stage1_3_stability_summary": stage1_3_stability,
        "stage4_release_adapter_bridge_project_code_recall_summary": dict(
            stage4_project_code_recall_summary
        ),
        "stage1_6_internal_ready_count": int(readiness_state_counts.get("STAGE1_6_INTERNAL_READY") or 0),
        "stage1_6_review_or_blocked_count": sum(
            count
            for state, count in readiness_state_counts.items()
            if state != "STAGE1_6_INTERNAL_READY"
        ),
        "stage1_6_batch_regression_ledger_state": "READY",
    }


_STAGE1_3_STABILITY_LEDGER_KEYS = (
    "stage2_attachment_capture_attempted_count",
    "stage2_attachment_snapshot_count",
    "stage2_attachment_snapshot_missing_count",
    "attachment_snapshot_readback_missing_count",
    "stage3_attachment_ocr_required_count",
    "stage3_attachment_ocr_extracted_count",
    "stage3_attachment_ocr_pending_count",
    "attachment_text_cache_hit_count",
    "stage3_responsible_role_gap_count",
    "stage3_parse_blocker_count",
)


def _stage1_3_stability_from_readiness_ledger(
    readiness_records: list[Mapping[str, Any]],
    readiness_source_summary: Mapping[str, Any],
) -> dict[str, int]:
    source_summary = readiness_source_summary.get("stage1_3_stability_summary")
    if isinstance(source_summary, Mapping) and source_summary:
        return {key: int(source_summary.get(key) or 0) for key in _STAGE1_3_STABILITY_LEDGER_KEYS}
    return {
        key: sum(int(record.get(key) or 0) for record in readiness_records)
        for key in _STAGE1_3_STABILITY_LEDGER_KEYS
    }


def _stage1_6_table_payload(path_value: Any) -> dict[str, Any]:
    return _json_payload(path_value)


def _stage1_6_pressure_report_payload(path_value: Any) -> dict[str, Any]:
    return _json_payload(path_value)


def _json_payload(path_value: Any) -> dict[str, Any]:
    path_text = str(path_value or "").strip()
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _runtime_input_artifact_diagnostics(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for field_name in (
        "release_evidence_adapter_plan_json",
        "gdcic_browser_readback_json",
        "stage1_6_readiness_json",
        "stage1_6_gap_summary_json",
        "stage1_6_real_public_pressure_report_json",
        "stage4_backfill_followup_queue_json",
    ):
        diagnostic = _json_payload_diagnostic(payload.get(field_name), field_name=field_name)
        if diagnostic:
            diagnostics.append(diagnostic)
    return diagnostics


def _json_payload_diagnostic(path_value: Any, *, field_name: str) -> dict[str, Any]:
    path_text = str(path_value or "").strip()
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        code = "BLOCKED_INPUT_MISSING"
        detail = "input_artifact_path_missing"
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            code = "BLOCKED_INPUT_INVALID_JSON"
            detail = f"{type(exc).__name__}: {exc}"
        else:
            if isinstance(loaded, Mapping):
                return {}
            code = "BLOCKED_INPUT_NOT_OBJECT"
            detail = f"json_root_type={type(loaded).__name__}"
    return {
        "blocker_code": code,
        "blocking_reason": f"{code}:{field_name}",
        "input_field": field_name,
        "input_path": path_text,
        "detail": detail,
    }


def _stage1_6_table_records(path_value: Any) -> list[dict[str, Any]]:
    payload = _stage1_6_table_payload(path_value)
    records = payload.get("records") if isinstance(payload, Mapping) else []
    if not isinstance(records, list):
        return []
    return [dict(record) for record in records if isinstance(record, Mapping)]


def _stage123_output_refs(stage123_front_chain: Mapping[str, Any]) -> list[str]:
    if not stage123_front_chain:
        return []
    manifest = stage123_front_chain.get("manifest") if isinstance(stage123_front_chain.get("manifest"), Mapping) else {}
    refs = [
        str(ref)
        for record in list(manifest.get("stage2_capture_records") or []) + list(manifest.get("stage3_parse_records") or [])
        if isinstance(record, Mapping)
        for ref in list(record.get("output_artifact_refs") or [])
        if str(ref or "").strip()
    ]
    if not refs:
        refs.append("tmp/evaluation-real-samples/stage123-runtime-front-chain-v1/stage123-runtime-front-chain-v1.json")
    return list(dict.fromkeys(refs))


def _stage6_cycle_output_refs(cycle_manifest: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in (
        "stage6_fact_package_json",
        "stage6_review_action_dispatch_json",
        "stage6_review_action_dispatch_runner_json",
        "runtime_blocker_next_subqueue_json",
        "runtime_blocker_subqueue_controller_json",
        "runtime_blocker_controller_dispatch_json",
        "runtime_blocker_controller_dispatch_runner_json",
        "runtime_blocker_worker_followup_queue_json",
        "derived_release_field_query_from_gdcic_browser_readback_json",
        "operator_projection_status_table_json",
    ):
        text = str(cycle_manifest.get(key) or "").strip()
        if text:
            refs.append(text)
    return refs


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        out[text] = out.get(text, 0) + 1
    return out
