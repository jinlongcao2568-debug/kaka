# Stage: stage4_verification
# Consumes formal objects: public_attack_surface, focus_bidder_verification_profile, pseudo_competitor_signal_set, evidence_grade_profile
# Dependent handoff: H-03-STAGE3-TO-STAGE4, H-04-STAGE4-TO-STAGE5
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, get_flag, resolve_bundle
from stage4_verification.active_conflict import (
    build_project_manager_active_conflict_readback as build_active_conflict_readback,
    evaluate_project_manager_active_conflict as evaluate_active_conflict,
)
from stage4_verification.hard_defect_strategy import (
    build_evidence_risk_hard_defect_strategy as build_hard_defect_strategy,
    build_evidence_risk_hard_defect_strategy_readback as build_hard_defect_strategy_readback,
)
from stage4_verification.verification import PublicVerificationAdapter, build_public_verification_readback
from storage.repositories.object_storage_repo import ObjectStorageRepository


def _record_mapping(record: Any) -> Mapping[str, Any]:
    data = getattr(record, "data", None)
    return data if isinstance(data, Mapping) else {}


class Stage4Service:
    H03_FORMAL_FIELDS = (
        "project_id",
        "project_root_id",
        "notice_version_id",
        "candidate_order_mode",
        "award_determination_mode",
        "public_chain_status",
        "lineage_status",
        "conflict_state",
        "fixation_bundle_id",
        "source_registry_id",
        "route_policy_id",
        "fallback_route",
        "route_decision_state",
        "route_review_reasons",
        "winning_version_resolution_rule_id",
        "version_conflict_state",
        "clock_resolution_rule_id",
        "clock_precedence_rule_id",
        "clock_conflict_state",
        "collection_state",
        "stage3_review_path_ref_optional",
    )
    H03_OPTIONAL_FORMAL_FIELDS = (
        "current_action_start_at_optional",
        "current_action_deadline_at_optional",
    )

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage3_bundle = resolve_bundle(payload)
        inputs = stage3_bundle.inputs or {}
        flags = inputs.get("flags", {})
        handoff_map = stage3_bundle.handoff or {}

        project_base = stage3_bundle.record("project_base")
        bidder_candidate = stage3_bundle.record("bidder_candidate")
        lineage = stage3_bundle.record("field_lineage_record")
        project_manager = stage3_bundle.records.get("project_manager")

        project_base_map = _record_mapping(project_base)
        bidder_candidate_map = _record_mapping(bidder_candidate)
        lineage_map = _record_mapping(lineage)
        project_manager_map = _record_mapping(project_manager)

        def resolve_h03_field(field_name: str, carriers: tuple[Mapping[str, Any], ...]) -> Any:
            handoff_value = handoff_map.get(field_name)
            if handoff_value not in (None, ""):
                return handoff_value
            for carrier in carriers:
                value = carrier.get(field_name)
                if value not in (None, ""):
                    return value
            return None

        project_id = resolve_h03_field(
            "project_id",
            (project_base_map, bidder_candidate_map, lineage_map, project_manager_map),
        )
        project_root_id = resolve_h03_field("project_root_id", (project_base_map,))
        notice_version_id = resolve_h03_field("notice_version_id", (project_base_map,))
        candidate_order_mode = resolve_h03_field("candidate_order_mode", (project_base_map,))
        award_determination_mode = resolve_h03_field("award_determination_mode", (project_base_map,))
        public_chain_status = resolve_h03_field("public_chain_status", (project_base_map,))
        lineage_status = resolve_h03_field("lineage_status", (lineage_map,))
        conflict_state = resolve_h03_field("conflict_state", (lineage_map,))
        fixation_bundle_id = resolve_h03_field("fixation_bundle_id", ())
        source_registry_id = resolve_h03_field("source_registry_id", (project_base_map, lineage_map))
        route_policy_id = resolve_h03_field("route_policy_id", (project_base_map, lineage_map))
        fallback_route = resolve_h03_field("fallback_route", ())
        route_decision_state = resolve_h03_field("route_decision_state", ())
        route_review_reasons = ensure_list(resolve_h03_field("route_review_reasons", ()))
        winning_version_resolution_rule_id = resolve_h03_field("winning_version_resolution_rule_id", ())
        version_conflict_state = resolve_h03_field("version_conflict_state", ())
        clock_resolution_rule_id = resolve_h03_field("clock_resolution_rule_id", ())
        clock_precedence_rule_id = resolve_h03_field("clock_precedence_rule_id", ())
        clock_conflict_state = resolve_h03_field("clock_conflict_state", ())
        collection_state = resolve_h03_field("collection_state", ())
        current_action_start_at_optional = resolve_h03_field("current_action_start_at_optional", ())
        current_action_deadline_at_optional = resolve_h03_field("current_action_deadline_at_optional", ())
        stage3_review_path_ref = resolve_h03_field("stage3_review_path_ref_optional", (project_base_map,))
        if stage3_review_path_ref in (None, ""):
            stage3_review_path_ref = resolve_h03_field("review_path_optional", (lineage_map,))
        candidate_collection_ref = resolve_h03_field(
            "candidate_collection_ref_optional",
            (bidder_candidate_map, lineage_map),
        )
        if candidate_collection_ref in (None, ""):
            candidate_collection_ref = resolve_h03_field("bidder_candidate_collection_ref_optional", (project_base_map,))
        field_lineage_collection_ref = resolve_h03_field("field_lineage_collection_ref_optional", (project_base_map,))
        bidder_candidate_collection_ref = resolve_h03_field(
            "bidder_candidate_collection_ref_optional",
            (project_base_map,),
        )
        project_manager_id = resolve_h03_field("project_manager_id", (project_manager_map,))
        focus_bidder_id = resolve_h03_field("bidder_candidate_id", (bidder_candidate_map,))

        h03_values = {
            "project_id": project_id,
            "project_root_id": project_root_id,
            "notice_version_id": notice_version_id,
            "candidate_order_mode": candidate_order_mode,
            "award_determination_mode": award_determination_mode,
            "public_chain_status": public_chain_status,
            "lineage_status": lineage_status,
            "conflict_state": conflict_state,
            "fixation_bundle_id": fixation_bundle_id,
            "source_registry_id": source_registry_id,
            "route_policy_id": route_policy_id,
            "fallback_route": fallback_route,
            "route_decision_state": route_decision_state,
            "route_review_reasons": route_review_reasons,
            "winning_version_resolution_rule_id": winning_version_resolution_rule_id,
            "version_conflict_state": version_conflict_state,
            "clock_resolution_rule_id": clock_resolution_rule_id,
            "clock_precedence_rule_id": clock_precedence_rule_id,
            "clock_conflict_state": clock_conflict_state,
            "collection_state": collection_state,
            "stage3_review_path_ref_optional": stage3_review_path_ref,
        }
        missing_h03_fields = [
            field_name
            for field_name, value in h03_values.items()
            if value in (None, "")
        ]
        review_reasons = list(route_review_reasons)
        if stage3_review_path_ref != "STAGE3_READY_FOR_STAGE4":
            review_reasons.append("stage3_review_path_requires_review")
        if candidate_collection_ref in (None, ""):
            review_reasons.append("candidate_collection_ref_missing")
        if lineage_status != "NORMALIZED":
            review_reasons.append("lineage_status_not_normalized")
        if conflict_state != "CONSISTENT":
            review_reasons.append("conflict_state_not_consistent")
        if version_conflict_state != "CONSISTENT":
            review_reasons.append("version_conflict_state_not_consistent")
        if collection_state != "NORMALIZED":
            review_reasons.append("collection_state_not_normalized")
        if clock_conflict_state != "CONSISTENT":
            review_reasons.append("clock_conflict_state_not_consistent")
        review_reasons = list(dict.fromkeys(reason for reason in review_reasons if reason))

        trace_rules: list[str] = []
        verification_state = "NOT_RUN"
        if get_flag(flags, "verification_blocked"):
            apply_rule(self.store, trace_rules, "STATE-402")
            verification_state = "BLOCK"
        elif missing_h03_fields:
            apply_rule(self.store, trace_rules, "STATE-402")
            verification_state = "BLOCK"
        elif (
            review_reasons
            or public_chain_status != "COMPLETE"
            or route_decision_state == "BLOCK"
            or get_flag(flags, "verification_review")
        ):
            apply_rule(self.store, trace_rules, "STATE-401")
            verification_state = "REVIEW"
        else:
            apply_rule(self.store, trace_rules, "STATE-403")
            verification_state = "PASS"

        public_attack_surface_id = build_id("PAS", project_id)
        verification_profile_id = build_id("VFP", project_id)
        evidence_grade_profile_id = build_id("EGP", project_id)
        signal_set_id = build_id("PCS", project_id)

        candidate_set_ids = [focus_bidder_id] if focus_bidder_id else []
        ranked_candidate_ids = candidate_set_ids if candidate_order_mode == "ORDERED" else []
        stage3_context_refs = [
            f"STAGE3_LINEAGE_STATUS:{lineage_status}",
            f"STAGE3_CONFLICT_STATE:{conflict_state}",
            f"STAGE3_REVIEW_PATH:{stage3_review_path_ref}",
            f"STAGE3_CANDIDATE_COLLECTION:{candidate_collection_ref}",
            f"STAGE3_FIXATION_BUNDLE:{fixation_bundle_id}",
            f"STAGE3_SOURCE_REGISTRY:{source_registry_id}",
            f"STAGE3_ROUTE_POLICY:{route_policy_id}",
            f"STAGE3_FALLBACK_ROUTE:{fallback_route}",
            f"STAGE3_ROUTE_DECISION:{route_decision_state}",
            f"STAGE3_VERSION_RULE:{winning_version_resolution_rule_id}",
            f"STAGE3_VERSION_CONFLICT:{version_conflict_state}",
            f"STAGE3_CLOCK_RULE:{clock_resolution_rule_id}",
            f"STAGE3_CLOCK_PRECEDENCE:{clock_precedence_rule_id}",
            f"STAGE3_CLOCK_CONFLICT:{clock_conflict_state}",
            f"STAGE3_COLLECTION_STATE:{collection_state}",
        ]
        if current_action_start_at_optional not in (None, ""):
            stage3_context_refs.append(f"STAGE3_ACTION_START:{current_action_start_at_optional}")
        if current_action_deadline_at_optional not in (None, ""):
            stage3_context_refs.append(f"STAGE3_ACTION_DEADLINE:{current_action_deadline_at_optional}")
        if project_manager_id:
            stage3_context_refs.append(f"STAGE3_PROJECT_MANAGER:{project_manager_id}")

        public_attack_surface = self.store.build_record(
            "public_attack_surface",
            {
                "public_attack_surface_id": public_attack_surface_id,
                "project_id": project_id,
                "focus_bidder_id": focus_bidder_id,
                "candidate_set_ids": candidate_set_ids,
                "ranked_candidate_ids_optional": ranked_candidate_ids,
                "primary_attack_points": ensure_list(inputs.get("primary_attack_points", ["BID_PRICE"])),
                "public_supporting_refs": list(
                    dict.fromkeys(ensure_list(inputs.get("public_supporting_refs", ["PUBLIC_CHAIN"])) + stage3_context_refs)
                ),
                "window_status": ensure_enum(self.store, "window_status", inputs.get("window_status")),
                "verification_state": verification_state,
            },
        )

        focus_bidder_verification_profile = self.store.build_record(
            "focus_bidder_verification_profile",
            {
                "verification_profile_id": verification_profile_id,
                "project_id": project_id,
                "focus_bidder_id": focus_bidder_id,
                "illegality_risk_state": inputs.get("illegality_risk_state", "NOT_RUN"),
                "qualification_state": inputs.get("qualification_state", "NOT_RUN"),
                "performance_state": inputs.get("performance_state", "NOT_RUN"),
                "personnel_state": inputs.get("personnel_state", "NOT_RUN"),
                "credit_state": inputs.get("credit_state", "NOT_RUN"),
                "financial_change_state": inputs.get("financial_change_state", "NOT_RUN"),
                "production_condition_state": inputs.get("production_condition_state", "NOT_RUN"),
                "bid_bond_state": inputs.get("bid_bond_state", "NOT_RUN"),
                "relation_conflict_state": conflict_state or "NOT_RUN",
                "consortium_consistency_state": inputs.get("consortium_consistency_state", "NOT_RUN"),
                "verification_state": verification_state,
            },
        )

        if get_flag(flags, "evidence_blocked") or verification_state == "BLOCK":
            cross_check_state = "BLOCK"
            provenance_chain_status = "BROKEN"
            fixation_status = "NOT_FIXED"
            retrieval_status = "BLOCKED"
            external_use_grade = ensure_enum(self.store, "external_use_grade", "E1_INTERNAL_ONLY")
        elif get_flag(flags, "evidence_review") or verification_state == "REVIEW":
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
                "project_id": project_id,
                "source_level": inputs.get("source_level", "PUBLIC"),
                "public_capability_tier": ensure_enum(
                    self.store, "public_capability_tier", inputs.get("public_capability_tier") or "A_PUBLIC_CORE"
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
        signal_tags = list(
            dict.fromkeys(
                signal_tags
                + [
                    f"STAGE3_LINEAGE_{lineage_status}",
                    f"STAGE3_CONFLICT_{conflict_state}",
                ]
            )
        )

        pseudo_competitor_signal_set = self.store.build_record(
            "pseudo_competitor_signal_set",
            {
                "signal_set_id": signal_set_id,
                "project_id": project_id,
                "candidate_ids": candidate_set_ids,
                "signal_tags": signal_tags,
                "confidence_band": confidence_band,
                "explanation": inputs.get(
                    "pseudo_competitor_explanation",
                    (
                        "Conservative pseudo competitor filter for downstream challenger review; "
                        f"stage3_lineage={lineage_status}; stage3_conflict={conflict_state}; "
                        f"stage3_review_path={stage3_review_path_ref}."
                    ),
                ),
            },
        )

        handoff = {
            "project_id": project_id,
            "focus_bidder_id": focus_bidder_id,
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
            "fallback_route": fallback_route,
            "route_decision_state": route_decision_state,
            "route_review_reasons": route_review_reasons,
            "winning_version_resolution_rule_id": winning_version_resolution_rule_id,
            "version_conflict_state": version_conflict_state,
            "clock_resolution_rule_id": clock_resolution_rule_id,
            "clock_precedence_rule_id": clock_precedence_rule_id,
            "clock_conflict_state": clock_conflict_state,
            "collection_state": collection_state,
        }
        if current_action_start_at_optional not in (None, ""):
            handoff["current_action_start_at_optional"] = current_action_start_at_optional
        if current_action_deadline_at_optional not in (None, ""):
            handoff["current_action_deadline_at_optional"] = current_action_deadline_at_optional

        inputs_out = dict(inputs)
        for field_name, value in h03_values.items():
            inputs_out[field_name] = value
        for field_name in self.H03_OPTIONAL_FORMAL_FIELDS:
            value = locals()[field_name]
            if value not in (None, ""):
                inputs_out[field_name] = value
        inputs_out["stage3_review_reasons"] = review_reasons
        inputs_out["candidate_collection_ref_optional"] = candidate_collection_ref
        inputs_out["field_lineage_collection_ref_optional"] = field_lineage_collection_ref
        inputs_out["bidder_candidate_collection_ref_optional"] = bidder_candidate_collection_ref
        inputs_out["project_manager_id_optional"] = project_manager_id
        inputs_out["h03_formal_consumption_trace"] = {
            "source_precedence": "stage3_handoff_then_formal_producer_objects",
            "missing_required_fields": missing_h03_fields,
            "review_reasons": review_reasons,
            "formal_carrier_fields": list(self.H03_FORMAL_FIELDS),
            "optional_formal_carrier_fields": list(self.H03_OPTIONAL_FORMAL_FIELDS),
        }
        inputs_out["focus_bidder_id"] = focus_bidder_id
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

    def verify_public_parsed_carrier(
        self,
        parsed_carrier: Mapping[str, Any],
        *,
        target: Mapping[str, Any],
        repository: ObjectStorageRepository | None = None,
        snapshot_readback: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        carrier = PublicVerificationAdapter(repository=repository).verify(
            parsed_carrier,
            target=target,
            snapshot_readback=snapshot_readback,
        )
        return carrier.as_payload()

    def build_public_verification_readback(
        self,
        carrier: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return build_public_verification_readback(carrier)

    def evaluate_project_manager_active_conflict(
        self,
        parsed_context: Mapping[str, Any] | StageBundle,
        *,
        public_verification_carriers: list[Mapping[str, Any]] | None = None,
        possible_conflicting_projects: list[Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        carrier = evaluate_active_conflict(
            parsed_context,
            public_verification_carriers=public_verification_carriers,
            possible_conflicting_projects=possible_conflicting_projects,
        )
        return carrier.as_payload()

    def build_project_manager_active_conflict_readback(
        self,
        carrier: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return build_active_conflict_readback(carrier)

    def build_evidence_risk_hard_defect_strategy(
        self,
        parsed_context: Mapping[str, Any] | StageBundle,
        *,
        existing_public_verification_carriers: list[Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        carrier = build_hard_defect_strategy(
            parsed_context,
            existing_public_verification_carriers=existing_public_verification_carriers,
        )
        return carrier.as_payload()

    def build_evidence_risk_hard_defect_strategy_readback(
        self,
        carrier: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return build_hard_defect_strategy_readback(carrier)
