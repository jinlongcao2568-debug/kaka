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
            if evidence_artifacts.evidence_gate_status != "PASS":
                missing_condition_family = "MISSING_EVIDENCE"
            elif inputs.get("version_conflict_state") not in (None, "CONSISTENT"):
                missing_condition_family = "MISSING_CLOCK"
            else:
                missing_condition_family = "MISSING_PUBLIC_PAGE"

        requested_materials = ensure_list(inputs.get("requested_materials"))
        if not requested_materials:
            requested_materials = (
                ["source carrier replay", "public attachment backfill"]
                if evidence_artifacts.evidence_gate_status != "PASS"
                else ["window confirmation", "manual challenger review"]
            )

        review_request = None
        if review_required:
            review_request = self.store.build_record(
                "review_request",
                {
                    "review_request_id": build_id("RR", project_id),
                    "project_id": project_id,
                    "requested_materials": requested_materials,
                    "missing_condition_family": ensure_enum(
                        self.store, "missing_condition_family", missing_condition_family
                    ),
                    "target_object_type": "rule_hit" if rule_artifacts.rule_gate_status != "PASS" else "evidence",
                    "target_object_id": (
                        rule_artifacts.rule_hit.get("rule_hit_id")
                        if rule_artifacts.rule_gate_status != "PASS"
                        else evidence_artifacts.evidence.get("evidence_id")
                    ),
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
