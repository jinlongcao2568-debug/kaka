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
from stage4_verification.jzsc_personnel import (
    build_jzsc_company_first_capture_plan,
    build_jzsc_company_personnel_resolution_carrier,
    build_jzsc_personnel_project_conflict_records,
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

    def build_jzsc_project_manager_company_first_readback(
        self,
        parsed_context: Mapping[str, Any] | StageBundle,
        *,
        target_company_name: str,
        target_project_manager_name: str,
        rendered_company_personnel_rows: list[Any],
        company_personnel_source_url: str,
        company_personnel_source_snapshot_id: str,
        rendered_personnel_project_rows: list[Any] | None = None,
        personnel_project_source_url: str | None = None,
        personnel_project_source_snapshot_id: str | None = None,
        target_identifier: str | None = None,
        required_registration_category: str | None = None,
        required_registration_profession_keywords: list[str] | None = None,
        base_public_verification_carriers: list[Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        capture_plan = self.build_jzsc_project_manager_company_first_capture_plan(
            target_company_name=target_company_name,
            target_project_manager_name=target_project_manager_name,
            target_identifier=target_identifier,
        )
        personnel_carrier = build_jzsc_company_personnel_resolution_carrier(
            rendered_company_personnel_rows,
            target_company_name=target_company_name,
            target_name=target_project_manager_name,
            target_identifier=target_identifier,
            source_url=company_personnel_source_url,
            source_snapshot_id=company_personnel_source_snapshot_id,
            required_registration_category=required_registration_category,
            required_registration_profession_keywords=required_registration_profession_keywords,
        )
        public_verification_carriers = [
            *[dict(carrier) for carrier in ensure_list(base_public_verification_carriers)],
            personnel_carrier,
        ]
        resolved_identifier = (
            personnel_carrier.get("project_manager_public_identifier_optional")
            or target_identifier
            or target_project_manager_name
        )
        conflict_records: list[Mapping[str, Any]] = []
        if rendered_personnel_project_rows is not None:
            conflict_records = build_jzsc_personnel_project_conflict_records(
                rendered_personnel_project_rows,
                project_manager_name=target_project_manager_name,
                project_manager_identifier=str(resolved_identifier),
                registered_unit_name=target_company_name,
                source_url=personnel_project_source_url or company_personnel_source_url,
                source_snapshot_id=(
                    personnel_project_source_snapshot_id
                    or company_personnel_source_snapshot_id
                ),
            )
        strategy = self.build_evidence_risk_hard_defect_strategy(
            parsed_context,
            existing_public_verification_carriers=public_verification_carriers,
        )
        active_conflict = self.evaluate_project_manager_active_conflict(
            parsed_context,
            public_verification_carriers=public_verification_carriers,
            possible_conflicting_projects=list(conflict_records),
        )
        active_conflict_readback = self.build_project_manager_active_conflict_readback(
            active_conflict
        )
        return {
            "route": "JZSC_COMPANY_FIRST_PROJECT_MANAGER",
            "target_company_name": target_company_name,
            "target_project_manager_name": target_project_manager_name,
            "resolved_public_identifier_optional": resolved_identifier,
            "capture_plan": capture_plan,
            "personnel_carrier": personnel_carrier,
            "conflict_records": [dict(record) for record in conflict_records],
            "evidence_risk_hard_defect_strategy": dict(strategy),
            "project_manager_active_conflict": dict(active_conflict),
            "project_manager_active_conflict_readback": dict(active_conflict_readback),
            "next_required_runtime_adapter": (
                "browser_rendered_jzsc_company_personnel_and_project_pages"
            ),
        }

    def run_jzsc_company_first_rendered_readback(
        self,
        parsed_context: Mapping[str, Any] | StageBundle,
        *,
        target_company_name: str,
        target_project_manager_name: str,
        rendered_company_personnel_rows: list[Any] | None = None,
        company_personnel_source_url: str | None = None,
        company_personnel_source_snapshot_id: str | None = None,
        rendered_personnel_project_rows: list[Any] | None = None,
        personnel_project_source_url: str | None = None,
        personnel_project_source_snapshot_id: str | None = None,
        target_identifier: str | None = None,
        required_registration_category: str | None = None,
        required_registration_profession_keywords: list[str] | None = None,
        base_public_verification_carriers: list[Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        company_name = str(target_company_name or "").strip()
        manager_name = str(target_project_manager_name or "").strip()
        company_source_url = str(company_personnel_source_url or "").strip()
        company_snapshot_id = str(company_personnel_source_snapshot_id or "").strip()
        project_source_url = str(personnel_project_source_url or "").strip()
        project_snapshot_id = str(personnel_project_source_snapshot_id or "").strip()
        personnel_rows = list(rendered_company_personnel_rows or [])
        project_rows_supplied = rendered_personnel_project_rows is not None
        project_rows = list(rendered_personnel_project_rows or [])
        capture_plan = self.build_jzsc_project_manager_company_first_capture_plan(
            target_company_name=company_name,
            target_project_manager_name=manager_name,
            target_identifier=target_identifier,
        )
        fail_closed_reasons: list[str] = []
        if not company_name:
            fail_closed_reasons.append("target_company_name_missing")
        if not manager_name:
            fail_closed_reasons.append("target_project_manager_name_missing")
        if not personnel_rows:
            fail_closed_reasons.append("rendered_personnel_rows_missing")
        if not company_source_url:
            fail_closed_reasons.append("company_personnel_source_url_missing")
        if not company_snapshot_id:
            fail_closed_reasons.append("company_personnel_source_snapshot_missing")
        if project_rows:
            if not project_source_url:
                fail_closed_reasons.append("personnel_project_source_url_missing_for_project_rows")
            if not project_snapshot_id:
                fail_closed_reasons.append("personnel_project_source_snapshot_missing_for_project_rows")

        adapter_base: dict[str, Any] = {
            "adapter_id": "stage4.jzsc_company_first_rendered.v1",
            "route": "JZSC_COMPANY_FIRST_PROJECT_MANAGER",
            "source_family": "national_construction_market_platform",
            "browser_required": True,
            "live_browser_executed": False,
            "rendered_snapshot_input_required": True,
            "target_company_name": company_name,
            "target_project_manager_name": manager_name,
            "target_identifier_optional": target_identifier,
            "capture_plan": capture_plan,
            "rendered_company_personnel_row_count": len(personnel_rows),
            "rendered_personnel_project_row_count": len(project_rows),
            "rendered_personnel_project_rows_supplied": project_rows_supplied,
            "company_personnel_source_url": company_source_url,
            "company_personnel_source_snapshot_id": company_snapshot_id,
            "personnel_project_source_url": project_source_url,
            "personnel_project_source_snapshot_id": project_snapshot_id,
            "fail_closed_reasons": list(dict.fromkeys(fail_closed_reasons)),
            "next_required_runtime_adapter": (
                "browser_rendered_jzsc_company_personnel_and_project_pages"
            ),
        }

        if fail_closed_reasons:
            personnel_carrier: Mapping[str, Any] | None = None
            if company_name and manager_name:
                personnel_carrier = build_jzsc_company_personnel_resolution_carrier(
                    personnel_rows,
                    target_company_name=company_name,
                    target_name=manager_name,
                    target_identifier=target_identifier,
                    source_url=company_source_url,
                    source_snapshot_id=company_snapshot_id,
                    required_registration_category=required_registration_category,
                    required_registration_profession_keywords=required_registration_profession_keywords,
                )
            return {
                **adapter_base,
                "adapter_state": "FAIL_CLOSED",
                "readback_state": "REVIEW_REQUIRED",
                "identity_resolution_state": "NOT_RUN_FAIL_CLOSED",
                "personnel_carrier": dict(personnel_carrier or {}),
                "conflict_records": [],
                "evidence_risk_hard_defect_strategy": {},
                "project_manager_active_conflict": {},
                "project_manager_active_conflict_readback": {},
                "customer_sellable_evidence_ready": False,
                "no_name_only_final_proof": True,
            }

        readback = dict(
            self.build_jzsc_project_manager_company_first_readback(
                parsed_context,
                target_company_name=company_name,
                target_project_manager_name=manager_name,
                rendered_company_personnel_rows=personnel_rows,
                company_personnel_source_url=company_source_url,
                company_personnel_source_snapshot_id=company_snapshot_id,
                rendered_personnel_project_rows=project_rows if project_rows_supplied else None,
                personnel_project_source_url=personnel_project_source_url,
                personnel_project_source_snapshot_id=personnel_project_source_snapshot_id,
                target_identifier=target_identifier,
                required_registration_category=required_registration_category,
                required_registration_profession_keywords=required_registration_profession_keywords,
                base_public_verification_carriers=base_public_verification_carriers,
            )
        )
        personnel_carrier = dict(readback.get("personnel_carrier") or {})
        personnel_result = str(personnel_carrier.get("verification_result") or "")
        identity_state = "MATCHED" if personnel_result == "MATCHED" else "REVIEW_REQUIRED"
        return {
            **adapter_base,
            **readback,
            "adapter_id": adapter_base["adapter_id"],
            "adapter_state": "READBACK_READY",
            "readback_state": "READBACK_READY",
            "identity_resolution_state": identity_state,
            "fail_closed_reasons": list(dict.fromkeys(fail_closed_reasons)),
            "customer_sellable_evidence_ready": False,
            "no_name_only_final_proof": True,
        }

    def run_jzsc_company_first_browser_execution(
        self,
        parsed_context: Mapping[str, Any] | StageBundle,
        *,
        target_company_name: str,
        target_project_manager_name: str,
        target_identifier: str | None = None,
        repository: ObjectStorageRepository | None = None,
        browser_runner: Any | None = None,
        base_public_verification_carriers: list[Mapping[str, Any]] | None = None,
        max_personnel_pages: int = 20,
        max_project_pages: int = 20,
        personnel_retry_attempts: int = 3,
        project_retry_attempts: int = 3,
        capture_personnel_project_records: bool = False,
        required_registration_category: str | None = None,
        required_registration_profession_keywords: list[str] | None = None,
    ) -> Mapping[str, Any]:
        from stage4_verification.jzsc_browser_executor import (
            execute_jzsc_company_first_browser_capture,
        )

        return execute_jzsc_company_first_browser_capture(
            parsed_context,
            target_company_name=target_company_name,
            target_project_manager_name=target_project_manager_name,
            target_identifier=target_identifier,
            repository=repository,
            browser_runner=browser_runner,
            base_public_verification_carriers=base_public_verification_carriers,
            max_personnel_pages=max_personnel_pages,
            max_project_pages=max_project_pages,
            personnel_retry_attempts=personnel_retry_attempts,
            project_retry_attempts=project_retry_attempts,
            capture_personnel_project_records=capture_personnel_project_records,
            required_registration_category=required_registration_category,
            required_registration_profession_keywords=required_registration_profession_keywords,
        )

    def build_stage4_provider_plan(
        self,
        context: Mapping[str, Any] | StageBundle | None = None,
        *,
        opportunity_priority_class: str | None = None,
        candidate_company_name: str | None = None,
        responsible_person_name: str | None = None,
        certificate_no: str | None = None,
        person_public_id: str | None = None,
        requested_provider_ids: list[str] | None = None,
    ) -> Mapping[str, Any]:
        from stage4_verification.provider_registry import build_stage4_provider_plan

        payload = _record_mapping(context) if not isinstance(context, Mapping) else dict(context)
        return build_stage4_provider_plan(
            payload,
            opportunity_priority_class=opportunity_priority_class,
            candidate_company_name=candidate_company_name,
            responsible_person_name=responsible_person_name,
            certificate_no=certificate_no,
            person_public_id=person_public_id,
            requested_provider_ids=requested_provider_ids,
        )

    def enqueue_stage4_provider_plan_jobs(
        self,
        provider_plan: Mapping[str, Any],
        *,
        queue_path: str | None = None,
        max_attempts: int = 3,
    ) -> Mapping[str, Any]:
        from stage4_verification.local_job_queue import (
            Stage4LocalJobQueue,
            enqueue_provider_plan_tasks,
        )

        queue = Stage4LocalJobQueue(queue_path)
        jobs = enqueue_provider_plan_tasks(queue, provider_plan, max_attempts=max_attempts)
        return {
            "queue_path": str(queue.queue_path),
            "enqueued_count": len(jobs),
            "jobs": jobs,
        }

    def run_stage4_local_provider_jobs(
        self,
        *,
        queue_path: str | None = None,
        handlers: Mapping[str, Any] | None = None,
        enable_live_gdcic: bool = False,
        limit: int = 10,
        lease_owner: str = "stage4-local-worker",
        retry_delay_seconds: float = 30.0,
    ) -> Mapping[str, Any]:
        from stage4_verification.local_job_queue import Stage4LocalJobQueue
        from stage4_verification.provider_handlers import build_stage4_provider_handlers

        queue = Stage4LocalJobQueue(queue_path)
        return queue.run_due_jobs(
            handlers or build_stage4_provider_handlers(enable_live_gdcic=enable_live_gdcic),
            limit=limit,
            lease_owner=lease_owner,
            retry_delay_seconds=retry_delay_seconds,
        )

    def build_stage4_provider_handlers(
        self,
        *,
        enable_live_gdcic: bool = False,
    ) -> Mapping[str, Any]:
        from stage4_verification.provider_handlers import build_stage4_provider_handlers

        return build_stage4_provider_handlers(enable_live_gdcic=enable_live_gdcic)

    def extract_stage4_attachment_document(
        self,
        document_path: str,
        *,
        source_url: str,
        detail_page_url: str = "",
        opportunity_priority_class: str | None = None,
        enable_ocr: bool = False,
    ) -> Mapping[str, Any]:
        from stage4_verification.document_extraction import build_attachment_document_evidence

        return build_attachment_document_evidence(
            document_path,
            source_url=source_url,
            detail_page_url=detail_page_url,
            opportunity_priority_class=opportunity_priority_class,
            enable_ocr=enable_ocr,
        )

    def build_jzsc_project_manager_company_first_capture_plan(
        self,
        *,
        target_company_name: str,
        target_project_manager_name: str,
        target_identifier: str | None = None,
        entry_url: str | None = None,
        max_personnel_pages: int = 20,
        max_project_pages: int = 20,
    ) -> Mapping[str, Any]:
        kwargs: dict[str, Any] = {
            "target_company_name": target_company_name,
            "target_project_manager_name": target_project_manager_name,
            "target_identifier": target_identifier,
            "max_personnel_pages": max_personnel_pages,
            "max_project_pages": max_project_pages,
        }
        if entry_url not in (None, ""):
            kwargs["entry_url"] = entry_url
        return build_jzsc_company_first_capture_plan(**kwargs)

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
