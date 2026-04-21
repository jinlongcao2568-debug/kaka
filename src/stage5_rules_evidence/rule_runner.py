# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shared.contracts_runtime import ContractStore
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, get_flag
from stage5_rules_evidence.evidence_builder import EvidenceArtifacts


@dataclass(frozen=True)
class RuleArtifacts:
    rule_hit: Any
    rule_gate_decision: Any
    rule_hit_state: str
    rule_gate_status: str
    lineage_status: str
    conflict_state: str


class RuleRunner:
    def __init__(self, store: ContractStore) -> None:
        self.store = store

    def run(
        self,
        *,
        project_id: str,
        evidence_grade_profile: Any,
        public_attack_surface: Any,
        focus_bidder_verification_profile: Any,
        pseudo_competitor_signal_set: Any,
        evidence_artifacts: EvidenceArtifacts,
        inputs: Mapping[str, Any],
        flags: Mapping[str, Any],
        trace_rules: list[str],
    ) -> RuleArtifacts:
        lineage_status = str(inputs["lineage_status"])
        conflict_state = str(inputs["conflict_state"])
        verification_state = str(inputs["verification_state"])
        rule_hit_state = "DETECTED"
        rule_gate_status = "REVIEW"
        blocking_reasons: list[str] = []

        if get_flag(flags, "rule_superseded"):
            apply_rule(self.store, trace_rules, "STATE-508")
            rule_hit_state = "SUPERSEDED"
            rule_gate_status = "REVIEW"
        elif verification_state == "BLOCK" or evidence_artifacts.evidence_gate_status == "BLOCK":
            apply_rule(self.store, trace_rules, "STATE-504")
            rule_gate_status = "BLOCK"
            rule_hit_state = "BLOCKED"
            if verification_state == "BLOCK":
                blocking_reasons.append("verification blocked")
            if evidence_artifacts.evidence_gate_status == "BLOCK":
                blocking_reasons.append("evidence gate blocked")
        elif (
            evidence_artifacts.evidence_gate_status == "PASS"
            and verification_state == "PASS"
            and lineage_status == "NORMALIZED"
            and conflict_state == "CONSISTENT"
        ):
            apply_rule(self.store, trace_rules, "STATE-506")
            rule_hit_state = "READY_FOR_GATE"
            if get_flag(flags, "rule_blocked"):
                apply_rule(self.store, trace_rules, "STATE-504")
                rule_gate_status = "BLOCK"
                rule_hit_state = "BLOCKED"
            elif get_flag(flags, "rule_review"):
                apply_rule(self.store, trace_rules, "STATE-503")
                rule_gate_status = "REVIEW"
                rule_hit_state = "REVIEW_REQUIRED"
            else:
                rule_gate_status = "PASS"
                apply_rule(self.store, trace_rules, "STATE-507")
                rule_hit_state = "CONFIRMED"
        elif (
            verification_state in {"REVIEW", "NOT_RUN"}
            or evidence_artifacts.evidence_gate_status == "REVIEW"
            or lineage_status != "NORMALIZED"
            or conflict_state != "CONSISTENT"
        ):
            apply_rule(self.store, trace_rules, "STATE-503")
            rule_gate_status = "REVIEW"
            rule_hit_state = "REVIEW_REQUIRED"
        else:
            apply_rule(self.store, trace_rules, "STATE-504")
            rule_gate_status = "BLOCK"
            rule_hit_state = "BLOCKED"
            blocking_reasons.append("rule gate blocked")

        rule_hit = self.store.build_record(
            "rule_hit",
            {
                "rule_hit_id": build_id("RH", project_id),
                "project_id": project_id,
                "rule_code": inputs.get("rule_code", "PROC-001"),
                "result_type": ensure_enum(self.store, "result_type", inputs.get("result_type")),
                "rule_hit_state": rule_hit_state,
                "evidence_refs": [evidence_artifacts.evidence.get("evidence_id")],
                "boundary_note": inputs.get(
                    "boundary_note",
                    f"verification={verification_state}; pseudo_signal={pseudo_competitor_signal_set.get('confidence_band')}",
                ),
                "evidence_grade": evidence_grade_profile.get("external_use_grade"),
                "source_object_refs": ensure_list(
                    inputs.get(
                        "source_object_refs",
                        [
                            public_attack_surface.get("public_attack_surface_id"),
                            focus_bidder_verification_profile.get("verification_profile_id"),
                            pseudo_competitor_signal_set.get("signal_set_id"),
                        ],
                    )
                ),
            },
        )

        rule_gate_decision = self.store.build_record(
            "rule_gate_decision",
            {
                "gate_id": build_id("RGATE", project_id),
                "project_id": project_id,
                "gate_scope": "PROJECT",
                "rule_gate_status": rule_gate_status,
                "passed_rule_hits": [rule_hit.get("rule_hit_id")] if rule_gate_status == "PASS" else [],
                "blocked_rule_hits": [rule_hit.get("rule_hit_id")] if rule_gate_status == "BLOCK" else [],
                "blocking_reasons": [] if rule_gate_status == "PASS" else blocking_reasons or ["rule gate blocked"],
                "resolved_by_version_state": inputs.get("version_conflict_state", "CONSISTENT"),
            },
        )

        return RuleArtifacts(
            rule_hit=rule_hit,
            rule_gate_decision=rule_gate_decision,
            rule_hit_state=rule_hit_state,
            rule_gate_status=rule_gate_status,
            lineage_status=lineage_status,
            conflict_state=conflict_state,
        )


__all__ = ["RuleArtifacts", "RuleRunner"]
