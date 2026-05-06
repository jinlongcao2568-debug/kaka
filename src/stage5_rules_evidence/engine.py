# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from typing import Any

from shared.contracts_runtime import ContractStore, StageBundle
from shared.model_assist_governance import (
    MODEL_ASSIST_INPUT_KEY,
    MODEL_ASSIST_SUMMARY_INPUT_KEY,
    build_model_assist_summary,
    build_rule_model_assist,
)
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
        stage5_rule_execution_trace = []
        for trace_entry in rule_artifacts.rule_execution_trace:
            enriched_entry = dict(trace_entry)
            enriched_entry["review_request_target_object_type"] = gate_artifacts.review_target_object_type
            enriched_entry["review_request_target_object_id"] = gate_artifacts.review_target_object_id
            enriched_entry["review_request_target_selected"] = bool(
                gate_artifacts.review_target_object_type == "rule_hit"
                and trace_entry.get("rule_hit_id") == gate_artifacts.review_target_object_id
            )
            stage5_rule_execution_trace.append(enriched_entry)

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
        inputs_out["stage5_rule_hits"] = [dict(rule_hit.data) for rule_hit in rule_artifacts.rule_hits]
        inputs_out["stage5_rule_codes"] = [
            rule_hit.get("rule_code") for rule_hit in rule_artifacts.rule_hits
        ]
        inputs_out["stage5_rule_selection_trace"] = [
            dict(trace_entry) for trace_entry in rule_artifacts.rule_selection_trace
        ]
        inputs_out["stage5_rule_execution_trace"] = stage5_rule_execution_trace
        rule_coverage_summary = dict(rule_artifacts.rule_coverage_summary)
        rule_coverage_summary["review_required"] = gate_artifacts.review_required
        rule_coverage_summary["coverage_sellable_state"] = gate_artifacts.coverage_sellable_state
        rule_coverage_summary["delivery_risk_state"] = gate_artifacts.delivery_risk_state
        if gate_artifacts.review_request is not None:
            rule_coverage_summary["review_request_id"] = gate_artifacts.review_request.get("review_request_id")
            rule_coverage_summary["review_target_object_type"] = gate_artifacts.review_target_object_type
            rule_coverage_summary["review_target_object_id"] = gate_artifacts.review_target_object_id
        inputs_out["stage5_rule_coverage_summary"] = rule_coverage_summary
        stage5_rule_readback_summary = {
            "catalog_id": rule_coverage_summary.get("catalog_id"),
            "catalog_version": rule_coverage_summary.get("catalog_version"),
            "factory_version": rule_coverage_summary.get("factory_version"),
            "selected_count": rule_coverage_summary.get("selected_count"),
            "skipped_count": rule_coverage_summary.get("skipped_count"),
            "disabled_count": rule_coverage_summary.get("disabled_count"),
            "unsupported_count": rule_coverage_summary.get("unsupported_count"),
            "missing_dependency_count": rule_coverage_summary.get("missing_dependency_count"),
            "basis_gate_review_count": rule_coverage_summary.get("basis_gate_review_count"),
            "basis_missing_count": rule_coverage_summary.get("basis_missing_count"),
            "basis_internal_only_count": rule_coverage_summary.get("basis_internal_only_count"),
            "basis_heuristic_only_count": rule_coverage_summary.get("basis_heuristic_only_count"),
            "pass_count": rule_coverage_summary.get("pass_count"),
            "review_count": rule_coverage_summary.get("review_count"),
            "block_count": rule_coverage_summary.get("block_count"),
            "golden_case_refs": list(rule_coverage_summary.get("golden_case_refs", [])),
            "rule_gate_decision_id": rule_artifacts.rule_gate_decision.get("gate_id"),
            "evidence_gate_decision_id": evidence_artifacts.evidence_gate_decision.get("gate_id"),
            "review_request_id": rule_coverage_summary.get("review_request_id"),
            "evidence_refs": list(rule_coverage_summary.get("evidence_refs", [])),
            "stage4_public_verification_refs": list(inputs.get("stage4_public_verification_refs", [])),
            "stage4_public_evidence_refs": list(inputs.get("stage4_public_evidence_refs", [])),
            "source_object_refs": list(inputs.get("source_object_refs", [])),
        }
        model_assist = build_rule_model_assist(
            stage5_readback_summary=stage5_rule_readback_summary,
            rule_execution_trace=stage5_rule_execution_trace,
        )
        stage5_rule_readback_summary[MODEL_ASSIST_INPUT_KEY] = model_assist
        stage5_rule_readback_summary[MODEL_ASSIST_SUMMARY_INPUT_KEY] = build_model_assist_summary(
            model_assist
        )
        inputs_out["stage5_rule_readback_summary"] = stage5_rule_readback_summary
        inputs_out[MODEL_ASSIST_INPUT_KEY] = model_assist
        inputs_out[MODEL_ASSIST_SUMMARY_INPUT_KEY] = build_model_assist_summary(model_assist)
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
