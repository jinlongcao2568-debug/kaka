# Stage: stage4_verification
# Consumes formal objects: public_attack_surface, focus_bidder_verification_profile, pseudo_competitor_signal_set, evidence_grade_profile
# Dependent handoff: H-03-STAGE3-TO-STAGE4, H-04-STAGE4-TO-STAGE5
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, get_flag, resolve_bundle


class Stage4Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage3_bundle = resolve_bundle(payload)
        inputs = stage3_bundle.inputs or {}
        flags = inputs.get("flags", {})

        project_base = stage3_bundle.record("project_base")
        bidder_candidate = stage3_bundle.record("bidder_candidate")
        lineage = stage3_bundle.record("field_lineage_record")

        lineage_status = lineage.get("lineage_status")
        conflict_state = lineage.get("conflict_state")

        trace_rules: list[str] = []
        verification_state = "NOT_RUN"
        if get_flag(flags, "verification_blocked"):
            apply_rule(self.store, trace_rules, "STATE-402")
            verification_state = "BLOCK"
        elif lineage_status != "NORMALIZED" or conflict_state != "CONSISTENT" or get_flag(flags, "verification_review"):
            apply_rule(self.store, trace_rules, "STATE-401")
            verification_state = "REVIEW"
        else:
            apply_rule(self.store, trace_rules, "STATE-403")
            verification_state = "PASS"

        public_attack_surface_id = build_id("PAS", project_base.get("project_id"))
        verification_profile_id = build_id("VFP", project_base.get("project_id"))
        evidence_grade_profile_id = build_id("EGP", project_base.get("project_id"))
        signal_set_id = build_id("PCS", project_base.get("project_id"))

        public_attack_surface = self.store.build_record(
            "public_attack_surface",
            {
                "public_attack_surface_id": public_attack_surface_id,
                "project_id": project_base.get("project_id"),
                "focus_bidder_id": bidder_candidate.get("bidder_candidate_id"),
                "candidate_set_ids": ensure_list(inputs.get("candidate_set_ids", [bidder_candidate.get("bidder_candidate_id")])),
                "ranked_candidate_ids_optional": ensure_list(inputs.get("ranked_candidate_ids_optional", [])),
                "primary_attack_points": ensure_list(inputs.get("primary_attack_points", ["BID_PRICE"])),
                "public_supporting_refs": ensure_list(inputs.get("public_supporting_refs", ["PUBLIC_CHAIN"])),
                "window_status": ensure_enum(self.store, "window_status", inputs.get("window_status")),
                "verification_state": verification_state,
            },
        )

        focus_bidder_verification_profile = self.store.build_record(
            "focus_bidder_verification_profile",
            {
                "verification_profile_id": verification_profile_id,
                "project_id": project_base.get("project_id"),
                "focus_bidder_id": bidder_candidate.get("bidder_candidate_id"),
                "illegality_risk_state": inputs.get("illegality_risk_state", "NOT_RUN"),
                "qualification_state": inputs.get("qualification_state", "NOT_RUN"),
                "performance_state": inputs.get("performance_state", "NOT_RUN"),
                "personnel_state": inputs.get("personnel_state", "NOT_RUN"),
                "credit_state": inputs.get("credit_state", "NOT_RUN"),
                "financial_change_state": inputs.get("financial_change_state", "NOT_RUN"),
                "production_condition_state": inputs.get("production_condition_state", "NOT_RUN"),
                "bid_bond_state": inputs.get("bid_bond_state", "NOT_RUN"),
                "relation_conflict_state": inputs.get("relation_conflict_state", "NOT_RUN"),
                "consortium_consistency_state": inputs.get("consortium_consistency_state", "NOT_RUN"),
                "verification_state": verification_state,
            },
        )

        if get_flag(flags, "evidence_blocked"):
            cross_check_state = "BLOCK"
            provenance_chain_status = "BROKEN"
            fixation_status = "NOT_FIXED"
            retrieval_status = "BLOCKED"
            external_use_grade = ensure_enum(self.store, "external_use_grade", "E1_INTERNAL_ONLY")
        elif get_flag(flags, "evidence_review"):
            cross_check_state = "REVIEW"
            provenance_chain_status = "PARTIAL"
            fixation_status = "SNAPSHOT_CAPTURED"
            retrieval_status = "PARTIAL"
            external_use_grade = ensure_enum(self.store, "external_use_grade", "E2_REVIEW_READY")
        else:
            cross_check_state = "PASS"
            provenance_chain_status = "COMPLETE"
            fixation_status = "HASH_LOCKED"
            retrieval_status = "READY"
            external_use_grade = ensure_enum(self.store, "external_use_grade", "E2_REVIEW_READY")

        evidence_grade_profile = self.store.build_record(
            "evidence_grade_profile",
            {
                "evidence_grade_profile_id": evidence_grade_profile_id,
                "project_id": project_base.get("project_id"),
                "source_level": inputs.get("source_level", "PUBLIC"),
                "public_capability_tier": ensure_enum(
                    self.store, "public_capability_tier", inputs.get("public_capability_tier")
                ),
                "cross_check_state": cross_check_state,
                "external_use_grade": external_use_grade,
                "requires_manual_confirmation": verification_state != "PASS",
                "provenance_chain_status": provenance_chain_status,
                "fixation_status": fixation_status,
                "retrieval_readiness_status": retrieval_status,
            },
        )

        confidence_band = ensure_enum(self.store, "confidence_band", inputs.get("confidence_band"))
        if not inputs.get("confidence_band"):
            confidence_band = "LOW" if verification_state != "PASS" else "MEDIUM"

        signal_tags = ensure_list(inputs.get("signal_tags"))
        if not signal_tags:
            if verification_state == "BLOCK":
                signal_tags = ["PUBLIC_CONFLICT_BLOCKED"]
            elif verification_state == "REVIEW":
                signal_tags = ["PSEUDO_COMPETITOR_REVIEW_REQUIRED"]
            else:
                signal_tags = ["NO_STRONG_PSEUDO_COMPETITOR_SIGNAL"]

        pseudo_competitor_signal_set = self.store.build_record(
            "pseudo_competitor_signal_set",
            {
                "signal_set_id": signal_set_id,
                "project_id": project_base.get("project_id"),
                "candidate_ids": ensure_list(
                    inputs.get("candidate_ids", [bidder_candidate.get("bidder_candidate_id")])
                ),
                "signal_tags": signal_tags,
                "confidence_band": confidence_band,
                "explanation": inputs.get(
                    "pseudo_competitor_explanation",
                    "Conservative pseudo competitor filter for downstream challenger review.",
                ),
            },
        )

        handoff = {
            "project_id": project_base.get("project_id"),
            "focus_bidder_id": bidder_candidate.get("bidder_candidate_id"),
            "public_attack_surface_id": public_attack_surface.get("public_attack_surface_id"),
            "verification_profile_id": focus_bidder_verification_profile.get("verification_profile_id"),
            "evidence_grade_profile_id": evidence_grade_profile.get("evidence_grade_profile_id"),
            "public_capability_tier": evidence_grade_profile.get("public_capability_tier"),
            "verification_state": verification_state,
            "external_use_grade": external_use_grade,
            "cross_check_state": evidence_grade_profile.get("cross_check_state"),
            "fixation_status": evidence_grade_profile.get("fixation_status"),
            "provenance_chain_status": evidence_grade_profile.get("provenance_chain_status"),
            "retrieval_readiness_status": evidence_grade_profile.get("retrieval_readiness_status"),
            "lineage_status": lineage_status,
            "conflict_state": conflict_state,
            "pseudo_competitor_signal_set_id": pseudo_competitor_signal_set.get("signal_set_id"),
            "confidence_band": pseudo_competitor_signal_set.get("confidence_band"),
        }

        inputs_out = dict(inputs)
        inputs_out["focus_bidder_id"] = bidder_candidate.get("bidder_candidate_id")
        inputs_out["public_attack_surface_id"] = public_attack_surface.get("public_attack_surface_id")
        inputs_out["verification_profile_id"] = focus_bidder_verification_profile.get("verification_profile_id")
        inputs_out["evidence_grade_profile_id"] = evidence_grade_profile.get("evidence_grade_profile_id")
        inputs_out["public_capability_tier"] = evidence_grade_profile.get("public_capability_tier")
        inputs_out["verification_state"] = verification_state
        inputs_out["external_use_grade"] = external_use_grade
        inputs_out["cross_check_state"] = evidence_grade_profile.get("cross_check_state")
        inputs_out["fixation_status"] = evidence_grade_profile.get("fixation_status")
        inputs_out["provenance_chain_status"] = evidence_grade_profile.get("provenance_chain_status")
        inputs_out["retrieval_readiness_status"] = evidence_grade_profile.get("retrieval_readiness_status")
        inputs_out["lineage_status"] = lineage_status
        inputs_out["conflict_state"] = conflict_state
        inputs_out["pseudo_competitor_signal_set_id"] = pseudo_competitor_signal_set.get("signal_set_id")
        inputs_out["confidence_band"] = pseudo_competitor_signal_set.get("confidence_band")

        return StageBundle(
            stage=4,
            records={
                "public_attack_surface": public_attack_surface,
                "focus_bidder_verification_profile": focus_bidder_verification_profile,
                "pseudo_competitor_signal_set": pseudo_competitor_signal_set,
                "evidence_grade_profile": evidence_grade_profile,
            },
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff
