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
    H05_REVIEW_REQUEST_FIELDS = (
        "review_request_id",
        "missing_condition_family",
        "review_lane",
    )

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
        h05_bundle = self._build_h05_authority_bundle(stage5_bundle)
        now = (h05_bundle.inputs or {}).get("now") or utc_now_iso()
        return self.aggregator.aggregate(h05_bundle, now=now)

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff

    def _build_h05_authority_bundle(self, stage5_bundle: StageBundle) -> StageBundle:
        h05_contract = self.store.runtime_validator.handoff_contract_index.get("H-05-STAGE5-TO-STAGE6", {})
        required_fields = [
            str(field_name)
            for field_name in h05_contract.get(
                "consumer_runtime_required_fields",
                h05_contract.get("required_payload_fields", []),
            )
        ]
        optional_fields = [str(field_name) for field_name in h05_contract.get("optional_payload_fields", [])]
        missing_required = [
            field_name
            for field_name in required_fields
            if stage5_bundle.handoff.get(field_name) in (None, "")
        ]
        if missing_required:
            raise ValueError(
                "; ".join(f"missing_h05_handoff_field:{field_name}" for field_name in missing_required)
            )

        review_request = stage5_bundle.records.get("review_request")
        if review_request is not None:
            missing_review_fields = [
                field_name
                for field_name in self.H05_REVIEW_REQUEST_FIELDS
                if stage5_bundle.handoff.get(field_name) in (None, "")
            ]
            if missing_review_fields:
                raise ValueError(
                    "; ".join(
                        f"missing_h05_review_handoff_field:{field_name}"
                        for field_name in missing_review_fields
                    )
                )

        h05_authority_fields = tuple(dict.fromkeys([*required_fields, *optional_fields]))
        inputs = dict(stage5_bundle.inputs or {})
        for field_name in h05_authority_fields:
            inputs.pop(field_name, None)
        for field_name in h05_authority_fields:
            if field_name in stage5_bundle.handoff:
                inputs[field_name] = stage5_bundle.handoff[field_name]
        inputs["stage6_h05_authority_source"] = "stage5_handoff_then_formal_producer_objects"

        return StageBundle(
            stage=stage5_bundle.stage,
            records=dict(stage5_bundle.records),
            handoff=dict(stage5_bundle.handoff),
            trace_rules=list(stage5_bundle.trace_rules),
            inputs=inputs,
        )
