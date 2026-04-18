# Stage: stage7_sales
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/sales/challenger_profile_catalog.json, contracts/sales/buyer_fit_scorecard.json, contracts/sales/opportunity_policy_catalog.json, contracts/sales/stage7_resolution_policy.json

from __future__ import annotations

from typing import Any, Mapping

from stage7_sales.resolution import resolve_actor_seed
from shared.capability_runtime import CapabilityRuntime
from shared.context_packet import ContextPacket
from shared.contracts_runtime import ContractStore, StageBundle
from shared.state_packet import StatePacket
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, get_flag, resolve_bundle, utc_now_iso


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return float(value)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


class Stage7Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)
        self.runtime = CapabilityRuntime(settings)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage6_bundle = resolve_bundle(payload)
        handoff_validation = self.store.evaluate_handoff_consumer(
            producer_bundle=stage6_bundle,
            consumer_stage=7,
        )
        if handoff_validation and handoff_validation.decision_state == "BLOCK":
            raise ValueError(f"{handoff_validation.semantic_scope} blocked: {handoff_validation.reasons}")
        inputs = stage6_bundle.inputs or {}
        flags = inputs.get("flags", {})
        now = inputs.get("now") or utc_now_iso()

        project_fact = stage6_bundle.record("project_fact")
        legal_action_recommendation = stage6_bundle.record("legal_action_recommendation")
        challenger_candidate_profile = stage6_bundle.record("challenger_candidate_profile")
        report_record = stage6_bundle.record("report_record")
        project_id = project_fact.get("project_id")
        stage6_handoff = stage6_bundle.handoff or {}

        sale_gate_status = stage6_handoff.get("sale_gate_status", project_fact.get("sale_gate_status"))
        competitor_quality_grade = stage6_handoff.get(
            "competitor_quality_grade",
            project_fact.get("competitor_quality_grade"),
        )
        window_status = stage6_handoff.get(
            "window_status",
            legal_action_recommendation.get("window_status"),
        )
        report_status = stage6_handoff.get("report_status", report_record.get("report_status"))
        review_task_status = stage6_handoff.get(
            "review_task_status",
            report_record.get("review_task_status"),
        )
        action_family = stage6_handoff.get(
            "action_family",
            legal_action_recommendation.get("action_family"),
        )
        challenger_profile_id = stage6_handoff.get(
            "challenger_profile_id",
            challenger_candidate_profile.get("challenger_profile_id"),
        )
        focus_bidder_id = stage6_handoff.get(
            "focus_bidder_id",
            challenger_candidate_profile.get("focus_bidder_id"),
        )
        challenger_bidder_id = stage6_handoff.get(
            "challenger_bidder_id",
            challenger_candidate_profile.get("challenger_bidder_id"),
        )
        challenge_actionability_score = int(
            stage6_handoff.get(
                "challenge_actionability_score",
                challenger_candidate_profile.get("challenge_actionability_score"),
            )
        )
        execution_readiness_score = int(
            stage6_handoff.get(
                "execution_readiness_score",
                challenger_candidate_profile.get("execution_readiness_score"),
            )
        )
        legal_actor_seed = resolve_actor_seed(
            settings=self.settings,
            policy_id="legal_action_actor_seed_resolution_v1",
            stage6_handoff=stage6_handoff,
            inputs=inputs,
            project_id=project_id,
            challenger_bidder_id=challenger_bidder_id,
        )
        procurement_actor_seed = resolve_actor_seed(
            settings=self.settings,
            policy_id="procurement_decision_actor_seed_resolution_v1",
            stage6_handoff=stage6_handoff,
            inputs=inputs,
            project_id=project_id,
            challenger_bidder_id=challenger_bidder_id,
        )
        legal_action_actor_org_name_seed = legal_actor_seed["value"]
        procurement_decision_actor_org_name_seed = procurement_actor_seed["value"]
        buyer_type_hint = stage6_handoff.get("buyer_type_hint", inputs.get("buyer_type"))
        project_value_score_seed = stage6_handoff.get(
            "project_value_score_optional",
            project_fact.get("project_value_score_optional", inputs.get("project_value_score_optional")),
        )
        normalized_price_amount_seed = stage6_handoff.get(
            "normalized_price_amount_optional",
            inputs.get("normalized_price_amount_optional"),
        )
        price_conflict_gate_status_seed = stage6_handoff.get(
            "price_conflict_gate_status_optional",
            inputs.get("price_conflict_gate_status_optional"),
        )
        confidence_score_seed = stage6_handoff.get(
            "confidence_score_optional",
            challenger_candidate_profile.get("confidence_score_optional", inputs.get("confidence_score_optional")),
        )
        candidate_position_label = stage6_handoff.get(
            "candidate_position_label",
            challenger_candidate_profile.get("candidate_position_label"),
        )
        current_action_start_at_optional = _optional_str(
            stage6_handoff.get(
                "current_action_start_at_optional",
                inputs.get("current_action_start_at_optional"),
            )
        )
        current_action_deadline_at_optional = _optional_str(
            stage6_handoff.get(
                "current_action_deadline_at_optional",
                inputs.get("current_action_deadline_at_optional", inputs.get("current_action_deadline_optional")),
            )
        )

        trace_rules: list[str] = []
        semantic_state = StatePacket(capability_mode="stage7_sales")

        offer_state = "DRAFT"
        if get_flag(flags, "offer_review"):
            apply_rule(self.store, trace_rules, "SALE-003")
            offer_state = "REVIEW_REQUIRED"
        elif sale_gate_status == "BLOCK":
            offer_state = "BLOCKED"
        elif sale_gate_status in ("REVIEW", "HOLD"):
            offer_state = "REVIEW_REQUIRED"
        else:
            offer_state = "APPROVED"

        runtime_context = ContextPacket.from_records(
            capability_mode="stage7_sales",
            stage=7,
            project_id=project_id,
            records={
                "project_fact": project_fact,
                "legal_action_recommendation": legal_action_recommendation,
                "challenger_candidate_profile": challenger_candidate_profile,
                "report_record": report_record,
            },
            inputs={
                **dict(inputs),
                "now": now,
                "sale_gate_status": sale_gate_status,
                "competitor_quality_grade": competitor_quality_grade,
                "window_status": window_status,
                "report_status": report_status,
                "review_task_status": review_task_status,
                "focus_bidder_id": focus_bidder_id,
                "challenger_bidder_id": challenger_bidder_id,
                "challenger_profile_id": challenger_profile_id,
                "candidate_position_label": candidate_position_label,
                "buyer_type_hint": buyer_type_hint,
                "challenge_actionability_score": challenge_actionability_score,
                "execution_readiness_score": execution_readiness_score,
                "real_competitor_count": int(
                    stage6_handoff.get("real_competitor_count", project_fact.get("real_competitor_count", 0))
                ),
                "project_value_score_optional": project_value_score_seed,
                "normalized_price_amount_optional": normalized_price_amount_seed,
                "price_conflict_gate_status_optional": price_conflict_gate_status_seed,
                "confidence_score_optional": confidence_score_seed,
                "current_action_start_at_optional": current_action_start_at_optional,
                "current_action_deadline_at_optional": current_action_deadline_at_optional,
            },
        )
        runtime_state = self.runtime.run(runtime_context)
        def required_runtime_value(field_name: str) -> Any:
            value = runtime_state.resolve(field_name)
            if value is None:
                raise ValueError(f"Stage7 formal policy derivation missing {field_name}")
            return value

        multi_competitor_candidates = ensure_list(required_runtime_value("multi_competitor_candidates"))
        top_n_competitor_ids = ensure_list(required_runtime_value("top_n_candidate_ids"))
        winning_competitor_candidate = dict(required_runtime_value("winning_competitor_candidate"))
        competitor_selection_trace = dict(required_runtime_value("competitor_selection_trace"))
        competitor_trace_summary = dict(required_runtime_value("competitor_trace_summary"))
        challenger_profile_id = winning_competitor_candidate.get("challenger_profile_id", challenger_profile_id)
        focus_bidder_id = winning_competitor_candidate.get("focus_bidder_id", focus_bidder_id)
        challenger_bidder_id = winning_competitor_candidate.get("challenger_bidder_id", challenger_bidder_id)
        candidate_position_label = winning_competitor_candidate.get("candidate_position_label", candidate_position_label)
        challenge_actionability_score = int(
            winning_competitor_candidate.get("challenge_actionability_score", challenge_actionability_score)
        )
        execution_readiness_score = int(
            winning_competitor_candidate.get("execution_readiness_score", execution_readiness_score)
        )
        confidence_score_seed = winning_competitor_candidate.get("confidence_score_optional", confidence_score_seed)
        project_value_score_optional = _optional_int(required_runtime_value("project_value_score"))
        opportunity_value_score_optional = _optional_int(required_runtime_value("opportunity_value_score"))
        normalized_price_amount_optional = _optional_number(
            runtime_state.resolve("normalized_price_amount", normalized_price_amount_seed)
        )
        price_conflict_gate_status_optional = _optional_str(
            runtime_state.resolve("price_conflict_gate_status", price_conflict_gate_status_seed)
        )
        confidence_score_optional = _optional_int(
            runtime_state.resolve("competitor_confidence_score", confidence_score_seed)
        )
        buyer_fit_runtime_score = int(required_runtime_value("buyer_fit_scorecard_score"))
        buyer_fit_purchase_intent_score = int(required_runtime_value("buyer_fit_purchase_intent_score"))
        buyer_fit_payment_capacity_score = int(required_runtime_value("buyer_fit_payment_capacity_score"))
        buyer_fit_window_urgency_score = int(required_runtime_value("buyer_fit_window_urgency_score"))
        buyer_fit_attack_motivation_score = int(required_runtime_value("buyer_fit_attack_motivation_score"))
        challenger_buyer_fit_runtime_score = int(required_runtime_value("challenger_buyer_fit_scorecard_score"))
        buyer_fit_reason_tags = ensure_list(required_runtime_value("buyer_fit_reason_tags"))
        challenger_buyer_fit_reason_tags = ensure_list(required_runtime_value("challenger_buyer_fit_reason_tags"))
        lead_value_reason_tags = ensure_list(required_runtime_value("lead_value_reason_tags"))
        opportunity_value_reason_tags = ensure_list(required_runtime_value("opportunity_value_reason_tags"))

        lead_status = "QUALIFIED"
        if sale_gate_status == "BLOCK" or runtime_state.decision_state == "BLOCK":
            apply_rule(self.store, trace_rules, "SALE-001")
            lead_status = "DISQUALIFIED"
        elif (
            get_flag(flags, "sale_review")
            or sale_gate_status in ("REVIEW", "HOLD")
            or report_status != "ISSUED"
        ):
            apply_rule(self.store, trace_rules, "SALE-001")
            lead_status = "REVIEW"

        lead_score = int(required_runtime_value("lead_score"))
        sales_lead_payload = {
            "lead_id": build_id("LEAD", project_id),
            "project_id": project_id,
            "lead_reason_summary": ";".join(lead_value_reason_tags),
            "lead_score": lead_score,
            "lead_status": lead_status,
            "generated_at": now,
        }
        sales_lead_semantic = self.store.evaluate_object_semantics(
            stage=7,
            object_type="sales_lead",
            payload=sales_lead_payload,
            semantic_context={
                "sale_gate_status": sale_gate_status,
                "report_status": report_status,
            },
        )
        if sales_lead_semantic:
            semantic_state.add_semantic_validation(sales_lead_semantic)
            if sales_lead_semantic.decision_state == "BLOCK":
                sales_lead_payload["lead_status"] = "DISQUALIFIED"
        sales_lead = self.store.build_record("sales_lead", sales_lead_payload)

        saleability_status = "QUALIFIED"
        if get_flag(flags, "sale_blocked") or sale_gate_status == "BLOCK" or runtime_state.decision_state == "BLOCK":
            apply_rule(self.store, trace_rules, "SALE-002")
            saleability_status = "BLOCKED"
        elif sale_gate_status in ("REVIEW", "HOLD") or report_status != "ISSUED" or runtime_state.resolve("offer_recommendation_state", offer_state) == "REVIEW_REQUIRED":
            apply_rule(self.store, trace_rules, "SALE-002")
            saleability_status = "RESTRICTED"

        action_window_state = "UNKNOWN"
        runtime_window_status = runtime_state.resolve("window_status", window_status)
        if runtime_window_status == "ACTIONABLE":
            action_window_state = "WITHIN_WINDOW"
        elif runtime_window_status in ("MISSED", "CLOSED"):
            action_window_state = "OUT_OF_WINDOW"

        legal_actor_payload = {
            "actor_id": build_id("ACTOR", project_id, "LEGAL"),
            "project_id": project_id,
            "actor_org_name": legal_action_actor_org_name_seed,
            "actor_role_cluster": "LEGAL_ACTION",
            "standing_state": (
                "HAS_STANDING" if lead_status == "QUALIFIED" else "LIMITED_STANDING"
            ),
            "action_window_state": action_window_state,
            "actionability_state": (
                "ACTIONABLE"
                if lead_status == "QUALIFIED" and offer_state == "APPROVED"
                else "REVIEW_REQUIRED"
                if lead_status == "REVIEW"
                else "BLOCKED"
            ),
            "action_family_scope": action_family,
        }
        legal_actor_semantic = self.store.evaluate_object_semantics(
            stage=7,
            object_type="legal_action_actor_profile",
            payload=legal_actor_payload,
            semantic_context={
                "saleability_status": saleability_status,
            },
        )
        if legal_actor_semantic:
            semantic_state.add_semantic_validation(legal_actor_semantic)
            if legal_actor_semantic.decision_state == "BLOCK":
                legal_actor_payload["actionability_state"] = "BLOCKED"
        legal_action_actor_profile = self.store.build_record("legal_action_actor_profile", legal_actor_payload)

        procurement_actor_payload = {
            "actor_id": build_id("ACTOR", project_id, "PROC"),
            "project_id": project_id,
            "actor_org_name": procurement_decision_actor_org_name_seed,
            "actor_role_cluster": "PROCUREMENT_DECISION",
            "procurement_authority_state": (
                "FULL_AUTHORITY" if lead_status == "QUALIFIED" else "LIMITED_AUTHORITY"
            ),
            "purchase_authority_state": (
                "FULL_AUTHORITY" if offer_state == "APPROVED" else "LIMITED_AUTHORITY"
            ),
            "payment_authority_state": (
                "FULL_AUTHORITY" if saleability_status != "BLOCKED" else "NO_AUTHORITY"
            ),
            "reachable_state": "REACHABLE" if lead_status != "DISQUALIFIED" else "UNREACHABLE",
        }
        procurement_actor_semantic = self.store.evaluate_object_semantics(
            stage=7,
            object_type="procurement_decision_actor_profile",
            payload=procurement_actor_payload,
            semantic_context={
                "saleability_status": saleability_status,
            },
        )
        if procurement_actor_semantic:
            semantic_state.add_semantic_validation(procurement_actor_semantic)
            if procurement_actor_semantic.decision_state == "BLOCK":
                procurement_actor_payload["payment_authority_state"] = "NO_AUTHORITY"
        procurement_decision_actor_profile = self.store.build_record("procurement_decision_actor_profile", procurement_actor_payload)

        buyer_fit = self.store.build_record(
            "buyer_fit",
            {
                "buyer_fit_id": build_id("BF", project_id),
                "project_id": project_id,
                "buyer_type": ensure_enum(self.store, "buyer_type", buyer_type_hint),
                "fit_score": buyer_fit_runtime_score,
                "attack_motivation_score": buyer_fit_attack_motivation_score,
                "purchase_intent_score": buyer_fit_purchase_intent_score,
                "payment_capacity_score": buyer_fit_payment_capacity_score,
                "window_urgency_score": buyer_fit_window_urgency_score,
                "fit_reason_tags": buyer_fit_reason_tags,
            },
        )

        challenger_buyer_fit = self.store.build_record(
            "challenger_buyer_fit",
            {
                "challenger_buyer_fit_id": build_id("CBF", project_id),
                "project_id": project_id,
                "buyer_type": buyer_fit.get("buyer_type"),
                "fit_score": challenger_buyer_fit_runtime_score,
                "attack_motivation_score": challenge_actionability_score,
                "purchase_intent_score": buyer_fit_purchase_intent_score,
                "payment_capacity_score": buyer_fit_payment_capacity_score,
                "window_urgency_score": buyer_fit_window_urgency_score,
                "fit_reason_tags": challenger_buyer_fit_reason_tags,
            },
        )

        offer_state = runtime_state.resolve("offer_recommendation_state", offer_state)
        offer_recommendation_payload = {
            "offer_recommendation_id": build_id("OFFER", project_id),
            "project_id": project_id,
            "offer_recommendation_state": offer_state,
            "sku_code": ensure_enum(
                self.store,
                "sku_code",
                runtime_state.resolve("sku_code", inputs.get("sku_code")),
            ),
            "recommended_delivery_form": ensure_enum(
                self.store,
                "recommended_delivery_form",
                runtime_state.resolve("recommended_delivery_form", inputs.get("recommended_delivery_form")),
            ),
            "recommended_quote_band": ensure_enum(
                self.store,
                "recommended_quote_band",
                runtime_state.resolve("recommended_quote_band", inputs.get("recommended_quote_band")),
            ),
            "why_recommended": required_runtime_value("why_recommended"),
            "prerequisites": ensure_list(
                inputs.get(
                    "prerequisites",
                    [
                        f"report_status={report_status}",
                        f"review_task_status={review_task_status}",
                        f"legal_action={action_family}",
                    ],
                )
            ),
        }
        offer_semantic = self.store.evaluate_object_semantics(
            stage=7,
            object_type="offer_recommendation",
            payload=offer_recommendation_payload,
            semantic_context={
                "saleability_status": saleability_status,
                "report_status": report_status,
            },
        )
        if offer_semantic:
            semantic_state.add_semantic_validation(offer_semantic)
            if offer_semantic.decision_state == "BLOCK":
                offer_recommendation_payload["offer_recommendation_state"] = "BLOCKED"
            elif offer_semantic.decision_state == "REVIEW" and offer_recommendation_payload["offer_recommendation_state"] == "APPROVED":
                offer_recommendation_payload["offer_recommendation_state"] = "REVIEW_REQUIRED"
        offer_recommendation = self.store.build_record("offer_recommendation", offer_recommendation_payload)

        opportunity_payload = {
            "opportunity_id": build_id("OPP", project_id),
            "project_id": project_id,
            "recommended_sku": offer_recommendation.get("sku_code"),
            "buyer_fit_id": buyer_fit.get("buyer_fit_id"),
            "challenger_profile_id": challenger_profile_id,
            "opportunity_grade": ensure_enum(
                self.store,
                "opportunity_grade",
                runtime_state.resolve("opportunity_grade", inputs.get("opportunity_grade")),
            ),
            "saleability_status": saleability_status,
            "major_value_points": opportunity_value_reason_tags,
            "blocking_reasons": ensure_list(
                inputs.get(
                    "blocking_reasons",
                    [] if saleability_status == "QUALIFIED" else runtime_state.resolve("offer_blocking_reasons_optional", ["stage7_review_required"]),
                )
            ),
            "expected_close_days_band": required_runtime_value("expected_close_days_band"),
            "expected_contract_value_band": inputs.get(
                "expected_contract_value_band",
                runtime_state.resolve("price_band", "UNKNOWN"),
            ),
            "expected_delivery_cost_band": required_runtime_value("expected_delivery_cost_band"),
            "crm_owner_state": ensure_enum(
                self.store,
                "crm_owner_state",
                inputs.get(
                    "crm_owner_state",
                    "UNASSIGNED",
                ),
            ),
            "opportunity_value_score_optional": opportunity_value_score_optional,
        }
        opportunity_semantic = self.store.evaluate_object_semantics(
            stage=7,
            object_type="saleable_opportunity",
            payload=opportunity_payload,
            semantic_context={
                "project_fact_present": True,
                "challenger_profile_present": bool(challenger_profile_id),
                "sale_gate_status": sale_gate_status,
                "report_status": report_status,
            },
        )
        if opportunity_semantic:
            semantic_state.add_semantic_validation(opportunity_semantic)
            if opportunity_semantic.decision_state == "BLOCK":
                opportunity_payload["saleability_status"] = "BLOCKED"
                opportunity_payload["blocking_reasons"] = ensure_list(opportunity_payload["blocking_reasons"]) + opportunity_semantic.reasons
            elif opportunity_semantic.decision_state == "REVIEW" and opportunity_payload["saleability_status"] == "QUALIFIED":
                opportunity_payload["saleability_status"] = "RESTRICTED"
        saleable_opportunity = self.store.build_record("saleable_opportunity", opportunity_payload)
        multi_competitor_collection = self.store.build_record(
            "multi_competitor_collection",
            {
                "multi_competitor_collection_id": build_id("MCOMP", project_id),
                "project_id": project_id,
                "opportunity_id": saleable_opportunity.get("opportunity_id"),
                "candidate_list": multi_competitor_candidates,
                "top_n_candidate_ids": top_n_competitor_ids,
                "winning_candidate_id": winning_competitor_candidate.get("candidate_id"),
                "winning_challenger_profile_id": challenger_profile_id,
                "selection_trace": competitor_selection_trace,
                "created_by_stage": 7,
                "downstream_consumer": [
                    "saleable_opportunity",
                    "contact_candidate_collection",
                    "contact_selection_trace",
                    "contact_target",
                ],
            },
        )

        handoff = {
            "project_id": project_id,
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "source_family": inputs.get("source_family", "PROCUREMENT_NOTICE"),
            "channel_family": ensure_enum(self.store, "channel_family", inputs.get("channel_family")),
            "channel_policy_status": ensure_enum(
                self.store, "channel_policy_status", inputs.get("channel_policy_status", "REVIEW")
            ),
            "contact_validity_status": ensure_enum(
                self.store, "contact_validity_status", inputs.get("contact_validity_status", "UNKNOWN")
            ),
            "contact_legal_basis": ensure_enum(
                self.store, "contact_legal_basis", inputs.get("contact_legal_basis", "REVIEW_REQUIRED")
            ),
            "reasonable_expectation_status": ensure_enum(
                self.store, "reasonable_expectation_status", inputs.get("reasonable_expectation_status", "UNKNOWN")
            ),
            "frequency_policy_state": ensure_enum(
                self.store, "frequency_policy_state", inputs.get("frequency_policy_state", "REVIEW")
            ),
            "opt_out_state": ensure_enum(
                self.store, "opt_out_state", inputs.get("opt_out_state", "PENDING_CONFIRMATION")
            ),
            "quiet_hours_policy_state": ensure_enum(
                self.store, "quiet_hours_policy_state", inputs.get("quiet_hours_policy_state", "REVIEW")
            ),
            "commercial_urgency_level_optional": inputs.get(
                "commercial_urgency_level_optional",
                "CRITICAL" if runtime_state.resolve("window_urgency_score", 0) >= 90 else "HIGH" if runtime_state.resolve("window_urgency_score", 0) >= 80 else "NORMAL",
            ),
            "role_cluster": procurement_decision_actor_profile.get("actor_role_cluster"),
            "multi_competitor_collection_id_optional": multi_competitor_collection.get("multi_competitor_collection_id"),
            "winning_competitor_candidate_id_optional": multi_competitor_collection.get("winning_candidate_id"),
            "winning_challenger_profile_id_optional": multi_competitor_collection.get("winning_challenger_profile_id"),
            "policy_trace": runtime_state.trace,
            "policy_decision_state": runtime_state.decision_state,
            "project_value_score_optional": project_value_score_optional,
            "opportunity_value_score_optional": opportunity_value_score_optional,
            "normalized_price_amount_optional": normalized_price_amount_optional,
            "price_conflict_gate_status_optional": price_conflict_gate_status_optional,
            "confidence_score_optional": confidence_score_optional,
            "current_action_start_at_optional": current_action_start_at_optional,
            "current_action_deadline_at_optional": current_action_deadline_at_optional,
        }

        inputs_out = dict(inputs)
        inputs_out["policy_trace"] = runtime_state.trace
        inputs_out["policy_decision_state"] = runtime_state.decision_state
        inputs_out["stage7_resolution_trace"] = {
            "actor_seed_provenance": {
                "legal_action_actor_org_name": legal_actor_seed,
                "procurement_decision_actor_org_name": procurement_actor_seed,
            },
            "buyer_fit_scorecard": {
                "buyer_fit_scorecard_id": runtime_state.resolve("buyer_fit_scorecard_id"),
                "buyer_fit_scorecard_score": runtime_state.resolve("buyer_fit_scorecard_score"),
                "buyer_fit_scorecard_grade": runtime_state.resolve("buyer_fit_scorecard_grade"),
                "challenger_buyer_fit_scorecard_id": runtime_state.resolve("challenger_buyer_fit_scorecard_id"),
                "challenger_buyer_fit_scorecard_score": runtime_state.resolve("challenger_buyer_fit_scorecard_score"),
                "challenger_buyer_fit_scorecard_grade": runtime_state.resolve("challenger_buyer_fit_scorecard_grade"),
                "buyer_fit_reason_tag_policy_id": runtime_state.resolve("buyer_fit_reason_tag_policy_id"),
                "buyer_fit_reason_tags": buyer_fit_reason_tags,
                "challenger_buyer_fit_reason_tag_policy_id": runtime_state.resolve("challenger_buyer_fit_reason_tag_policy_id"),
                "challenger_buyer_fit_reason_tags": challenger_buyer_fit_reason_tags,
                "buyer_fit_missing_formal_sources": runtime_state.resolve("buyer_fit_missing_formal_sources", []),
                "buyer_fit_derivation_trace": runtime_state.resolve("buyer_fit_derivation_trace"),
            },
            "value_derivation": {
                "value_derivation_trace": runtime_state.resolve("value_derivation_trace"),
                "project_value_band": runtime_state.resolve("project_value_band"),
                "lead_value_band": runtime_state.resolve("lead_value_band"),
                "opportunity_value_band": runtime_state.resolve("opportunity_value_band"),
                "project_value_reason_tag_policy_id": runtime_state.resolve("project_value_reason_tag_policy_id"),
                "project_value_reason_tags": runtime_state.resolve("project_value_reason_tags"),
                "lead_value_reason_tag_policy_id": runtime_state.resolve("lead_value_reason_tag_policy_id"),
                "lead_value_reason_tags": lead_value_reason_tags,
                "opportunity_value_reason_tag_policy_id": runtime_state.resolve("opportunity_value_reason_tag_policy_id"),
                "opportunity_value_reason_tags": opportunity_value_reason_tags,
            },
            "opportunity_policy": {
                "opportunity_policy_trace": runtime_state.resolve("opportunity_policy_trace"),
                "why_recommended_template_id": runtime_state.resolve("why_recommended_template_id"),
                "why_recommended_rule_outputs": runtime_state.resolve("why_recommended_rule_outputs"),
                "expected_close_days_band": saleable_opportunity.get("expected_close_days_band"),
                "expected_delivery_cost_band": saleable_opportunity.get("expected_delivery_cost_band"),
                "why_recommended": offer_recommendation.get("why_recommended"),
            },
            "price_resolution": {
                "policy_id": runtime_state.resolve("price_resolution_policy_id"),
                "selected_source_type": runtime_state.resolve("selected_price_source_type"),
                "price_candidate_count": runtime_state.resolve("price_candidate_count", 0),
                "price_candidate_deduped_count": runtime_state.resolve("price_candidate_deduped_count", 0),
                "price_source_priority_applied": runtime_state.resolve("price_source_priority_applied", []),
                "normalized_currency": runtime_state.resolve("normalized_price_currency", "CNY"),
                "normalized_tax_basis": runtime_state.resolve("normalized_tax_basis", "EX_TAX"),
                "normalized_unit_basis": runtime_state.resolve("normalized_unit_basis", "TOTAL_AMOUNT"),
                "selected_scope_key": runtime_state.resolve("selected_scope_key", "GLOBAL"),
                "review_flags": runtime_state.resolve("price_review_flags", []),
                "selected_candidate_trace": runtime_state.resolve("selected_candidate_trace", {}),
            },
            "multi_competitor_collection": {
                "policy_id": competitor_trace_summary["policy_id"],
                "ranking_policy_id": competitor_trace_summary.get("ranking_policy_id"),
                "cutoff_policy_id": competitor_trace_summary.get("cutoff_policy_id"),
                "multi_competitor_collection_id": multi_competitor_collection.get("multi_competitor_collection_id"),
                "candidate_count": len(multi_competitor_collection.get("candidate_list")),
                "deduped_candidate_count": competitor_trace_summary["deduped_candidate_count"],
                "top_n_limit": competitor_trace_summary.get("top_n_limit"),
                "top_n_candidate_ids": multi_competitor_collection.get("top_n_candidate_ids"),
                "winning_candidate_id": multi_competitor_collection.get("winning_candidate_id"),
                "winning_challenger_profile_id": multi_competitor_collection.get("winning_challenger_profile_id"),
                "candidate_only_candidate_ids": competitor_trace_summary["candidate_only_candidate_ids"],
                "alias_deduped_count": competitor_trace_summary["alias_deduped_count"],
                "selection_trace": multi_competitor_collection.get("selection_trace"),
            },
            "formal_sink_projection": {
                "project_value_score_optional": project_value_score_optional,
                "opportunity_value_score_optional": opportunity_value_score_optional,
                "normalized_price_amount_optional": normalized_price_amount_optional,
                "price_conflict_gate_status_optional": price_conflict_gate_status_optional,
                "confidence_score_optional": confidence_score_optional,
                "current_action_start_at_optional": current_action_start_at_optional,
                "current_action_deadline_at_optional": current_action_deadline_at_optional,
            },
        }
        inputs_out["commercial_urgency_level_optional"] = inputs.get(
            "commercial_urgency_level_optional",
            "CRITICAL" if runtime_state.resolve("window_urgency_score", 0) >= 90 else "HIGH" if runtime_state.resolve("window_urgency_score", 0) >= 80 else "NORMAL",
        )
        inputs_out["multi_competitor_collection_id_optional"] = multi_competitor_collection.get("multi_competitor_collection_id")
        inputs_out["winning_competitor_candidate_id_optional"] = multi_competitor_collection.get("winning_candidate_id")
        inputs_out["winning_challenger_profile_id_optional"] = multi_competitor_collection.get("winning_challenger_profile_id")
        inputs_out["window_urgency_score"] = runtime_state.resolve(
            "window_urgency_score",
            buyer_fit.get("window_urgency_score"),
        )
        inputs_out["buyer_fit_id"] = buyer_fit.get("buyer_fit_id")
        inputs_out["offer_recommendation_id"] = offer_recommendation.get("offer_recommendation_id")
        inputs_out["legal_action_actor_id"] = legal_action_actor_profile.get("actor_id")
        inputs_out["procurement_decision_actor_id"] = procurement_decision_actor_profile.get("actor_id")
        inputs_out["legal_action_actor_actionability_state_optional"] = legal_action_actor_profile.get("actionability_state")
        inputs_out["procurement_decision_reachable_state_optional"] = procurement_decision_actor_profile.get("reachable_state")
        inputs_out["role_cluster"] = procurement_decision_actor_profile.get("actor_role_cluster")
        inputs_out["project_value_score_optional"] = project_value_score_optional
        inputs_out["opportunity_value_score_optional"] = opportunity_value_score_optional
        inputs_out["normalized_price_amount_optional"] = normalized_price_amount_optional
        inputs_out["price_conflict_gate_status_optional"] = price_conflict_gate_status_optional
        inputs_out["confidence_score_optional"] = confidence_score_optional
        inputs_out["current_action_start_at_optional"] = current_action_start_at_optional
        inputs_out["current_action_deadline_at_optional"] = current_action_deadline_at_optional
        inputs_out["semantic_trace"] = semantic_state.semantic_trace
        inputs_out["semantic_decision_state"] = semantic_state.semantic_decision_state
        inputs_out["semantic_additions"] = semantic_state.semantic_additions

        return StageBundle(
            stage=7,
            records={
                "legal_action_actor_profile": legal_action_actor_profile,
                "procurement_decision_actor_profile": procurement_decision_actor_profile,
                "buyer_fit": buyer_fit,
                "challenger_buyer_fit": challenger_buyer_fit,
                "sales_lead": sales_lead,
                "offer_recommendation": offer_recommendation,
                "saleable_opportunity": saleable_opportunity,
                "multi_competitor_collection": multi_competitor_collection,
            },
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff
