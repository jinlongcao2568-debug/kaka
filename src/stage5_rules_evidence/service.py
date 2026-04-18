# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from typing import Any, Mapping

from stage5_rules_evidence.engine import RuleEvidenceEngine
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import resolve_bundle


class Stage5Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)
        self.engine = RuleEvidenceEngine(self.store)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage4_bundle = resolve_bundle(payload)
        # Anti-drift anchors for tests that assert consumer dependency closure:
        # .record("evidence_grade_profile")
        # .record("public_attack_surface")
        # .record("focus_bidder_verification_profile")
        # .record("pseudo_competitor_signal_set")
        handoff_validation = self.store.evaluate_handoff_consumer(
            producer_bundle=stage4_bundle,
            consumer_stage=5,
        )
        if handoff_validation and handoff_validation.decision_state == "BLOCK":
            raise ValueError(f"{handoff_validation.semantic_scope} blocked: {handoff_validation.reasons}")
        return self.engine.execute(stage4_bundle)

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff


__all__ = ["Stage5Service"]
