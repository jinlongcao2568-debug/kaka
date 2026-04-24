# Stage: stage6_fact_review
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/governance/field_policy_dictionary.json, contracts/release/delivery_matrix.json, contracts/release/release_gates.json

from __future__ import annotations

from typing import Any, Mapping

from shared.context_packet import ContextPacket
from shared.contracts_runtime import ContractStore, StageBundle
from shared.policy_executor import PolicyExecutor
from shared.state_packet import StatePacket
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, get_flag


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _private_supplement_carrier_summary(
    supplement: Mapping[str, Any],
    *,
    supplement_loop_state: str,
    missing_condition_family: Any,
) -> dict[str, Any]:
    release_state = str(supplement.get("release_state", "ISOLATED"))
    usable_scope = str(supplement.get("usable_scope", "BLOCKED"))
    written_back_policy = str(supplement.get("written_back_policy", "GOVERNANCE_SINK_ONLY"))
    stage6_internal_runtime_allowed = release_state in {"REVIEW_ELIGIBLE", "IMPACT_ELIGIBLE"} and usable_scope != "BLOCKED"
    return {
        "supplement_id": supplement.get("supplement_id"),
        "project_id": supplement.get("project_id"),
        "linked_review_request_id": supplement.get("linked_review_request_id"),
        "release_state": release_state,
        "usable_scope": usable_scope,
        "written_back_policy": written_back_policy,
        "supplement_loop_state": supplement_loop_state,
        "impact_readiness_state": release_state,
        "impact_decision_trace": {
            "source": "stage6_private_supplement_record",
            "stage6_internal_runtime_allowed": stage6_internal_runtime_allowed,
            "stage6_internal_impact_allowed": release_state == "IMPACT_ELIGIBLE" and stage6_internal_runtime_allowed,
            "stage7_formal_surface_allowed": False,
            "external_or_live_allowed": False,
            "missing_condition_family_optional": missing_condition_family,
        },
    }


class ProjectFactAggregator:
    def __init__(self, store: ContractStore) -> None:
        self.store = store

    def aggregate(self, stage5_bundle: StageBundle, *, now: str) -> StageBundle:
        stage5_handoff = stage5_bundle.handoff or {}
        inputs = dict(stage5_bundle.inputs or {})
        for field_name in (
            "project_id",
            "rule_hit_id",
            "rule_hit_state",
            "evidence_id",
            "rule_gate_decision_id",
            "evidence_gate_decision_id",
            "rule_gate_status",
            "evidence_gate_status",
            "coverage_sellable_state",
            "delivery_risk_state",
            "review_request_id",
            "missing_condition_family",
            "review_lane",
            "verification_state",
            "cross_check_state",
            "fixation_status",
            "provenance_chain_status",
            "retrieval_readiness_status",
        ):
            if field_name in stage5_handoff:
                inputs[field_name] = stage5_handoff[field_name]
        flags = inputs.get("flags", {})

        evidence_gate = stage5_bundle.record("evidence_gate_decision")
        rule_gate = stage5_bundle.record("rule_gate_decision")
        rule_hit = stage5_bundle.record("rule_hit")
        evidence = stage5_bundle.record("evidence")
        review_request = stage5_bundle.records.get("review_request")
        review_request_id = stage5_handoff.get(
            "review_request_id",
            review_request.get("review_request_id") if review_request else None,
        )
        missing_condition_family = stage5_handoff.get(
            "missing_condition_family",
            review_request.get("missing_condition_family") if review_request else None,
        )

        project_id = evidence_gate.get("project_id")
        evidence_gate_status = evidence_gate.get("evidence_gate_status")
        rule_gate_status = rule_gate.get("rule_gate_status")
        confidence_band = ensure_enum(self.store, "confidence_band", inputs.get("confidence_band", "MEDIUM"))
        focus_bidder_id = inputs.get("focus_bidder_id", build_id("BID", project_id, "01"))
        challenger_bidder_id = inputs.get("challenger_bidder_id", build_id("BID", project_id, "02"))
        candidate_position_label = ensure_enum(
            self.store,
            "candidate_position_label",
            inputs.get("candidate_position_label", "FIRST_CANDIDATE"),
        )

        trace_rules: list[str] = []
        semantic_state = StatePacket(capability_mode="stage6_fact_review")
        policy_executor = PolicyExecutor()

        gate_sale_gate_status = "OPEN"
        if evidence_gate_status == "BLOCK" or rule_gate_status == "BLOCK":
            gate_sale_gate_status = "BLOCK"
        elif evidence_gate_status == "REVIEW" or rule_gate_status == "REVIEW":
            gate_sale_gate_status = "REVIEW"

        real_competitor_count = inputs.get("real_competitor_count")
        if real_competitor_count is None:
            real_competitor_count = 1 if confidence_band in ("MEDIUM", "HIGH") and gate_sale_gate_status != "BLOCK" else 0
        serviceable_competitor_count = inputs.get("serviceable_competitor_count")

        legal_action_actor_org_name_seed = (
            inputs.get("legal_action_actor_org_name_seed")
            or inputs.get("legal_action_actor_org_name")
            or challenger_bidder_id
        )
        procurement_decision_actor_org_name_seed = (
            inputs.get("procurement_decision_actor_org_name_seed")
            or inputs.get("procurement_actor_org_name")
            or f"PROCUREMENT_DECISION::{project_id}"
        )
        buyer_type_hint = ensure_enum(self.store, "buyer_type", inputs.get("buyer_type", "GOVERNMENT"))
        queue_policy_context = ContextPacket.from_records(
            capability_mode="stage6_fact_review",
            stage=6,
            project_id=project_id,
            records={
                "project_fact": {"sale_gate_status": gate_sale_gate_status},
                "clock_chain_profile": {
                    "current_action_clock": inputs.get("current_action_clock"),
                    "clock_conflict_state": inputs.get("clock_conflict_state"),
                },
                "legal_action_recommendation": {},
            },
            inputs={
                **dict(inputs),
                "sale_gate_status": gate_sale_gate_status,
            },
        )
        queue_policy_state = StatePacket(capability_mode="stage6_fact_review")
        queue_policy_decision = policy_executor.execute(
            "window_value",
            queue_policy_context,
            queue_policy_state,
        )
        queue_policy_state.add_decision(queue_policy_decision)
        queue_outputs = queue_policy_state.merged_outputs()

        requested_review_lane = stage5_handoff.get(
            "review_lane",
            review_request.get("review_lane") if review_request else None,
        )
        review_lane = ensure_enum(
            self.store,
            "review_lane",
            str(requested_review_lane or queue_outputs.get("review_lane", "STANDARD")),
        )
        review_queue_bucket = ensure_enum(
            self.store,
            "review_queue_bucket",
            str(queue_outputs.get("review_queue_bucket", "NORMAL")),
        )
        window_risk_level = ensure_enum(
            self.store,
            "window_risk_level",
            str(queue_outputs.get("window_risk_level", "MEDIUM")),
        )
        commercial_urgency_level = ensure_enum(
            self.store,
            "commercial_urgency_level",
            str(queue_outputs.get("commercial_urgency_level", "NORMAL")),
        )
        review_priority_score = int(queue_outputs.get("review_priority_score", 40))
        window_status = ensure_enum(
            self.store,
            "window_status",
            str(queue_outputs.get("window_status", "REVIEW_REQUIRED")),
        )
        apply_rule(self.store, trace_rules, "STATE-605")

        review_queue_profile = self.store.build_record(
            "review_queue_profile",
            {
                "queue_profile_id": build_id("QUEUE", project_id),
                "project_id": project_id,
                "review_lane": review_lane,
                "review_priority_score": review_priority_score,
                "review_queue_bucket": review_queue_bucket,
                "window_risk_level": window_risk_level,
                "commercial_urgency_level": commercial_urgency_level,
                "assigned_reviewer_optional": inputs.get("assigned_reviewer_optional", "UNASSIGNED"),
            },
        )

        report_status = "DRAFT"
        review_task_status = "NOT_READY"
        if evidence_gate_status != "BLOCK" and rule_gate_status != "BLOCK":
            apply_rule(self.store, trace_rules, "STATE-601")
            report_status = "READY"
            review_task_status = "IN_REVIEW"

        if get_flag(flags, "report_superseded"):
            apply_rule(self.store, trace_rules, "STATE-604")
            report_status = "REVOKED"
            review_task_status = "SUPERSEDED"
        elif get_flag(flags, "report_blocked") or evidence_gate_status == "BLOCK" or rule_gate_status == "BLOCK":
            apply_rule(self.store, trace_rules, "STATE-603")
            report_status = "REVOKED"
            review_task_status = "CLOSED"
        elif get_flag(flags, "report_approved") and evidence_gate_status == "PASS" and rule_gate_status == "PASS":
            apply_rule(self.store, trace_rules, "STATE-602")
            report_status = "ISSUED"
            review_task_status = "CLOSED"

        minimum_release_level = ensure_enum(
            self.store, "release_level", inputs.get("minimum_release_level", "INTERNAL_OPERABLE")
        )

        supplement_trace: dict[str, Any] = {
            "supplement_loop_state": "NOT_REQUESTED",
            "linked_review_request_id_optional": review_request_id,
            "missing_condition_family_optional": missing_condition_family,
            "impact_decision_trace": {
                "source": "stage6_private_supplement_record",
                "stage6_internal_runtime_allowed": False,
                "stage6_internal_impact_allowed": False,
                "stage7_formal_surface_allowed": False,
                "external_or_live_allowed": False,
            },
        }
        private_supplement_record_optional: Mapping[str, Any] | None = None
        private_supplement_carrier_summary: dict[str, Any] | None = None
        supplement_requested = bool(
            review_request_id
            and (
                inputs.get("supplement_material_family")
                or inputs.get("supplement_source_owner")
                or get_flag(flags, "supplement_requested")
            )
        )
        if supplement_requested:
            supplement_release_state = "REVIEW_ELIGIBLE"
            supplement_usable_scope = "REVIEW_ONLY"
            supplement_loop_state = "REQUESTED"
            if get_flag(flags, "supplement_blocked"):
                supplement_release_state = "ISOLATED"
                supplement_usable_scope = "BLOCKED"
                supplement_loop_state = "BLOCKED"
            elif get_flag(flags, "supplement_ready_for_impact"):
                supplement_release_state = "IMPACT_ELIGIBLE"
                supplement_loop_state = "IMPACT_READY"
            private_supplement_record_optional = self.store.build_record(
                "private_supplement_record",
                {
                    "supplement_id": inputs.get("supplement_id", build_id("SUP", project_id)),
                    "project_id": project_id,
                    "linked_review_request_id": review_request_id,
                    "material_family": inputs.get("supplement_material_family", "REVIEW_BACKFILL"),
                    "source_owner": inputs.get("supplement_source_owner", "REVIEW_CHAIN"),
                    "lawful_basis": inputs.get("supplement_lawful_basis", "REVIEW_CHAIN_AUTHORIZED"),
                    "usable_scope": ensure_enum(self.store, "usable_scope", supplement_usable_scope),
                    "release_state": ensure_enum(self.store, "release_state", supplement_release_state),
                    "visible_roles": inputs.get(
                        "supplement_visible_roles",
                        "review_user,governance_owner",
                    ),
                    "written_back_policy": inputs.get(
                        "supplement_written_back_policy",
                        "GOVERNANCE_SINK_ONLY",
                    ),
                },
            ).data
            private_supplement_carrier_summary = _private_supplement_carrier_summary(
                private_supplement_record_optional,
                supplement_loop_state=supplement_loop_state,
                missing_condition_family=missing_condition_family,
            )
            supplement_trace = {
                "supplement_loop_state": supplement_loop_state,
                "linked_review_request_id_optional": review_request_id,
                "missing_condition_family_optional": missing_condition_family,
                "private_supplement_record_id_optional": private_supplement_record_optional.get("supplement_id"),
                "private_supplement_release_state_optional": private_supplement_record_optional.get("release_state"),
                "private_supplement_usable_scope_optional": private_supplement_record_optional.get("usable_scope"),
                "private_supplement_written_back_policy_optional": private_supplement_record_optional.get("written_back_policy"),
                "impact_readiness_state": private_supplement_carrier_summary.get("impact_readiness_state"),
                "impact_decision_trace": private_supplement_carrier_summary.get("impact_decision_trace"),
                "private_supplement_carrier_summary": private_supplement_carrier_summary,
            }

        report_payload = {
            "report_id": build_id("REPORT", project_id),
            "project_id": project_id,
            "brief_path": inputs.get("brief_path", f"reports/{project_id}/brief.md"),
            "evidence_pack_path": inputs.get("evidence_pack_path", f"reports/{project_id}/evidence.zip"),
            "objection_draft_path": inputs.get("objection_draft_path", f"reports/{project_id}/objection.md"),
            "review_task_status": review_task_status,
            "report_status": report_status,
            "review_lane": review_lane,
            "review_sla_due_at": inputs.get("review_sla_due_at", now),
            "minimum_release_level": minimum_release_level,
        }
        report_semantic = self.store.evaluate_object_semantics(
            stage=6,
            object_type="report_record",
            payload=report_payload,
            semantic_context={
                "rule_gate_status": rule_gate_status,
                "evidence_gate_status": evidence_gate_status,
            },
        )
        if report_semantic:
            semantic_state.add_semantic_validation(report_semantic)
            if report_semantic.decision_state == "BLOCK":
                report_payload["report_status"] = "REVOKED"
                report_payload["review_task_status"] = "CLOSED"
            elif report_semantic.decision_state == "REVIEW" and report_payload["report_status"] == "ISSUED":
                report_payload["report_status"] = "READY"
                report_payload["review_task_status"] = "IN_REVIEW"
        report_record = self.store.build_record("report_record", report_payload)
        report_status = report_record.get("report_status")
        review_task_status = report_record.get("review_task_status")

        sale_gate_status = gate_sale_gate_status
        if gate_sale_gate_status == "OPEN" and report_record.get("report_status") != "ISSUED":
            sale_gate_status = "HOLD"

        if serviceable_competitor_count is None:
            serviceable_competitor_count = 1 if sale_gate_status == "OPEN" and real_competitor_count > 0 else 0

        project_fact_payload = {
            "project_fact_id": build_id("FACT", project_id),
            "project_id": project_id,
            "sale_gate_status": sale_gate_status,
            "rule_gate_status": rule_gate_status,
            "evidence_gate_status": evidence_gate_status,
            "rule_hit_summary": inputs.get("rule_hit_summary", [rule_hit.get("rule_hit_id")]),
            "clue_summary": ensure_list(inputs.get("clue_summary")),
            "risk_summary": ensure_list(inputs.get("risk_summary")),
            "coverage_sellable_state": ensure_enum(
                self.store, "coverage_sellable_state", inputs.get("coverage_sellable_state")
            ),
            "delivery_risk_state": ensure_enum(
                self.store, "delivery_risk_state", inputs.get("delivery_risk_state")
            ),
            "manual_override_status": ensure_enum(
                self.store, "manual_override_status", inputs.get("manual_override_status")
            ),
            "real_competitor_count": int(real_competitor_count),
            "serviceable_competitor_count": int(serviceable_competitor_count),
        }

        focus_bidder_attackability_score = int(
            inputs.get(
                "focus_bidder_attackability_score",
                88 if sale_gate_status == "OPEN" and confidence_band == "HIGH"
                else 78 if sale_gate_status == "OPEN"
                else 68 if sale_gate_status == "HOLD"
                else 58 if sale_gate_status == "REVIEW"
                else 32,
            )
        )
        challenger_pain_score = int(
            inputs.get(
                "challenger_pain_score",
                84 if sale_gate_status == "OPEN" else 72 if sale_gate_status == "HOLD" else 60 if sale_gate_status == "REVIEW" else 36,
            )
        )
        succession_gain_score = int(
            inputs.get(
                "succession_gain_score",
                79 if report_status == "ISSUED" else 61 if report_status == "READY" else 35,
            )
        )
        execution_readiness_score = int(
            inputs.get(
                "execution_readiness_score",
                82 if report_status == "ISSUED" and sale_gate_status == "OPEN"
                else 64 if sale_gate_status != "BLOCK"
                else 28,
            )
        )
        challenge_actionability_score = int(
            inputs.get(
                "challenge_actionability_score",
                round(
                    (
                        focus_bidder_attackability_score
                        + challenger_pain_score
                        + succession_gain_score
                        + execution_readiness_score
                    ) / 4
                ),
            )
        )
        challenger_payload = {
            "challenger_profile_id": build_id("CH", project_id),
            "project_id": project_id,
            "focus_bidder_id": focus_bidder_id,
            "challenger_bidder_id": challenger_bidder_id,
            "candidate_position_label": candidate_position_label,
            "focus_bidder_attackability_score": focus_bidder_attackability_score,
            "challenger_pain_score": challenger_pain_score,
            "succession_gain_score": succession_gain_score,
            "execution_readiness_score": execution_readiness_score,
            "challenge_actionability_score": challenge_actionability_score,
        }
        challenger_semantic = self.store.evaluate_object_semantics(
            stage=6,
            object_type="challenger_candidate_profile",
            payload=challenger_payload,
            semantic_context={
                "sale_gate_status": sale_gate_status,
                "real_competitor_count": int(real_competitor_count),
            },
        )
        if challenger_semantic:
            semantic_state.add_semantic_validation(challenger_semantic)
            if challenger_semantic.decision_state in ("REVIEW", "BLOCK"):
                challenger_payload["challenge_actionability_score"] = min(
                    challenger_payload["challenge_actionability_score"],
                    54,
                )
        challenger_candidate_profile = self.store.build_record(
            "challenger_candidate_profile",
            challenger_payload,
        )

        competitor_policy_context = ContextPacket.from_records(
            capability_mode="stage6_fact_review",
            stage=6,
            project_id=project_id,
            records={
                "challenger_candidate_profile": challenger_candidate_profile,
            },
            inputs={
                **dict(inputs),
                "external_use_grade": inputs.get("external_use_grade"),
                "confidence_band": confidence_band,
                "evidence_ref_count_optional": inputs.get("evidence_ref_count_optional", 2),
                "now": now,
            },
        )
        competitor_policy_state = StatePacket(capability_mode="stage6_fact_review")
        competitor_policy_decision = policy_executor.execute(
            "competitor_confidence",
            competitor_policy_context,
            competitor_policy_state,
        )
        competitor_policy_state.add_decision(competitor_policy_decision)
        competitor_outputs = competitor_policy_state.merged_outputs()
        competitor_quality_grade = ensure_enum(
            self.store,
            "competitor_quality_grade",
            str(competitor_outputs.get("competitor_quality_grade", "D")),
        )
        competitor_confidence_score = competitor_outputs.get("competitor_confidence_score")
        competitor_confidence_band = competitor_outputs.get("competitor_confidence_band")

        project_fact_payload["competitor_quality_grade"] = competitor_quality_grade
        project_fact_semantic = self.store.evaluate_object_semantics(
            stage=6,
            object_type="project_fact",
            payload=project_fact_payload,
            semantic_context={
                "report_status": report_record.get("report_status"),
            },
        )
        if project_fact_semantic:
            semantic_state.add_semantic_validation(project_fact_semantic)
            if project_fact_semantic.decision_state == "BLOCK":
                project_fact_payload["sale_gate_status"] = "BLOCK"
        project_fact = self.store.build_record("project_fact", project_fact_payload)

        blocking_reasons = ensure_list(inputs.get("blocking_reasons"))
        if not blocking_reasons:
            if rule_gate_status != "PASS":
                blocking_reasons.append("rule_gate_not_passed")
            if evidence_gate_status != "PASS":
                blocking_reasons.append("evidence_gate_not_passed")
            if report_status != "ISSUED":
                blocking_reasons.append(f"report_status={report_status}")
            if window_status in ("REVIEW_REQUIRED", "MISSED"):
                blocking_reasons.append(f"window_status={window_status}")
            if review_request and review_request.get("missing_condition_family"):
                blocking_reasons.append(review_request.get("missing_condition_family"))
            cutoff_reasons = ensure_list(competitor_outputs.get("competitor_cutoff_reasons"))
            if competitor_policy_state.decision_state != "ALLOW":
                if cutoff_reasons:
                    blocking_reasons.extend(cutoff_reasons)
                else:
                    blocking_reasons.append("competitor_confidence_review_required")
        blocking_reasons = _dedupe_strings(blocking_reasons)

        legal_action_resolution_context = ContextPacket.from_records(
            capability_mode="stage6_fact_review",
            stage=6,
            project_id=project_id,
            records={
                "project_fact": project_fact,
                "report_record": report_record,
                "legal_action_recommendation": {},
            },
            inputs={
                **dict(inputs),
                "sale_gate_status": sale_gate_status,
                "report_status": report_status,
                "rule_gate_status": rule_gate_status,
                "evidence_gate_status": evidence_gate_status,
                "window_status": window_status,
                "requested_action_family_optional": inputs.get("action_family"),
                "requested_recommended_next_step_optional": inputs.get("recommended_next_step"),
            },
        )
        legal_action_resolution_state = StatePacket(capability_mode="stage6_fact_review")
        legal_action_resolution_decision = policy_executor.execute(
            "stage6_legal_action",
            legal_action_resolution_context,
            legal_action_resolution_state,
        )
        legal_action_resolution_state.add_decision(legal_action_resolution_decision)
        legal_action_outputs = legal_action_resolution_state.merged_outputs()
        action_family = ensure_enum(
            self.store,
            "action_family",
            str(legal_action_outputs.get("action_family", "REVIEW_ONLY")),
        )
        recommended_next_step = str(
            legal_action_outputs.get("recommended_next_step", "route_to_review_queue")
        )

        legal_action_payload = {
            "action_id": build_id("LAR", project_id),
            "project_id": project_id,
            "action_family": action_family,
            "applicable_regime": ensure_enum(
                self.store, "procurement_regime", inputs.get("procurement_regime", "UNKNOWN")
            ),
            "competent_authority_scope": inputs.get(
                "competent_authority_scope", "PROCUREMENT_AUTHORITY"
            ),
            "window_status": window_status,
            "basis_summary": inputs.get(
                "basis_summary",
                f"rule={rule_gate_status}; evidence={evidence_gate_status}; evidence_ref={evidence.get('evidence_id')}; report={report_status}; confidence={confidence_band}",
            ),
            "blocking_reasons": blocking_reasons,
            "recommended_next_step": recommended_next_step,
        }
        legal_action_semantic = self.store.evaluate_object_semantics(
            stage=6,
            object_type="legal_action_recommendation",
            payload=legal_action_payload,
            semantic_context={
                "sale_gate_status": project_fact_payload["sale_gate_status"],
            },
        )
        if legal_action_semantic:
            semantic_state.add_semantic_validation(legal_action_semantic)
            if legal_action_semantic.decision_state in ("REVIEW", "BLOCK"):
                semantic_override_context = ContextPacket.from_records(
                    capability_mode="stage6_fact_review",
                    stage=6,
                    project_id=project_id,
                    records={
                        "project_fact": project_fact,
                        "report_record": report_record,
                        "legal_action_recommendation": legal_action_payload,
                    },
                    inputs={
                        **dict(inputs),
                        "sale_gate_status": sale_gate_status,
                        "report_status": report_status,
                        "rule_gate_status": rule_gate_status,
                        "evidence_gate_status": evidence_gate_status,
                        "window_status": window_status,
                        "requested_action_family_optional": inputs.get("action_family"),
                        "requested_recommended_next_step_optional": inputs.get(
                            "recommended_next_step"
                        ),
                        "semantic_decision_state_optional": legal_action_semantic.decision_state,
                    },
                )
                semantic_override_state = StatePacket(capability_mode="stage6_fact_review")
                semantic_override_decision = policy_executor.execute(
                    "stage6_legal_action",
                    semantic_override_context,
                    semantic_override_state,
                )
                semantic_override_state.add_decision(semantic_override_decision)
                semantic_outputs = semantic_override_state.merged_outputs()
                legal_action_payload["action_family"] = ensure_enum(
                    self.store,
                    "action_family",
                    str(semantic_outputs.get("action_family", "REVIEW_ONLY")),
                )
                legal_action_payload["recommended_next_step"] = str(
                    semantic_outputs.get(
                        "recommended_next_step",
                        legal_action_payload["recommended_next_step"],
                    )
                )
        legal_action_recommendation = self.store.build_record("legal_action_recommendation", legal_action_payload)

        handoff = {
            "project_id": project_id,
            "review_queue_profile_id": review_queue_profile.get("queue_profile_id"),
            "review_lane": review_lane,
            "review_priority_score": review_priority_score,
            "review_queue_bucket": review_queue_bucket,
            "window_risk_level": window_risk_level,
            "commercial_urgency_level": commercial_urgency_level,
            "sale_gate_status": sale_gate_status,
            "real_competitor_count": project_fact.get("real_competitor_count"),
            "competitor_quality_grade": project_fact.get("competitor_quality_grade"),
            "window_status": legal_action_recommendation.get("window_status"),
            "report_id": report_record.get("report_id"),
            "report_status": report_status,
            "review_task_status": review_task_status,
            "minimum_release_level": report_record.get("minimum_release_level"),
            "action_family": legal_action_recommendation.get("action_family"),
            "recommended_next_step": legal_action_recommendation.get("recommended_next_step"),
            "challenger_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
            "focus_bidder_id": challenger_candidate_profile.get("focus_bidder_id"),
            "challenger_bidder_id": challenger_candidate_profile.get("challenger_bidder_id"),
            "candidate_position_label": challenger_candidate_profile.get("candidate_position_label"),
            "challenge_actionability_score": challenger_candidate_profile.get("challenge_actionability_score"),
            "execution_readiness_score": challenger_candidate_profile.get("execution_readiness_score"),
            "legal_action_actor_org_name_seed": legal_action_actor_org_name_seed,
            "procurement_decision_actor_org_name_seed": procurement_decision_actor_org_name_seed,
            "buyer_type_hint": buyer_type_hint,
        }
        if competitor_confidence_score is not None:
            handoff["confidence_score_optional"] = int(competitor_confidence_score)
        if review_request_id:
            handoff["linked_review_request_id_optional"] = review_request_id
            handoff["missing_condition_family_optional"] = missing_condition_family
        if private_supplement_record_optional:
            handoff["private_supplement_record_id_optional"] = private_supplement_record_optional.get("supplement_id")
            handoff["private_supplement_release_state_optional"] = private_supplement_record_optional.get("release_state")
            handoff["private_supplement_usable_scope_optional"] = private_supplement_record_optional.get("usable_scope")
            handoff["private_supplement_written_back_policy_optional"] = private_supplement_record_optional.get("written_back_policy")
        if private_supplement_carrier_summary:
            handoff["private_supplement_carrier_summary"] = private_supplement_carrier_summary

        inputs_out = dict(inputs)
        inputs_out["window_status"] = legal_action_recommendation.get("window_status")
        inputs_out["challenger_profile_id"] = challenger_candidate_profile.get("challenger_profile_id")
        inputs_out["action_family"] = legal_action_recommendation.get("action_family")
        inputs_out["recommended_next_step"] = legal_action_recommendation.get("recommended_next_step")
        inputs_out["focus_bidder_id"] = challenger_candidate_profile.get("focus_bidder_id")
        inputs_out["challenger_bidder_id"] = challenger_candidate_profile.get("challenger_bidder_id")
        inputs_out["candidate_position_label"] = challenger_candidate_profile.get("candidate_position_label")
        inputs_out["report_status"] = report_status
        inputs_out["review_task_status"] = review_task_status
        inputs_out["challenge_actionability_score"] = challenger_candidate_profile.get("challenge_actionability_score")
        inputs_out["execution_readiness_score"] = challenger_candidate_profile.get("execution_readiness_score")
        inputs_out["legal_action_actor_org_name_seed"] = legal_action_actor_org_name_seed
        inputs_out["procurement_decision_actor_org_name_seed"] = procurement_decision_actor_org_name_seed
        inputs_out["buyer_type_hint"] = buyer_type_hint
        inputs_out["review_lane"] = review_lane
        inputs_out["review_priority_score"] = review_priority_score
        inputs_out["review_queue_bucket"] = review_queue_bucket
        inputs_out["window_risk_level"] = window_risk_level
        inputs_out["commercial_urgency_level"] = commercial_urgency_level
        inputs_out["window_urgency_score"] = int(queue_outputs.get("window_urgency_score", 50))
        inputs_out["review_queue_profile_id"] = review_queue_profile.get("queue_profile_id")
        inputs_out["report_id"] = report_record.get("report_id")
        inputs_out["minimum_release_level"] = report_record.get("minimum_release_level")
        inputs_out["confidence_score_optional"] = (
            int(competitor_confidence_score) if competitor_confidence_score is not None else None
        )
        inputs_out["confidence_band_optional"] = competitor_confidence_band
        inputs_out["linked_review_request_id_optional"] = review_request_id
        inputs_out["missing_condition_family_optional"] = missing_condition_family
        inputs_out["stage6_review_report_trace"] = {
            "h05_authority_snapshot": {
                "rule_gate_status": rule_gate_status,
                "evidence_gate_status": evidence_gate_status,
                "coverage_sellable_state": inputs.get("coverage_sellable_state"),
                "delivery_risk_state": inputs.get("delivery_risk_state"),
                "linked_review_request_id_optional": review_request_id,
            },
            "review_queue_snapshot": {
                "review_lane": review_lane,
                "review_priority_score": review_priority_score,
                "review_queue_bucket": review_queue_bucket,
                "window_risk_level": window_risk_level,
                "commercial_urgency_level": commercial_urgency_level,
            },
            "report_snapshot": {
                "report_id": report_record.get("report_id"),
                "report_status": report_status,
                "review_task_status": review_task_status,
                "minimum_release_level": report_record.get("minimum_release_level"),
            },
            "supplement_trace": supplement_trace,
        }
        inputs_out["private_supplement_record_optional"] = private_supplement_record_optional
        if private_supplement_carrier_summary:
            inputs_out["private_supplement_carrier_summary"] = private_supplement_carrier_summary
        inputs_out["stage6_review_queue_policy_trace"] = queue_policy_state.trace
        inputs_out["stage6_competitor_confidence_trace"] = competitor_policy_state.trace
        inputs_out["stage6_legal_action_resolution_trace"] = legal_action_resolution_state.trace
        inputs_out["semantic_trace"] = semantic_state.semantic_trace
        inputs_out["semantic_decision_state"] = semantic_state.semantic_decision_state
        inputs_out["semantic_additions"] = semantic_state.semantic_additions

        return StageBundle(
            stage=6,
            records={
                "project_fact": project_fact,
                "legal_action_recommendation": legal_action_recommendation,
                "review_queue_profile": review_queue_profile,
                "report_record": report_record,
                "challenger_candidate_profile": challenger_candidate_profile,
            },
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )


__all__ = ["ProjectFactAggregator"]
