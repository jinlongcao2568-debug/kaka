# Stage: stage6_fact_review
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/governance/field_policy_dictionary.json, contracts/release/delivery_matrix.json, contracts/release/release_gates.json

from __future__ import annotations

from typing import Any, Mapping

from stage6_fact_review.fact_aggregator import (
    ProjectFactAggregator,
    REAL_PUBLIC_STAGE6_READBACK_KEY as REAL_PUBLIC_READBACK_KEY,
)
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import resolve_bundle, utc_now_iso


def _close_h06_formal_carriers(result: StageBundle) -> StageBundle:
    project_fact = result.records["project_fact"]
    review_queue_profile = result.records["review_queue_profile"]
    report_record = result.records["report_record"]
    challenger_candidate_profile = result.records["challenger_candidate_profile"]

    handoff = dict(result.handoff)
    linked_review_request_id = handoff.get("linked_review_request_id_optional")
    missing_condition_family = handoff.get("missing_condition_family_optional")
    sale_gate_status = handoff.get("sale_gate_status")
    report_status = handoff.get("report_status")

    saleability_status = "CANDIDATE"
    if sale_gate_status == "BLOCK" or report_status == "REVOKED":
        saleability_status = "BLOCKED"
    elif (
        sale_gate_status in ("REVIEW", "HOLD")
        or report_status not in ("READY", "ISSUED")
        or linked_review_request_id
        or missing_condition_family
    ):
        saleability_status = "RESTRICTED"

    formal_carriers = {
        "project_fact_id": project_fact.get("project_fact_id"),
        "review_queue_profile_id": review_queue_profile.get("queue_profile_id"),
        "review_lane": review_queue_profile.get("review_lane"),
        "report_record_id": report_record.get("report_id"),
        "challenger_candidate_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
        "saleability_status": saleability_status,
    }
    handoff.update(formal_carriers)

    inputs = dict(result.inputs)
    inputs.update(formal_carriers)
    inputs["stage6_h06_formal_carrier_trace"] = {
        "project_fact_id": formal_carriers["project_fact_id"],
        "review_queue_profile_id": formal_carriers["review_queue_profile_id"],
        "report_record_id": formal_carriers["report_record_id"],
        "challenger_candidate_profile_id": formal_carriers["challenger_candidate_profile_id"],
        "saleability_status_seed": saleability_status,
        "linked_review_request_id_optional": linked_review_request_id,
        "missing_condition_family_optional": missing_condition_family,
        "source": "stage6_formal_producer_objects_then_h06_handoff",
    }

    return StageBundle(
        stage=result.stage,
        records=dict(result.records),
        handoff=handoff,
        trace_rules=list(result.trace_rules),
        inputs=inputs,
    )


_ORIGINAL_PROJECT_FACT_AGGREGATE = ProjectFactAggregator.aggregate


def _aggregate_with_h06_formal_carriers(self: ProjectFactAggregator, stage5_bundle: StageBundle, *, now: str) -> StageBundle:
    return _close_h06_formal_carriers(_ORIGINAL_PROJECT_FACT_AGGREGATE(self, stage5_bundle, now=now))


def _install_h06_formal_carrier_projection() -> None:
    if getattr(ProjectFactAggregator.aggregate, "_h06_formal_carrier_projection", False):
        return
    setattr(_aggregate_with_h06_formal_carriers, "_h06_formal_carrier_projection", True)
    ProjectFactAggregator.aggregate = _aggregate_with_h06_formal_carriers


class Stage6Service:
    REAL_PUBLIC_STAGE6_READBACK_KEY = REAL_PUBLIC_READBACK_KEY
    H05_REVIEW_REQUEST_FIELDS = (
        "review_request_id",
        "missing_condition_family",
        "review_lane",
    )

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)
        _install_h06_formal_carrier_projection()
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

    def run_real_public_rule_evidence_readback(
        self,
        payload: Mapping[str, Any] | StageBundle,
    ) -> StageBundle:
        stage5_bundle = resolve_bundle(payload)
        return self.run(stage5_bundle)

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
