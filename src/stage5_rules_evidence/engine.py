# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from typing import Any

from shared.contracts_runtime import ContractStore, StageBundle
from stage5_rules_evidence.evidence_builder import EvidenceBuilder
from stage5_rules_evidence.gate_evaluator import GateEvaluator
from stage5_rules_evidence.rule_runner import RuleRunner


class RuleEvidenceEngine:
    H04_CLOCK_AUTHORITY_FIELDS = (
        "clock_resolution_rule_id",
        "clock_precedence_rule_id",
        "clock_conflict_state",
        "collection_state",
    )

    def __init__(self, store: ContractStore) -> None:
        self.store = store
        self.evidence_builder = EvidenceBuilder(store)
        self.rule_runner = RuleRunner(store)
        self.gate_evaluator = GateEvaluator(store)

    def _build_stage4_authority_inputs(self, stage4_bundle: StageBundle) -> dict[str, Any]:
        contract = self.store.runtime_validator.handoff_contract_index.get("H-04-STAGE4-TO-STAGE5", {})
        stage4_handoff_authority_required_fields = [
            str(value)
            for value in contract.get(
                "consumer_runtime_required_fields",
                contract.get("required_payload_fields", []),
            )
        ]
        stage4_handoff_authority_optional_fields = [
            str(value) for value in contract.get("optional_payload_fields", [])
        ]
        inputs = dict(stage4_bundle.inputs or {})
        for field_name in (
            *stage4_handoff_authority_required_fields,
            *stage4_handoff_authority_optional_fields,
            "lineage",
        ):
            inputs.pop(field_name, None)

        missing_h04_fields = [
            field_name
            for field_name in stage4_handoff_authority_required_fields
            if stage4_bundle.handoff.get(field_name) in (None, "")
        ]
        if missing_h04_fields:
            missing_tokens = [f"missing_h04_handoff_field:{field_name}" for field_name in missing_h04_fields]
            raise ValueError("; ".join(missing_tokens))

        for field_name in stage4_handoff_authority_required_fields:
            inputs[field_name] = stage4_bundle.handoff.get(field_name)
        for field_name in stage4_handoff_authority_optional_fields:
            if field_name in stage4_bundle.handoff:
                inputs[field_name] = stage4_bundle.handoff.get(field_name)
        self._apply_h04_clock_authority_guard(inputs)
        return inputs

    def _apply_h04_clock_authority_guard(self, inputs: dict[str, Any]) -> None:
        clock_authority = {
            field_name: inputs.get(field_name)
            for field_name in self.H04_CLOCK_AUTHORITY_FIELDS
        }
        authority_review_reasons: list[str] = []
        if clock_authority.get("clock_conflict_state") != "CONSISTENT":
            authority_review_reasons.append("h04_clock_conflict_state_not_consistent")
        if clock_authority.get("collection_state") not in ("NORMALIZED", "PARSED"):
            authority_review_reasons.append("h04_collection_state_not_normalized")
        if inputs.get("route_decision_state") == "BLOCK" or clock_authority.get("collection_state") == "BLOCKED":
            authority_review_reasons.append("h04_route_or_collection_blocked")

        if not authority_review_reasons:
            return

        existing_reasons = inputs.get("h04_authority_review_reasons")
        if isinstance(existing_reasons, list):
            merged_reasons = existing_reasons + authority_review_reasons
        elif existing_reasons:
            merged_reasons = [str(existing_reasons), *authority_review_reasons]
        else:
            merged_reasons = authority_review_reasons
        inputs["h04_authority_review_reasons"] = list(dict.fromkeys(merged_reasons))
        if inputs.get("verification_state") == "PASS":
            inputs["verification_state"] = "REVIEW"

    def execute(self, stage4_bundle: StageBundle) -> StageBundle:
        inputs = self._build_stage4_authority_inputs(stage4_bundle)
        flags = inputs.get("flags", {})

        evidence_grade_profile = stage4_bundle.record("evidence_grade_profile")
        public_attack_surface = stage4_bundle.record("public_attack_surface")
        focus_bidder_verification_profile = stage4_bundle.record("focus_bidder_verification_profile")
        pseudo_competitor_signal_set = stage4_bundle.record("pseudo_competitor_signal_set")
        project_id = str(inputs.get("project_id", evidence_grade_profile.get("project_id")))

        trace_rules: list[str] = []
        evidence_artifacts = self.evidence_builder.build(
            project_id=project_id,
            evidence_grade_profile=evidence_grade_profile,
            inputs=inputs,
            flags=flags,
            trace_rules=trace_rules,
        )
        rule_artifacts = self.rule_runner.run(
            project_id=project_id,
            evidence_grade_profile=evidence_grade_profile,
            public_attack_surface=public_attack_surface,
            focus_bidder_verification_profile=focus_bidder_verification_profile,
            pseudo_competitor_signal_set=pseudo_competitor_signal_set,
            evidence_artifacts=evidence_artifacts,
            inputs=inputs,
            flags=flags,
            trace_rules=trace_rules,
        )
        gate_artifacts = self.gate_evaluator.evaluate(
            project_id=project_id,
            evidence_artifacts=evidence_artifacts,
            rule_artifacts=rule_artifacts,
            inputs=inputs,
            flags=flags,
        )

        records: dict[str, Any] = {
            "evidence": evidence_artifacts.evidence,
            "rule_hit": rule_artifacts.rule_hit,
            "evidence_gate_decision": evidence_artifacts.evidence_gate_decision,
            "rule_gate_decision": rule_artifacts.rule_gate_decision,
        }
        if gate_artifacts.review_request is not None:
            records["review_request"] = gate_artifacts.review_request

        handoff = {
            "project_id": project_id,
            "rule_hit_id": rule_artifacts.rule_hit.get("rule_hit_id"),
            "rule_hit_state": rule_artifacts.rule_hit_state,
            "evidence_id": evidence_artifacts.evidence.get("evidence_id"),
            "rule_gate_decision_id": rule_artifacts.rule_gate_decision.get("gate_id"),
            "evidence_gate_decision_id": evidence_artifacts.evidence_gate_decision.get("gate_id"),
            "verification_state": inputs.get("verification_state"),
            "cross_check_state": evidence_artifacts.cross_check_state,
            "fixation_status": evidence_artifacts.fixation_status,
            "provenance_chain_status": evidence_artifacts.provenance_chain_status,
            "retrieval_readiness_status": evidence_artifacts.retrieval_readiness_status,
            "evidence_gate_status": evidence_artifacts.evidence_gate_status,
            "rule_gate_status": rule_artifacts.rule_gate_status,
            "coverage_sellable_state": gate_artifacts.coverage_sellable_state,
            "delivery_risk_state": gate_artifacts.delivery_risk_state,
        }
        if gate_artifacts.review_request is not None:
            handoff["review_request_id"] = gate_artifacts.review_request.get("review_request_id")
            handoff["missing_condition_family"] = gate_artifacts.review_request.get("missing_condition_family")
            handoff["review_lane"] = gate_artifacts.review_request.get("review_lane")

        inputs_out = dict(inputs)
        inputs_out["rule_hit_id"] = rule_artifacts.rule_hit.get("rule_hit_id")
        inputs_out["rule_hit_state"] = rule_artifacts.rule_hit_state
        inputs_out["evidence_id"] = evidence_artifacts.evidence.get("evidence_id")
        inputs_out["rule_gate_decision_id"] = rule_artifacts.rule_gate_decision.get("gate_id")
        inputs_out["evidence_gate_decision_id"] = evidence_artifacts.evidence_gate_decision.get("gate_id")
        inputs_out["verification_state"] = inputs.get("verification_state")
        inputs_out["cross_check_state"] = evidence_artifacts.cross_check_state
        inputs_out["fixation_status"] = evidence_artifacts.fixation_status
        inputs_out["provenance_chain_status"] = evidence_artifacts.provenance_chain_status
        inputs_out["retrieval_readiness_status"] = evidence_artifacts.retrieval_readiness_status
        inputs_out["evidence_gate_status"] = evidence_artifacts.evidence_gate_status
        inputs_out["rule_gate_status"] = rule_artifacts.rule_gate_status
        inputs_out["coverage_sellable_state"] = gate_artifacts.coverage_sellable_state
        inputs_out["delivery_risk_state"] = gate_artifacts.delivery_risk_state
        if gate_artifacts.review_request is not None:
            inputs_out["review_request_id"] = gate_artifacts.review_request.get("review_request_id")
            inputs_out["missing_condition_family"] = gate_artifacts.review_request.get("missing_condition_family")
            inputs_out["review_lane"] = gate_artifacts.review_request.get("review_lane")

        return StageBundle(
            stage=5,
            records=records,
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )


__all__ = ["RuleEvidenceEngine"]
