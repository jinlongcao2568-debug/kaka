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


STAGE6_PRODUCT_PACKAGE_READINESS_KEY = "stage6_product_package_readiness"

_RELEASE_LEVEL_RANK = {
    "DEV_ALLOWED": 0,
    "INTERNAL_OPERABLE": 1,
    "LEADPACK_DELIVERABLE": 2,
    "EXTERNAL_BLOCKED": 3,
}

_EXTERNAL_USE_GRADE_RANK = {
    "E1_INTERNAL_ONLY": 1,
    "E2_REVIEW_READY": 2,
    "E3_CLIENT_VISIBLE": 3,
    "E4_EXTERNAL_ACTION_READY": 4,
}

_STAGE6_DELIVERABLE_OBJECTS = (
    "project_fact",
    "report_record",
    "legal_action_recommendation",
    "challenger_candidate_profile",
)


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


def _rank_allows(rank_map: Mapping[str, int], value: Any, minimum: str) -> bool:
    return rank_map.get(str(value), -1) >= rank_map[minimum]


def _package_state_from_reasons(
    *,
    block_reasons: list[str],
    review_reasons: list[str],
) -> str:
    if block_reasons:
        return "BLOCKED"
    if review_reasons:
        return "REVIEW_REQUIRED"
    return "INTERNAL_READY"


def _governance_guard_summary(result: Any) -> dict[str, Any]:
    additions = dict(getattr(result, "governance_additions", {}) or {})
    trace_fields = dict(getattr(result, "trace_fields", {}) or {})
    field_policy = dict(additions.get("field_policy", {}) or {})
    return {
        "object_type": getattr(result, "object_type", None),
        "decision_state": getattr(result, "decision_state", "ALLOW"),
        "reasons": list(getattr(result, "reasons", []) or []),
        "field_policy": {
            "blocked_fields": list(field_policy.get("blocked_fields", []) or []),
            "review_fields": list(field_policy.get("review_fields", []) or []),
            "projected_fields": dict(field_policy.get("projected_fields", {}) or {}),
        },
        "delivery_matrix": dict(additions.get("delivery_matrix", {}) or {}),
        "release_gates": dict(additions.get("release_gates", {}) or {}),
        "trace": {
            "current_surface": trace_fields.get("current_surface"),
            "target_surfaces": list(trace_fields.get("target_surfaces", []) or []),
            "release_level": trace_fields.get("release_level"),
            "approval_state": trace_fields.get("approval_state"),
            "action_intent": trace_fields.get("action_intent"),
        },
    }


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

    def _source_object_refs(
        self,
        *,
        inputs: Mapping[str, Any],
        project_fact: Mapping[str, Any],
        report_record: Mapping[str, Any],
        review_queue_profile: Mapping[str, Any],
        challenger_candidate_profile: Mapping[str, Any],
        legal_action_recommendation: Mapping[str, Any],
        rule_hit: Mapping[str, Any],
        evidence: Mapping[str, Any],
        rule_gate: Mapping[str, Any],
        evidence_gate: Mapping[str, Any],
        private_supplement_carrier_summary: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        refs = {
            "project_id": project_fact.get("project_id"),
            "project_fact_id": project_fact.get("project_fact_id"),
            "report_record_id": report_record.get("report_id"),
            "review_queue_profile_id": review_queue_profile.get("queue_profile_id"),
            "challenger_candidate_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
            "legal_action_recommendation_id": legal_action_recommendation.get("action_id"),
            "rule_hit_id": rule_hit.get("rule_hit_id") or inputs.get("rule_hit_id"),
            "evidence_id": evidence.get("evidence_id") or inputs.get("evidence_id"),
            "rule_gate_decision_id": rule_gate.get("gate_id") or inputs.get("rule_gate_decision_id"),
            "evidence_gate_decision_id": evidence_gate.get("gate_id") or inputs.get("evidence_gate_decision_id"),
            "review_request_id": inputs.get("linked_review_request_id_optional") or inputs.get("review_request_id"),
            "private_supplement_record_id_optional": (
                private_supplement_carrier_summary.get("supplement_id")
                if isinstance(private_supplement_carrier_summary, Mapping)
                else None
            ),
            "source_document_ref": inputs.get("source_document_ref"),
            "source_slice_ref": inputs.get("source_slice_ref"),
            "public_attack_surface_id": inputs.get("public_attack_surface_id"),
            "verification_profile_id": inputs.get("verification_profile_id"),
            "evidence_grade_profile_id": inputs.get("evidence_grade_profile_id"),
            "pseudo_competitor_signal_set_id": inputs.get("pseudo_competitor_signal_set_id"),
        }
        stage4_public_verification = inputs.get("stage4_public_verification_carrier")
        if isinstance(stage4_public_verification, Mapping):
            refs.update(
                {
                    "stage4_public_verification_run_id_optional": stage4_public_verification.get("verification_run_id"),
                    "stage4_public_verification_target_id_optional": stage4_public_verification.get(
                        "verification_target_id"
                    ),
                    "stage4_public_verification_target_type_optional": stage4_public_verification.get(
                        "verification_target_type"
                    ),
                    "stage4_public_verification_result_optional": stage4_public_verification.get(
                        "verification_result"
                    ),
                    "source_snapshot_id_optional": stage4_public_verification.get("source_snapshot_id"),
                    "input_parse_run_id_optional": stage4_public_verification.get("input_parse_run_id"),
                    "parsed_field_refs_optional": stage4_public_verification.get("parsed_field_refs"),
                }
            )
        stage5_rule_readback = inputs.get("stage5_rule_readback_summary")
        if isinstance(stage5_rule_readback, Mapping):
            refs["stage4_public_verification_refs_optional"] = stage5_rule_readback.get(
                "stage4_public_verification_refs"
            )
        return {
            key: value
            for key, value in refs.items()
            if value not in (None, "", "UNKNOWN")
        }

    def _delivery_governance_summary(
        self,
        *,
        records: Mapping[str, Mapping[str, Any]],
        inputs: Mapping[str, Any],
        minimum_release_level: str,
        requested_delivery_surface: str,
        report_status: str,
        rule_gate_status: str,
        evidence_gate_status: str,
    ) -> dict[str, Any]:
        approval_state = str(inputs.get("approval_state", "NOT_REQUIRED"))
        guard_context = {
            "current_surface": "INTERNAL_OPERATIONS",
            "target_surfaces": [requested_delivery_surface],
            "requested_target_surface": requested_delivery_surface,
            "release_level": minimum_release_level,
            "approval_state": approval_state,
            "action_intent": "PREVIEW_ONLY",
            "requested_gate_ids": ["client_report_release"],
            "gate_conditions": {
                "rule_gate_passed": rule_gate_status == "PASS",
                "evidence_gate_passed": evidence_gate_status == "PASS",
                "report_issued": report_status == "ISSUED",
                "stage9_outcome_governance_writeback_recorded": bool(
                    inputs.get("stage9_outcome_governance_writeback_recorded", False)
                ),
            },
        }
        object_results: dict[str, dict[str, Any]] = {}
        governance_reasons: list[str] = []
        decision_state = "ALLOW"
        field_policy_masking: dict[str, Any] = {
            "blocked_fields": [],
            "review_fields": [],
            "projected_fields": {},
        }

        for object_type in _STAGE6_DELIVERABLE_OBJECTS:
            result = self.store.evaluate_runtime_guards(
                object_type,
                dict(records[object_type]),
                guard_context,
            )
            summary = _governance_guard_summary(result)
            object_results[object_type] = summary
            governance_reasons.extend(
                f"{object_type}:{reason}" for reason in summary["reasons"]
            )
            if summary["decision_state"] == "BLOCK":
                decision_state = "BLOCK"
            elif summary["decision_state"] == "REVIEW" and decision_state != "BLOCK":
                decision_state = "REVIEW"

            field_policy = summary["field_policy"]
            field_policy_masking["blocked_fields"].extend(field_policy["blocked_fields"])
            field_policy_masking["review_fields"].extend(field_policy["review_fields"])
            for surface, projected_fields in field_policy["projected_fields"].items():
                field_policy_masking["projected_fields"].setdefault(surface, []).extend(
                    projected_fields
                )

        return {
            "decision_state": decision_state,
            "requested_delivery_surface": requested_delivery_surface,
            "governance_reasons": _dedupe_strings(governance_reasons),
            "field_policy_masking": {
                "blocked_fields": _dedupe_strings(field_policy_masking["blocked_fields"]),
                "review_fields": _dedupe_strings(field_policy_masking["review_fields"]),
                "projected_fields": field_policy_masking["projected_fields"],
            },
            "objects": object_results,
            "excluded_internal_only_object_refs": {
                "review_queue_profile": records["review_queue_profile"].get("queue_profile_id"),
            },
        }

    def _product_package_readiness(
        self,
        *,
        inputs: Mapping[str, Any],
        project_fact: Mapping[str, Any],
        report_record: Mapping[str, Any],
        review_queue_profile: Mapping[str, Any],
        challenger_candidate_profile: Mapping[str, Any],
        legal_action_recommendation: Mapping[str, Any],
        rule_hit: Mapping[str, Any],
        evidence: Mapping[str, Any],
        rule_gate: Mapping[str, Any],
        evidence_gate: Mapping[str, Any],
        semantic_state: StatePacket,
        private_supplement_carrier_summary: Mapping[str, Any] | None,
        now: str,
    ) -> dict[str, Any]:
        rule_gate_status = str(project_fact.get("rule_gate_status"))
        evidence_gate_status = str(project_fact.get("evidence_gate_status"))
        sale_gate_status = str(project_fact.get("sale_gate_status"))
        report_status = str(report_record.get("report_status"))
        review_task_status = str(report_record.get("review_task_status"))
        minimum_release_level = str(report_record.get("minimum_release_level"))
        external_use_grade = str(inputs.get("external_use_grade", "E1_INTERNAL_ONLY"))
        confidence_band = str(inputs.get("confidence_band", "MEDIUM"))
        delivery_risk_state = str(project_fact.get("delivery_risk_state"))
        action_family = str(legal_action_recommendation.get("action_family"))
        window_status = str(legal_action_recommendation.get("window_status"))
        linked_review_request_id = inputs.get("linked_review_request_id_optional") or inputs.get("review_request_id")
        missing_condition_family = inputs.get("missing_condition_family_optional") or inputs.get("missing_condition_family")
        evidence_ref_count = inputs.get("evidence_ref_count_optional")
        requested_delivery_surface = str(inputs.get("requested_delivery_surface", "LEADPACK_DELIVERABLE"))
        approval_state = str(inputs.get("approval_state", "NOT_REQUIRED"))

        records = {
            "project_fact": project_fact,
            "report_record": report_record,
            "review_queue_profile": review_queue_profile,
            "legal_action_recommendation": legal_action_recommendation,
            "challenger_candidate_profile": challenger_candidate_profile,
        }
        source_object_refs = self._source_object_refs(
            inputs=inputs,
            project_fact=project_fact,
            report_record=report_record,
            review_queue_profile=review_queue_profile,
            challenger_candidate_profile=challenger_candidate_profile,
            legal_action_recommendation=legal_action_recommendation,
            rule_hit=rule_hit,
            evidence=evidence,
            rule_gate=rule_gate,
            evidence_gate=evidence_gate,
            private_supplement_carrier_summary=private_supplement_carrier_summary,
        )
        required_source_ref_keys = (
            "project_fact_id",
            "report_record_id",
            "review_queue_profile_id",
            "challenger_candidate_profile_id",
            "legal_action_recommendation_id",
            "rule_hit_id",
            "evidence_id",
            "rule_gate_decision_id",
            "evidence_gate_decision_id",
        )
        missing_source_refs = [
            key for key in required_source_ref_keys if key not in source_object_refs
        ]

        delivery_governance = self._delivery_governance_summary(
            records=records,
            inputs=inputs,
            minimum_release_level=minimum_release_level,
            requested_delivery_surface=requested_delivery_surface,
            report_status=report_status,
            rule_gate_status=rule_gate_status,
            evidence_gate_status=evidence_gate_status,
        )

        block_reasons: list[str] = []
        downgrade_reasons: list[str] = []
        if rule_gate_status == "BLOCK":
            block_reasons.append("rule_gate_status=BLOCK")
        elif rule_gate_status != "PASS":
            downgrade_reasons.append(f"rule_gate_status={rule_gate_status}")
        if evidence_gate_status == "BLOCK":
            block_reasons.append("evidence_gate_status=BLOCK")
        elif evidence_gate_status != "PASS":
            downgrade_reasons.append(f"evidence_gate_status={evidence_gate_status}")
        if delivery_risk_state == "BLOCK":
            block_reasons.append("delivery_risk_state=BLOCK")
        elif delivery_risk_state not in ("ALLOW", "READY"):
            downgrade_reasons.append(f"delivery_risk_state={delivery_risk_state}")
        if report_status == "REVOKED":
            block_reasons.append("report_status=REVOKED_not_ISSUED")
        elif report_status != "ISSUED":
            downgrade_reasons.append(f"report_status={report_status}_not_ISSUED")
        if review_task_status not in ("CLOSED", "APPROVED"):
            downgrade_reasons.append(
                f"review_task_status={review_task_status}_requires_closed_or_approved"
            )
        if linked_review_request_id:
            downgrade_reasons.append("linked_review_request_id_present")
        if missing_condition_family:
            downgrade_reasons.append(f"missing_condition_family={missing_condition_family}")
        if window_status in ("REVIEW_REQUIRED", "MISSED"):
            downgrade_reasons.append(f"window_status={window_status}")
        if sale_gate_status == "BLOCK":
            block_reasons.append("sale_gate_status=BLOCK")
        elif sale_gate_status in ("REVIEW", "HOLD"):
            downgrade_reasons.append(f"sale_gate_status={sale_gate_status}")
        if not _rank_allows(_EXTERNAL_USE_GRADE_RANK, external_use_grade, "E3_CLIENT_VISIBLE"):
            downgrade_reasons.append(
                f"external_use_grade={external_use_grade}_below_E3_CLIENT_VISIBLE"
            )
        if confidence_band == "LOW":
            downgrade_reasons.append("confidence_band=LOW")
        if evidence_ref_count is not None:
            try:
                evidence_ref_count_int = int(evidence_ref_count)
            except (TypeError, ValueError):
                downgrade_reasons.append(f"evidence_ref_count={evidence_ref_count}_unusable")
            else:
                if evidence_ref_count_int < 2:
                    downgrade_reasons.append(f"evidence_ref_count={evidence_ref_count}_below_2")
        if not _rank_allows(_RELEASE_LEVEL_RANK, minimum_release_level, "LEADPACK_DELIVERABLE"):
            downgrade_reasons.append(
                f"minimum_release_level={minimum_release_level}_below_LEADPACK_DELIVERABLE"
            )
        if approval_state != "APPROVED":
            downgrade_reasons.append(
                f"approval_state={approval_state}_not_APPROVED_for_client_report_release"
            )
        if not bool(inputs.get("stage9_outcome_governance_writeback_recorded", False)):
            downgrade_reasons.append("stage9_writeback_before_delivery_missing")
        if missing_source_refs:
            block_reasons.append("source_object_refs_missing:" + ",".join(missing_source_refs))

        if linked_review_request_id and not private_supplement_carrier_summary:
            downgrade_reasons.append("private_supplement_unavailable_for_review_request")
        elif private_supplement_carrier_summary:
            supplement_trace = private_supplement_carrier_summary.get("impact_decision_trace", {})
            if not supplement_trace.get("stage6_internal_runtime_allowed", False):
                block_reasons.append("private_supplement_internal_runtime_blocked")
            if not supplement_trace.get("stage6_internal_impact_allowed", False):
                downgrade_reasons.append("private_supplement_not_impact_ready")

        if semantic_state.semantic_decision_state == "BLOCK":
            block_reasons.append("semantic_decision_state=BLOCK")
        elif semantic_state.semantic_decision_state in ("REVIEW", "FALLBACK"):
            downgrade_reasons.append(f"semantic_decision_state={semantic_state.semantic_decision_state}")

        governance_state = str(delivery_governance["decision_state"])
        if governance_state == "BLOCK":
            block_reasons.extend(
                f"delivery_governance:{reason}"
                for reason in delivery_governance["governance_reasons"]
            )
        elif governance_state == "REVIEW":
            downgrade_reasons.extend(
                f"delivery_governance:{reason}"
                for reason in delivery_governance["governance_reasons"]
            )

        block_reasons = _dedupe_strings(block_reasons)
        downgrade_reasons = _dedupe_strings(downgrade_reasons)

        public_visibility_ready = _rank_allows(
            _EXTERNAL_USE_GRADE_RANK,
            external_use_grade,
            "E3_CLIENT_VISIBLE",
        )
        review_state_ready = report_status == "ISSUED" and review_task_status in ("CLOSED", "APPROVED") and not linked_review_request_id
        field_allowlist_masking_ready = not delivery_governance["field_policy_masking"]["blocked_fields"]
        delivery_governance_ready = (
            governance_state == "ALLOW"
            and delivery_risk_state == "ALLOW"
            and bool(inputs.get("stage9_outcome_governance_writeback_recorded", False))
        )
        minimum_release_ready = _rank_allows(
            _RELEASE_LEVEL_RANK,
            minimum_release_level,
            "LEADPACK_DELIVERABLE",
        )
        evidence_gate_ready = rule_gate_status == "PASS" and evidence_gate_status == "PASS"
        approval_ready = approval_state == "APPROVED"
        customer_delivery_constraints = {
            "evidence_gate_ready": evidence_gate_ready,
            "public_visibility_ready": public_visibility_ready,
            "review_state_ready": review_state_ready,
            "field_allowlist_masking_ready": field_allowlist_masking_ready,
            "delivery_governance_ready": delivery_governance_ready,
            "minimum_release_ready": minimum_release_ready,
            "approval_ready": approval_ready,
            "stage9_writeback_ready": bool(inputs.get("stage9_outcome_governance_writeback_recorded", False)),
        }
        customer_delivery_eligibility = (
            "ELIGIBLE_GATED_NOT_PUBLISHED"
            if all(customer_delivery_constraints.values()) and not block_reasons
            else "NOT_ELIGIBLE"
        )

        internal_review_reasons = [
            reason
            for reason in downgrade_reasons
            if not reason.startswith("external_use_grade=")
            and not reason.startswith("minimum_release_level=")
            and not reason.startswith("approval_state=")
            and reason != "stage9_writeback_before_delivery_missing"
            and not reason.startswith("delivery_governance:")
        ]
        product_package_readiness = _package_state_from_reasons(
            block_reasons=block_reasons,
            review_reasons=internal_review_reasons,
        )

        if block_reasons:
            evidence_strength = "BLOCKED"
        elif rule_gate_status != "PASS" or evidence_gate_status != "PASS":
            evidence_strength = "WEAK"
        elif public_visibility_ready and confidence_band in ("MEDIUM", "HIGH"):
            evidence_strength = "STRONG"
        elif confidence_band in ("MEDIUM", "HIGH"):
            evidence_strength = "MEDIUM"
        else:
            evidence_strength = "WEAK"

        if block_reasons:
            objection_viability = "BLOCKED"
        elif action_family == "OBJECTION_PREP" and window_status == "ACTIONABLE" and evidence_gate_ready:
            objection_viability = "VIABLE"
        else:
            objection_viability = "REVIEW_REQUIRED"

        if block_reasons or sale_gate_status == "BLOCK":
            sellable_signal = "BLOCKED"
        elif sale_gate_status == "OPEN" and int(project_fact.get("real_competitor_count", 0)) > 0:
            sellable_signal = "SELLABLE_INTERNAL"
        else:
            sellable_signal = "RESTRICTED"

        if block_reasons:
            objection_pack_readiness = "BLOCKED"
            sales_readiness = "BLOCKED"
            delivery_readiness = "BLOCKED"
        elif product_package_readiness == "INTERNAL_READY":
            objection_pack_readiness = "INTERNAL_READY" if objection_viability == "VIABLE" else "REVIEW_REQUIRED"
            sales_readiness = "INTERNAL_READY_NO_EXECUTION_TRIGGERED" if sellable_signal == "SELLABLE_INTERNAL" else "REVIEW_REQUIRED"
            delivery_readiness = (
                "CUSTOMER_DELIVERY_ELIGIBLE_GATED"
                if customer_delivery_eligibility == "ELIGIBLE_GATED_NOT_PUBLISHED"
                else "INTERNAL_READY_CUSTOMER_GATED"
            )
        else:
            objection_pack_readiness = "REVIEW_REQUIRED"
            sales_readiness = "REVIEW_REQUIRED"
            delivery_readiness = "REVIEW_REQUIRED"

        external_visibility_status = (
            "LEADPACK_ELIGIBLE_NOT_PUBLISHED_EXTERNAL_PLATFORM_BLOCKED"
            if customer_delivery_eligibility == "ELIGIBLE_GATED_NOT_PUBLISHED"
            else "INTERNAL_ONLY_EXTERNAL_PLATFORM_BLOCKED"
        )

        customer_delivery_reasons = [
            reason
            for reason in [*downgrade_reasons, *block_reasons]
            if reason.startswith("external_use_grade=")
            or reason.startswith("minimum_release_level=")
            or reason.startswith("approval_state=")
            or reason == "stage9_writeback_before_delivery_missing"
            or reason.startswith("delivery_governance:")
            or reason.startswith("source_object_refs_missing:")
            or reason.endswith("_not_ISSUED")
            or reason.startswith("review_task_status=")
            or reason.endswith("_not_APPROVED_for_client_report_release")
        ]

        return {
            "carrier_id": build_id("S6PKG", project_fact.get("project_id")),
            "carrier_role": "internal_additive_product_package_readback",
            "generated_at": now,
            "objection_viability": objection_viability,
            "evidence_strength": evidence_strength,
            "review_priority": {
                "score": review_queue_profile.get("review_priority_score"),
                "bucket": review_queue_profile.get("review_queue_bucket"),
                "lane": review_queue_profile.get("review_lane"),
                "window_risk_level": review_queue_profile.get("window_risk_level"),
                "commercial_urgency_level": review_queue_profile.get("commercial_urgency_level"),
            },
            "sellable_signal": sellable_signal,
            "customer_delivery_eligibility": customer_delivery_eligibility,
            "customer_delivery_constraints": customer_delivery_constraints,
            "customer_delivery_reasons": _dedupe_strings(customer_delivery_reasons),
            "external_visibility_status": external_visibility_status,
            "delivery_readiness": delivery_readiness,
            "objection_pack_readiness": objection_pack_readiness,
            "sales_readiness": sales_readiness,
            "product_package_readiness": product_package_readiness,
            "downgrade_reasons": downgrade_reasons,
            "block_reasons": block_reasons,
            "source_object_refs": source_object_refs,
            "delivery_governance": delivery_governance,
            "audit_readback_summary": {
                "source": "stage6_project_fact_aggregator",
                "stage_scope": 6,
                "replayable": True,
                "no_customer_visible_material_generated": True,
                "no_external_release_enabled": True,
                "no_stage7_stage8_stage9_execution_triggered": True,
                "stage9_feedback_writeback_policy": "trace_only_not_stage6_formal_fact_input",
                "formal_facts_mutated_by_carrier": False,
                "runtime_scope": "INTERNAL_READY",
            },
            "external_visibility_trace": {
                "external_platform_allowed": False,
                "external_software_release_enabled": False,
                "leadpack_publication_generated": False,
                "requested_delivery_surface": requested_delivery_surface,
                "review_queue_profile_delivery_scope": "INTERNAL_ONLY",
            },
        }

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

        product_package_readiness = self._product_package_readiness(
            inputs=inputs,
            project_fact=project_fact.data,
            report_record=report_record.data,
            review_queue_profile=review_queue_profile.data,
            challenger_candidate_profile=challenger_candidate_profile.data,
            legal_action_recommendation=legal_action_recommendation.data,
            rule_hit=rule_hit,
            evidence=evidence,
            rule_gate=rule_gate,
            evidence_gate=evidence_gate,
            semantic_state=semantic_state,
            private_supplement_carrier_summary=private_supplement_carrier_summary,
            now=now,
        )

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
        handoff[STAGE6_PRODUCT_PACKAGE_READINESS_KEY] = product_package_readiness

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
            "product_package_readiness": product_package_readiness,
        }
        inputs_out[STAGE6_PRODUCT_PACKAGE_READINESS_KEY] = product_package_readiness
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


__all__ = ["ProjectFactAggregator", "STAGE6_PRODUCT_PACKAGE_READINESS_KEY"]
