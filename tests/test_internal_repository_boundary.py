from __future__ import annotations

import unittest

from helpers import load_fixture
from shared.pipeline import run_internal_chain
from api.routes.stage7 import list_saleable_opportunities, refresh_saleable_opportunity
from api.routes.stage8 import create_touch_record, list_contact_targets
from api.routes.stage9 import create_governance_feedback_event, list_orders
from storage import reset_default_storage
from storage.repository_boundary import hydrate_stage_bundle
from storage.repositories import (
    BuyerFitRepository,
    ContactTargetRepository,
    DeliveryRecordRepository,
    GovernanceFeedbackEventRepository,
    LegalActionActorProfileRepository,
    OfferRecommendationRepository,
    OpportunityOutcomeEventRepository,
    OrderRecordRepository,
    OutreachPlanRepository,
    PaymentRecordRepository,
    ProcurementDecisionActorProfileRepository,
    SaleableOpportunityRepository,
    TouchRecordRepository,
)


class TestInternalRepositoryBoundary(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()
        self.result = run_internal_chain(load_fixture("internal_chain_happy.json"))

    def test_stage7_repository_boundary_persists_formal_objects_without_rejudging(self) -> None:
        stage7 = self.result["stage7"]
        refresh_saleable_opportunity(stage7)

        opportunity = stage7.record("saleable_opportunity")
        opportunity_entry = SaleableOpportunityRepository().get_by_id(opportunity.get("opportunity_id"))
        offer_entry = OfferRecommendationRepository().find_one_by_field("project_id", opportunity.get("project_id"))
        buyer_entry = BuyerFitRepository().get_by_id(opportunity.get("buyer_fit_id"))

        self.assertIsNotNone(opportunity_entry)
        self.assertIsNotNone(offer_entry)
        self.assertIsNotNone(buyer_entry)
        self.assertEqual(opportunity_entry.stage_scope, 7)
        self.assertEqual(opportunity_entry.payload["saleability_status"], opportunity.get("saleability_status"))
        self.assertEqual(offer_entry.payload["offer_recommendation_state"], stage7.record("offer_recommendation").get("offer_recommendation_state"))
        self.assertEqual(buyer_entry.payload["fit_score"], stage7.record("buyer_fit").get("fit_score"))

        replay = list_saleable_opportunities({"opportunity_id": opportunity.get("opportunity_id")})
        self.assertEqual(
            replay["formal_object_refs"]["saleable_opportunity"]["object_id"],
            opportunity.get("opportunity_id"),
        )
        self.assertEqual(
            replay["formal_object_refs"]["offer_recommendation"]["object_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertEqual(
            replay["formal_object_refs"]["buyer_fit"]["object_id"],
            stage7.record("buyer_fit").get("buyer_fit_id"),
        )
        self.assertEqual(
            replay["preview_projection"]["opportunity_summary"]["saleability_status"],
            opportunity.get("saleability_status"),
        )
        self.assertEqual(
            replay["preview_projection"]["offer_summary"]["offer_recommendation_state"],
            stage7.record("offer_recommendation").get("offer_recommendation_state"),
        )
        self.assertEqual(
            replay["decision_states"]["policy_decision_state"],
            stage7.inputs.get("policy_decision_state"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["object_refs"]["legal_action_actor_id"],
            stage7.record("legal_action_actor_profile").get("actor_id"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["object_refs"]["procurement_decision_actor_id"],
            stage7.record("procurement_decision_actor_profile").get("actor_id"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["object_refs"]["multi_competitor_collection_id_optional"],
            stage7.record("multi_competitor_collection").get("multi_competitor_collection_id"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["object_refs"]["winning_competitor_candidate_id_optional"],
            stage7.record("multi_competitor_collection").get("winning_candidate_id"),
        )
        hydrated = hydrate_stage_bundle(
            "stage7",
            {"opportunity_id": opportunity.get("opportunity_id")},
        )
        self.assertIsNotNone(hydrated)
        self.assertEqual(
            hydrated.record("multi_competitor_collection").get("multi_competitor_collection_id"),
            stage7.record("multi_competitor_collection").get("multi_competitor_collection_id"),
        )
        self.assertEqual(
            hydrated.inputs["offer_recommendation_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )

    def test_stage8_repository_boundary_keeps_governed_writeback_state(self) -> None:
        stage8 = self.result["stage8"]
        create_touch_record(stage8)

        touch = stage8.record("touch_record")
        touch_entry = TouchRecordRepository().get_by_id(touch.get("touch_record_id"))
        contact_entry = ContactTargetRepository().get_by_id(stage8.record("contact_target").get("contact_target_id"))
        plan_entry = OutreachPlanRepository().get_by_id(stage8.record("outreach_plan").get("outreach_plan_id"))

        self.assertIsNotNone(touch_entry)
        self.assertIsNotNone(contact_entry)
        self.assertIsNotNone(plan_entry)
        self.assertEqual(touch_entry.stage_scope, 8)
        self.assertEqual(
            touch_entry.writeback_state["written_back_at_optional"],
            touch.get("written_back_at_optional"),
        )
        self.assertEqual(
            touch_entry.decision_states["permission_decision_state"],
            touch.get("permission_decision_state"),
        )
        self.assertIn("execution_trace_id_optional", touch_entry.trace_refs)
        self.assertIn("source_audit_ref", contact_entry.audit_refs)

        replay = list_contact_targets(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": touch.get("touch_record_id"),
            }
        )
        self.assertEqual(
            replay["preview_projection"]["touch_record_preview"]["writeback_targets"],
            touch.get("writeback_targets"),
        )
        self.assertEqual(
            replay["preview_projection"]["outreach_plan_preview"]["projection_mode"],
            stage8.record("outreach_plan").get("projection_mode"),
        )
        self.assertEqual(
            replay["decision_states"]["permission_decision_state"],
            stage8.inputs.get("permission_decision_state"),
        )
        self.assertTrue(replay["blocked_by_default"])
        hydrated = hydrate_stage_bundle(
            "stage8",
            {"opportunity_id": stage8.record("contact_target").get("opportunity_id")},
        )
        self.assertIsNotNone(hydrated)
        self.assertEqual(hydrated.inputs["feedback_reason"], touch.get("feedback_reason"))
        self.assertEqual(hydrated.inputs["next_step_optional"], touch.get("next_step_optional"))
        self.assertEqual(hydrated.inputs["writeback_targets"], touch.get("writeback_targets"))
        self.assertEqual(
            hydrated.inputs["writeback_target_optional"],
            touch.get("writeback_target_optional"),
        )
        self.assertEqual(
            hydrated.inputs["failure_reason_tag_optional"],
            touch.get("failure_reason_tag_optional"),
        )
        self.assertEqual(
            hydrated.inputs["cadence_profile_id"],
            stage8.record("outreach_plan").get("cadence_profile_id"),
        )
        self.assertEqual(
            hydrated.inputs["retry_policy_id"],
            stage8.record("outreach_plan").get("retry_policy_id"),
        )
        self.assertEqual(
            hydrated.inputs["stop_policy_id"],
            stage8.record("outreach_plan").get("stop_policy_id"),
        )

    def test_stage9_repository_boundary_persists_internal_governed_writeback_loop(self) -> None:
        stage9 = self.result["stage9"]
        create_governance_feedback_event(stage9)

        order = stage9.record("order_record")
        payment = stage9.record("payment_record")
        delivery = stage9.record("delivery_record")
        outcome = stage9.record("opportunity_outcome_event")
        governance = stage9.record("governance_feedback_event")

        order_entry = OrderRecordRepository().get_by_id(order.get("order_id"))
        payment_entry = PaymentRecordRepository().get_by_id(payment.get("payment_id"))
        delivery_entry = DeliveryRecordRepository().get_by_id(delivery.get("delivery_id"))
        outcome_entry = OpportunityOutcomeEventRepository().get_by_id(outcome.get("outcome_event_id"))
        governance_entry = GovernanceFeedbackEventRepository().get_by_id(governance.get("governance_feedback_event_id"))

        self.assertIsNotNone(order_entry)
        self.assertIsNotNone(payment_entry)
        self.assertIsNotNone(delivery_entry)
        self.assertIsNotNone(outcome_entry)
        self.assertIsNotNone(governance_entry)
        self.assertEqual(order_entry.stage_scope, 9)
        self.assertEqual(order_entry.payload["commercial_status"], order.get("commercial_status"))
        self.assertEqual(payment_entry.payload["payment_status"], payment.get("payment_status"))
        self.assertEqual(delivery_entry.payload["delivery_status"], delivery.get("delivery_status"))
        self.assertEqual(outcome_entry.writeback_state["writeback_targets"], outcome.get("writeback_targets"))
        self.assertEqual(
            governance_entry.writeback_state["written_back_at_optional"],
            governance.get("written_back_at_optional"),
        )
        self.assertEqual(
            governance_entry.governed_state["governed_execution_mode"],
            governance.get("governed_execution_mode"),
        )

        replay = list_orders({"opportunity_id": order.get("opportunity_id")})
        self.assertEqual(
            replay["formal_object_refs"]["order_record"]["object_id"],
            order.get("order_id"),
        )
        self.assertEqual(
            replay["preview_projection"]["payment_draft_preview"]["payment_status"],
            payment.get("payment_status"),
        )
        self.assertEqual(
            replay["preview_projection"]["delivery_preview"]["delivery_status"],
            delivery.get("delivery_status"),
        )
        self.assertEqual(
            replay["preview_projection"]["outcome_writeback_preview"]["writeback_targets"],
            outcome.get("writeback_targets"),
        )
        self.assertEqual(
            replay["preview_projection"]["governance_feedback_preview"]["writeback_targets"],
            governance.get("writeback_targets"),
        )
        self.assertFalse(replay["live_execution_enabled"])
        self.assertTrue(replay["blocked_by_default"])
        self.assertEqual(
            replay["formal_object_refs"]["payment_record"]["object_id"],
            payment.get("payment_id"),
        )
        self.assertEqual(
            replay["formal_object_refs"]["delivery_record"]["object_id"],
            delivery.get("delivery_id"),
        )
        self.assertEqual(
            replay["formal_object_refs"]["opportunity_outcome_event"]["object_id"],
            outcome.get("outcome_event_id"),
        )
        self.assertEqual(
            replay["formal_object_refs"]["governance_feedback_event"]["object_id"],
            governance.get("governance_feedback_event_id"),
        )

    def test_stage7_repository_readback_prefers_persisted_formal_refs_over_project_lookup(self) -> None:
        stage7 = self.result["stage7"]
        original_offer = dict(stage7.record("offer_recommendation").data)
        original_legal_actor = dict(stage7.record("legal_action_actor_profile").data)
        original_procurement_actor = dict(stage7.record("procurement_decision_actor_profile").data)
        conflicting_offer = dict(original_offer)
        conflicting_offer["offer_recommendation_id"] = "OFFER-CONFLICT-PROJ-001"
        conflicting_offer["offer_recommendation_state"] = "REVIEW_REQUIRED"
        conflicting_legal_actor = dict(original_legal_actor)
        conflicting_legal_actor["actor_id"] = "ACTOR-CONFLICT-LEGAL-PROJ-001"
        conflicting_legal_actor["actionability_state"] = "BLOCKED"
        conflicting_procurement_actor = dict(original_procurement_actor)
        conflicting_procurement_actor["actor_id"] = "ACTOR-CONFLICT-PROC-PROJ-001"
        conflicting_procurement_actor["reachable_state"] = "UNREACHABLE"

        refresh_saleable_opportunity(stage7)
        OfferRecommendationRepository().save(conflicting_offer)
        LegalActionActorProfileRepository().save(conflicting_legal_actor)
        ProcurementDecisionActorProfileRepository().save(conflicting_procurement_actor)

        replay = list_saleable_opportunities(
            {"opportunity_id": stage7.record("saleable_opportunity").get("opportunity_id")}
        )
        hydrated = hydrate_stage_bundle(
            "stage7",
            {"opportunity_id": stage7.record("saleable_opportunity").get("opportunity_id")},
        )
        self.assertEqual(
            replay["formal_object_refs"]["offer_recommendation"]["object_id"],
            original_offer["offer_recommendation_id"],
        )
        self.assertEqual(
            replay["preview_projection"]["offer_summary"]["offer_recommendation_state"],
            original_offer["offer_recommendation_state"],
        )
        self.assertIsNotNone(hydrated)
        self.assertEqual(
            hydrated.record("legal_action_actor_profile").get("actor_id"),
            original_legal_actor["actor_id"],
        )
        self.assertEqual(
            hydrated.record("procurement_decision_actor_profile").get("actor_id"),
            original_procurement_actor["actor_id"],
        )

    def test_stage8_repository_readback_prefers_persisted_formal_refs_over_loose_lookup(self) -> None:
        stage8 = self.result["stage8"]
        original_contact = dict(stage8.record("contact_target").data)
        original_plan = dict(stage8.record("outreach_plan").data)
        original_touch = dict(stage8.record("touch_record").data)

        create_touch_record(stage8)

        conflicting_contact = dict(original_contact)
        conflicting_contact["contact_target_id"] = "CT-CONFLICT-PROJ-001"
        conflicting_contact["contact_target_status"] = "BLOCKED"
        conflicting_contact["contact_priority_score"] = -1

        conflicting_plan = dict(original_plan)
        conflicting_plan["outreach_plan_id"] = "PLAN-CONFLICT-PROJ-001"
        conflicting_plan["plan_status"] = "BLOCKED"
        conflicting_plan["retry_count"] = 99

        conflicting_touch = dict(original_touch)
        conflicting_touch["touch_record_id"] = "TOUCH-CONFLICT-PROJ-001"
        conflicting_touch["contact_target_id"] = conflicting_contact["contact_target_id"]
        conflicting_touch["outreach_plan_id"] = conflicting_plan["outreach_plan_id"]
        conflicting_touch["touch_record_state"] = "CANCELLED"
        conflicting_touch["feedback_reason"] = "CONFLICTING_FEEDBACK"
        conflicting_touch["writeback_targets"] = ["contact_target"]

        ContactTargetRepository().save(conflicting_contact)
        OutreachPlanRepository().save(conflicting_plan)
        TouchRecordRepository().save(conflicting_touch)

        replay = list_contact_targets({"opportunity_id": original_touch["opportunity_id"]})
        hydrated = hydrate_stage_bundle("stage8", {"opportunity_id": original_touch["opportunity_id"]})

        self.assertEqual(
            replay["preview_projection"]["touch_record_preview"]["touch_record_id"],
            original_touch["touch_record_id"],
        )
        self.assertEqual(
            replay["preview_projection"]["touch_record_preview"]["feedback_reason"],
            original_touch["feedback_reason"],
        )
        self.assertEqual(
            replay["preview_projection"]["outreach_plan_preview"]["outreach_plan_id"],
            original_plan["outreach_plan_id"],
        )
        self.assertEqual(
            replay["preview_projection"]["contact_target_preview"]["contact_target_id"],
            original_contact["contact_target_id"],
        )
        self.assertIsNotNone(hydrated)
        self.assertEqual(
            hydrated.record("touch_record").get("touch_record_id"),
            original_touch["touch_record_id"],
        )
        self.assertEqual(
            hydrated.record("outreach_plan").get("outreach_plan_id"),
            original_plan["outreach_plan_id"],
        )
        self.assertEqual(
            hydrated.record("contact_target").get("contact_target_id"),
            original_contact["contact_target_id"],
        )

    def test_stage9_repository_readback_prefers_persisted_formal_refs_over_loose_lookup(self) -> None:
        stage9 = self.result["stage9"]
        payment = dict(stage9.record("payment_record").data)
        delivery = dict(stage9.record("delivery_record").data)
        outcome = dict(stage9.record("opportunity_outcome_event").data)
        governance = dict(stage9.record("governance_feedback_event").data)

        conflicting_payment = dict(payment)
        conflicting_payment["payment_id"] = "PAY-CONFLICT-PROJ-001"
        conflicting_payment["payment_status"] = "PENDING_PAYMENT"
        conflicting_delivery = dict(delivery)
        conflicting_delivery["delivery_id"] = "DELIVERY-CONFLICT-PROJ-001"
        conflicting_delivery["delivery_status"] = "NOT_READY"
        conflicting_outcome = dict(outcome)
        conflicting_outcome["outcome_event_id"] = "OUTCOME-CONFLICT-PROJ-001"
        conflicting_outcome["outcome_family"] = "LOST"
        conflicting_governance = dict(governance)
        conflicting_governance["governance_feedback_event_id"] = "GOV-CONFLICT-PROJ-001"
        conflicting_governance["trigger_type"] = "OTHER"

        PaymentRecordRepository().save(conflicting_payment)
        DeliveryRecordRepository().save(conflicting_delivery)
        OpportunityOutcomeEventRepository().save(conflicting_outcome)
        GovernanceFeedbackEventRepository().save(conflicting_governance)
        create_governance_feedback_event(stage9)

        replay = list_orders({"opportunity_id": stage9.record("order_record").get("opportunity_id")})
        self.assertEqual(
            replay["formal_object_refs"]["payment_record"]["object_id"],
            payment["payment_id"],
        )
        self.assertEqual(
            replay["formal_object_refs"]["delivery_record"]["object_id"],
            delivery["delivery_id"],
        )
        self.assertEqual(
            replay["formal_object_refs"]["opportunity_outcome_event"]["object_id"],
            outcome["outcome_event_id"],
        )
        self.assertEqual(
            replay["formal_object_refs"]["governance_feedback_event"]["object_id"],
            governance["governance_feedback_event_id"],
        )
        self.assertEqual(
            replay["preview_projection"]["payment_draft_preview"]["payment_status"],
            payment["payment_status"],
        )
        self.assertEqual(
            replay["preview_projection"]["delivery_preview"]["delivery_status"],
            delivery["delivery_status"],
        )
        self.assertEqual(
            replay["preview_projection"]["outcome_writeback_preview"]["outcome_family"],
            outcome["outcome_family"],
        )
        self.assertEqual(
            replay["preview_projection"]["governance_feedback_preview"]["trigger_type"],
            governance["trigger_type"],
        )


if __name__ == "__main__":
    unittest.main()
