# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shared.contracts_runtime import ContractStore
from shared.utils import build_id, ensure_enum, ensure_list, get_flag
from stage5_rules_evidence.evidence_builder import EvidenceArtifacts
from stage5_rules_evidence.rule_runner import RuleArtifacts


@dataclass(frozen=True)
class GateArtifacts:
    coverage_sellable_state: str
    delivery_risk_state: str
    review_request: Any | None
    review_required: bool


class GateEvaluator:
    def __init__(self, store: ContractStore) -> None:
        self.store = store

    def _default_missing_condition_family(
        self,
        *,
        evidence_artifacts: EvidenceArtifacts,
        inputs: Mapping[str, Any],
    ) -> str:
        if evidence_artifacts.evidence_gate_status != "PASS":
            return "MISSING_EVIDENCE"
        if inputs.get("version_conflict_state") not in (None, "CONSISTENT"):
            return "MISSING_CLOCK"
        if inputs.get("clock_conflict_state") not in (None, "CONSISTENT"):
            return "MISSING_CLOCK"
        return "MISSING_PUBLIC_PAGE"

    def _default_requested_materials(
        self,
        *,
        evidence_artifacts: EvidenceArtifacts,
        rule_artifacts: RuleArtifacts,
    ) -> list[str]:
        if evidence_artifacts.evidence_gate_status != "PASS":
            return [
                "source carrier replay",
                "public attachment backfill",
            ]
        if rule_artifacts.rule_gate_status == "BLOCK":
            return ensure_list(rule_artifacts.rule_gate_decision.get("blocking_reasons")) + [
                "manual rule block review",
            ]
        if rule_artifacts.rule_gate_status == "REVIEW":
            return ensure_list(rule_artifacts.rule_gate_decision.get("blocking_reasons")) + [
                "window confirmation",
                "manual challenger review",
            ]
        return ["window confirmation", "manual challenger review"]

    def evaluate(
        self,
        *,
        project_id: str,
        evidence_artifacts: EvidenceArtifacts,
        rule_artifacts: RuleArtifacts,
        inputs: Mapping[str, Any],
        flags: Mapping[str, Any],
    ) -> GateArtifacts:
        review_required = (
            rule_artifacts.rule_gate_status != "PASS"
            or evidence_artifacts.evidence_gate_status != "PASS"
            or get_flag(flags, "force_review_request")
        )
        missing_condition_family = inputs.get("missing_condition_family")
        if not missing_condition_family:
            missing_condition_family = self._default_missing_condition_family(
                evidence_artifacts=evidence_artifacts,
                inputs=inputs,
            )

        requested_materials = ensure_list(inputs.get("requested_materials"))
        if not requested_materials:
            requested_materials = self._default_requested_materials(
                evidence_artifacts=evidence_artifacts,
                rule_artifacts=rule_artifacts,
            )
        requested_materials = list(dict.fromkeys(requested_materials))

        review_request = None
        if review_required:
            target_object_type = "evidence" if evidence_artifacts.evidence_gate_status != "PASS" else "rule_hit"
            target_object_id = (
                evidence_artifacts.evidence.get("evidence_id")
                if target_object_type == "evidence"
                else rule_artifacts.rule_hit.get("rule_hit_id")
            )
            review_request = self.store.build_record(
                "review_request",
                {
                    "review_request_id": build_id("RR", project_id),
                    "project_id": project_id,
                    "requested_materials": requested_materials,
                    "missing_condition_family": ensure_enum(
                        self.store, "missing_condition_family", missing_condition_family
                    ),
                    "target_object_type": target_object_type,
                    "target_object_id": target_object_id,
                    "review_lane": ensure_enum(self.store, "review_lane", inputs.get("review_lane", "STANDARD")),
                },
            )

        coverage_sellable_state = inputs.get("coverage_sellable_state")
        if not coverage_sellable_state:
            coverage_sellable_state = (
                "SELLABLE"
                if rule_artifacts.rule_gate_status == "PASS" and evidence_artifacts.evidence_gate_status == "PASS"
                else "RESTRICTED"
            )

        delivery_risk_state = inputs.get("delivery_risk_state")
        if not delivery_risk_state:
            delivery_risk_state = "ALLOW"
            if rule_artifacts.rule_gate_status == "BLOCK" or evidence_artifacts.evidence_gate_status == "BLOCK":
                delivery_risk_state = "BLOCK"
            elif rule_artifacts.rule_gate_status == "REVIEW" or evidence_artifacts.evidence_gate_status == "REVIEW":
                delivery_risk_state = "REVIEW"

        return GateArtifacts(
            coverage_sellable_state=coverage_sellable_state,
            delivery_risk_state=delivery_risk_state,
            review_request=review_request,
            review_required=review_required,
        )


__all__ = ["GateArtifacts", "GateEvaluator"]
