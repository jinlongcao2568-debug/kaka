# Stage: stage7_sales
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/sales/challenger_profile_catalog.json, contracts/sales/buyer_fit_scorecard.json, contracts/sales/opportunity_policy_catalog.json, contracts/sales/stage7_resolution_policy.json

from __future__ import annotations

from typing import Any, Mapping

from stage7_sales.commercial_hook import (
    COMMERCIAL_HOOK_LEAD_INPUT_KEY,
    COMMERCIAL_HOOK_READINESS_INPUT_KEY,
    build_commercial_hook_lead_carrier,
    build_commercial_hook_readiness_summary,
)
from stage7_sales.crm_quote_workbench import (
    CRM_ACTION_ID_INPUT_KEY,
    CRM_QUOTE_WORKBENCH_INPUT_KEY,
    CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY,
    QUOTE_DRAFT_ID_INPUT_KEY,
    build_crm_quote_workbench_carrier,
    build_crm_quote_workbench_readiness_summary,
)
from stage7_sales.leadpack_delivery_package import (
    LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY,
    LEADPACK_DELIVERY_PACKAGE_INPUT_KEY,
    LEADPACK_DELIVERY_READINESS_INPUT_KEY,
    LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY,
    LEADPACK_PACKAGE_ID_INPUT_KEY,
    LEADPACK_PAGE_DRAFT_ID_INPUT_KEY,
    build_leadpack_delivery_package_carrier,
    build_leadpack_delivery_readiness_summary,
)
from stage7_sales.pricing import build_price_resolution_trace, resolve_price_projection
from stage7_sales.recommendation import (
    build_crm_quote_prerequisite_readiness_carrier,
    build_opportunity_blocking_reasons,
    build_opportunity_policy_trace,
    build_stage7_restriction_reasons,
)
from stage7_sales.real_challenger import build_real_challenger_readback
from stage7_sales.resolution import resolve_actor_seed
from stage7_sales.runtime import (
    build_stage7_runtime_context,
    dedupe_strings,
    optional_int,
    optional_str,
    require_h06_field,
    required_runtime_value,
)
from stage7_sales.scorecard import (
    build_buyer_fit_scorecard_trace,
    build_value_derivation_trace,
    resolve_scorecard_projection,
)
from shared.capability_runtime import CapabilityRuntime
from shared.contracts_runtime import ContractStore, StageBundle
from shared.model_assist_governance import (
    MODEL_ASSIST_INPUT_KEY,
    MODEL_ASSIST_SUMMARY_INPUT_KEY,
    build_model_assist_summary,
    build_sales_talk_track_model_assist,
)
from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    provider_readiness_for_family,
)
from shared.settings import Settings
from shared.state_packet import StatePacket
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, resolve_bundle, utc_now_iso


class Stage7Service:
    REAL_PUBLIC_STAGE7_READBACK_KEY = "stage7_real_public_product_package_readback_summary"

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.store = ContractStore.default(self.settings)
        self.runtime = CapabilityRuntime(self.settings)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage6_bundle = resolve_bundle(payload)
        handoff_validation = self.store.evaluate_handoff_consumer(
            producer_bundle=stage6_bundle,
            consumer_stage=7,
        )
        if handoff_validation and handoff_validation.decision_state == "BLOCK":
            raise ValueError(f"{handoff_validation.semantic_scope} blocked: {handoff_validation.reasons}")
        inputs = stage6_bundle.inputs or {}
        now = inputs.get("now") or utc_now_iso()

        project_fact = stage6_bundle.record("project_fact")
        legal_action_recommendation = stage6_bundle.record("legal_action_recommendation")
        review_queue_profile = stage6_bundle.records.get("review_queue_profile")
        challenger_candidate_profile = stage6_bundle.record("challenger_candidate_profile")
        report_record = stage6_bundle.record("report_record")
        if review_queue_profile is None:
            raise ValueError("missing H-06 formal producer object: review_queue_profile")
        project_id = project_fact.get("project_id")
        stage6_handoff = stage6_bundle.handoff or {}

        project_fact_id = require_h06_field(stage6_handoff, "project_fact_id")
        review_queue_profile_id = require_h06_field(stage6_handoff, "review_queue_profile_id")
        review_lane = require_h06_field(stage6_handoff, "review_lane")
        report_record_id = require_h06_field(stage6_handoff, "report_record_id")
        challenger_candidate_profile_id = require_h06_field(stage6_handoff, "challenger_candidate_profile_id")
        sale_gate_status = require_h06_field(stage6_handoff, "sale_gate_status")
        saleability_status_seed = require_h06_field(stage6_handoff, "saleability_status")
        competitor_quality_grade = require_h06_field(stage6_handoff, "competitor_quality_grade")
        window_status = require_h06_field(stage6_handoff, "window_status")
        report_status = require_h06_field(stage6_handoff, "report_status")
        review_task_status = require_h06_field(stage6_handoff, "review_task_status")
        action_family = require_h06_field(stage6_handoff, "action_family")
        challenger_profile_id = require_h06_field(stage6_handoff, "challenger_profile_id")
        focus_bidder_id = require_h06_field(stage6_handoff, "focus_bidder_id")
        challenger_bidder_id = require_h06_field(stage6_handoff, "challenger_bidder_id")
        challenge_actionability_score = int(require_h06_field(stage6_handoff, "challenge_actionability_score"))
        execution_readiness_score = int(require_h06_field(stage6_handoff, "execution_readiness_score"))
        linked_review_request_id_optional = optional_str(stage6_handoff.get("linked_review_request_id_optional"))
        missing_condition_family_optional = optional_str(stage6_handoff.get("missing_condition_family_optional"))
        has_review_constraint = bool(linked_review_request_id_optional or missing_condition_family_optional)
        if challenger_candidate_profile_id != challenger_profile_id:
            raise ValueError("H-06 challenger_candidate_profile_id must match challenger_profile_id")
        stage6_formal_carriers = {
            "project_fact_id": project_fact_id,
            "review_queue_profile_id": review_queue_profile_id,
            "review_lane": review_lane,
            "report_record_id": report_record_id,
            "challenger_candidate_profile_id": challenger_candidate_profile_id,
            "sale_gate_status": sale_gate_status,
            "saleability_status": saleability_status_seed,
            "report_status": report_status,
            "linked_review_request_id_optional": linked_review_request_id_optional,
            "missing_condition_family_optional": missing_condition_family_optional,
        }
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
        buyer_type_hint = require_h06_field(stage6_handoff, "buyer_type_hint")
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
        current_action_start_at_optional = optional_str(
            stage6_handoff.get(
                "current_action_start_at_optional",
                inputs.get("current_action_start_at_optional"),
            )
        )
        current_action_deadline_at_optional = optional_str(
            stage6_handoff.get(
                "current_action_deadline_at_optional",
                inputs.get("current_action_deadline_at_optional", inputs.get("current_action_deadline_optional")),
            )
        )

        trace_rules: list[str] = []
        semantic_state = StatePacket(capability_mode="stage7_sales")

        offer_state = "DRAFT"
        if sale_gate_status == "BLOCK":
            offer_state = "BLOCKED"
        elif sale_gate_status in ("REVIEW", "HOLD") or has_review_constraint:
            offer_state = "REVIEW_REQUIRED"
        else:
            offer_state = "APPROVED"

        runtime_context = build_stage7_runtime_context(
            project_id=project_id,
            project_fact=project_fact,
            legal_action_recommendation=legal_action_recommendation,
            challenger_candidate_profile=challenger_candidate_profile,
            report_record=report_record,
            inputs=inputs,
            now=now,
            sale_gate_status=sale_gate_status,
            competitor_quality_grade=competitor_quality_grade,
            window_status=window_status,
            report_status=report_status,
            review_task_status=review_task_status,
            focus_bidder_id=focus_bidder_id,
            challenger_bidder_id=challenger_bidder_id,
            challenger_profile_id=challenger_profile_id,
            candidate_position_label=candidate_position_label,
            buyer_type_hint=buyer_type_hint,
            challenge_actionability_score=challenge_actionability_score,
            execution_readiness_score=execution_readiness_score,
            real_competitor_count=int(
                stage6_handoff.get("real_competitor_count", project_fact.get("real_competitor_count", 0))
            ),
            project_value_score_seed=project_value_score_seed,
            normalized_price_amount_seed=normalized_price_amount_seed,
            price_conflict_gate_status_seed=price_conflict_gate_status_seed,
            confidence_score_seed=confidence_score_seed,
            current_action_start_at_optional=current_action_start_at_optional,
            current_action_deadline_at_optional=current_action_deadline_at_optional,
        )
        runtime_state = self.runtime.run(runtime_context)

        multi_competitor_candidates = ensure_list(required_runtime_value(runtime_state, "multi_competitor_candidates"))
        top_n_competitor_ids = ensure_list(required_runtime_value(runtime_state, "top_n_candidate_ids"))
        winning_competitor_candidate = dict(required_runtime_value(runtime_state, "winning_competitor_candidate"))
        competitor_selection_trace = dict(required_runtime_value(runtime_state, "competitor_selection_trace"))
        competitor_trace_summary = dict(required_runtime_value(runtime_state, "competitor_trace_summary"))
        offer_recommendation_id = build_id("OFFER", project_id)
        real_challenger_projection = build_real_challenger_readback(
            project_id=str(project_id),
            inputs=inputs,
            runtime_state=runtime_state,
            multi_competitor_candidates=multi_competitor_candidates,
            top_n_competitor_ids=top_n_competitor_ids,
            winning_competitor_candidate=winning_competitor_candidate,
            competitor_selection_trace=competitor_selection_trace,
            competitor_trace_summary=competitor_trace_summary,
            sale_gate_status=str(sale_gate_status),
            saleability_status_seed=str(saleability_status_seed),
            report_status=str(report_status),
            review_task_status=str(review_task_status),
            action_family=str(action_family),
            linked_review_request_id_optional=linked_review_request_id_optional,
            missing_condition_family_optional=missing_condition_family_optional,
            offer_recommendation_id=offer_recommendation_id,
        )
        multi_competitor_candidates = ensure_list(real_challenger_projection["multi_competitor_candidates"])
        winning_competitor_candidate = dict(real_challenger_projection["winning_competitor_candidate"])
        competitor_selection_trace = dict(real_challenger_projection["competitor_selection_trace"])
        real_challenger_readback = dict(real_challenger_projection["real_challenger_readback"])
        real_challenger_decision_state = str(real_challenger_projection["real_challenger_decision_state"])
        real_challenger_blocking_reasons = ensure_list(
            real_challenger_projection["real_challenger_blocking_reasons"]
        )
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
        price_projection = resolve_price_projection(runtime_state)
        normalized_price_amount_optional = price_projection["normalized_price_amount_optional"]
        price_conflict_gate_status_optional = price_projection["price_conflict_gate_status_optional"]
        price_band_optional = price_projection["price_band_optional"]
        price_recommended_quote_band = price_projection["price_recommended_quote_band"]

        scorecard_projection = resolve_scorecard_projection(runtime_state)
        project_value_score_optional = scorecard_projection["project_value_score_optional"]
        opportunity_value_score_optional = scorecard_projection["opportunity_value_score_optional"]
        buyer_fit_runtime_score = scorecard_projection["buyer_fit_runtime_score"]
        buyer_fit_purchase_intent_score = scorecard_projection["buyer_fit_purchase_intent_score"]
        buyer_fit_payment_capacity_score = scorecard_projection["buyer_fit_payment_capacity_score"]
        buyer_fit_window_urgency_score = scorecard_projection["buyer_fit_window_urgency_score"]
        buyer_fit_attack_motivation_score = scorecard_projection["buyer_fit_attack_motivation_score"]
        challenger_buyer_fit_runtime_score = scorecard_projection["challenger_buyer_fit_runtime_score"]
        buyer_fit_reason_tags = scorecard_projection["buyer_fit_reason_tags"]
        challenger_buyer_fit_reason_tags = scorecard_projection["challenger_buyer_fit_reason_tags"]
        lead_value_reason_tags = scorecard_projection["lead_value_reason_tags"]
        opportunity_value_reason_tags = scorecard_projection["opportunity_value_reason_tags"]
        confidence_score_optional = optional_int(
            runtime_state.resolve("competitor_confidence_score", confidence_score_seed)
        )

        lead_status = "QUALIFIED"
        if (
            sale_gate_status == "BLOCK"
            or runtime_state.decision_state == "BLOCK"
            or real_challenger_decision_state == "BLOCK"
        ):
            apply_rule(self.store, trace_rules, "SALE-001")
            lead_status = "DISQUALIFIED"
        elif (
            sale_gate_status in ("REVIEW", "HOLD")
            or report_status != "ISSUED"
            or has_review_constraint
            or real_challenger_decision_state == "REVIEW"
        ):
            apply_rule(self.store, trace_rules, "SALE-001")
            lead_status = "REVIEW"

        lead_score = int(required_runtime_value(runtime_state, "lead_score"))
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
        if (
            saleability_status_seed == "BLOCKED"
            or sale_gate_status == "BLOCK"
            or runtime_state.decision_state == "BLOCK"
            or real_challenger_decision_state == "BLOCK"
        ):
            apply_rule(self.store, trace_rules, "SALE-002")
            saleability_status = "BLOCKED"
        elif (
            saleability_status_seed == "RESTRICTED"
            or sale_gate_status in ("REVIEW", "HOLD")
            or report_status != "ISSUED"
            or has_review_constraint
            or runtime_state.resolve("offer_recommendation_state", offer_state) == "REVIEW_REQUIRED"
            or real_challenger_decision_state == "REVIEW"
        ):
            apply_rule(self.store, trace_rules, "SALE-002")
            saleability_status = "RESTRICTED"

        if real_challenger_decision_state == "BLOCK":
            offer_state = "BLOCKED"
        elif real_challenger_decision_state == "REVIEW" and offer_state == "APPROVED":
            offer_state = "REVIEW_REQUIRED"

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
        if real_challenger_decision_state == "BLOCK":
            offer_state = "BLOCKED"
        elif real_challenger_decision_state == "REVIEW" and offer_state == "APPROVED":
            offer_state = "REVIEW_REQUIRED"
        offer_recommendation_payload = {
            "offer_recommendation_id": offer_recommendation_id,
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
                price_recommended_quote_band,
            ),
            "why_recommended": required_runtime_value(runtime_state, "why_recommended"),
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
        final_offer_summary = {
            "offer_recommendation_id": offer_recommendation.get("offer_recommendation_id"),
            "sku_code": offer_recommendation.get("sku_code"),
            "recommended_delivery_form": offer_recommendation.get("recommended_delivery_form"),
            "recommended_quote_band": offer_recommendation.get("recommended_quote_band"),
            "offer_recommendation_state": offer_recommendation.get("offer_recommendation_state"),
            "why_recommended": offer_recommendation.get("why_recommended"),
        }
        for candidate in multi_competitor_candidates:
            if isinstance(candidate, dict):
                candidate["recommended_offer_ref"] = offer_recommendation.get("offer_recommendation_id")
                candidate["recommended_offer_summary"] = dict(final_offer_summary)
        real_challenger_readback["candidate_set"] = multi_competitor_candidates
        real_challenger_readback["recommended_offer_summary"] = dict(final_offer_summary)
        if isinstance(real_challenger_readback.get("winning_candidate"), dict):
            real_challenger_readback["winning_candidate"]["recommended_offer_ref"] = offer_recommendation.get(
                "offer_recommendation_id"
            )
            real_challenger_readback["winning_candidate"]["recommended_offer_summary"] = dict(final_offer_summary)

        stage7_restriction_reasons = build_stage7_restriction_reasons(
            saleability_status_seed=saleability_status_seed,
            sale_gate_status=sale_gate_status,
            report_status=report_status,
            linked_review_request_id_optional=linked_review_request_id_optional,
            missing_condition_family_optional=missing_condition_family_optional,
            offer_recommendation_state=runtime_state.resolve("offer_recommendation_state", offer_state),
        )
        opportunity_blocking_reasons = build_opportunity_blocking_reasons(
            inputs=inputs,
            runtime_state=runtime_state,
            saleability_status=saleability_status,
            stage7_restriction_reasons=stage7_restriction_reasons,
        )
        if real_challenger_decision_state != "ALLOW":
            opportunity_blocking_reasons = dedupe_strings(
                opportunity_blocking_reasons
                + [
                    f"real_challenger:{reason}"
                    for reason in real_challenger_blocking_reasons
                ]
            )

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
            "blocking_reasons": opportunity_blocking_reasons,
            "expected_close_days_band": required_runtime_value(runtime_state, "expected_close_days_band"),
            "expected_contract_value_band": inputs.get(
                "expected_contract_value_band",
                price_band_optional or "UNKNOWN",
            ),
            "expected_delivery_cost_band": required_runtime_value(runtime_state, "expected_delivery_cost_band"),
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
            "sale_gate_status": sale_gate_status,
            "report_status": report_status,
            "project_fact_id_optional": project_fact_id,
            "review_queue_profile_id_optional": review_queue_profile_id,
            "review_lane_optional": review_lane,
            "report_record_id_optional": report_record_id,
            "challenger_candidate_profile_id_optional": challenger_candidate_profile_id,
            "linked_review_request_id_optional": linked_review_request_id_optional,
            "missing_condition_family_optional": missing_condition_family_optional,
            "stage6_formal_carriers_trace_optional": stage6_formal_carriers,
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
        inputs_out.update(
            {
                "project_fact_id": project_fact_id,
                "review_queue_profile_id": review_queue_profile_id,
                "review_lane": review_lane,
                "report_record_id": report_record_id,
                "challenger_candidate_profile_id": challenger_candidate_profile_id,
                "sale_gate_status": sale_gate_status,
                "report_status": report_status,
                "linked_review_request_id_optional": linked_review_request_id_optional,
                "missing_condition_family_optional": missing_condition_family_optional,
            }
        )
        stage7_resolution_trace = {
            "stage6_formal_carriers": stage6_formal_carriers,
            "review_gate_report_constraints": {
                "sale_gate_status": sale_gate_status,
                "saleability_status_seed": saleability_status_seed,
                "report_status": report_status,
                "review_task_status": review_task_status,
                "review_lane": review_lane,
                "linked_review_request_id_optional": linked_review_request_id_optional,
                "missing_condition_family_optional": missing_condition_family_optional,
                "stage7_restriction_reasons": stage7_restriction_reasons,
            },
            "actor_seed_provenance": {
                "legal_action_actor_org_name": legal_actor_seed,
                "procurement_decision_actor_org_name": procurement_actor_seed,
            },
            "buyer_fit_scorecard": build_buyer_fit_scorecard_trace(
                runtime_state,
                buyer_fit_reason_tags=buyer_fit_reason_tags,
                challenger_buyer_fit_reason_tags=challenger_buyer_fit_reason_tags,
            ),
            "value_derivation": build_value_derivation_trace(
                runtime_state,
                lead_value_reason_tags=lead_value_reason_tags,
                opportunity_value_reason_tags=opportunity_value_reason_tags,
            ),
            "opportunity_policy": build_opportunity_policy_trace(
                runtime_state,
                saleable_opportunity=saleable_opportunity,
                offer_recommendation=offer_recommendation,
            ),
            "price_resolution": build_price_resolution_trace(
                runtime_state,
                price_band_optional=price_band_optional,
                price_recommended_quote_band=price_recommended_quote_band,
            ),
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
                "real_challenger_decision_state": real_challenger_decision_state,
                "candidate_source_types_covered": real_challenger_readback.get("candidate_source_types_covered"),
            },
            "real_challenger_identification": real_challenger_readback,
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
        input_provider_adapter_readiness_summary = inputs.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY)
        provider_adapter_readiness_summary = (
            dict(input_provider_adapter_readiness_summary)
            if isinstance(input_provider_adapter_readiness_summary, Mapping)
            else self.settings.provider_adapter_readiness_summary()
        )
        crm_quote_prerequisite_readiness = build_crm_quote_prerequisite_readiness_carrier(
            sales_lead=sales_lead,
            saleable_opportunity=saleable_opportunity,
            offer_recommendation=offer_recommendation,
            stage7_resolution_trace=stage7_resolution_trace,
        )
        crm_quote_prerequisite_readiness = {
            **crm_quote_prerequisite_readiness,
            PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: provider_adapter_readiness_summary,
            "provider_adapter_readiness": provider_readiness_for_family(
                provider_adapter_readiness_summary,
                "crm_quote",
            ),
            "provider_adapter_config_source": provider_adapter_readiness_summary.get("config_source"),
            "provider_adapter_mode": provider_adapter_readiness_summary.get("mode"),
        }
        crm_quote_workbench = build_crm_quote_workbench_carrier(
            sales_lead=sales_lead,
            saleable_opportunity=saleable_opportunity,
            offer_recommendation=offer_recommendation,
            inputs=inputs,
            stage7_resolution_trace=stage7_resolution_trace,
            now=now,
            provider_adapter_readiness_summary=provider_adapter_readiness_summary,
        )
        crm_quote_workbench_readiness_summary = build_crm_quote_workbench_readiness_summary(
            crm_quote_workbench
        )
        leadpack_delivery_package = build_leadpack_delivery_package_carrier(
            sales_lead=sales_lead,
            saleable_opportunity=saleable_opportunity,
            offer_recommendation=offer_recommendation,
            buyer_fit=buyer_fit,
            legal_action_actor_profile=legal_action_actor_profile,
            procurement_decision_actor_profile=procurement_decision_actor_profile,
            inputs={
                **inputs,
                CRM_ACTION_ID_INPUT_KEY: crm_quote_workbench.get("crm_action_id"),
                QUOTE_DRAFT_ID_INPUT_KEY: crm_quote_workbench.get("quote_draft_id"),
            },
            stage7_resolution_trace=stage7_resolution_trace,
            now=now,
            provider_adapter_readiness_summary=provider_adapter_readiness_summary,
        )
        leadpack_delivery_readiness_summary = build_leadpack_delivery_readiness_summary(
            leadpack_delivery_package
        )
        sales_talk_track_model_assist = build_sales_talk_track_model_assist(
            sales_lead=sales_lead,
            saleable_opportunity=saleable_opportunity,
            offer_recommendation=offer_recommendation,
            source_refs={
                "project_id": project_id,
                "real_challenger_readback_id": real_challenger_readback.get("readback_id"),
                "buyer_fit_id": buyer_fit.get("buyer_fit_id"),
                "offer_recommendation_id": offer_recommendation.get("offer_recommendation_id"),
            },
        )
        sales_talk_track_model_assist_summary = build_model_assist_summary(
            sales_talk_track_model_assist
        )
        commercial_hook_lead = build_commercial_hook_lead_carrier(
            sales_lead=sales_lead,
            saleable_opportunity=saleable_opportunity,
            offer_recommendation=offer_recommendation,
            buyer_fit=buyer_fit,
            challenger_buyer_fit=challenger_buyer_fit,
            legal_action_actor_profile=legal_action_actor_profile,
            procurement_decision_actor_profile=procurement_decision_actor_profile,
            stage6_product_package=dict(inputs.get("stage6_product_package_readiness", {}) or {}),
            stage7_resolution_trace=stage7_resolution_trace,
            leadpack_delivery_package=leadpack_delivery_package,
            model_assist_summary=sales_talk_track_model_assist_summary,
            now=now,
        )
        commercial_hook_readiness_summary = build_commercial_hook_readiness_summary(
            commercial_hook_lead
        )
        crm_quote_workbench[MODEL_ASSIST_INPUT_KEY] = sales_talk_track_model_assist
        crm_quote_workbench[MODEL_ASSIST_SUMMARY_INPUT_KEY] = sales_talk_track_model_assist_summary
        crm_quote_workbench[COMMERCIAL_HOOK_LEAD_INPUT_KEY] = commercial_hook_lead
        crm_quote_workbench[COMMERCIAL_HOOK_READINESS_INPUT_KEY] = commercial_hook_readiness_summary
        leadpack_delivery_package[MODEL_ASSIST_INPUT_KEY] = sales_talk_track_model_assist
        leadpack_delivery_package[MODEL_ASSIST_SUMMARY_INPUT_KEY] = sales_talk_track_model_assist_summary
        leadpack_delivery_package[COMMERCIAL_HOOK_LEAD_INPUT_KEY] = commercial_hook_lead
        leadpack_delivery_package[COMMERCIAL_HOOK_READINESS_INPUT_KEY] = commercial_hook_readiness_summary
        stage7_resolution_trace["crm_quote_prerequisite_readiness"] = crm_quote_prerequisite_readiness
        stage7_resolution_trace[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY] = provider_adapter_readiness_summary
        stage7_resolution_trace[CRM_QUOTE_WORKBENCH_INPUT_KEY] = crm_quote_workbench
        stage7_resolution_trace[MODEL_ASSIST_INPUT_KEY] = sales_talk_track_model_assist
        stage7_resolution_trace[MODEL_ASSIST_SUMMARY_INPUT_KEY] = sales_talk_track_model_assist_summary
        stage7_resolution_trace[COMMERCIAL_HOOK_LEAD_INPUT_KEY] = commercial_hook_lead
        stage7_resolution_trace[COMMERCIAL_HOOK_READINESS_INPUT_KEY] = commercial_hook_readiness_summary
        stage7_resolution_trace[LEADPACK_DELIVERY_PACKAGE_INPUT_KEY] = {
            "package_id": leadpack_delivery_package.get("package_id"),
            "evidence_pack_id": leadpack_delivery_package.get("evidence_pack_id"),
            "page_draft_id": leadpack_delivery_package.get("page_draft_id"),
            "artifact_manifest_id": leadpack_delivery_package.get("artifact_manifest_id"),
            "package_state": leadpack_delivery_package.get("package_state"),
            "page_state": leadpack_delivery_package.get("page_state"),
            "delivery_state": leadpack_delivery_package.get("delivery_state"),
            "customer_visible_enabled": bool(
                leadpack_delivery_package.get("customer_visible_enabled", False)
            ),
            "customer_visible_export_enabled": bool(
                leadpack_delivery_package.get("customer_visible_export_enabled", False)
            ),
            "page_publication_enabled": bool(
                leadpack_delivery_package.get("page_publication_enabled", False)
            ),
            "export_artifact_generation_enabled": bool(
                leadpack_delivery_package.get("export_artifact_generation_enabled", False)
            ),
            "external_delivery_enabled": False,
            "approved_customer_visible_unlock_summary": dict(
                leadpack_delivery_package.get("approved_customer_visible_unlock_summary", {})
            ),
        }
        inputs_out["stage7_resolution_trace"] = stage7_resolution_trace
        inputs_out[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY] = provider_adapter_readiness_summary
        inputs_out["crm_quote_prerequisite_readiness"] = crm_quote_prerequisite_readiness
        inputs_out[CRM_QUOTE_WORKBENCH_INPUT_KEY] = crm_quote_workbench
        inputs_out[CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY] = crm_quote_workbench_readiness_summary
        inputs_out["provider_execution_id"] = crm_quote_workbench.get("provider_execution_id")
        inputs_out[CRM_ACTION_ID_INPUT_KEY] = crm_quote_workbench.get("crm_action_id")
        inputs_out[QUOTE_DRAFT_ID_INPUT_KEY] = crm_quote_workbench.get("quote_draft_id")
        inputs_out[LEADPACK_DELIVERY_PACKAGE_INPUT_KEY] = leadpack_delivery_package
        inputs_out[LEADPACK_DELIVERY_READINESS_INPUT_KEY] = leadpack_delivery_readiness_summary
        inputs_out[LEADPACK_PACKAGE_ID_INPUT_KEY] = leadpack_delivery_package.get("package_id")
        inputs_out[LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY] = leadpack_delivery_package.get("evidence_pack_id")
        inputs_out[LEADPACK_PAGE_DRAFT_ID_INPUT_KEY] = leadpack_delivery_package.get("page_draft_id")
        inputs_out[LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY] = leadpack_delivery_package.get("artifact_manifest_id")
        inputs_out[MODEL_ASSIST_INPUT_KEY] = sales_talk_track_model_assist
        inputs_out[MODEL_ASSIST_SUMMARY_INPUT_KEY] = sales_talk_track_model_assist_summary
        inputs_out[COMMERCIAL_HOOK_LEAD_INPUT_KEY] = commercial_hook_lead
        inputs_out[COMMERCIAL_HOOK_READINESS_INPUT_KEY] = commercial_hook_readiness_summary
        handoff["crm_quote_prerequisite_readiness_optional"] = crm_quote_prerequisite_readiness
        handoff["provider_adapter_readiness_summary_optional"] = provider_adapter_readiness_summary
        handoff["crm_quote_workbench_optional"] = crm_quote_workbench
        handoff["model_assist_governance_optional"] = sales_talk_track_model_assist
        handoff["model_assist_governance_summary_optional"] = sales_talk_track_model_assist_summary
        handoff["commercial_hook_lead_optional"] = commercial_hook_lead
        handoff["commercial_hook_readiness_summary_optional"] = commercial_hook_readiness_summary
        handoff["provider_execution_id"] = crm_quote_workbench.get("provider_execution_id")
        handoff[CRM_ACTION_ID_INPUT_KEY] = crm_quote_workbench.get("crm_action_id")
        handoff[QUOTE_DRAFT_ID_INPUT_KEY] = crm_quote_workbench.get("quote_draft_id")
        handoff["leadpack_delivery_package_optional"] = leadpack_delivery_package
        handoff[LEADPACK_PACKAGE_ID_INPUT_KEY] = leadpack_delivery_package.get("package_id")
        handoff[LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY] = leadpack_delivery_package.get("evidence_pack_id")
        handoff[LEADPACK_PAGE_DRAFT_ID_INPUT_KEY] = leadpack_delivery_package.get("page_draft_id")
        handoff[LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY] = leadpack_delivery_package.get("artifact_manifest_id")
        inputs_out["commercial_urgency_level_optional"] = inputs.get(
            "commercial_urgency_level_optional",
            "CRITICAL" if runtime_state.resolve("window_urgency_score", 0) >= 90 else "HIGH" if runtime_state.resolve("window_urgency_score", 0) >= 80 else "NORMAL",
        )
        inputs_out["multi_competitor_collection_id_optional"] = multi_competitor_collection.get("multi_competitor_collection_id")
        inputs_out["winning_competitor_candidate_id_optional"] = multi_competitor_collection.get("winning_candidate_id")
        inputs_out["winning_challenger_profile_id_optional"] = multi_competitor_collection.get("winning_challenger_profile_id")
        inputs_out["real_challenger_readback"] = real_challenger_readback
        inputs_out["real_challenger_candidate_set"] = real_challenger_readback.get("candidate_set")
        inputs_out["winning_real_challenger_candidate"] = real_challenger_readback.get("winning_candidate")
        inputs_out["real_challenger_decision_state"] = real_challenger_decision_state
        inputs_out["real_challenger_blocking_reasons"] = real_challenger_blocking_reasons
        inputs_out["saleability_status"] = saleable_opportunity.get("saleability_status")
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
        semantic_additions = dict(semantic_state.semantic_additions)
        semantic_additions["real_challenger_identification"] = real_challenger_readback
        semantic_additions["crm_quote_prerequisite_readiness"] = crm_quote_prerequisite_readiness
        semantic_additions[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY] = provider_adapter_readiness_summary
        semantic_additions[CRM_QUOTE_WORKBENCH_INPUT_KEY] = crm_quote_workbench
        semantic_additions[CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY] = crm_quote_workbench_readiness_summary
        semantic_additions[LEADPACK_DELIVERY_PACKAGE_INPUT_KEY] = leadpack_delivery_package
        semantic_additions[LEADPACK_DELIVERY_READINESS_INPUT_KEY] = leadpack_delivery_readiness_summary
        semantic_additions[COMMERCIAL_HOOK_LEAD_INPUT_KEY] = commercial_hook_lead
        semantic_additions[COMMERCIAL_HOOK_READINESS_INPUT_KEY] = commercial_hook_readiness_summary
        inputs_out["semantic_additions"] = semantic_additions

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

    def run_real_public_product_package_readback(
        self,
        payload: Mapping[str, Any] | StageBundle,
    ) -> StageBundle:
        stage6_bundle = resolve_bundle(payload)
        result = self.run(stage6_bundle)
        summary = self._build_real_public_product_package_readback_summary(
            stage6_bundle=stage6_bundle,
            stage7_bundle=result,
        )
        inputs = dict(result.inputs)
        handoff = dict(result.handoff)
        resolution_trace = dict(inputs.get("stage7_resolution_trace", {}) or {})
        leadpack_package = dict(inputs.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY, {}) or {})
        if leadpack_package:
            source_object_refs = dict(leadpack_package.get("source_object_refs", {}) or {})
            source_object_refs["real_public_stage6_product_package"] = dict(summary.get("source_refs", {}))
            leadpack_package["source_object_refs"] = source_object_refs
            inputs[LEADPACK_DELIVERY_PACKAGE_INPUT_KEY] = leadpack_package
            handoff["leadpack_delivery_package_optional"] = leadpack_package
            resolution_trace["leadpack_delivery_package"] = dict(
                resolution_trace.get("leadpack_delivery_package", {})
            )
            resolution_trace["leadpack_delivery_package"]["real_public_stage6_product_package_refs"] = dict(
                summary.get("source_refs", {})
            )

        inputs[self.REAL_PUBLIC_STAGE7_READBACK_KEY] = summary
        handoff[self.REAL_PUBLIC_STAGE7_READBACK_KEY] = summary
        resolution_trace[self.REAL_PUBLIC_STAGE7_READBACK_KEY] = summary
        inputs["stage7_resolution_trace"] = resolution_trace
        return StageBundle(
            stage=result.stage,
            records=dict(result.records),
            handoff=handoff,
            trace_rules=list(result.trace_rules),
            inputs=inputs,
        )

    def _build_real_public_product_package_readback_summary(
        self,
        *,
        stage6_bundle: StageBundle,
        stage7_bundle: StageBundle,
    ) -> dict[str, Any]:
        stage6_summary = dict(
            stage6_bundle.inputs.get("stage6_real_public_rule_evidence_readback_summary", {}) or {}
        )
        stage6_product_package = dict(stage6_bundle.inputs.get("stage6_product_package_readiness", {}) or {})
        leadpack_package = dict(stage7_bundle.inputs.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY, {}) or {})
        commercial_hook = dict(stage7_bundle.inputs.get(COMMERCIAL_HOOK_LEAD_INPUT_KEY, {}) or {})
        commercial_hook_summary = dict(stage7_bundle.inputs.get(COMMERCIAL_HOOK_READINESS_INPUT_KEY, {}) or {})
        crm_quote_workbench = dict(stage7_bundle.inputs.get(CRM_QUOTE_WORKBENCH_INPUT_KEY, {}) or {})
        real_challenger_readback = dict(stage7_bundle.inputs.get("real_challenger_readback", {}) or {})
        real_challenger_state = str(stage7_bundle.inputs.get("real_challenger_decision_state", "UNKNOWN"))
        fail_closed_reasons: list[str] = []

        if not stage6_summary:
            fail_closed_reasons.append("stage6_real_public_rule_evidence_readback_summary_missing")
        elif stage6_summary.get("real_public_product_package_chain_state") != "INTERNAL_READY":
            fail_closed_reasons.append(
                "stage6_real_public_product_package_chain_state="
                + str(stage6_summary.get("real_public_product_package_chain_state"))
            )
        if not stage6_product_package:
            fail_closed_reasons.append("stage6_product_package_readiness_missing")
        elif stage6_product_package.get("product_package_readiness") != "INTERNAL_READY":
            fail_closed_reasons.append(
                "stage6_product_package_readiness="
                + str(stage6_product_package.get("product_package_readiness"))
            )
        if real_challenger_state == "BLOCK":
            fail_closed_reasons.append("real_challenger_decision_state=BLOCK")
        elif real_challenger_state not in {"ALLOW", "INTERNAL_READY"}:
            fail_closed_reasons.append(f"real_challenger_decision_state={real_challenger_state}")
        if not leadpack_package:
            fail_closed_reasons.append("leadpack_delivery_package_missing")
        if not commercial_hook:
            fail_closed_reasons.append("commercial_hook_lead_missing")
        if bool(commercial_hook.get("customer_visible_enabled", False)):
            fail_closed_reasons.append("commercial_hook_customer_visible_enabled_unexpected")
        if bool(commercial_hook.get("external_send_enabled", False)):
            fail_closed_reasons.append("commercial_hook_external_send_enabled_unexpected")
        if not bool(commercial_hook.get("no_full_evidence_leakage", False)):
            fail_closed_reasons.append("commercial_hook_full_evidence_leakage_guard_failed")
        if bool(leadpack_package.get("customer_visible_enabled", False)):
            fail_closed_reasons.append("leadpack_customer_visible_enabled_unexpected")
        if bool(leadpack_package.get("external_delivery_enabled", False)):
            fail_closed_reasons.append("leadpack_external_delivery_enabled_unexpected")
        if bool(crm_quote_workbench.get("approved_crm_quote_execution_enabled", False)):
            fail_closed_reasons.append("crm_quote_execution_enabled_unexpected")
        if bool(crm_quote_workbench.get("real_provider_call_enabled", False)):
            fail_closed_reasons.append("crm_quote_real_provider_call_enabled_unexpected")

        if any(reason.endswith("=BLOCK") for reason in fail_closed_reasons):
            chain_state = "BLOCKED"
        elif fail_closed_reasons:
            chain_state = "REVIEW_REQUIRED"
        else:
            chain_state = "INTERNAL_READY"

        return {
            "readback_state": "READBACK_READY" if chain_state == "INTERNAL_READY" else "REVIEW_REQUIRED",
            "real_public_sales_package_chain_state": chain_state,
            "stage6_product_package_readiness": stage6_product_package.get("product_package_readiness"),
            "real_challenger_decision_state": real_challenger_state,
            "leadpack_package_state": leadpack_package.get("package_state"),
            "leadpack_delivery_state": leadpack_package.get("delivery_state"),
            "commercial_hook_eligibility_state": commercial_hook.get("hook_eligibility_state"),
            "commercial_hook_disclosure_level": commercial_hook.get("disclosure_level"),
            "commercial_hook_leakage_risk_level": commercial_hook_summary.get("leakage_risk_level"),
            "source_refs": {
                "stage6_real_public_rule_evidence_readback": dict(stage6_summary.get("source_refs", {})),
                "stage6_product_package_source_refs": dict(
                    stage6_product_package.get("source_object_refs", {})
                ),
                "sales_lead_id": stage7_bundle.records["sales_lead"].get("lead_id"),
                "saleable_opportunity_id": stage7_bundle.records["saleable_opportunity"].get("opportunity_id"),
                "offer_recommendation_id": stage7_bundle.records["offer_recommendation"].get(
                    "offer_recommendation_id"
                ),
                "buyer_fit_id": stage7_bundle.records["buyer_fit"].get("buyer_fit_id"),
                "real_challenger_readback_id": real_challenger_readback.get("readback_id"),
                "leadpack_package_id": leadpack_package.get("package_id"),
                "commercial_hook_lead_id": commercial_hook.get("hook_lead_id"),
                "evidence_pack_id": leadpack_package.get("evidence_pack_id"),
                "artifact_manifest_id": leadpack_package.get("artifact_manifest_id"),
                "crm_action_id": crm_quote_workbench.get("crm_action_id"),
                "quote_draft_id": crm_quote_workbench.get("quote_draft_id"),
            },
            "fail_closed_reasons": fail_closed_reasons,
            "customer_visible_material_generated": False,
            "customer_visible_enabled": False,
            "external_delivery_enabled": False,
            "crm_quote_provider_execution_enabled": False,
            "stage8_stage9_execution_triggered": False,
            "legal_conclusion_generated": False,
            "audit_readback_summary": {
                "source": "stage7_real_public_product_package_readback",
                "replayable": True,
                "stage_scope": 7,
                "no_customer_visible_material_generated": True,
                "no_external_delivery_enabled": True,
                "no_crm_quote_provider_execution_enabled": True,
                "no_stage8_stage9_execution_triggered": True,
            },
        }

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff
