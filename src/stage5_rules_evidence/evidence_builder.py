# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shared.contracts_runtime import ContractStore
from shared.utils import apply_rule, build_id, ensure_enum, get_flag


@dataclass(frozen=True)
class EvidenceArtifacts:
    evidence: Any
    evidence_gate_decision: Any
    evidence_gate_status: str
    cross_check_state: str
    fixation_status: str
    provenance_chain_status: str
    retrieval_readiness_status: str


class EvidenceBuilder:
    def __init__(self, store: ContractStore) -> None:
        self.store = store

    def build(
        self,
        *,
        project_id: str,
        evidence_grade_profile: Any,
        inputs: Mapping[str, Any],
        flags: Mapping[str, Any],
        trace_rules: list[str],
    ) -> EvidenceArtifacts:
        cross_check_state = str(evidence_grade_profile.get("cross_check_state", "NOT_RUN"))
        fixation_status = str(evidence_grade_profile.get("fixation_status", "NOT_FIXED"))
        provenance_chain_status = str(evidence_grade_profile.get("provenance_chain_status", "UNVERIFIED"))
        retrieval_readiness_status = str(evidence_grade_profile.get("retrieval_readiness_status", "NOT_READY"))

        if (
            cross_check_state == "BLOCK"
            or fixation_status == "NOT_FIXED"
            or provenance_chain_status == "BROKEN"
            or retrieval_readiness_status == "BLOCKED"
        ):
            apply_rule(self.store, trace_rules, "STATE-502")
            evidence_gate_status = "BLOCK"
        elif (
            cross_check_state != "PASS"
            or fixation_status != "HASH_LOCKED"
            or provenance_chain_status != "COMPLETE"
            or retrieval_readiness_status != "READY"
        ):
            apply_rule(self.store, trace_rules, "STATE-501")
            evidence_gate_status = "REVIEW"
        else:
            apply_rule(self.store, trace_rules, "STATE-505")
            evidence_gate_status = "PASS"

        evidence = self.store.build_record(
            "evidence",
            {
                "evidence_id": build_id("EVD", project_id),
                "project_id": project_id,
                "evidence_family": inputs.get("evidence_family", "NOTICE"),
                "source_document_ref": inputs.get("source_document_ref", "DOC-001"),
                "source_slice_ref": inputs.get("source_slice_ref", "SLICE-001"),
                "carrier_type": ensure_enum(self.store, "carrier_type", inputs.get("carrier_type")),
                "cross_check_state": cross_check_state,
                "fixation_status": fixation_status,
                "external_use_grade": evidence_grade_profile.get("external_use_grade"),
                "provenance_chain_status": provenance_chain_status,
                "retrieval_readiness_status": retrieval_readiness_status,
            },
        )

        evidence_gate_decision = self.store.build_record(
            "evidence_gate_decision",
            {
                "gate_id": build_id("EGATE", project_id),
                "project_id": project_id,
                "gate_scope": "PROJECT",
                "evidence_gate_status": evidence_gate_status,
                "minimum_external_use_grade": evidence_grade_profile.get("external_use_grade"),
                "blocking_evidence_refs": [] if evidence_gate_status == "PASS" else [evidence.get("evidence_id")],
                "manual_confirmation_required": evidence_gate_status != "PASS",
                "visibility_reason_summary": inputs.get("visibility_reason_summary", "evidence gate"),
            },
        )

        return EvidenceArtifacts(
            evidence=evidence,
            evidence_gate_decision=evidence_gate_decision,
            evidence_gate_status=evidence_gate_status,
            cross_check_state=cross_check_state,
            fixation_status=fixation_status,
            provenance_chain_status=provenance_chain_status,
            retrieval_readiness_status=retrieval_readiness_status,
        )


__all__ = ["EvidenceArtifacts", "EvidenceBuilder"]
