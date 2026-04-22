from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import ContractRecord, StageBundle

from storage.db import DatabaseSession
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
from storage.repository_boundary import (
    STAGE_SURFACE_IDS,
    _find_stage8_records,
    _get_stage_state,
    _get_stage_work_item,
    _persist_auxiliary_record,
    _record_from_persisted_refs,
    _resolve_stage9_stage_state,
    _resolve_typed_ref,
    _save_stage_state,
    _sync_stage_operational_loop,
)


def persist_stage7_bundle(bundle: StageBundle) -> StageBundle:
    SaleableOpportunityRepository().save(bundle.record("saleable_opportunity").data)
    OfferRecommendationRepository().save(bundle.record("offer_recommendation").data)
    BuyerFitRepository().save(bundle.record("buyer_fit").data)
    LegalActionActorProfileRepository().save(bundle.record("legal_action_actor_profile").data)
    ProcurementDecisionActorProfileRepository().save(bundle.record("procurement_decision_actor_profile").data)
    _persist_auxiliary_record(
        object_type="multi_competitor_collection",
        id_field="multi_competitor_collection_id",
        stage_scope=7,
        payload=bundle.record("multi_competitor_collection").data,
    )
    _save_stage_state(bundle)
    _sync_stage_operational_loop(bundle)
    return bundle


def persist_stage8_bundle(bundle: StageBundle) -> StageBundle:
    ContactTargetRepository().save(bundle.record("contact_target").data)
    OutreachPlanRepository().save(bundle.record("outreach_plan").data)
    TouchRecordRepository().save(bundle.record("touch_record").data)
    _save_stage_state(bundle)
    _sync_stage_operational_loop(bundle)
    return bundle


def persist_stage9_bundle(bundle: StageBundle) -> StageBundle:
    OrderRecordRepository().save(bundle.record("order_record").data)
    PaymentRecordRepository().save(bundle.record("payment_record").data)
    DeliveryRecordRepository().save(bundle.record("delivery_record").data)
    OpportunityOutcomeEventRepository().save(bundle.record("opportunity_outcome_event").data)
    GovernanceFeedbackEventRepository().save(bundle.record("governance_feedback_event").data)
    _save_stage_state(bundle)
    _sync_stage_operational_loop(bundle)
    return bundle


def hydrate_stage7_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    opportunity_id = str(payload.get("opportunity_id", "")).strip()
    if not opportunity_id:
        return None
    opportunity = SaleableOpportunityRepository().get_by_id(opportunity_id)
    if not opportunity:
        return None

    stage_state = _get_stage_state(7, STAGE_SURFACE_IDS[7], opportunity.record_id)
    work_item = _get_stage_work_item(7, "saleable_opportunity", opportunity.record_id)
    stage_inputs = dict(stage_state.inputs) if stage_state is not None else {}
    persisted_refs = stage_state.typed_object_refs if stage_state is not None else None
    buyer_fit_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("buyer_fit_id",),
    )
    buyer_fit = BuyerFitRepository().get_by_id(buyer_fit_id) if buyer_fit_id else None
    offer_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("offer_recommendation_id",),
    )
    offer = OfferRecommendationRepository().get_by_id(offer_id) if offer_id else None
    legal_actor_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("legal_action_actor_id",),
    )
    legal_actor = (
        LegalActionActorProfileRepository().get_by_id(legal_actor_id)
        if legal_actor_id
        else None
    )
    procurement_actor_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("procurement_decision_actor_id",),
    )
    procurement_actor = (
        ProcurementDecisionActorProfileRepository().get_by_id(procurement_actor_id)
        if procurement_actor_id
        else None
    )
    multi_competitor_collection_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity.object_refs,
        work_item.object_refs if work_item is not None else None,
        keys=("multi_competitor_collection_id_optional",),
    )
    multi_competitor_collection = (
        DatabaseSession.default().get_record("multi_competitor_collection", multi_competitor_collection_id)
        if multi_competitor_collection_id
        else None
    )
    if not all((buyer_fit, offer, legal_actor, procurement_actor, multi_competitor_collection, stage_state)):
        return None

    return StageBundle(
        stage=7,
        records={
            "saleable_opportunity": ContractRecord("saleable_opportunity", opportunity.as_payload()),
            "offer_recommendation": ContractRecord("offer_recommendation", offer.as_payload()),
            "buyer_fit": ContractRecord("buyer_fit", buyer_fit.as_payload()),
            "legal_action_actor_profile": ContractRecord("legal_action_actor_profile", legal_actor.as_payload()),
            "procurement_decision_actor_profile": ContractRecord(
                "procurement_decision_actor_profile",
                procurement_actor.as_payload(),
            ),
            "multi_competitor_collection": ContractRecord(
                "multi_competitor_collection",
                multi_competitor_collection.as_payload(),
            ),
        },
        handoff={},
        inputs=stage_inputs,
    )


def hydrate_stage8_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    contact_target, outreach_plan, touch_record, stage_state = _find_stage8_records(payload)
    if not all((contact_target, outreach_plan, touch_record, stage_state)):
        return None
    if stage_state.root_record_id != touch_record.record_id:
        stage_state = _get_stage_state(8, STAGE_SURFACE_IDS[8], touch_record.record_id)
    if not stage_state:
        return None

    return StageBundle(
        stage=8,
        records={
            "contact_target": ContractRecord("contact_target", contact_target.as_payload()),
            "outreach_plan": ContractRecord("outreach_plan", outreach_plan.as_payload()),
            "touch_record": ContractRecord("touch_record", touch_record.as_payload()),
        },
        handoff={},
        inputs=dict(stage_state.inputs),
    )


def hydrate_stage9_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    opportunity_id = str(payload.get("opportunity_id", "")).strip()
    stage_state = _resolve_stage9_stage_state(payload)
    order_id = str(payload.get("order_id", "")).strip() or (
        stage_state.root_record_id if stage_state is not None else ""
    )
    order = OrderRecordRepository().get_by_id(order_id) if order_id else None
    if not order and opportunity_id:
        order = OrderRecordRepository().find_one_by_field("opportunity_id", opportunity_id)
    if not order:
        return None

    if stage_state is None or stage_state.root_record_id != order.record_id:
        stage_state = _get_stage_state(9, STAGE_SURFACE_IDS[9], order.record_id)
    work_item = _get_stage_work_item(9, "order_record", order.record_id)
    persisted_refs = stage_state.typed_object_refs if stage_state is not None else None
    work_item_refs = work_item.object_refs if work_item is not None else None
    payment = _record_from_persisted_refs(
        PaymentRecordRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("payment_id",),
        fallback_field="order_id",
        fallback_value=order.record_id,
    )
    delivery = _record_from_persisted_refs(
        DeliveryRecordRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("delivery_id",),
        fallback_field="order_id",
        fallback_value=order.record_id,
    )
    outcome = _record_from_persisted_refs(
        OpportunityOutcomeEventRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("outcome_event_id",),
        fallback_field="opportunity_id",
        fallback_value=opportunity_id or str(order.object_refs.get("opportunity_id", "")).strip(),
    )
    governance = _record_from_persisted_refs(
        GovernanceFeedbackEventRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("governance_feedback_event_id",),
        fallback_field="project_id",
        fallback_value=order.project_id or "",
    )
    if not all((payment, delivery, outcome, governance, stage_state)):
        return None

    return StageBundle(
        stage=9,
        records={
            "order_record": ContractRecord("order_record", order.as_payload()),
            "payment_record": ContractRecord("payment_record", payment.as_payload()),
            "delivery_record": ContractRecord("delivery_record", delivery.as_payload()),
            "opportunity_outcome_event": ContractRecord("opportunity_outcome_event", outcome.as_payload()),
            "governance_feedback_event": ContractRecord("governance_feedback_event", governance.as_payload()),
        },
        handoff={},
        inputs=dict(stage_state.inputs),
    )
