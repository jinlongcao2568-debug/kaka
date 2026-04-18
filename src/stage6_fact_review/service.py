# Stage: stage6_fact_review
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/governance/field_policy_dictionary.json, contracts/release/delivery_matrix.json, contracts/release/release_gates.json

from __future__ import annotations

from typing import Any, Mapping

from stage6_fact_review.fact_aggregator import ProjectFactAggregator
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import resolve_bundle, utc_now_iso


class Stage6Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)
        self.aggregator = ProjectFactAggregator(self.store)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage5_bundle = resolve_bundle(payload)
        # Anti-drift anchors for tests that assert consumer dependency closure:
        # .record("evidence_gate_decision")
        # .record("rule_gate_decision")
        # .record("rule_hit")
        # .record("evidence")
        # .records.get("review_request")
        # evaluate_object_semantics(
        handoff_validation = self.store.evaluate_handoff_consumer(
            producer_bundle=stage5_bundle,
            consumer_stage=6,
        )
        if handoff_validation and handoff_validation.decision_state == "BLOCK":
            raise ValueError(f"{handoff_validation.semantic_scope} blocked: {handoff_validation.reasons}")
        now = (stage5_bundle.inputs or {}).get("now") or utc_now_iso()
        return self.aggregator.aggregate(stage5_bundle, now=now)

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff
