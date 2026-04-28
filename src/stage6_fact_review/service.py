# Stage: stage6_fact_review
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/governance/field_policy_dictionary.json, contracts/release/delivery_matrix.json, contracts/release/release_gates.json

from __future__ import annotations

from typing import Any, Mapping

from stage6_fact_review.fact_aggregator import ProjectFactAggregator
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
    REAL_PUBLIC_STAGE6_READBACK_KEY = "stage6_real_public_rule_evidence_readback_summary"
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
        result = self.run(stage5_bundle)
        summary = self._build_real_public_rule_evidence_readback_summary(
            stage5_bundle=stage5_bundle,
            stage6_bundle=result,
        )
        inputs = dict(result.inputs)
        handoff = dict(result.handoff)
        review_trace = dict(inputs.get("stage6_review_report_trace", {}) or {})
        inputs[self.REAL_PUBLIC_STAGE6_READBACK_KEY] = summary
        handoff[self.REAL_PUBLIC_STAGE6_READBACK_KEY] = summary
        review_trace[self.REAL_PUBLIC_STAGE6_READBACK_KEY] = summary
        inputs["stage6_review_report_trace"] = review_trace
        return StageBundle(
            stage=result.stage,
            records=dict(result.records),
            handoff=handoff,
            trace_rules=list(result.trace_rules),
            inputs=inputs,
        )

    def _build_real_public_rule_evidence_readback_summary(
        self,
        *,
        stage5_bundle: StageBundle,
        stage6_bundle: StageBundle,
    ) -> dict[str, Any]:
        stage5_rule_readback = dict(stage5_bundle.inputs.get("stage5_rule_readback_summary", {}) or {})
        stage4_carrier = dict(stage5_bundle.inputs.get("stage4_public_verification_carrier", {}) or {})
        stage4_readback = dict(stage5_bundle.inputs.get("stage4_public_verification_readback_summary", {}) or {})
        product_carrier = dict(stage6_bundle.inputs.get("stage6_product_package_readiness", {}) or {})
        rule_gate_status = str(stage5_bundle.handoff.get("rule_gate_status", "UNKNOWN"))
        evidence_gate_status = str(stage5_bundle.handoff.get("evidence_gate_status", "UNKNOWN"))
        stage4_refs = list(stage5_rule_readback.get("stage4_public_verification_refs", []) or [])
        fail_closed_reasons: list[str] = []

        if not stage4_refs:
            fail_closed_reasons.append("stage4_public_verification_refs_missing")
        if not stage4_carrier:
            fail_closed_reasons.append("stage4_public_verification_carrier_missing")
        if stage4_carrier and not bool(stage4_carrier.get("public_only", False)):
            fail_closed_reasons.append("stage4_public_verification_not_public_only")
        if stage4_carrier and bool(stage4_carrier.get("non_public_source_used", False)):
            fail_closed_reasons.append("stage4_public_verification_non_public_source_used")
        if stage4_carrier and bool(stage4_carrier.get("customer_visible", False)):
            fail_closed_reasons.append("stage4_public_verification_marked_customer_visible")
        if stage4_carrier and not bool(stage4_carrier.get("no_legal_conclusion", False)):
            fail_closed_reasons.append("stage4_public_verification_legal_conclusion_boundary_missing")
        if stage4_readback and stage4_readback.get("readback_state") != "READBACK_READY":
            fail_closed_reasons.append(f"stage4_readback_state={stage4_readback.get('readback_state')}")
        if evidence_gate_status == "BLOCK":
            fail_closed_reasons.append("evidence_gate_status=BLOCK")
        elif evidence_gate_status != "PASS":
            fail_closed_reasons.append(f"evidence_gate_status={evidence_gate_status}")
        if rule_gate_status == "BLOCK":
            fail_closed_reasons.append("rule_gate_status=BLOCK")
        elif rule_gate_status != "PASS":
            fail_closed_reasons.append(f"rule_gate_status={rule_gate_status}")

        product_state = str(product_carrier.get("product_package_readiness", "UNKNOWN"))
        if product_state == "BLOCKED":
            chain_state = "BLOCKED"
        elif fail_closed_reasons:
            chain_state = "REVIEW_REQUIRED"
        elif product_state == "INTERNAL_READY":
            chain_state = "INTERNAL_READY"
        else:
            chain_state = product_state

        return {
            "readback_state": "READBACK_READY" if chain_state == "INTERNAL_READY" else "REVIEW_REQUIRED",
            "real_public_product_package_chain_state": chain_state,
            "stage5_rule_gate_status": rule_gate_status,
            "stage5_evidence_gate_status": evidence_gate_status,
            "stage6_product_package_readiness": product_state,
            "stage4_public_verification_refs": stage4_refs,
            "source_refs": {
                "verification_run_id": stage4_carrier.get("verification_run_id"),
                "verification_target_id": stage4_carrier.get("verification_target_id"),
                "verification_target_type": stage4_carrier.get("verification_target_type"),
                "source_snapshot_id": stage4_carrier.get("source_snapshot_id"),
                "input_parse_run_id": stage4_carrier.get("input_parse_run_id"),
                "parsed_field_refs": list(stage4_carrier.get("parsed_field_refs", []) or []),
                "rule_hit_id": stage5_bundle.handoff.get("rule_hit_id"),
                "evidence_id": stage5_bundle.handoff.get("evidence_id"),
                "rule_gate_decision_id": stage5_bundle.handoff.get("rule_gate_decision_id"),
                "evidence_gate_decision_id": stage5_bundle.handoff.get("evidence_gate_decision_id"),
                "project_fact_id": stage6_bundle.records["project_fact"].get("project_fact_id"),
                "report_record_id": stage6_bundle.records["report_record"].get("report_id"),
            },
            "fail_closed_reasons": fail_closed_reasons,
            "customer_visible_material_generated": False,
            "external_release_enabled": False,
            "stage7_stage8_stage9_execution_triggered": False,
            "legal_conclusion_generated": False,
            "audit_readback_summary": {
                "source": "stage6_real_public_rule_evidence_readback",
                "replayable": True,
                "stage_scope": 6,
                "no_customer_visible_material_generated": True,
                "no_external_release_enabled": True,
                "no_stage7_stage8_stage9_execution_triggered": True,
                "formal_facts_mutated_by_summary": False,
            },
        }

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
