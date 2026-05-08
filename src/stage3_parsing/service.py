# Stage: stage3_parsing
# Consumes formal objects: project_base, field_lineage_record, bidder_candidate, project_manager
# Dependent handoff: H-02-STAGE2-TO-STAGE3, H-03-STAGE3-TO-STAGE4
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import ContractStore, ContractRecord, StageBundle
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, get_flag, resolve_bundle
from stage3_parsing.mainline_risk import build_mainline_risk_profile
from stage3_parsing.real_parser import Stage3RealParser
from storage.repositories.object_storage_repo import ObjectStorageRepository


def _carrier_mapping(carrier: Any) -> Mapping[str, Any]:
    if isinstance(carrier, Mapping):
        return carrier
    if isinstance(carrier, ContractRecord):
        return carrier.data
    return {}


class Stage3Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage2_bundle = resolve_bundle(payload)
        inputs = stage2_bundle.inputs or {}
        flags = inputs.get("flags", {})

        public_chain = stage2_bundle.record("public_chain")
        clock_chain_profile = stage2_bundle.record("clock_chain_profile")
        notice_version_chain = stage2_bundle.record("notice_version_chain")
        fixation_bundle = stage2_bundle.record("fixation_bundle")

        handoff_map = stage2_bundle.handoff
        public_chain_map = _carrier_mapping(public_chain)
        clock_chain_map = _carrier_mapping(clock_chain_profile)
        notice_version_map = _carrier_mapping(notice_version_chain)

        project_id = public_chain.get("project_id")

        authority_review_reasons: list[str] = []
        authority_block_reasons: list[str] = []

        def resolve_h02_authority(
            field_name: str,
            carriers: list[tuple[str, Mapping[str, Any]]],
            *,
            missing_is_block: bool = False,
            normalize_list: bool = False,
        ) -> Any:
            values: list[tuple[str, Any, Any]] = []
            handoff_present = False
            for source_name, carrier in carriers:
                if field_name not in carrier:
                    continue
                raw_value = carrier[field_name]
                if raw_value is None or raw_value == "":
                    continue
                if source_name == "handoff":
                    handoff_present = True
                if normalize_list:
                    value = ensure_list(raw_value)
                    normalized = tuple(value)
                else:
                    value = raw_value
                    normalized = raw_value
                values.append((source_name, value, normalized))

            if not handoff_present:
                reason = f"missing_h02_handoff_field:{field_name}"
                if missing_is_block:
                    authority_block_reasons.append(reason)
                else:
                    authority_review_reasons.append(reason)

            if not values:
                reason = f"missing_h02_authority_field:{field_name}"
                if missing_is_block:
                    authority_block_reasons.append(reason)
                else:
                    authority_review_reasons.append(reason)
                return [] if normalize_list else None

            unique_values: list[Any] = []
            for _, _, normalized in values:
                if normalized not in unique_values:
                    unique_values.append(normalized)
            if len(unique_values) > 1:
                reason = f"h02_authority_conflict:{field_name}"
                if missing_is_block:
                    authority_block_reasons.append(reason)
                else:
                    authority_review_reasons.append(reason)

            handoff_value = next((value for source_name, value, _ in values if source_name == "handoff"), None)
            if handoff_value is not None:
                return handoff_value
            return values[0][1]

        def resolve_optional_h02_authority(
            field_name: str,
            carriers: list[tuple[str, Mapping[str, Any]]],
            *,
            normalize_list: bool = False,
        ) -> Any:
            values: list[tuple[str, Any, Any]] = []
            for source_name, carrier in carriers:
                if field_name not in carrier:
                    continue
                raw_value = carrier[field_name]
                if raw_value is None or raw_value == "":
                    continue
                if normalize_list:
                    value = ensure_list(raw_value)
                    normalized = tuple(value)
                else:
                    value = raw_value
                    normalized = raw_value
                values.append((source_name, value, normalized))

            handoff_value = next((value for source_name, value, _ in values if source_name == "handoff"), None)
            if handoff_value is not None:
                return handoff_value
            if values:
                return values[0][1]
            return [] if normalize_list else None

        fixation_bundle_id = fixation_bundle.get("fixation_bundle_id")
        handoff_fixation_bundle_id = handoff_map.get("fixation_bundle_id")
        if handoff_fixation_bundle_id in (None, ""):
            authority_block_reasons.append("missing_h02_handoff_field:fixation_bundle_id")
        if fixation_bundle_id in (None, ""):
            authority_block_reasons.append("missing_h02_authority_field:fixation_bundle_id")
        elif handoff_fixation_bundle_id not in (None, "") and handoff_fixation_bundle_id != fixation_bundle_id:
            authority_block_reasons.append("h02_authority_conflict:fixation_bundle_id")

        source_registry_id = resolve_h02_authority(
            "source_registry_id",
            [
                ("handoff", handoff_map),
                ("public_chain", public_chain_map),
                ("notice_version_chain", notice_version_map),
            ],
        )
        route_policy_id = resolve_h02_authority(
            "route_policy_id",
            [
                ("handoff", handoff_map),
                ("public_chain", public_chain_map),
                ("notice_version_chain", notice_version_map),
            ],
        )
        fallback_route = resolve_optional_h02_authority(
            "fallback_route",
            [
                ("handoff", handoff_map),
                ("public_chain", public_chain_map),
                ("notice_version_chain", notice_version_map),
            ],
        )
        route_decision_state = resolve_h02_authority(
            "route_decision_state",
            [
                ("handoff", handoff_map),
                ("public_chain", public_chain_map),
            ],
        )
        route_review_reasons = resolve_h02_authority(
            "route_review_reasons",
            [
                ("handoff", handoff_map),
                ("public_chain", public_chain_map),
            ],
            normalize_list=True,
        )
        winning_version_resolution_rule_id = resolve_h02_authority(
            "winning_version_resolution_rule_id",
            [
                ("handoff", handoff_map),
                ("notice_version_chain", notice_version_map),
            ],
        )
        version_conflict_state = resolve_h02_authority(
            "version_conflict_state",
            [
                ("handoff", handoff_map),
                ("notice_version_chain", notice_version_map),
            ],
        )
        clock_resolution_rule_id = resolve_h02_authority(
            "clock_resolution_rule_id",
            [
                ("handoff", handoff_map),
                ("clock_chain_profile", clock_chain_map),
            ],
        )
        clock_precedence_rule_id = resolve_h02_authority(
            "clock_precedence_rule_id",
            [
                ("handoff", handoff_map),
            ],
        )
        clock_conflict_state = resolve_h02_authority(
            "clock_conflict_state",
            [
                ("handoff", handoff_map),
                ("clock_chain_profile", clock_chain_map),
            ],
        )
        collection_state = resolve_h02_authority(
            "collection_state",
            [
                ("handoff", handoff_map),
                ("public_chain", public_chain_map),
                ("clock_chain_profile", clock_chain_map),
                ("notice_version_chain", notice_version_map),
            ],
        )
        current_action_start_at_optional = resolve_optional_h02_authority(
            "current_action_start_at_optional",
            [
                ("handoff", handoff_map),
                ("clock_chain_profile", clock_chain_map),
            ],
        )
        current_action_deadline_at_optional = resolve_optional_h02_authority(
            "current_action_deadline_at_optional",
            [
                ("handoff", handoff_map),
                ("clock_chain_profile", clock_chain_map),
            ],
        )

        if version_conflict_state in (None, ""):
            version_conflict_state = "UNRESOLVED"
        if clock_conflict_state in (None, ""):
            clock_conflict_state = "UNRESOLVED"
        if collection_state in (None, ""):
            collection_state = "BLOCKED" if authority_block_reasons else "REVIEW_REQUIRED"

        route_review_reasons = list(
            dict.fromkeys(ensure_list(route_review_reasons) + authority_review_reasons + authority_block_reasons)
        )
        if authority_block_reasons:
            route_decision_state = "BLOCK"
            collection_state = "BLOCKED"
        elif route_review_reasons:
            if route_decision_state in (None, "", "ALLOW"):
                route_decision_state = "REVIEW"
            if collection_state != "BLOCKED":
                collection_state = "REVIEW_REQUIRED"
        elif route_decision_state in (None, ""):
            route_decision_state = "ALLOW"

        conflict_state = "CONFLICTING" if get_flag(flags, "field_conflict") else "CONSISTENT"
        if get_flag(flags, "missing_source"):
            conflict_state = "UNRESOLVED"
        lineage_status = "EXTRACTED" if conflict_state == "CONSISTENT" else "CONFLICTING"
        if conflict_state == "UNRESOLVED":
            lineage_status = "UNVERIFIED"
        stage3_truth_layer_ref = build_id("ST3TL", project_id)
        lineage_collection_ref = build_id("LINEAGE", project_id)
        candidate_collection_ref = build_id("CSET", project_id)
        lineage_conflict_group_id = build_id("LCG", project_id)
        candidate_conflict_group_id = build_id("CCG", project_id)

        trace_rules: list[str] = []
        missing_source = get_flag(flags, "missing_source")
        unresolved_reason_optional: str | None = None
        if missing_source:
            apply_rule(self.store, trace_rules, "STATE-302")
            lineage_status = "UNVERIFIED"
            conflict_state = "UNRESOLVED"
            unresolved_reason_optional = "missing_source_slice_or_normalization_rule"
            if collection_state != "BLOCKED":
                collection_state = "REVIEW_REQUIRED"
        elif (
            conflict_state in ("CONFLICTING", "UNRESOLVED")
            or version_conflict_state != "CONSISTENT"
            or clock_conflict_state != "CONSISTENT"
        ):
            apply_rule(self.store, trace_rules, "STATE-301")
            lineage_status = "CONFLICTING"
            conflict_state = "CONFLICTING"
            if version_conflict_state != "CONSISTENT":
                unresolved_reason_optional = "version_conflict_requires_review"
            elif clock_conflict_state != "CONSISTENT":
                unresolved_reason_optional = "clock_conflict_requires_review"
            else:
                unresolved_reason_optional = "field_conflict_requires_review"
            if collection_state != "BLOCKED":
                collection_state = "REVIEW_REQUIRED"
        else:
            apply_rule(self.store, trace_rules, "STATE-303")
            lineage_status = "NORMALIZED"
            conflict_state = "CONSISTENT"
            if collection_state not in ("BLOCKED", "REVIEW_REQUIRED"):
                collection_state = "NORMALIZED"

        if authority_block_reasons and conflict_state == "CONSISTENT":
            lineage_status = "UNVERIFIED"
            conflict_state = "UNRESOLVED"
            unresolved_reason_optional = unresolved_reason_optional or "field_conflict_requires_review"
        elif authority_review_reasons and conflict_state == "CONSISTENT":
            lineage_status = "CONFLICTING"
            conflict_state = "CONFLICTING"
            unresolved_reason_optional = unresolved_reason_optional or "field_conflict_requires_review"

        stage3_review_path_ref = (
            "STAGE3_READY_FOR_STAGE4"
            if lineage_status == "NORMALIZED"
            and conflict_state == "CONSISTENT"
            and route_decision_state == "ALLOW"
            and collection_state == "NORMALIZED"
            else "STAGE3_REVIEW_REQUIRED"
        )

        if route_decision_state == "BLOCK" or collection_state == "BLOCKED":
            derived_public_chain_status = "BROKEN"
        elif (
            route_decision_state == "REVIEW"
            or collection_state == "REVIEW_REQUIRED"
            or version_conflict_state != "CONSISTENT"
            or clock_conflict_state != "CONSISTENT"
        ):
            derived_public_chain_status = "PARTIAL"
        else:
            derived_public_chain_status = "COMPLETE"

        candidate_order_mode = ensure_enum(self.store, "candidate_order_mode", inputs.get("candidate_order_mode"))
        candidate_collection_role = (
            "ORDERED_PRIMARY_CANDIDATE"
            if candidate_order_mode == "ORDERED"
            else "CANDIDATE_COLLECTION_MEMBER"
        )

        field_lineage_payload = {
            "field_lineage_id": build_id("FL", project_id),
            "project_id": project_id,
            "owning_object_type": inputs.get("owning_object_type", "project_base"),
            "owning_object_id": inputs.get("owning_object_id", project_id),
            "field_name": inputs.get("field_name", "project_name"),
            "source_notice_version_id": notice_version_chain.get("current_notice_version_id"),
            "source_document_ref": inputs.get("source_document_ref", "DOC-001"),
            "source_slice_ref": inputs.get("source_slice_ref", "SLICE-001"),
            "source_family": public_chain.get("source_family"),
            "platform_level": public_chain.get("platform_level"),
            "carrier_type": fixation_bundle.get("carrier_type"),
            "coverage_tier": public_chain.get("coverage_tier"),
            "parser_confidence_score": inputs.get("parser_confidence_score", 0.92),
            "normalization_rule_id": inputs.get("normalization_rule_id", "NR-DEFAULT"),
            "lineage_status": lineage_status,
            "conflict_state": conflict_state,
            "collection_state": collection_state,
            "normalized_value_ref_optional": "project_base.project_name",
            "review_path_optional": stage3_review_path_ref,
            "candidate_collection_ref_optional": candidate_collection_ref,
        }
        if unresolved_reason_optional:
            field_lineage_payload["unresolved_reason_optional"] = unresolved_reason_optional
        if conflict_state != "CONSISTENT":
            field_lineage_payload["lineage_conflict_group_id_optional"] = lineage_conflict_group_id
        updated_lineage = self.store.build_record("field_lineage_record", field_lineage_payload)

        project_base = self.store.build_record(
            "project_base",
            {
                "project_id": project_id,
                "project_root_id": inputs.get("project_root_id", build_id("ROOT", project_id)),
                "notice_version_id": notice_version_chain.get("current_notice_version_id"),
                "project_name": inputs.get("project_name", "UNKNOWN_PROJECT"),
                "region_code": inputs.get("region_code", "CN"),
                "source_family": public_chain.get("source_family"),
                "procurement_regime": ensure_enum(self.store, "procurement_regime", inputs.get("procurement_regime")),
                "procurement_category": inputs.get("procurement_category", "GENERAL"),
                "bid_eval_method": inputs.get("bid_eval_method", "STANDARD"),
                "candidate_order_mode": candidate_order_mode,
                "award_determination_mode": ensure_enum(self.store, "award_determination_mode", inputs.get("award_determination_mode")),
                "public_chain_status": ensure_enum(self.store, "public_chain_status", derived_public_chain_status),
                "stage3_truth_layer_ref_optional": stage3_truth_layer_ref,
                "field_lineage_collection_ref_optional": lineage_collection_ref,
                "bidder_candidate_collection_ref_optional": candidate_collection_ref,
                "stage3_review_path_ref_optional": stage3_review_path_ref,
            },
        )

        bidder_candidate_payload = {
            "bidder_candidate_id": build_id("BID", project_id, "01"),
            "project_id": project_id,
            "bidder_name": inputs.get("bidder_name", "DEFAULT_BIDDER"),
            "candidate_group_label": ensure_enum(self.store, "candidate_group_label", inputs.get("candidate_group_label")),
            "candidate_rank_optional": inputs.get("candidate_rank_optional", 1),
            "bid_price": inputs.get("bid_price", 1000000.0),
            "total_score": inputs.get("total_score", 90.0),
            "is_invalid": bool(inputs.get("bidder_invalid", False)),
            "candidate_collection_ref_optional": candidate_collection_ref,
            "candidate_collection_role_optional": candidate_collection_role,
            "candidate_source_lineage_ids_optional": [updated_lineage.get("field_lineage_id")],
        }
        if conflict_state != "CONSISTENT":
            bidder_candidate_payload["candidate_conflict_group_id_optional"] = candidate_conflict_group_id
            bidder_candidate_payload["candidate_review_path_optional"] = stage3_review_path_ref
        bidder_candidate = self.store.build_record("bidder_candidate", bidder_candidate_payload)

        project_manager_name = str(
            inputs.get("project_manager_name")
            or inputs.get("primary_responsible_person_name")
            or ""
        )
        project_manager_field_source_state = (
            "FIELD_EXTRACTED"
            if project_manager_name
            else "MISSING_REVIEW_REQUIRED"
        )
        project_manager_missing_review_reasons = []
        if not project_manager_name:
            project_manager_missing_review_reasons.append(
                "project_manager_name_missing_from_stage3_inputs"
            )

        project_manager = self.store.build_record(
            "project_manager",
            {
                "project_manager_id": build_id("PM", project_id),
                "project_id": project_id,
                "project_manager_name": project_manager_name or "REVIEW_REQUIRED",
                "project_manager_cert_specialty": str(
                    inputs.get("project_manager_cert_specialty") or "REVIEW_REQUIRED"
                ),
                "project_manager_cert_level": str(
                    inputs.get("project_manager_cert_level") or "REVIEW_REQUIRED"
                ),
                "project_manager_cert_unit": str(
                    inputs.get("project_manager_cert_unit") or "REVIEW_REQUIRED"
                ),
                "project_manager_conflict_clue_status": ensure_enum(
                    self.store,
                    "project_manager_conflict_clue_status",
                    inputs.get("project_manager_conflict_clue_status"),
                ),
            },
        )

        handoff = {
            "project_id": project_id,
            "project_root_id": project_base.get("project_root_id"),
            "notice_version_id": project_base.get("notice_version_id"),
            "candidate_order_mode": project_base.get("candidate_order_mode"),
            "award_determination_mode": project_base.get("award_determination_mode"),
            "public_chain_status": project_base.get("public_chain_status"),
            "lineage_status": lineage_status,
            "conflict_state": conflict_state,
            "fixation_bundle_id": fixation_bundle.get("fixation_bundle_id"),
            "source_registry_id": source_registry_id,
            "route_policy_id": route_policy_id,
            "fallback_route": fallback_route,
            "route_decision_state": route_decision_state,
            "route_review_reasons": route_review_reasons,
            "winning_version_resolution_rule_id": winning_version_resolution_rule_id,
            "clock_resolution_rule_id": clock_resolution_rule_id,
            "clock_precedence_rule_id": clock_precedence_rule_id,
            "collection_state": collection_state,
            "stage3_truth_layer_ref_optional": stage3_truth_layer_ref,
            "field_lineage_collection_ref_optional": lineage_collection_ref,
            "bidder_candidate_collection_ref_optional": candidate_collection_ref,
            "candidate_collection_ref_optional": candidate_collection_ref,
            "stage3_review_path_ref_optional": stage3_review_path_ref,
            "version_conflict_state": version_conflict_state,
            "clock_conflict_state": clock_conflict_state,
        }
        if current_action_start_at_optional is not None:
            handoff["current_action_start_at_optional"] = current_action_start_at_optional
        if current_action_deadline_at_optional is not None:
            handoff["current_action_deadline_at_optional"] = current_action_deadline_at_optional
        if unresolved_reason_optional:
            handoff["unresolved_reason_optional"] = unresolved_reason_optional

        inputs_out = dict(inputs)
        inputs_out["lineage_status"] = lineage_status
        inputs_out["conflict_state"] = conflict_state
        inputs_out["version_conflict_state"] = version_conflict_state
        inputs_out["clock_conflict_state"] = clock_conflict_state
        inputs_out["collection_state"] = collection_state
        inputs_out["fixation_bundle_id"] = fixation_bundle_id
        inputs_out["source_registry_id"] = source_registry_id
        inputs_out["route_policy_id"] = route_policy_id
        inputs_out["fallback_route"] = fallback_route
        inputs_out["route_decision_state"] = route_decision_state
        inputs_out["route_review_reasons"] = route_review_reasons
        inputs_out["winning_version_resolution_rule_id"] = winning_version_resolution_rule_id
        inputs_out["clock_resolution_rule_id"] = clock_resolution_rule_id
        inputs_out["clock_precedence_rule_id"] = clock_precedence_rule_id
        inputs_out["stage3_truth_layer_ref_optional"] = stage3_truth_layer_ref
        inputs_out["field_lineage_collection_ref_optional"] = lineage_collection_ref
        inputs_out["bidder_candidate_collection_ref_optional"] = candidate_collection_ref
        inputs_out["candidate_collection_ref_optional"] = candidate_collection_ref
        inputs_out["stage3_review_path_ref_optional"] = stage3_review_path_ref
        inputs_out["project_manager_field_source_state"] = project_manager_field_source_state
        inputs_out["project_manager_missing_review_reasons"] = project_manager_missing_review_reasons
        if current_action_start_at_optional is not None:
            inputs_out["current_action_start_at_optional"] = current_action_start_at_optional
        if current_action_deadline_at_optional is not None:
            inputs_out["current_action_deadline_at_optional"] = current_action_deadline_at_optional
        if unresolved_reason_optional:
            inputs_out["unresolved_reason_optional"] = unresolved_reason_optional
        mainline_risk_profile = build_mainline_risk_profile(inputs_out)
        inputs_out["mainline_risk_profile"] = mainline_risk_profile
        for field_name in (
            "bid_selection_score",
            "bid_selection_state",
            "blind_bid_pipeline_stage",
            "evaluation_method_profile",
            "tailored_bid_risk_level",
            "qualification_clause_hits",
            "fatal_rejection_risk_hits",
            "price_performance_risk_profile",
            "payment_risk_level",
            "abnormally_low_bid_explanation_required",
            "abnormal_low_price_trigger",
            "unbalanced_bid_risk_hits",
            "cost_breakdown_ready",
            "low_price_review_record",
            "self_score_forecast",
        ):
            inputs_out[field_name] = mainline_risk_profile.get(field_name)

        return StageBundle(
            stage=3,
            records={
                "field_lineage_record": updated_lineage,
                "project_base": project_base,
                "bidder_candidate": bidder_candidate,
                "project_manager": project_manager,
            },
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff

    def parse_raw_snapshot(
        self,
        snapshot_id: str,
        *,
        repository: ObjectStorageRepository | None = None,
    ) -> Mapping[str, Any]:
        return Stage3RealParser(repository=repository).parse_snapshot(snapshot_id)

    def parse_raw_snapshot_readback(self, readback: Mapping[str, Any]) -> Mapping[str, Any]:
        return Stage3RealParser().parse_readback(readback)
