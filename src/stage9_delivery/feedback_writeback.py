from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from stage9_delivery.impact_executor import ImpactExecutor
from shared.utils import build_id, ensure_enum, ensure_list


@dataclass(frozen=True)
class WritebackProjection:
    outcome_writeback_targets: list[str]
    outcome_authoritative_base_targets: list[str]
    upstream_feedback_projected_targets: list[str]
    upstream_feedback_advisory_targets: list[str]
    upstream_feedback_contracts: dict[str, Any]
    governance_writeback_targets: list[str]
    governance_legacy_writeback_targets: list[str]
    governance_owned_self_target: str
    payment_exception_writeback_targets: list[str]
    delivery_exception_writeback_targets: list[str]
    effective_writeback_targets: list[str]
    resolved_effective_writeback_targets: list[str]
    writeback_target_resolution: dict[str, Any]
    writeback_contract: dict[str, Any]


def build_stage9_governed_metadata(
    *,
    plan_status: str,
    touch_record_state: str,
    feedback_reason: str,
    written_back_at_optional: str | None,
    upstream_governance_decision_state: str,
    projection: WritebackProjection,
) -> dict[str, Any]:
    return {
        "skeleton_only": True,
        "live_execution_enabled": False,
        "projection_only": True,
        "governed_execution_mode": "INTERNAL_GOVERNED",
        "source_handoff_id": "H-08-STAGE8-TO-STAGE9",
        "upstream_plan_status": plan_status,
        "upstream_touch_record_state": touch_record_state,
        "upstream_feedback_reason": feedback_reason,
        "upstream_written_back_at_optional": written_back_at_optional,
        "upstream_governance_decision_state": upstream_governance_decision_state,
        "outcome_writeback_targets": list(projection.outcome_writeback_targets),
        "outcome_authoritative_base_targets": list(projection.outcome_authoritative_base_targets),
        "governance_writeback_targets_optional": list(projection.governance_writeback_targets),
        "governance_legacy_writeback_targets": list(projection.governance_legacy_writeback_targets),
        "governance_owned_self_target": projection.governance_owned_self_target,
        "payment_exception_writeback_targets_optional": list(projection.payment_exception_writeback_targets),
        "delivery_exception_writeback_targets_optional": list(projection.delivery_exception_writeback_targets),
        "effective_writeback_targets": list(projection.effective_writeback_targets),
        "writeback_contract_state": projection.writeback_contract.get("writeback_contract_state", "UNKNOWN"),
        "writeback_projected_targets": list(projection.writeback_contract.get("writeback_projected_targets", [])),
        "writeback_persistence_targets": list(projection.writeback_contract.get("writeback_persistence_targets", [])),
        "writeback_advisory_targets": list(projection.writeback_contract.get("writeback_advisory_targets", [])),
        "writeback_trace_only_targets": list(projection.writeback_contract.get("writeback_trace_only_targets", [])),
        "writeback_source_contracts": dict(projection.writeback_target_resolution["writeback_source_contracts"]),
        "writeback_target_sources": dict(projection.writeback_target_resolution["writeback_target_sources"]),
    }


def resolve_upstream_feedback_contract(
    *,
    policy: Mapping[str, Any],
    outcome_family: str,
    projected_feedback_only_targets: list[str],
    advisory_targets: list[str],
    feedback_loop_contract_ref: str | None,
) -> dict[str, Any]:
    outcome_key = str(outcome_family or "").lower()
    required_outcomes = {str(item).lower() for item in policy.get("requiredOutcomes", [])}
    if not (projected_feedback_only_targets or advisory_targets):
        return {
            "upstream_feedback_projected_targets": [],
            "upstream_feedback_advisory_targets": [],
            "upstream_feedback_contracts": {},
        }
    if outcome_key not in required_outcomes:
        raise ValueError(
            f"Stage9 upstream feedback loop outcome not declared: outcome_family={outcome_family}"
        )

    contract = dict(policy.get("upstreamFeedbackLoopContracts", {}).get(outcome_key, {}))
    if not contract:
        raise ValueError(
            f"Stage9 upstream feedback loop contract missing for outcome_family={outcome_family}"
        )
    projected_contracts = dict(contract.get("projectedOnlyTargets", {}))
    advisory_contracts = dict(contract.get("advisoryTargets", {}))
    missing_projected_targets = [
        target for target in projected_feedback_only_targets if target not in projected_contracts
    ]
    missing_advisory_targets = [
        target for target in advisory_targets if target not in advisory_contracts
    ]
    if missing_projected_targets or missing_advisory_targets:
        raise ValueError(
            "Stage9 upstream feedback loop target contract mismatch: "
            f"missing_projected={missing_projected_targets}; "
            f"missing_advisory={missing_advisory_targets}"
        )
    return {
        "upstream_feedback_projected_targets": list(projected_feedback_only_targets),
        "upstream_feedback_advisory_targets": list(advisory_targets),
        "upstream_feedback_contracts": {
            "outcome_family": outcome_key,
            "feedback_loop_contract_ref": feedback_loop_contract_ref,
            "projectedOnlyTargets": {
                target: projected_contracts[target] for target in projected_feedback_only_targets
            },
            "advisoryTargets": {
                target: advisory_contracts[target] for target in advisory_targets
            },
            "mustWriteBackTo": [
                target
                for target in policy.get("mustWriteBackTo", [])
                if target in projected_feedback_only_targets
            ],
            "mustAdvisoryWriteBackTo": [
                target
                for target in policy.get("mustAdvisoryWriteBackTo", [])
                if target in advisory_targets
            ],
        },
    }


def resolve_writeback_projection(
    *,
    runtime_state: Any,
    runtime_inputs: Mapping[str, Any],
    impact_executor: ImpactExecutor,
    outcome_feedback_policy: Mapping[str, Any],
) -> WritebackProjection:
    outcome_taxonomy_output = runtime_state.outputs.get("outcome_taxonomy", {})
    outcome_writeback_targets = ensure_list(
        outcome_taxonomy_output.get("writeback_targets", ["project_fact"])
    )
    outcome_authoritative_base_targets = ensure_list(
        outcome_taxonomy_output.get("authoritative_base_targets", outcome_writeback_targets)
    )
    resolved_outcome_family = str(
        runtime_state.resolve("outcome_family", runtime_inputs["outcome_family"])
    )
    upstream_feedback_contract = resolve_upstream_feedback_contract(
        policy=outcome_feedback_policy,
        outcome_family=resolved_outcome_family,
        projected_feedback_only_targets=ensure_list(
            outcome_taxonomy_output.get("projected_feedback_only_targets", [])
        ),
        advisory_targets=ensure_list(outcome_taxonomy_output.get("advisory_targets", [])),
        feedback_loop_contract_ref=outcome_taxonomy_output.get("feedback_loop_contract_ref"),
    )
    upstream_feedback_projected_targets = ensure_list(
        upstream_feedback_contract.get("upstream_feedback_projected_targets", [])
    )
    upstream_feedback_advisory_targets = ensure_list(
        upstream_feedback_contract.get("upstream_feedback_advisory_targets", [])
    )

    governance_taxonomy_output = runtime_state.outputs.get("governance_taxonomy", {})
    governance_writeback_targets = ensure_list(
        governance_taxonomy_output.get(
            "additive_writeback_targets",
            governance_taxonomy_output.get("writeback_targets", []),
        )
    )
    governance_legacy_writeback_targets = ensure_list(
        governance_taxonomy_output.get("writeback_targets", governance_writeback_targets)
    )
    governance_owned_self_target = str(
        governance_taxonomy_output.get(
            "governance_owned_self_target",
            "governance_feedback_event",
        )
    )
    payment_exception_writeback_targets = ensure_list(
        runtime_state.resolve("payment_exception_writeback_targets_optional", [])
    )
    delivery_exception_writeback_targets = ensure_list(
        runtime_state.resolve("delivery_exception_writeback_targets_optional", [])
    )
    writeback_target_resolution = impact_executor.resolve_effective_targets(
        outcome_targets=outcome_authoritative_base_targets,
        outcome_legacy_targets=outcome_writeback_targets,
        upstream_feedback_targets=(
            upstream_feedback_projected_targets + upstream_feedback_advisory_targets
        ),
        governance_targets=governance_writeback_targets,
        payment_exception_targets=payment_exception_writeback_targets,
        delivery_exception_targets=delivery_exception_writeback_targets,
        governance_self_target=governance_owned_self_target,
    )
    effective_writeback_targets = list(
        writeback_target_resolution["legacy_effective_writeback_targets"]
    )
    resolved_effective_writeback_targets = list(
        writeback_target_resolution["effective_writeback_targets"]
    )
    writeback_contract = impact_executor.describe_targets(
        resolved_effective_writeback_targets,
        target_sources=writeback_target_resolution["writeback_target_sources"],
    )
    return WritebackProjection(
        outcome_writeback_targets=outcome_writeback_targets,
        outcome_authoritative_base_targets=outcome_authoritative_base_targets,
        upstream_feedback_projected_targets=upstream_feedback_projected_targets,
        upstream_feedback_advisory_targets=upstream_feedback_advisory_targets,
        upstream_feedback_contracts=dict(upstream_feedback_contract["upstream_feedback_contracts"]),
        governance_writeback_targets=governance_writeback_targets,
        governance_legacy_writeback_targets=governance_legacy_writeback_targets,
        governance_owned_self_target=governance_owned_self_target,
        payment_exception_writeback_targets=payment_exception_writeback_targets,
        delivery_exception_writeback_targets=delivery_exception_writeback_targets,
        effective_writeback_targets=effective_writeback_targets,
        resolved_effective_writeback_targets=resolved_effective_writeback_targets,
        writeback_target_resolution=writeback_target_resolution,
        writeback_contract=writeback_contract,
    )


def build_governance_feedback_payload(
    *,
    store: Any,
    project_id: str,
    runtime_state: Any,
    runtime_inputs: Mapping[str, Any],
    now: str,
    written_back_at_optional: str | None,
    feedback_reason: str,
    projection: WritebackProjection,
    governed_execution_mode: str,
    permission_effective_state: str,
    governance_effective_state: str,
    semantic_effective_state: str,
    governed_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "governance_feedback_event_id": build_id("GOV", project_id),
        "project_id": project_id,
        "trigger_type": ensure_enum(
            store,
            "trigger_type",
            runtime_state.resolve("trigger_type", runtime_inputs["trigger_type"]),
        ),
        "trigger_summary": runtime_inputs["trigger_summary"],
        "action_taken": "; ".join(
            runtime_state.resolve(
                "required_actions",
                [runtime_inputs.get("action_taken", "NONE")],
            )
        ),
        "written_back_at": now,
        "written_back_at_optional": written_back_at_optional or now,
        "archive_scope": runtime_inputs.get(
            "archive_scope",
            runtime_state.resolve("impact_scope", "INTERNAL"),
        ),
        "feedback_reason": feedback_reason,
        "writeback_targets": (
            projection.governance_legacy_writeback_targets
            or [projection.governance_owned_self_target]
        ),
        "governance_feedback_policy_id_optional": runtime_state.resolve(
            "governance_feedback_policy_id_optional",
            runtime_state.resolve("trigger_type", runtime_inputs["trigger_type"]),
        ),
        "impact_scope_optional": runtime_state.resolve("impact_scope", "INTERNAL"),
        "governed_execution_mode": governed_execution_mode,
        "permission_decision_state": permission_effective_state,
        "governance_decision_state": governance_effective_state,
        "semantic_decision_state": semantic_effective_state,
        "governed_metadata": governed_metadata,
    }


def governance_feedback_guard_conditions(
    governance_payload: Mapping[str, Any],
    *,
    audit_trail_present: bool,
) -> dict[str, Any]:
    return {
        "trigger and action valid": bool(
            governance_payload["trigger_type"] and governance_payload["action_taken"]
        ),
        "written_back_at present": bool(governance_payload["written_back_at"]),
        "governance audit present": audit_trail_present,
    }


def build_opportunity_outcome_payload(
    *,
    store: Any,
    project_id: str,
    order_record: Mapping[str, Any],
    governance_payload: Mapping[str, Any],
    runtime_state: Any,
    runtime_inputs: Mapping[str, Any],
    now: str,
    written_back_at_optional: str | None,
    feedback_reason: str,
    projection: WritebackProjection,
    governed_execution_mode: str,
    permission_effective_state: str,
    governance_effective_state: str,
    semantic_effective_state: str,
    governed_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "outcome_event_id": build_id("OUTCOME", project_id),
        "project_id": project_id,
        "opportunity_id": order_record.get("opportunity_id"),
        "outcome_family": ensure_enum(
            store,
            "outcome_family",
            runtime_state.resolve("outcome_family", runtime_inputs["outcome_family"]),
        ),
        "outcome_reason_tags": ensure_list(
            runtime_state.resolve(
                "outcome_reason_tags",
                runtime_inputs["outcome_reason_tags"],
            )
        ),
        "is_false_positive": bool(runtime_inputs.get("is_false_positive", False)),
        "window_missed_state": ensure_enum(
            store,
            "window_missed_state",
            runtime_inputs["window_missed_state"],
        ),
        "contact_failure_state": ensure_enum(
            store,
            "contact_failure_state",
            runtime_inputs["contact_failure_state"],
        ),
        "payer_mismatch_state": ensure_enum(
            store,
            "payer_mismatch_state",
            runtime_inputs["payer_mismatch_state"],
        ),
        "feedback_reason": feedback_reason,
        "trigger_type": governance_payload["trigger_type"],
        "action_taken": governance_payload["action_taken"],
        "writeback_targets": list(projection.outcome_writeback_targets),
        "governance_feedback_triggered_optional": bool(
            runtime_state.resolve("governance_feedback_triggered_optional", False)
        ),
        "written_back_at": written_back_at_optional or now,
        "written_back_at_optional": written_back_at_optional or now,
        "governed_execution_mode": governed_execution_mode,
        "permission_decision_state": permission_effective_state,
        "governance_decision_state": governance_effective_state,
        "semantic_decision_state": semantic_effective_state,
        "governed_metadata": governed_metadata,
    }


def opportunity_outcome_guard_conditions(
    outcome_payload: Mapping[str, Any],
    *,
    audit_trail_present: bool,
) -> dict[str, Any]:
    return {
        "taxonomy valid": bool(
            outcome_payload["outcome_family"] and outcome_payload["outcome_reason_tags"]
        ),
        "written_back_at present": bool(outcome_payload["written_back_at"]),
        "audit trail present": audit_trail_present,
    }


def opportunity_outcome_semantic_context(
    *,
    delivery_payload: Mapping[str, Any],
    plan_status: str,
    feedback_reason: str,
    governance_effective_state: str,
) -> dict[str, Any]:
    return {
        "delivery_status": delivery_payload["delivery_status"],
        "plan_status": plan_status,
        "feedback_reason": feedback_reason,
        "governance_decision_state": governance_effective_state,
    }


def feedback_summary_fields(
    *,
    projection: WritebackProjection,
    runtime_state: Any,
    impact_result: Mapping[str, Any],
    h08_workflow_fallback_trace: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "outcome_writeback_targets": projection.outcome_writeback_targets,
        "outcome_authoritative_base_targets": projection.outcome_authoritative_base_targets,
        "upstream_feedback_projected_targets": projection.upstream_feedback_projected_targets,
        "upstream_feedback_advisory_targets": projection.upstream_feedback_advisory_targets,
        "upstream_feedback_contracts": projection.upstream_feedback_contracts,
        "governance_writeback_targets_optional": projection.governance_writeback_targets,
        "governance_legacy_writeback_targets": projection.governance_legacy_writeback_targets,
        "governance_owned_self_target": projection.governance_owned_self_target,
        "payment_exception_writeback_targets_optional": projection.payment_exception_writeback_targets,
        "delivery_exception_writeback_targets_optional": projection.delivery_exception_writeback_targets,
        "payment_exception_match_trace_optional": runtime_state.resolve(
            "payment_exception_match_trace_optional", {}
        ),
        "delivery_exception_match_trace_optional": runtime_state.resolve(
            "delivery_exception_match_trace_optional", {}
        ),
        "effective_writeback_targets": projection.effective_writeback_targets,
        "resolved_effective_writeback_targets": projection.resolved_effective_writeback_targets,
        "writeback_contract_state": impact_result["writeback_contract_state"],
        "writeback_contract_semantics": impact_result["writeback_contract_semantics"],
        "writeback_source_contracts": impact_result["writeback_source_contracts"],
        "writeback_target_sources": impact_result["writeback_target_sources"],
        "writeback_target_contracts": impact_result["writeback_target_contracts"],
        "writeback_persistence_targets": impact_result["writeback_persistence_targets"],
        "writeback_projected_targets": impact_result["writeback_projected_targets"],
        "writeback_advisory_targets": impact_result["writeback_advisory_targets"],
        "writeback_trace_only_targets": impact_result["writeback_trace_only_targets"],
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
        "impact_executor_state": impact_result["impact_executor_state"],
        "impact_targets_projected": impact_result["impact_targets_projected"],
        "impact_targets_projected_contract_only": impact_result[
            "impact_targets_projected_contract_only"
        ],
        "impact_targets_advisory": impact_result["impact_targets_advisory"],
        "impact_mutations": impact_result["impact_mutations"],
        "impact_projected_contracts": impact_result["impact_projected_contracts"],
        "impact_advisories": impact_result["impact_advisories"],
        "impact_trace": impact_result["impact_trace"],
        "h08_workflow_fallback_trace": h08_workflow_fallback_trace,
    }


def build_feedback_handoff(
    *,
    project_id: str,
    order_record: Mapping[str, Any],
    delivery_record: Mapping[str, Any],
    plan_status: str,
    touch_record_state: str,
    feedback_reason: str,
    written_back_at: str,
    governed_execution_mode: str,
    projection: WritebackProjection,
    runtime_state: Any,
    impact_result: Mapping[str, Any],
    h08_workflow_fallback_trace: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "order_status": order_record.get("order_status"),
        "delivery_status": delivery_record.get("delivery_status"),
        "plan_status": plan_status,
        "touch_record_state": touch_record_state,
        "feedback_reason": feedback_reason,
        "written_back_at_optional": written_back_at,
        "governed_execution_mode": governed_execution_mode,
        **feedback_summary_fields(
            projection=projection,
            runtime_state=runtime_state,
            impact_result=impact_result,
            h08_workflow_fallback_trace=h08_workflow_fallback_trace,
        ),
    }


def build_feedback_inputs(
    *,
    runtime_inputs: Mapping[str, Any],
    projection: WritebackProjection,
    runtime_state: Any,
    impact_result: Mapping[str, Any],
    h08_workflow_fallback_trace: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **runtime_inputs,
        **feedback_summary_fields(
            projection=projection,
            runtime_state=runtime_state,
            impact_result=impact_result,
            h08_workflow_fallback_trace=h08_workflow_fallback_trace,
        ),
        "impact_runtime_executor_enabled": impact_result["runtime_executor_enabled"],
        "impact_mutation_mode": impact_result["mutation_mode"],
        "impact_formal_targets": impact_result["formal_targets"],
    }


__all__ = [
    "WritebackProjection",
    "build_feedback_handoff",
    "build_feedback_inputs",
    "build_governance_feedback_payload",
    "build_opportunity_outcome_payload",
    "build_stage9_governed_metadata",
    "governance_feedback_guard_conditions",
    "opportunity_outcome_guard_conditions",
    "opportunity_outcome_semantic_context",
    "resolve_upstream_feedback_contract",
    "resolve_writeback_projection",
]
