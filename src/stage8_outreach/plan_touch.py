# Stage: stage8_outreach
# Internal helpers for outreach_plan / touch_record projection.

from __future__ import annotations

from typing import Any, Mapping

from stage8_outreach.candidate_compliance import build_governed_metadata
from stage8_outreach.execution_outbox import (
    OUTBOX_ID_INPUT_KEY,
    OUTBOX_READINESS_INPUT_KEY,
    OUTBOX_SNAPSHOT_INPUT_KEY,
    build_outbox_readiness_summary,
)
from shared.utils import build_id, ensure_enum, ensure_list


def required_runtime_value(runtime_state: Any, field_name: str) -> Any:
    value = runtime_state.resolve(field_name)
    if value is None:
        raise ValueError(f"Stage8 formal policy derivation missing {field_name}")
    return value


def project_plan_status(
    *,
    runtime_state: Any,
    execution_resolution_blocked: bool,
    execution_resolution_review: bool,
    source_merge_review_required: bool,
    source_conflict_present: bool,
    run_mode: str,
    approval_state: str,
) -> str:
    plan_status = runtime_state.resolve("plan_status", "DRAFT")
    if execution_resolution_blocked or runtime_state.permission_blocked_reasons:
        plan_status = "BLOCKED"
    elif (execution_resolution_review or runtime_state.permission_review_reasons) and plan_status == "APPROVED":
        plan_status = "REVIEW_REQUIRED"
    if source_merge_review_required and plan_status not in ("BLOCKED", "SCHEDULED"):
        plan_status = "REVIEW_REQUIRED"
    if source_conflict_present and plan_status not in ("BLOCKED", "SCHEDULED"):
        plan_status = "REVIEW_REQUIRED"
    if run_mode in ("APPROVAL_RUN", "REAL_RUN") and approval_state != "APPROVED":
        plan_status = "REVIEW_REQUIRED"
    return str(plan_status)


def project_plan_requires_manual_review(
    *,
    contact_target: Mapping[str, Any],
    plan_status: str,
    approval_state: str,
) -> bool:
    return bool(
        contact_target.get("requires_manual_review")
        or plan_status in ("REVIEW_REQUIRED", "BLOCKED")
        or approval_state == "PENDING"
    )


def collect_writeback_projection(runtime_state: Any) -> dict[str, Any]:
    writeback_required = bool(required_runtime_value(runtime_state, "writeback_required"))
    writeback_targets = ensure_list(required_runtime_value(runtime_state, "writeback_targets"))
    writeback_target = runtime_state.resolve("writeback_target_optional")
    if writeback_target in (None, "") and writeback_targets:
        writeback_target = writeback_targets[0]
    return {
        "writeback_required": writeback_required,
        "writeback_targets": writeback_targets,
        "writeback_target_optional": writeback_target,
    }


def build_outreach_plan_payload(
    *,
    store: Any,
    runtime_state: Any,
    project_id: str,
    saleable_opportunity: Mapping[str, Any],
    contact_target: Mapping[str, Any],
    authoritative_inputs: Mapping[str, Any],
    now: str,
    run_mode: str,
    approval_state: str,
    plan_status: str,
    plan_requires_manual_review: bool,
    execution_vendor_payload: Mapping[str, Any],
    writeback_projection: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "outreach_plan_id": build_id("PLAN", project_id),
        "opportunity_id": saleable_opportunity.get("opportunity_id"),
        "project_id": project_id,
        "saleability_status": saleable_opportunity.get("saleability_status"),
        "contact_target_id": contact_target.get("contact_target_id"),
        "channel_strategy": authoritative_inputs.get("channel_strategy", "DEFAULT"),
        "requested_delivery_surface": str(
            runtime_state.resolve(
                "requested_delivery_surface",
                authoritative_inputs.get("requested_delivery_surface", "INTERNAL_OPERATIONS"),
            )
        ),
        "projection_mode": str(runtime_state.resolve("projection_mode", "INTERNAL_GOVERNED_PREVIEW")),
        "cadence_profile_id": str(required_runtime_value(runtime_state, "cadence_profile_id")),
        "retry_policy_id": str(required_runtime_value(runtime_state, "retry_policy_id")),
        "stop_policy_id": str(required_runtime_value(runtime_state, "stop_policy_id")),
        "primary_message": authoritative_inputs.get("primary_message", "internal preview"),
        "planned_touch_at": authoritative_inputs.get("planned_touch_at", now),
        "attempt_index": int(
            runtime_state.resolve("attempt_index", authoritative_inputs.get("attempt_index", 1))
        ),
        "approval_state": approval_state,
        "plan_status": plan_status,
        "run_mode": run_mode,
        "automation_level": ensure_enum(
            store, "automation_level", authoritative_inputs.get("automation_level", "MANUAL")
        ),
        "next_touch_due_at_optional": str(required_runtime_value(runtime_state, "next_touch_due_at_optional")),
        "retry_count": int(required_runtime_value(runtime_state, "retry_count")),
        "max_retry_count": int(required_runtime_value(runtime_state, "max_retry_count")),
        "stop_reason_optional": str(
            runtime_state.resolve(
                "stop_reason_optional",
                authoritative_inputs.get("stop_reason_optional"),
            )
        ),
        "approval_run_required": bool(
            runtime_state.resolve(
                "approval_run_required",
                run_mode in ("APPROVAL_RUN", "REAL_RUN"),
            )
        ),
        "writeback_required": bool(writeback_projection["writeback_required"]),
        "writeback_target_optional": str(writeback_projection["writeback_target_optional"] or ""),
        "permission_decision_state": runtime_state.permission_decision_state,
        "governance_decision_state": runtime_state.governance_decision_state,
        "semantic_decision_state": runtime_state.semantic_decision_state,
        "requires_manual_review": bool(plan_requires_manual_review),
        **dict(execution_vendor_payload),
    }


def apply_outreach_plan_policy_projection(
    *,
    store: Any,
    runtime_state: Any,
    outreach_payload: dict[str, Any],
    outreach_guard_context: Mapping[str, Any],
    saleable_opportunity: Mapping[str, Any],
    contact_payload: Mapping[str, Any],
    run_mode: str,
    approval_state: str,
    writeback_targets: list[str],
) -> dict[str, Any]:
    outreach_guard = store.evaluate_runtime_guards(
        "outreach_plan",
        outreach_payload,
        outreach_guard_context,
    )
    runtime_state.add_governance_guard(outreach_guard)
    if outreach_guard.decision_state == "BLOCK":
        outreach_payload["plan_status"] = "BLOCKED"
        outreach_payload["requires_manual_review"] = True
    elif outreach_guard.decision_state == "REVIEW" and outreach_payload["plan_status"] == "APPROVED":
        outreach_payload["plan_status"] = "REVIEW_REQUIRED"
        outreach_payload["requires_manual_review"] = True

    outreach_semantic = store.evaluate_object_semantics(
        stage=8,
        object_type="outreach_plan",
        payload=outreach_payload,
        semantic_context={
            "contact_target_status": contact_payload["contact_target_status"],
            "upstream_saleability_status": saleable_opportunity.get("saleability_status"),
        },
    )
    if outreach_semantic:
        runtime_state.add_semantic_validation(outreach_semantic)
        if outreach_semantic.decision_state == "BLOCK":
            outreach_payload["plan_status"] = "BLOCKED"
            outreach_payload["requires_manual_review"] = True
        elif outreach_semantic.decision_state == "REVIEW" and outreach_payload["plan_status"] == "APPROVED":
            outreach_payload["plan_status"] = "REVIEW_REQUIRED"
            outreach_payload["requires_manual_review"] = True

    outreach_payload["permission_decision_state"] = runtime_state.permission_decision_state
    outreach_payload["governance_decision_state"] = runtime_state.governance_decision_state
    outreach_payload["semantic_decision_state"] = runtime_state.semantic_decision_state
    outreach_payload["governed_metadata"] = build_governed_metadata(
        runtime_state=runtime_state,
        requested_delivery_surface=outreach_payload["requested_delivery_surface"],
        projection_mode=outreach_payload["projection_mode"],
        run_mode=run_mode,
        approval_state=approval_state,
        writeback_targets=writeback_targets,
    )
    return outreach_payload


def build_trace_rules(runtime_state: Any) -> list[str]:
    return [
        f"POLICY:emit_decision:{entry.get('policy_key', '')}"
        for entry in runtime_state.trace
        if entry.get("event") == "emit_decision"
    ]


def project_next_step_optional(
    *,
    runtime_state: Any,
    authoritative_inputs: Mapping[str, Any],
    human_handoff: dict[str, Any] | None,
) -> str:
    next_step_optional = runtime_state.resolve(
        "next_step_optional",
        authoritative_inputs.get("next_step_optional"),
    )
    if human_handoff and next_step_optional in (None, ""):
        next_step_optional = human_handoff["next_step_optional"]
    if human_handoff and next_step_optional not in (None, ""):
        human_handoff["next_step_optional"] = next_step_optional
    return str(next_step_optional or authoritative_inputs.get("next_step_optional") or "WAIT")


def project_touch_record_state(
    *,
    runtime_state: Any,
    plan_status: str,
    run_mode: str,
    response_status: str,
) -> str:
    if runtime_state.permission_blocked_reasons or plan_status in ("CANCELLED", "BLOCKED"):
        return "CANCELLED"
    if plan_status != "APPROVED" or run_mode == "DRY_RUN":
        return "CREATED"
    if response_status in (
        "CONNECTED",
        "DECLINED",
        "OPTED_OUT",
        "WRONG_ROLE",
        "INVALID_CONTACT",
        "FOLLOWUP_REQUIRED",
        "OPPORTUNITY_CHANGED",
    ):
        return "RESPONDED"
    return "SENT"


def build_touch_record_payload(
    *,
    store: Any,
    runtime_state: Any,
    project_id: str,
    saleable_opportunity: Mapping[str, Any],
    contact_target: Mapping[str, Any],
    outreach_plan: Mapping[str, Any],
    authoritative_inputs: Mapping[str, Any],
    now: str,
    response_status: str,
    touch_state: str,
    next_step_optional: str,
    stop_reason_optional: Any,
    written_back_at_optional: Any,
    retry_scheduled_optional: bool,
    execution_vendor_payload: Mapping[str, Any],
    writeback_projection: Mapping[str, Any],
) -> dict[str, Any]:
    writeback_targets = ensure_list(writeback_projection["writeback_targets"])
    writeback_target = writeback_projection["writeback_target_optional"]
    if not writeback_targets and writeback_target not in (None, ""):
        writeback_targets = [writeback_target]
    if writeback_target in (None, "") and writeback_targets:
        writeback_target = writeback_targets[0]
    return {
        "touch_record_id": build_id("TOUCH", project_id),
        "opportunity_id": saleable_opportunity.get("opportunity_id"),
        "project_id": project_id,
        "saleability_status": saleable_opportunity.get("saleability_status"),
        "contact_target_id": contact_target.get("contact_target_id"),
        "outreach_plan_id": outreach_plan.get("outreach_plan_id"),
        "touch_at": authoritative_inputs.get("touch_at", now),
        "attempt_index": int(
            runtime_state.resolve("attempt_index", authoritative_inputs.get("attempt_index", 1))
        ),
        "touch_record_state": touch_state,
        "response_status": response_status,
        "feedback_reason": str(
            runtime_state.resolve(
                "feedback_reason",
                authoritative_inputs.get("feedback_reason", response_status),
            )
        ),
        "next_step_optional": next_step_optional,
        "stop_reason_optional": str(stop_reason_optional),
        "touch_channel": ensure_enum(store, "channel_family", contact_target.get("channel_family")),
        "written_back_at_optional": written_back_at_optional,
        "retry_scheduled_optional": retry_scheduled_optional,
        "failure_reason_tag_optional": str(
            runtime_state.resolve(
                "failure_reason_tag_optional",
                authoritative_inputs.get("failure_reason_tag_optional", response_status),
            )
        ),
        "writeback_targets": writeback_targets,
        "writeback_target_optional": str(writeback_target),
        "permission_decision_state": runtime_state.permission_decision_state,
        "governance_decision_state": runtime_state.governance_decision_state,
        "semantic_decision_state": runtime_state.semantic_decision_state,
        "execution_vendor_id_optional": execution_vendor_payload["execution_vendor_id_optional"],
        "execution_vendor_type_optional": execution_vendor_payload["execution_vendor_type_optional"],
        "execution_vendor_role_optional": execution_vendor_payload["execution_vendor_role_optional"],
        "execution_trace_id_optional": execution_vendor_payload["execution_trace_id_optional"],
        "vendor_response_ref_optional": execution_vendor_payload["vendor_response_ref_optional"],
    }


def apply_touch_record_policy_projection(
    *,
    store: Any,
    runtime_state: Any,
    touch_payload: dict[str, Any],
    touch_guard_context: Mapping[str, Any],
    outreach_payload: Mapping[str, Any],
    saleable_opportunity: Mapping[str, Any],
    outreach_plan: Mapping[str, Any],
    run_mode: str,
    approval_state: str,
    human_handoff: dict[str, Any] | None,
) -> dict[str, Any]:
    touch_guard = store.evaluate_runtime_guards("touch_record", touch_payload, touch_guard_context)
    runtime_state.add_governance_guard(touch_guard)
    if touch_guard.decision_state == "BLOCK":
        touch_payload["touch_record_state"] = "CANCELLED"
    elif touch_guard.decision_state == "REVIEW" and touch_payload["touch_record_state"] == "SENT":
        touch_payload["touch_record_state"] = "CREATED"

    touch_semantic = store.evaluate_object_semantics(
        stage=8,
        object_type="touch_record",
        payload=touch_payload,
        semantic_context={
            "plan_status": outreach_payload["plan_status"],
            "upstream_saleability_status": saleable_opportunity.get("saleability_status"),
        },
    )
    if touch_semantic:
        runtime_state.add_semantic_validation(touch_semantic)
        if touch_semantic.decision_state == "BLOCK":
            touch_payload["touch_record_state"] = "CANCELLED"
        elif touch_semantic.decision_state == "REVIEW" and touch_payload["touch_record_state"] == "SENT":
            touch_payload["touch_record_state"] = "CREATED"

    touch_payload["permission_decision_state"] = runtime_state.permission_decision_state
    touch_payload["governance_decision_state"] = runtime_state.governance_decision_state
    touch_payload["semantic_decision_state"] = runtime_state.semantic_decision_state
    touch_payload["governed_metadata"] = build_governed_metadata(
        runtime_state=runtime_state,
        requested_delivery_surface=outreach_plan.get("requested_delivery_surface"),
        projection_mode=outreach_plan.get("projection_mode"),
        run_mode=run_mode,
        approval_state=approval_state,
        writeback_targets=touch_payload["writeback_targets"],
    )
    if human_handoff:
        touch_payload["governed_metadata"]["human_handoff"] = human_handoff
    return touch_payload


def build_h08_handoff_payload(
    *,
    project_id: str,
    saleable_opportunity: Mapping[str, Any],
    contact_candidate_collection: Mapping[str, Any],
    contact_selection_trace: Mapping[str, Any],
    contact_target: Mapping[str, Any],
    outreach_plan: Mapping[str, Any],
    touch_record: Mapping[str, Any],
    outreach_execution_outbox: Mapping[str, Any],
    human_handoff: Mapping[str, Any] | None,
    runtime_state: Any,
) -> dict[str, Any]:
    outbox_summary = build_outbox_readiness_summary(outreach_execution_outbox)
    return {
        "project_id": project_id,
        "opportunity_id": saleable_opportunity.get("opportunity_id"),
        "contact_candidate_collection_id": contact_candidate_collection.get(
            "contact_candidate_collection_id"
        ),
        "contact_selection_trace_id": contact_selection_trace.get("contact_selection_trace_id"),
        "contact_candidate_collection_id_optional": contact_candidate_collection.get(
            "contact_candidate_collection_id"
        ),
        "contact_selection_trace_id_optional": contact_selection_trace.get(
            "contact_selection_trace_id"
        ),
        "winning_contact_candidate_id_optional": contact_candidate_collection.get(
            "winning_contact_candidate_id"
        ),
        "reselect_reason_optional": contact_candidate_collection.get("reselect_reason_optional"),
        "source_conflict_candidate_count": contact_candidate_collection.get(
            "source_conflict_candidate_count"
        ),
        "source_merge_review_required_count": contact_candidate_collection.get(
            "source_merge_review_required_count"
        ),
        "touch_record_id": touch_record.get("touch_record_id"),
        "response_status": touch_record.get("response_status"),
        "saleability_status": saleable_opportunity.get("saleability_status"),
        "crm_owner_state": saleable_opportunity.get("crm_owner_state"),
        "contact_target_status": contact_target.get("contact_target_status"),
        "plan_status": outreach_plan.get("plan_status"),
        "touch_record_state": touch_record.get("touch_record_state"),
        OUTBOX_ID_INPUT_KEY: outreach_execution_outbox.get("outbox_id"),
        "outreach_execution_outbox_id_optional": outreach_execution_outbox.get("outbox_id"),
        OUTBOX_READINESS_INPUT_KEY: outbox_summary,
        "feedback_reason": touch_record.get("feedback_reason"),
        "written_back_at_optional": touch_record.get("written_back_at_optional"),
        "human_handoff_policy_id_optional": human_handoff.get("policy_id") if human_handoff else None,
        "human_handoff_next_owner_role_optional": human_handoff.get("next_owner_role_optional") if human_handoff else None,
        "human_handoff_sla_hours_optional": human_handoff.get("sla_hours_optional") if human_handoff else None,
        "human_handoff_sla_due_at_optional": human_handoff.get("sla_due_at_optional") if human_handoff else None,
        "human_handoff_reason_optional": human_handoff.get("reason_optional") if human_handoff else None,
        "policy_trace": runtime_state.trace,
        "policy_decision_state": runtime_state.decision_state,
        "permission_trace": runtime_state.capability_trace,
        "permission_decision_state": runtime_state.permission_decision_state,
        "permission_governance": runtime_state.capability_governance(),
        "governance_trace": runtime_state.governance_trace,
        "governance_decision_state": runtime_state.governance_decision_state,
        "governance_additions": runtime_state.governance_additions,
        "semantic_trace": runtime_state.semantic_trace,
        "semantic_decision_state": runtime_state.semantic_decision_state,
        "semantic_additions": runtime_state.semantic_additions,
    }


def build_stage8_inputs_projection(
    *,
    authoritative_inputs: Mapping[str, Any],
    original_inputs: Mapping[str, Any],
    h07_authoritative_fields: tuple[str, ...],
    saleable_opportunity: Mapping[str, Any],
    outreach_plan: Mapping[str, Any],
    touch_record: Mapping[str, Any],
    outreach_execution_outbox: Mapping[str, Any],
    human_handoff: Mapping[str, Any] | None,
    runtime_state: Any,
    multi_competitor_collection_id: str,
    winning_competitor_candidate_id: Any,
    winning_challenger_profile_id: str,
    candidate_trace: Mapping[str, Any],
    contact_candidate_collection: Mapping[str, Any],
    contact_selection_trace: Mapping[str, Any],
    source_vendor_trace: Mapping[str, Any],
    execution_vendor_trace: Mapping[str, Any],
    formal_sink_trace: Mapping[str, Any],
) -> dict[str, Any]:
    outbox_summary = build_outbox_readiness_summary(outreach_execution_outbox)
    inputs_out = dict(authoritative_inputs)
    inputs_out["policy_trace"] = runtime_state.trace
    inputs_out["policy_decision_state"] = runtime_state.decision_state
    inputs_out["permission_trace"] = runtime_state.capability_trace
    inputs_out["permission_decision_state"] = runtime_state.permission_decision_state
    inputs_out["permission_governance"] = runtime_state.capability_governance()
    inputs_out["governance_trace"] = runtime_state.governance_trace
    inputs_out["governance_decision_state"] = runtime_state.governance_decision_state
    inputs_out["governance_additions"] = runtime_state.governance_additions
    inputs_out["semantic_trace"] = runtime_state.semantic_trace
    inputs_out["semantic_decision_state"] = runtime_state.semantic_decision_state
    inputs_out["semantic_additions"] = runtime_state.semantic_additions
    inputs_out["opportunity_id"] = saleable_opportunity.get("opportunity_id")
    inputs_out["touch_record_id"] = touch_record.get("touch_record_id")
    inputs_out["response_status"] = touch_record.get("response_status")
    inputs_out["saleability_status"] = saleable_opportunity.get("saleability_status")
    inputs_out["crm_owner_state"] = saleable_opportunity.get("crm_owner_state")
    inputs_out["requested_delivery_surface"] = outreach_plan.get("requested_delivery_surface")
    inputs_out["projection_mode"] = outreach_plan.get("projection_mode")
    inputs_out["next_step_optional"] = touch_record.get("next_step_optional")
    inputs_out["feedback_reason"] = touch_record.get("feedback_reason")
    inputs_out["written_back_at_optional"] = touch_record.get("written_back_at_optional")
    inputs_out["stop_reason_optional"] = touch_record.get("stop_reason_optional")
    inputs_out["retry_scheduled_optional"] = touch_record.get("retry_scheduled_optional")
    inputs_out[OUTBOX_ID_INPUT_KEY] = outreach_execution_outbox.get("outbox_id")
    inputs_out["outreach_execution_outbox_id_optional"] = outreach_execution_outbox.get("outbox_id")
    inputs_out[OUTBOX_SNAPSHOT_INPUT_KEY] = dict(outreach_execution_outbox)
    inputs_out[OUTBOX_READINESS_INPUT_KEY] = outbox_summary
    inputs_out["writeback_targets"] = touch_record.get("writeback_targets")
    inputs_out["writeback_target_optional"] = touch_record.get("writeback_target_optional")
    inputs_out["failure_reason_tag_optional"] = touch_record.get("failure_reason_tag_optional")
    inputs_out["human_handoff_policy_id_optional"] = human_handoff.get("policy_id") if human_handoff else None
    inputs_out["human_handoff_next_owner_role_optional"] = (
        human_handoff.get("next_owner_role_optional") if human_handoff else None
    )
    inputs_out["human_handoff_sla_hours_optional"] = human_handoff.get("sla_hours_optional") if human_handoff else None
    inputs_out["human_handoff_sla_due_at_optional"] = human_handoff.get("sla_due_at_optional") if human_handoff else None
    inputs_out["human_handoff_reason_optional"] = human_handoff.get("reason_optional") if human_handoff else None
    for field_name in h07_authoritative_fields:
        inputs_out[field_name] = authoritative_inputs.get(field_name, original_inputs.get(field_name))
    inputs_out["multi_competitor_collection_id_optional"] = str(multi_competitor_collection_id)
    inputs_out["winning_competitor_candidate_id_optional"] = winning_competitor_candidate_id
    inputs_out["winning_challenger_profile_id_optional"] = str(winning_challenger_profile_id)
    inputs_out["next_touch_due_at_optional"] = runtime_state.resolve("next_touch_due_at_optional")
    inputs_out["retry_count"] = runtime_state.resolve("retry_count", outreach_plan.get("retry_count"))
    inputs_out["max_retry_count"] = runtime_state.resolve(
        "max_retry_count",
        outreach_plan.get("max_retry_count"),
    )
    inputs_out["attempt_index"] = runtime_state.resolve(
        "attempt_index",
        touch_record.get("attempt_index"),
    )
    inputs_out["cadence_profile_id"] = outreach_plan.get("cadence_profile_id")
    inputs_out["retry_policy_id"] = outreach_plan.get("retry_policy_id")
    inputs_out["stop_policy_id"] = outreach_plan.get("stop_policy_id")
    inputs_out["stage8_resolution_trace"] = {
        "candidate_resolution": candidate_trace,
        "contact_candidate_collection_id": contact_candidate_collection.get("contact_candidate_collection_id"),
        "contact_selection_trace_id": contact_selection_trace.get("contact_selection_trace_id"),
        "winning_contact_candidate_id": contact_candidate_collection.get("winning_contact_candidate_id"),
        "contact_selection_trace": {
            "winning_selection_reason": contact_selection_trace.get("winning_selection_reason"),
            "conflict_flag": contact_selection_trace.get("conflict_flag"),
            "conflict_reason_optional": contact_selection_trace.get("conflict_reason_optional"),
            "reselect_reason_optional": contact_selection_trace.get("reselect_reason_optional"),
            "reselect_history": contact_selection_trace.get("reselect_history"),
        },
        "source_vendor_resolution": source_vendor_trace,
        "execution_vendor_resolution": execution_vendor_trace,
        "human_handoff": human_handoff,
        "formal_sink_consumption": formal_sink_trace,
    }
    inputs_out["contact_candidate_collection_id_optional"] = contact_candidate_collection.get(
        "contact_candidate_collection_id"
    )
    inputs_out["contact_selection_trace_id_optional"] = contact_selection_trace.get("contact_selection_trace_id")
    inputs_out["winning_contact_candidate_id_optional"] = contact_candidate_collection.get("winning_contact_candidate_id")
    inputs_out["reselect_reason_optional"] = contact_candidate_collection.get("reselect_reason_optional")
    inputs_out["contact_candidate_collection_snapshot"] = contact_candidate_collection.data
    inputs_out["contact_selection_trace_snapshot"] = contact_selection_trace.data
    return inputs_out


__all__ = [
    "apply_outreach_plan_policy_projection",
    "apply_touch_record_policy_projection",
    "build_h08_handoff_payload",
    "build_outreach_plan_payload",
    "build_stage8_inputs_projection",
    "build_touch_record_payload",
    "build_trace_rules",
    "collect_writeback_projection",
    "project_next_step_optional",
    "project_plan_requires_manual_review",
    "project_plan_status",
    "project_touch_record_state",
    "required_runtime_value",
]
