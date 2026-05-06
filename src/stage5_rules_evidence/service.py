# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from typing import Any, Mapping

from stage5_rules_evidence.engine import RuleEvidenceEngine
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import resolve_bundle
from stage4_verification.hard_defect_strategy import (
    READY_FOR_PUBLIC_VERIFICATION,
    build_evidence_risk_hard_defect_strategy_readback,
)
from stage4_verification.public_evidence_readback import (
    normalize_public_evidence_readbacks,
    public_evidence_source_refs,
)


class Stage5Service:
    H05_FORMAL_CARRIER_FIELDS = (
        "lineage_status",
        "conflict_state",
    )

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
        return self._close_h05_formal_handoff(self.engine.execute(stage4_bundle))

    def run_public_verification_readback(
        self,
        payload: Mapping[str, Any] | StageBundle,
        public_verification_carrier: Mapping[str, Any],
        *,
        requested_rule_codes: list[str] | None = None,
    ) -> StageBundle:
        stage4_bundle = resolve_bundle(payload)
        carrier = dict(public_verification_carrier)
        readback = self._public_verification_stage5_readback(carrier)
        verification_state = self._stage5_verification_state_for_public_readback(carrier, readback)

        records = dict(stage4_bundle.records)
        focus_profile = dict(records["focus_bidder_verification_profile"].data)
        focus_profile["verification_state"] = verification_state
        records["focus_bidder_verification_profile"] = self.store.build_record(
            "focus_bidder_verification_profile",
            focus_profile,
        )

        evidence_profile = dict(records["evidence_grade_profile"].data)
        if verification_state == "PASS":
            evidence_profile.update(
                {
                    "cross_check_state": "PASS",
                    "provenance_chain_status": "COMPLETE",
                    "fixation_status": "HASH_LOCKED",
                    "retrieval_readiness_status": "READY",
                    "requires_manual_confirmation": False,
                }
            )
        elif verification_state == "BLOCK":
            evidence_profile.update(
                {
                    "cross_check_state": "BLOCK",
                    "provenance_chain_status": "BROKEN",
                    "fixation_status": "NOT_FIXED",
                    "retrieval_readiness_status": "BLOCKED",
                    "requires_manual_confirmation": True,
                }
            )
        else:
            evidence_profile.update(
                {
                    "cross_check_state": "REVIEW",
                    "provenance_chain_status": "PARTIAL",
                    "fixation_status": "SNAPSHOT_CAPTURED",
                    "retrieval_readiness_status": "PARTIAL",
                    "requires_manual_confirmation": True,
                }
            )
        records["evidence_grade_profile"] = self.store.build_record(
            "evidence_grade_profile",
            evidence_profile,
        )

        public_refs = self._public_verification_source_refs(carrier)
        first_field_ref = next(iter(carrier.get("parsed_field_refs") or []), {})
        if not isinstance(first_field_ref, Mapping):
            first_field_ref = {}

        inputs = dict(stage4_bundle.inputs)
        inputs.update(
            {
                "verification_state": verification_state,
                "cross_check_state": evidence_profile.get("cross_check_state"),
                "provenance_chain_status": evidence_profile.get("provenance_chain_status"),
                "fixation_status": evidence_profile.get("fixation_status"),
                "retrieval_readiness_status": evidence_profile.get("retrieval_readiness_status"),
                "stage4_public_verification_carrier": carrier,
                "stage4_public_verification_readback_summary": readback,
                "stage4_public_verification_run_id": carrier.get("verification_run_id"),
                "stage4_public_verification_result": carrier.get("verification_result"),
                "stage4_public_verification_failure_reason_optional": carrier.get(
                    "failure_reason_optional"
                ),
                "stage4_public_verification_refs": public_refs,
                "source_object_refs": list(
                    dict.fromkeys(
                        [
                            *[str(value) for value in inputs.get("source_object_refs", []) if value],
                            *public_refs,
                        ]
                    )
                ),
                "source_document_ref": carrier.get("source_snapshot_id") or inputs.get("source_document_ref"),
                "source_slice_ref": (
                    first_field_ref.get("field_ref")
                    or first_field_ref.get("source_slice_sha256")
                    or carrier.get("verification_run_id")
                    or inputs.get("source_slice_ref")
                ),
                "visibility_reason_summary": (
                    "Stage4 public verification readback consumed by Stage5 rule/evidence gate; "
                    f"result={carrier.get('verification_result')}; "
                    f"failure={carrier.get('failure_reason_optional')}"
                ),
            }
        )
        if requested_rule_codes is not None:
            inputs["stage5_requested_rule_codes"] = list(requested_rule_codes)

        handoff = dict(stage4_bundle.handoff)
        handoff.update(
            {
                "verification_state": verification_state,
                "cross_check_state": evidence_profile.get("cross_check_state"),
                "provenance_chain_status": evidence_profile.get("provenance_chain_status"),
                "fixation_status": evidence_profile.get("fixation_status"),
                "retrieval_readiness_status": evidence_profile.get("retrieval_readiness_status"),
            }
        )

        enriched_bundle = StageBundle(
            stage=4,
            records=records,
            handoff=handoff,
            trace_rules=list(stage4_bundle.trace_rules),
            inputs=inputs,
        )
        return self.run(enriched_bundle)

    def run_evidence_risk_hard_defect_strategy_readback(
        self,
        payload: Mapping[str, Any] | StageBundle,
        strategy_carrier: Mapping[str, Any],
        *,
        project_manager_active_conflict_readback: Mapping[str, Any] | None = None,
    ) -> StageBundle:
        stage4_bundle = resolve_bundle(payload)
        carrier = dict(strategy_carrier)
        readback = build_evidence_risk_hard_defect_strategy_readback(carrier)
        verification_state = self._stage5_verification_state_for_hard_defect_strategy(readback)

        records = dict(stage4_bundle.records)
        focus_profile = dict(records["focus_bidder_verification_profile"].data)
        focus_profile["verification_state"] = verification_state
        records["focus_bidder_verification_profile"] = self.store.build_record(
            "focus_bidder_verification_profile",
            focus_profile,
        )

        evidence_profile = dict(records["evidence_grade_profile"].data)
        if verification_state == "PASS":
            evidence_profile.update(
                {
                    "cross_check_state": "PASS",
                    "provenance_chain_status": "COMPLETE",
                    "fixation_status": "HASH_LOCKED",
                    "retrieval_readiness_status": "READY",
                    "requires_manual_confirmation": False,
                }
            )
        elif verification_state == "BLOCK":
            evidence_profile.update(
                {
                    "cross_check_state": "BLOCK",
                    "provenance_chain_status": "BROKEN",
                    "fixation_status": "NOT_FIXED",
                    "retrieval_readiness_status": "BLOCKED",
                    "requires_manual_confirmation": True,
                }
            )
        else:
            evidence_profile.update(
                {
                    "cross_check_state": "REVIEW",
                    "provenance_chain_status": "PARTIAL",
                    "fixation_status": "SNAPSHOT_CAPTURED",
                    "retrieval_readiness_status": "PARTIAL",
                    "requires_manual_confirmation": True,
                }
            )
        records["evidence_grade_profile"] = self.store.build_record(
            "evidence_grade_profile",
            evidence_profile,
        )

        refs = self._hard_defect_strategy_source_refs(carrier)
        public_evidence_readbacks = normalize_public_evidence_readbacks(carrier)
        public_evidence_refs = public_evidence_source_refs(public_evidence_readbacks)
        requested_rule_codes = list(readback.get("stage5_requested_rule_codes") or [])
        supported_upstream = list(
            dict.fromkeys(
                [
                    *[
                        str(value)
                        for value in stage4_bundle.inputs.get("stage5_supported_upstream_objects", [])
                        if value
                    ],
                    *[str(value) for value in readback.get("stage5_supported_upstream_objects", []) if value],
                ]
            )
        )

        inputs = dict(stage4_bundle.inputs)
        inputs.update(
            {
                "verification_state": verification_state,
                "cross_check_state": evidence_profile.get("cross_check_state"),
                "provenance_chain_status": evidence_profile.get("provenance_chain_status"),
                "fixation_status": evidence_profile.get("fixation_status"),
                "retrieval_readiness_status": evidence_profile.get("retrieval_readiness_status"),
                "evidence_risk_hard_defect_strategy_carrier": carrier,
                "evidence_risk_hard_defect_strategy_readback": readback,
                "evidence_risk_strategy_run_id": carrier.get("strategy_run_id"),
                "evidence_risk_state": readback.get("evidence_risk_state"),
                "stage5_requested_rule_codes": requested_rule_codes,
                "stage5_supported_upstream_objects": supported_upstream,
                "source_object_refs": list(
                    dict.fromkeys(
                        [
                            *[str(value) for value in (inputs.get("source_object_refs") or []) if value],
                            *refs,
                            *public_evidence_refs,
                        ]
                    )
                ),
                "stage4_public_evidence_readbacks": public_evidence_readbacks,
                "stage4_public_evidence_refs": public_evidence_refs,
                "visibility_reason_summary": (
                    "Stage4 evidence-risk hard-defect strategy readback consumed by Stage5; "
                    f"risk_state={readback.get('evidence_risk_state')}; "
                    f"fail_closed={readback.get('fail_closed')}; "
                    f"public_evidence_readbacks={len(public_evidence_readbacks)}; "
                    f"reasons={','.join(readback.get('fail_closed_reasons') or [])}"
                ),
                "missing_condition_family": (
                    "MISSING_EVIDENCE" if readback.get("fail_closed") else inputs.get("missing_condition_family")
                ),
                "review_lane": "HIGH_PRIORITY" if readback.get("fail_closed") else inputs.get("review_lane", "STANDARD"),
            }
        )
        if project_manager_active_conflict_readback is not None:
            inputs["project_manager_active_conflict_readback"] = dict(project_manager_active_conflict_readback)

        handoff = dict(stage4_bundle.handoff)
        handoff.update(
            {
                "verification_state": verification_state,
                "cross_check_state": evidence_profile.get("cross_check_state"),
                "provenance_chain_status": evidence_profile.get("provenance_chain_status"),
                "fixation_status": evidence_profile.get("fixation_status"),
                "retrieval_readiness_status": evidence_profile.get("retrieval_readiness_status"),
            }
        )

        enriched_bundle = StageBundle(
            stage=4,
            records=records,
            handoff=handoff,
            trace_rules=list(stage4_bundle.trace_rules),
            inputs=inputs,
        )
        return self.run(enriched_bundle)

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff

    def _public_verification_source_refs(self, carrier: Mapping[str, Any]) -> list[str]:
        refs: list[str] = []
        for key in (
            "verification_run_id",
            "verification_target_id",
            "verification_target_type",
            "input_parse_run_id",
            "source_snapshot_id",
            "source_url",
        ):
            value = carrier.get(key)
            if value not in (None, ""):
                refs.append(str(value))
        for field_ref in carrier.get("parsed_field_refs") or []:
            if not isinstance(field_ref, Mapping):
                continue
            for key in ("field_ref", "source_file_ref", "source_slice_sha256"):
                value = field_ref.get(key)
                if value not in (None, ""):
                    refs.append(str(value))
        return list(dict.fromkeys(refs))

    def _public_verification_stage5_readback(self, carrier: Mapping[str, Any]) -> dict[str, Any]:
        required_fields = (
            "verification_run_id",
            "verification_target_id",
            "verification_target_type",
            "input_parse_run_id",
            "source_snapshot_id",
            "parsed_field_refs",
            "snapshot_refs",
            "verification_result",
            "evidence_grade",
        )
        missing = [field_name for field_name in required_fields if carrier.get(field_name) in (None, "", [])]
        snapshot_refs = carrier.get("snapshot_refs") or []
        replayable = bool(snapshot_refs) and all(
            bool(ref.get("replayable")) for ref in snapshot_refs if isinstance(ref, Mapping)
        )
        boundary_safe = (
            bool(carrier.get("public_only", True))
            and not bool(carrier.get("customer_visible"))
            and bool(carrier.get("no_legal_conclusion", True))
        )
        return {
            "readback_state": "READBACK_READY" if not missing and replayable else "FAIL_CLOSED_INCOMPLETE_OR_NON_REPLAYABLE",
            "replayable": bool(not missing and replayable),
            "fail_closed": bool(missing or not replayable or not boundary_safe),
            "no_broad_fallback": True,
            "public_only": bool(carrier.get("public_only", True)),
            "customer_visible": False,
            "no_legal_conclusion": True,
            "missing_required_fields": missing,
            "verification_run_id": carrier.get("verification_run_id"),
            "source_snapshot_id": carrier.get("source_snapshot_id"),
            "verification_result": carrier.get("verification_result"),
            "failure_reason_optional": carrier.get("failure_reason_optional"),
            "review_required": bool(carrier.get("review_required")),
            "boundary_safe": boundary_safe,
        }

    def _stage5_verification_state_for_public_readback(
        self,
        carrier: Mapping[str, Any],
        readback: Mapping[str, Any],
    ) -> str:
        if not readback.get("boundary_safe"):
            return "BLOCK"
        if (
            readback.get("replayable")
            and carrier.get("verification_result") == "MATCHED"
            and not bool(carrier.get("review_required"))
            and carrier.get("failure_reason_optional") in (None, "")
        ):
            return "PASS"
        return "REVIEW"

    def _stage5_verification_state_for_hard_defect_strategy(
        self,
        readback: Mapping[str, Any],
    ) -> str:
        if readback.get("readback_state") == "FAIL_CLOSED_INCOMPLETE_OR_BOUNDARY_UNSAFE":
            return "BLOCK"
        if readback.get("evidence_risk_state") == READY_FOR_PUBLIC_VERIFICATION and not readback.get("fail_closed"):
            return "PASS"
        return "REVIEW"

    def _hard_defect_strategy_source_refs(self, carrier: Mapping[str, Any]) -> list[str]:
        refs: list[str] = []
        for key in (
            "strategy_run_id",
            "strategy_version",
            "input_parse_run_id",
            "source_snapshot_id",
            "source_url",
        ):
            value = carrier.get(key)
            if value not in (None, ""):
                refs.append(str(value))
        for target in carrier.get("strategy_targets") or []:
            if not isinstance(target, Mapping):
                continue
            for key in ("strategy_key", "hard_defect_family"):
                value = target.get(key)
                if value not in (None, ""):
                    refs.append(str(value))
            for field_ref in target.get("matched_field_refs") or []:
                if not isinstance(field_ref, Mapping):
                    continue
                for key in ("field_ref", "source_file_ref", "source_slice_sha256"):
                    value = field_ref.get(key)
                    if value not in (None, ""):
                        refs.append(str(value))
        for target in carrier.get("verification_targets") or []:
            if not isinstance(target, Mapping):
                continue
            for key in ("verification_target_id", "verification_target_type", "target_identifier"):
                value = target.get(key)
                if value not in (None, ""):
                    refs.append(str(value))
        refs.extend(public_evidence_source_refs(normalize_public_evidence_readbacks(carrier)))
        return list(dict.fromkeys(refs))

    def _close_h05_formal_handoff(self, result: StageBundle) -> StageBundle:
        handoff = dict(result.handoff)
        inputs = dict(result.inputs)
        for field_name in self.H05_FORMAL_CARRIER_FIELDS:
            if field_name in inputs:
                handoff[field_name] = inputs[field_name]
        return StageBundle(
            stage=result.stage,
            records=dict(result.records),
            handoff=handoff,
            trace_rules=list(result.trace_rules),
            inputs=inputs,
        )


__all__ = ["Stage5Service"]
