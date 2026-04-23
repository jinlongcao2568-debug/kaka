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
    rule_hits: list[Any]
    rule_gate_decision: Any
    rule_hit_state: str
    rule_gate_status: str
    lineage_status: str
    conflict_state: str


class RuleRunner:
    PREFERRED_STAGE5_RULE_CODES = ("PROC-001", "PROC-002", "DOC-001")
    RULE_SOURCE_OBJECT_REF_FIELDS = {
        "PROC-001": (
            "public_attack_surface_id",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ),
        "PROC-002": (
            "winning_version_resolution_rule_id",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ),
        "DOC-001": (
            "winning_version_resolution_rule_id",
            "verification_profile_id",
            "public_attack_surface_id",
        ),
    }

    def __init__(self, store: ContractStore) -> None:
        self.store = store

    def _select_stage5_rules(self) -> list[Mapping[str, Any]]:
        stage5_rules = [
            entry
            for entry in self.store.rule_catalog.get("rules", [])
            if int(entry.get("stage", -1)) == 5
        ]
        preferred = []
        for rule_code in self.PREFERRED_STAGE5_RULE_CODES:
            matched_rule = next(
                (entry for entry in stage5_rules if str(entry.get("rule_code")) == rule_code),
                None,
            )
            if matched_rule is not None:
                preferred.append(matched_rule)
        if preferred:
            return preferred[:3]
        return stage5_rules[:3]

    def _build_rule_source_object_refs(
        self,
        rule_code: str,
        *,
        inputs: Mapping[str, Any],
        public_attack_surface: Any,
        focus_bidder_verification_profile: Any,
        pseudo_competitor_signal_set: Any,
    ) -> list[str]:
        source_refs = [
            inputs.get("project_root_id"),
            public_attack_surface.get("public_attack_surface_id"),
            focus_bidder_verification_profile.get("verification_profile_id"),
            pseudo_competitor_signal_set.get("signal_set_id"),
            inputs.get("pseudo_competitor_signal_set_id"),
            inputs.get("winning_version_resolution_rule_id"),
            inputs.get("clock_resolution_rule_id"),
            inputs.get("clock_precedence_rule_id"),
        ]
        preferred_fields = self.RULE_SOURCE_OBJECT_REF_FIELDS.get(rule_code, ())
        ordered_refs = [inputs.get(field_name) for field_name in preferred_fields]
        ordered_refs.extend(source_refs)
        return [str(ref) for ref in ordered_refs if ref not in (None, "")]

    def _evaluate_rule_status(
        self,
        *,
        rule_code: str,
        evidence_gate_status: str,
        verification_state: str,
        lineage_status: str,
        conflict_state: str,
        version_conflict_state: str,
        clock_conflict_state: str,
        flags: Mapping[str, Any],
    ) -> tuple[str, str, list[str], str]:
        reasons: list[str] = []
        if get_flag(flags, "rule_superseded"):
            reasons.append(f"{rule_code}: superseded by newer rule outcome")
            return "REVIEW", "SUPERSEDED", reasons, "STATE-508"

        if verification_state == "BLOCK":
            reasons.append(f"{rule_code}: verification blocked")
        if evidence_gate_status == "BLOCK":
            reasons.append(f"{rule_code}: evidence gate blocked")
        if get_flag(flags, "rule_blocked"):
            reasons.append(f"{rule_code}: rule_blocked flag active")
        if reasons:
            return "BLOCK", "BLOCKED", reasons, "STATE-504"

        if version_conflict_state != "CONSISTENT":
            reasons.append(f"{rule_code}: version conflict {version_conflict_state}")
        if clock_conflict_state != "CONSISTENT":
            reasons.append(f"{rule_code}: clock conflict {clock_conflict_state}")
        if verification_state in {"REVIEW", "NOT_RUN"}:
            reasons.append(f"{rule_code}: verification {verification_state.lower()}")
        if evidence_gate_status == "REVIEW":
            reasons.append(f"{rule_code}: evidence gate review")
        if lineage_status != "NORMALIZED":
            reasons.append(f"{rule_code}: lineage {lineage_status}")
        if conflict_state != "CONSISTENT":
            reasons.append(f"{rule_code}: conflict {conflict_state}")
        if get_flag(flags, "rule_review"):
            reasons.append(f"{rule_code}: rule_review flag active")
        if reasons:
            return "REVIEW", "REVIEW_REQUIRED", reasons, "STATE-503"

        return "PASS", "CONFIRMED", [], "STATE-507"

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
        version_conflict_state = str(inputs.get("version_conflict_state", "CONSISTENT"))
        clock_conflict_state = str(inputs.get("clock_conflict_state", "CONSISTENT"))

        selected_rules = self._select_stage5_rules()
        if not selected_rules:
            raise ValueError("stage5_rule_catalog_selection_empty")
        evaluated_rules: list[tuple[Any, str, str, list[str]]] = []
        for rule in selected_rules:
            rule_code = str(rule.get("rule_code"))
            apply_rule(self.store, trace_rules, rule_code)
            rule_gate_status_for_hit, rule_hit_state_for_hit, reasons, state_trace_rule = self._evaluate_rule_status(
                rule_code=rule_code,
                evidence_gate_status=evidence_artifacts.evidence_gate_status,
                verification_state=verification_state,
                lineage_status=lineage_status,
                conflict_state=conflict_state,
                version_conflict_state=version_conflict_state,
                clock_conflict_state=clock_conflict_state,
                flags=flags,
            )
            apply_rule(self.store, trace_rules, state_trace_rule)
            source_object_refs = ensure_list(
                inputs.get("source_object_refs")
                if len(selected_rules) == 1
                else self._build_rule_source_object_refs(
                    rule_code,
                    inputs=inputs,
                    public_attack_surface=public_attack_surface,
                    focus_bidder_verification_profile=focus_bidder_verification_profile,
                    pseudo_competitor_signal_set=pseudo_competitor_signal_set,
                )
            )
            boundary_note = (
                f"{rule.get('name')}; upstream={','.join(rule.get('upstream_objects', []))}; "
                f"verification={verification_state}; evidence_gate={evidence_artifacts.evidence_gate_status}; "
                f"version={version_conflict_state}; clock={clock_conflict_state}; "
                f"pseudo_signal={pseudo_competitor_signal_set.get('confidence_band')}"
            )
            if reasons:
                boundary_note = f"{boundary_note}; reasons={'; '.join(reasons)}"
            rule_hit = self.store.build_record(
                "rule_hit",
                {
                    "rule_hit_id": build_id("RH", project_id, rule_code),
                    "project_id": project_id,
                    "rule_code": rule_code,
                    "result_type": ensure_enum(
                        self.store,
                        "result_type",
                        inputs.get("result_type") or rule.get("default_result"),
                    ),
                    "rule_hit_state": rule_hit_state_for_hit,
                    "evidence_refs": [evidence_artifacts.evidence.get("evidence_id")],
                    "boundary_note": inputs.get("boundary_note", boundary_note),
                    "evidence_grade": evidence_grade_profile.get("external_use_grade"),
                    "source_object_refs": source_object_refs,
                },
            )
            evaluated_rules.append((rule_hit, rule_gate_status_for_hit, rule_hit_state_for_hit, reasons))

        severity_order = {"BLOCK": 0, "REVIEW": 1, "PASS": 2}
        primary_rule_hit, _, primary_rule_hit_state, _ = min(
            evaluated_rules,
            key=lambda entry: severity_order.get(entry[1], 99),
        )
        rule_hits = [entry[0] for entry in evaluated_rules]
        passed_rule_hits = [
            rule_hit.get("rule_hit_id")
            for rule_hit, rule_status, _, _ in evaluated_rules
            if rule_status == "PASS"
        ]
        blocked_rule_hits = [
            rule_hit.get("rule_hit_id")
            for rule_hit, rule_status, _, _ in evaluated_rules
            if rule_status == "BLOCK"
        ]
        aggregated_reasons: list[str] = []
        for _, rule_status, _, reasons in evaluated_rules:
            if rule_status != "PASS":
                aggregated_reasons.extend(reasons)
        blocking_reasons = list(dict.fromkeys(aggregated_reasons))
        if blocked_rule_hits:
            rule_gate_status = "BLOCK"
        elif any(rule_status == "REVIEW" for _, rule_status, _, _ in evaluated_rules):
            rule_gate_status = "REVIEW"
        else:
            rule_gate_status = "PASS"

        rule_gate_decision = self.store.build_record(
            "rule_gate_decision",
            {
                "gate_id": build_id("RGATE", project_id),
                "project_id": project_id,
                "gate_scope": "PROJECT",
                "rule_gate_status": rule_gate_status,
                "passed_rule_hits": passed_rule_hits,
                "blocked_rule_hits": blocked_rule_hits,
                "blocking_reasons": [] if rule_gate_status == "PASS" else blocking_reasons,
                "resolved_by_version_state": inputs.get("version_conflict_state", "CONSISTENT"),
            },
        )

        return RuleArtifacts(
            rule_hit=primary_rule_hit,
            rule_hits=rule_hits,
            rule_gate_decision=rule_gate_decision,
            rule_hit_state=primary_rule_hit_state,
            rule_gate_status=rule_gate_status,
            lineage_status=lineage_status,
            conflict_state=conflict_state,
        )


__all__ = ["RuleArtifacts", "RuleRunner"]
