from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import ContractRecord, StageBundle

from stage7_sales.crm_quote_workbench import (
    CRM_ACTION_ID_INPUT_KEY,
    CRM_QUOTE_WORKBENCH_INPUT_KEY,
    CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY,
    QUOTE_DRAFT_ID_INPUT_KEY,
    build_crm_quote_workbench_readiness_summary,
)
from stage7_sales.leadpack_delivery_package import (
    LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY,
    LEADPACK_DELIVERY_PACKAGE_INPUT_KEY,
    LEADPACK_DELIVERY_READINESS_INPUT_KEY,
    LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY,
    LEADPACK_PACKAGE_ID_INPUT_KEY,
    LEADPACK_PAGE_DRAFT_ID_INPUT_KEY,
    build_leadpack_delivery_readiness_summary,
)
from stage8_outreach.execution_outbox import (
    OUTBOX_ID_INPUT_KEY,
    OUTBOX_READINESS_INPUT_KEY,
    OUTBOX_SNAPSHOT_INPUT_KEY,
    build_outbox_readiness_summary,
)
from stage9_delivery.order_payment_delivery_execution import (
    PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY,
    build_stage9_execution_ledger_readiness_summary,
)
from storage.db import DatabaseSession, PersistedStageState, build_persisted_at
from storage.repositories import (
    BuyerFitRepository,
    ChallengerCandidateProfileRepository,
    ContactCandidateCollectionRepository,
    ContactSelectionTraceRepository,
    ContactTargetRepository,
    CRMQuoteWorkbenchRepository,
    DeliveryRecordRepository,
    GovernanceFeedbackEventRepository,
    LegalActionActorProfileRepository,
    LegalActionRecommendationRepository,
    LeadpackDeliveryPackageRepository,
    OfferRecommendationRepository,
    OpportunityOutcomeEventRepository,
    OrderRecordRepository,
    OutreachExecutionOutboxRepository,
    OutreachPlanRepository,
    PaymentRecordRepository,
    ProcurementDecisionActorProfileRepository,
    ProjectFactRepository,
    ReportRecordRepository,
    ReviewQueueProfileRepository,
    SaleableOpportunityRepository,
    Stage9ExecutionLedgerRepository,
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

STAGE6_SURFACE_ID = "stage6_fact_review"
_STAGE6_HANDOFF_SNAPSHOT_KEY = "_stage6_handoff_snapshot"
_STAGE6_TRACE_RULES_SNAPSHOT_KEY = "_stage6_trace_rules_snapshot"
_STAGE6_PRODUCT_PACKAGE_READINESS_KEY = "stage6_product_package_readiness"
_STAGE6_TYPED_REF_KEYS = (
    "project_fact_id",
    "report_record_id",
    "review_queue_profile_id",
    "challenger_candidate_profile_id",
    "action_id",
    "private_supplement_record_id_optional",
)
_STAGE7_HANDOFF_SNAPSHOT_KEY = "_stage7_handoff_snapshot"
_STAGE7_TRACE_RULES_SNAPSHOT_KEY = "_stage7_trace_rules_snapshot"
_STAGE8_HANDOFF_SNAPSHOT_KEY = "_stage8_handoff_snapshot"
_STAGE8_TRACE_RULES_SNAPSHOT_KEY = "_stage8_trace_rules_snapshot"
_STAGE9_HANDOFF_SNAPSHOT_KEY = "_stage9_handoff_snapshot"
_STAGE9_TRACE_RULES_SNAPSHOT_KEY = "_stage9_trace_rules_snapshot"


def _stage6_inputs_snapshot(bundle: StageBundle) -> dict[str, Any]:
    snapshot = {
        key: value
        for key, value in dict(bundle.inputs).items()
        if value not in (None, "")
    }
    snapshot[_STAGE6_HANDOFF_SNAPSHOT_KEY] = dict(bundle.handoff)
    if bundle.trace_rules:
        snapshot[_STAGE6_TRACE_RULES_SNAPSHOT_KEY] = list(bundle.trace_rules)
    return snapshot


def _stage6_typed_object_refs(bundle: StageBundle) -> dict[str, str]:
    refs = {
        "project_fact_id": str(bundle.record("project_fact").get("project_fact_id")),
        "report_record_id": str(bundle.record("report_record").get("report_id")),
        "review_queue_profile_id": str(bundle.record("review_queue_profile").get("queue_profile_id")),
        "challenger_candidate_profile_id": str(
            bundle.record("challenger_candidate_profile").get("challenger_profile_id")
        ),
        "action_id": str(bundle.record("legal_action_recommendation").get("action_id")),
    }
    supplement = _stage6_private_supplement_payload(bundle.inputs)
    if supplement:
        refs["private_supplement_record_id_optional"] = str(supplement["supplement_id"])
    return refs


def _stage6_private_supplement_payload(inputs: Mapping[str, Any]) -> dict[str, Any]:
    supplement = inputs.get("private_supplement_record_optional")
    return dict(supplement) if isinstance(supplement, Mapping) else {}


def _stage6_private_supplement_summary(
    supplement: Mapping[str, Any],
    *,
    stage_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    existing = stage_inputs.get("private_supplement_carrier_summary")
    if isinstance(existing, Mapping) and existing.get("supplement_id") == supplement.get("supplement_id"):
        return dict(existing)
    release_state = str(supplement.get("release_state", "ISOLATED"))
    usable_scope = str(supplement.get("usable_scope", "BLOCKED"))
    written_back_policy = str(supplement.get("written_back_policy", "GOVERNANCE_SINK_ONLY"))
    stage6_internal_runtime_allowed = release_state in {"REVIEW_ELIGIBLE", "IMPACT_ELIGIBLE"} and usable_scope != "BLOCKED"
    return {
        "supplement_id": supplement.get("supplement_id"),
        "project_id": supplement.get("project_id"),
        "linked_review_request_id": supplement.get("linked_review_request_id"),
        "release_state": release_state,
        "usable_scope": usable_scope,
        "written_back_policy": written_back_policy,
        "supplement_loop_state": stage_inputs.get("supplement_loop_state", "REQUESTED"),
        "impact_readiness_state": release_state,
        "impact_decision_trace": {
            "source": "stage6_private_supplement_record",
            "stage6_internal_runtime_allowed": stage6_internal_runtime_allowed,
            "stage6_internal_impact_allowed": release_state == "IMPACT_ELIGIBLE" and stage6_internal_runtime_allowed,
            "stage7_formal_surface_allowed": False,
            "external_or_live_allowed": False,
            "missing_condition_family_optional": stage_inputs.get("missing_condition_family_optional"),
        },
    }


def _hydrate_stage6_private_supplement(
    *,
    stage_inputs: Mapping[str, Any],
    persisted_refs: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    supplement_id = _resolve_typed_ref(
        persisted_refs,
        keys=("private_supplement_record_id_optional", "private_supplement_record_id"),
    )
    if supplement_id:
        record = DatabaseSession.default().get_record("private_supplement_record", supplement_id)
        if record is None:
            return None, True
        return record.as_payload(), False

    snapshot = stage_inputs.get("private_supplement_record_optional")
    if isinstance(snapshot, Mapping):
        return dict(snapshot), False
    return None, False


def _restore_stage6_private_supplement_carrier(
    *,
    stage_inputs: dict[str, Any],
    handoff: dict[str, Any],
    supplement: Mapping[str, Any] | None,
) -> None:
    if supplement is None:
        return
    supplement_payload = dict(supplement)
    summary = _stage6_private_supplement_summary(supplement_payload, stage_inputs=stage_inputs)
    stage_inputs["private_supplement_record_optional"] = supplement_payload
    stage_inputs["private_supplement_carrier_summary"] = summary
    review_trace = stage_inputs.get("stage6_review_report_trace")
    if isinstance(review_trace, Mapping):
        review_trace_payload = dict(review_trace)
        supplement_trace = dict(review_trace_payload.get("supplement_trace", {}))
        supplement_trace["private_supplement_carrier_summary"] = summary
        supplement_trace["impact_readiness_state"] = summary["impact_readiness_state"]
        supplement_trace["impact_decision_trace"] = summary["impact_decision_trace"]
        review_trace_payload["supplement_trace"] = supplement_trace
        stage_inputs["stage6_review_report_trace"] = review_trace_payload
    handoff["private_supplement_record_id_optional"] = str(summary["supplement_id"])
    handoff["private_supplement_release_state_optional"] = str(summary["release_state"])
    handoff["private_supplement_usable_scope_optional"] = str(summary["usable_scope"])
    handoff["private_supplement_written_back_policy_optional"] = str(summary["written_back_policy"])
    handoff["private_supplement_carrier_summary"] = summary


def _restore_stage6_product_package_readiness(
    *,
    stage_inputs: dict[str, Any],
    handoff: dict[str, Any],
) -> None:
    carrier = stage_inputs.get(_STAGE6_PRODUCT_PACKAGE_READINESS_KEY)
    if not isinstance(carrier, Mapping):
        return
    carrier_payload = dict(carrier)
    stage_inputs[_STAGE6_PRODUCT_PACKAGE_READINESS_KEY] = carrier_payload
    handoff[_STAGE6_PRODUCT_PACKAGE_READINESS_KEY] = carrier_payload
    review_trace = stage_inputs.get("stage6_review_report_trace")
    if isinstance(review_trace, Mapping):
        review_trace_payload = dict(review_trace)
        review_trace_payload["product_package_readiness"] = carrier_payload
        stage_inputs["stage6_review_report_trace"] = review_trace_payload


def _latest_stage6_state(project_id: str) -> PersistedStageState | None:
    if not project_id:
        return None
    rows = DatabaseSession.default().find_stage_states(
        stage_scope=6,
        surface_id=STAGE6_SURFACE_ID,
        project_id=project_id,
    )
    if not rows:
        return None
    rows.sort(
        key=lambda row: (
            str(row.persisted_at or ""),
            str(row.root_record_id or ""),
        ),
        reverse=True,
    )
    return rows[0]


def _payload_stage6_typed_refs(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: value
        for key in _STAGE6_TYPED_REF_KEYS
        if (value := str(payload.get(key, "")).strip())
    }


def _stage6_stage_state_from_payload(
    payload: Mapping[str, Any],
    *,
    project_fact_project_id: str = "",
    report_project_id: str = "",
    review_queue_project_id: str = "",
    challenger_project_id: str = "",
    action_project_id: str = "",
) -> PersistedStageState | None:
    project_fact_id = str(payload.get("project_fact_id", "")).strip()
    if project_fact_id:
        return DatabaseSession.default().get_stage_state(6, STAGE6_SURFACE_ID, project_fact_id)

    project_id = next(
        (
            candidate
            for candidate in (
                project_fact_project_id,
                report_project_id,
                review_queue_project_id,
                challenger_project_id,
                action_project_id,
                str(payload.get("project_id", "")).strip(),
            )
            if candidate
        ),
        "",
    )
    return _latest_stage6_state(project_id)


def _build_stage6_handoff(
    *,
    project_fact: ContractRecord,
    report_record: ContractRecord,
    review_queue_profile: ContractRecord,
    challenger_candidate_profile: ContractRecord,
    legal_action_recommendation: ContractRecord,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    handoff = {
        "project_id": project_fact.get("project_id"),
        "project_fact_id": project_fact.get("project_fact_id"),
        "review_queue_profile_id": review_queue_profile.get("queue_profile_id"),
        "review_lane": review_queue_profile.get("review_lane"),
        "review_priority_score": review_queue_profile.get("review_priority_score"),
        "review_queue_bucket": review_queue_profile.get("review_queue_bucket"),
        "window_risk_level": review_queue_profile.get("window_risk_level"),
        "commercial_urgency_level": review_queue_profile.get("commercial_urgency_level"),
        "sale_gate_status": project_fact.get("sale_gate_status"),
        "real_competitor_count": project_fact.get("real_competitor_count"),
        "competitor_quality_grade": project_fact.get("competitor_quality_grade"),
        "window_status": legal_action_recommendation.get("window_status"),
        "report_id": report_record.get("report_id"),
        "report_record_id": report_record.get("report_id"),
        "report_status": report_record.get("report_status"),
        "review_task_status": report_record.get("review_task_status"),
        "minimum_release_level": report_record.get("minimum_release_level"),
        "action_family": legal_action_recommendation.get("action_family"),
        "recommended_next_step": legal_action_recommendation.get("recommended_next_step"),
        "challenger_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
        "challenger_candidate_profile_id": challenger_candidate_profile.get("challenger_profile_id"),
        "focus_bidder_id": challenger_candidate_profile.get("focus_bidder_id"),
        "challenger_bidder_id": challenger_candidate_profile.get("challenger_bidder_id"),
        "candidate_position_label": challenger_candidate_profile.get("candidate_position_label"),
        "challenge_actionability_score": challenger_candidate_profile.get("challenge_actionability_score"),
        "execution_readiness_score": challenger_candidate_profile.get("execution_readiness_score"),
        "saleability_status": inputs.get("saleability_status", "CANDIDATE"),
    }
    for field_name in (
        "confidence_score_optional",
        "linked_review_request_id_optional",
        "missing_condition_family_optional",
        "private_supplement_record_id_optional",
        "private_supplement_release_state_optional",
        "private_supplement_usable_scope_optional",
        "private_supplement_written_back_policy_optional",
        "private_supplement_carrier_summary",
        _STAGE6_PRODUCT_PACKAGE_READINESS_KEY,
        "legal_action_actor_org_name_seed",
        "procurement_decision_actor_org_name_seed",
        "buyer_type_hint",
    ):
        if inputs.get(field_name) not in (None, ""):
            handoff[field_name] = inputs[field_name]
    return handoff


def persist_stage6_bundle(bundle: StageBundle) -> StageBundle:
    project_fact = ProjectFactRepository().save(bundle.record("project_fact").data)
    report_record = ReportRecordRepository().save(bundle.record("report_record").data)
    review_queue_profile = ReviewQueueProfileRepository().save(bundle.record("review_queue_profile").data)
    challenger_candidate_profile = ChallengerCandidateProfileRepository().save(
        bundle.record("challenger_candidate_profile").data
    )
    legal_action_recommendation = LegalActionRecommendationRepository().save(
        bundle.record("legal_action_recommendation").data
    )
    private_supplement = _stage6_private_supplement_payload(bundle.inputs)
    private_supplement_record = (
        _persist_auxiliary_record(
            object_type="private_supplement_record",
            id_field="supplement_id",
            stage_scope=6,
            payload=private_supplement,
        )
        if private_supplement
        else None
    )
    typed_object_refs = {
        **_stage6_typed_object_refs(bundle),
        "project_fact_id": str(project_fact.record_id),
        "report_record_id": str(report_record.record_id),
        "review_queue_profile_id": str(review_queue_profile.record_id),
        "challenger_candidate_profile_id": str(challenger_candidate_profile.record_id),
        "action_id": str(legal_action_recommendation.record_id),
    }
    if private_supplement_record is not None:
        typed_object_refs["private_supplement_record_id_optional"] = str(
            private_supplement_record.record_id
        )
    DatabaseSession.default().upsert_stage_state(
        PersistedStageState(
            stage_scope=6,
            project_id=str(project_fact.project_id or report_record.project_id or ""),
            surface_id=STAGE6_SURFACE_ID,
            root_object_type="project_fact",
            root_record_id=str(project_fact.record_id),
            inputs=_stage6_inputs_snapshot(bundle),
            persisted_at=build_persisted_at(),
            typed_object_refs=typed_object_refs,
        )
    )
    return bundle


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
    workbench_payload = _stage7_crm_quote_workbench_payload(bundle)
    if workbench_payload:
        CRMQuoteWorkbenchRepository().save(workbench_payload)
    leadpack_package_payload = _stage7_leadpack_delivery_package_payload(bundle)
    if leadpack_package_payload:
        LeadpackDeliveryPackageRepository().save(leadpack_package_payload)
    persisted_bundle = _stage7_bundle_with_persistence_snapshots(bundle)
    _save_stage_state(persisted_bundle)
    _sync_stage_operational_loop(persisted_bundle)
    return persisted_bundle


def _stage7_crm_quote_workbench_payload(bundle: StageBundle) -> dict[str, Any]:
    snapshot = bundle.inputs.get(CRM_QUOTE_WORKBENCH_INPUT_KEY)
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _stage7_leadpack_delivery_package_payload(bundle: StageBundle) -> dict[str, Any]:
    snapshot = bundle.inputs.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY)
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _stage7_bundle_with_persistence_snapshots(bundle: StageBundle) -> StageBundle:
    inputs = dict(bundle.inputs)
    inputs[_STAGE7_HANDOFF_SNAPSHOT_KEY] = dict(bundle.handoff)
    if bundle.trace_rules:
        inputs[_STAGE7_TRACE_RULES_SNAPSHOT_KEY] = list(bundle.trace_rules)
    return StageBundle(
        stage=bundle.stage,
        records=dict(bundle.records),
        handoff=dict(bundle.handoff),
        trace_rules=list(bundle.trace_rules),
        inputs=inputs,
    )


def _stage8_carrier_payload(
    bundle: StageBundle,
    *,
    object_type: str,
    input_key: str,
) -> dict[str, Any]:
    record = bundle.records.get(object_type)
    if record is not None:
        return dict(record.data)
    snapshot = bundle.inputs.get(input_key)
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _stage8_bundle_with_persistence_snapshots(bundle: StageBundle) -> StageBundle:
    inputs = dict(bundle.inputs)
    inputs[_STAGE8_HANDOFF_SNAPSHOT_KEY] = dict(bundle.handoff)
    if bundle.trace_rules:
        inputs[_STAGE8_TRACE_RULES_SNAPSHOT_KEY] = list(bundle.trace_rules)
    return StageBundle(
        stage=bundle.stage,
        records=dict(bundle.records),
        handoff=dict(bundle.handoff),
        trace_rules=list(bundle.trace_rules),
        inputs=inputs,
    )


def _stage8_outbox_payload(bundle: StageBundle) -> dict[str, Any]:
    snapshot = bundle.inputs.get(OUTBOX_SNAPSHOT_INPUT_KEY)
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def persist_stage8_bundle(bundle: StageBundle) -> StageBundle:
    contact_candidate_collection = _stage8_carrier_payload(
        bundle,
        object_type="contact_candidate_collection",
        input_key="contact_candidate_collection_snapshot",
    )
    contact_selection_trace = _stage8_carrier_payload(
        bundle,
        object_type="contact_selection_trace",
        input_key="contact_selection_trace_snapshot",
    )
    if contact_candidate_collection:
        ContactCandidateCollectionRepository().save(contact_candidate_collection)
    if contact_selection_trace:
        ContactSelectionTraceRepository().save(contact_selection_trace)
    outbox_payload = _stage8_outbox_payload(bundle)
    if outbox_payload:
        OutreachExecutionOutboxRepository().save(outbox_payload)
    ContactTargetRepository().save(bundle.record("contact_target").data)
    OutreachPlanRepository().save(bundle.record("outreach_plan").data)
    TouchRecordRepository().save(bundle.record("touch_record").data)
    persisted_bundle = _stage8_bundle_with_persistence_snapshots(bundle)
    _save_stage_state(persisted_bundle)
    _sync_stage_operational_loop(persisted_bundle)
    return persisted_bundle


def _stage9_bundle_with_persistence_snapshots(bundle: StageBundle) -> StageBundle:
    inputs = dict(bundle.inputs)
    inputs[_STAGE9_HANDOFF_SNAPSHOT_KEY] = dict(bundle.handoff)
    if bundle.trace_rules:
        inputs[_STAGE9_TRACE_RULES_SNAPSHOT_KEY] = list(bundle.trace_rules)
    return StageBundle(
        stage=bundle.stage,
        records=dict(bundle.records),
        handoff=dict(bundle.handoff),
        trace_rules=list(bundle.trace_rules),
        inputs=inputs,
    )


def persist_stage9_bundle(bundle: StageBundle) -> StageBundle:
    OrderRecordRepository().save(bundle.record("order_record").data)
    PaymentRecordRepository().save(bundle.record("payment_record").data)
    DeliveryRecordRepository().save(bundle.record("delivery_record").data)
    OpportunityOutcomeEventRepository().save(bundle.record("opportunity_outcome_event").data)
    GovernanceFeedbackEventRepository().save(bundle.record("governance_feedback_event").data)
    execution_ledger = _stage9_execution_ledger_payload(bundle)
    if execution_ledger:
        Stage9ExecutionLedgerRepository().save(execution_ledger)
    persisted_bundle = _stage9_bundle_with_persistence_snapshots(bundle)
    _save_stage_state(persisted_bundle)
    _sync_stage_operational_loop(persisted_bundle)
    return persisted_bundle


def _stage9_execution_ledger_payload(bundle: StageBundle) -> dict[str, Any]:
    snapshot = bundle.inputs.get(STAGE9_EXECUTION_LEDGER_INPUT_KEY)
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _hydrate_stage7_crm_quote_workbench(
    *,
    stage_inputs: Mapping[str, Any],
    persisted_refs: Mapping[str, Any] | None,
    opportunity_refs: Mapping[str, Any],
    work_item_refs: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    crm_action_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity_refs,
        work_item_refs,
        keys=("crm_action_id", CRM_ACTION_ID_INPUT_KEY),
    )
    provider_execution_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity_refs,
        work_item_refs,
        keys=("provider_execution_id",),
    )
    quote_draft_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity_refs,
        work_item_refs,
        keys=("quote_draft_id", QUOTE_DRAFT_ID_INPUT_KEY),
    )
    repository = CRMQuoteWorkbenchRepository()
    record = repository.get_by_id(crm_action_id) if crm_action_id else None
    if record is None and quote_draft_id:
        record = repository.get_by_quote_draft_id(quote_draft_id)
    if record is None and provider_execution_id:
        record = repository.get_by_provider_execution_id(provider_execution_id)
    if record is None:
        if crm_action_id or quote_draft_id or provider_execution_id:
            return None, True
        snapshot = stage_inputs.get(CRM_QUOTE_WORKBENCH_INPUT_KEY)
        return (dict(snapshot), False) if isinstance(snapshot, Mapping) else (None, False)

    payload = record.as_payload()
    if crm_action_id and str(payload.get("crm_action_id", "")).strip() != crm_action_id:
        return None, True
    if quote_draft_id and str(payload.get("quote_draft_id", "")).strip() != quote_draft_id:
        return None, True
    if provider_execution_id and str(payload.get("provider_execution_id", "")).strip() != provider_execution_id:
        return None, True
    return payload, False


def _restore_stage7_crm_quote_workbench(
    *,
    stage_inputs: dict[str, Any],
    handoff: dict[str, Any],
    workbench: Mapping[str, Any] | None,
) -> None:
    if not workbench:
        return
    workbench_payload = dict(workbench)
    readiness_summary = build_crm_quote_workbench_readiness_summary(workbench_payload)
    stage_inputs[CRM_QUOTE_WORKBENCH_INPUT_KEY] = workbench_payload
    stage_inputs[CRM_QUOTE_WORKBENCH_READINESS_INPUT_KEY] = readiness_summary
    stage_inputs["provider_execution_id"] = str(workbench_payload.get("provider_execution_id"))
    stage_inputs[CRM_ACTION_ID_INPUT_KEY] = str(workbench_payload.get("crm_action_id"))
    stage_inputs[QUOTE_DRAFT_ID_INPUT_KEY] = str(workbench_payload.get("quote_draft_id"))
    handoff["crm_quote_workbench_optional"] = workbench_payload
    handoff["provider_execution_id"] = str(workbench_payload.get("provider_execution_id"))
    handoff[CRM_ACTION_ID_INPUT_KEY] = str(workbench_payload.get("crm_action_id"))
    handoff[QUOTE_DRAFT_ID_INPUT_KEY] = str(workbench_payload.get("quote_draft_id"))
    resolution_trace = stage_inputs.get("stage7_resolution_trace")
    if isinstance(resolution_trace, Mapping):
        resolution_trace_payload = dict(resolution_trace)
        resolution_trace_payload[CRM_QUOTE_WORKBENCH_INPUT_KEY] = workbench_payload
        stage_inputs["stage7_resolution_trace"] = resolution_trace_payload


def _hydrate_stage7_leadpack_delivery_package(
    *,
    stage_inputs: Mapping[str, Any],
    persisted_refs: Mapping[str, Any] | None,
    opportunity_refs: Mapping[str, Any],
    work_item_refs: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    package_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity_refs,
        work_item_refs,
        keys=("package_id", LEADPACK_PACKAGE_ID_INPUT_KEY),
    )
    evidence_pack_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity_refs,
        work_item_refs,
        keys=("evidence_pack_id", LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY),
    )
    page_draft_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity_refs,
        work_item_refs,
        keys=("page_draft_id", LEADPACK_PAGE_DRAFT_ID_INPUT_KEY),
    )
    artifact_manifest_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        opportunity_refs,
        work_item_refs,
        keys=("artifact_manifest_id", LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY),
    )
    repository = LeadpackDeliveryPackageRepository()
    record = repository.get_by_id(package_id) if package_id else None
    if record is None and evidence_pack_id:
        record = repository.get_by_evidence_pack_id(evidence_pack_id)
    if record is None and page_draft_id:
        record = repository.get_by_page_draft_id(page_draft_id)
    if record is None and artifact_manifest_id:
        record = repository.get_by_artifact_manifest_id(artifact_manifest_id)
    if record is None:
        if package_id or evidence_pack_id or page_draft_id or artifact_manifest_id:
            return None, True
        snapshot = stage_inputs.get(LEADPACK_DELIVERY_PACKAGE_INPUT_KEY)
        return (dict(snapshot), False) if isinstance(snapshot, Mapping) else (None, False)

    payload = record.as_payload()
    if package_id and str(payload.get("package_id", "")).strip() != package_id:
        return None, True
    if evidence_pack_id and str(payload.get("evidence_pack_id", "")).strip() != evidence_pack_id:
        return None, True
    if page_draft_id and str(payload.get("page_draft_id", "")).strip() != page_draft_id:
        return None, True
    if artifact_manifest_id and str(payload.get("artifact_manifest_id", "")).strip() != artifact_manifest_id:
        return None, True
    return payload, False


def _restore_stage7_leadpack_delivery_package(
    *,
    stage_inputs: dict[str, Any],
    handoff: dict[str, Any],
    leadpack_package: Mapping[str, Any] | None,
) -> None:
    if not leadpack_package:
        return
    package_payload = dict(leadpack_package)
    readiness_summary = build_leadpack_delivery_readiness_summary(package_payload)
    stage_inputs[LEADPACK_DELIVERY_PACKAGE_INPUT_KEY] = package_payload
    stage_inputs[LEADPACK_DELIVERY_READINESS_INPUT_KEY] = readiness_summary
    stage_inputs[LEADPACK_PACKAGE_ID_INPUT_KEY] = str(package_payload.get("package_id"))
    stage_inputs[LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY] = str(package_payload.get("evidence_pack_id"))
    stage_inputs[LEADPACK_PAGE_DRAFT_ID_INPUT_KEY] = str(package_payload.get("page_draft_id"))
    stage_inputs[LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY] = str(package_payload.get("artifact_manifest_id"))
    handoff["leadpack_delivery_package_optional"] = package_payload
    handoff[LEADPACK_PACKAGE_ID_INPUT_KEY] = str(package_payload.get("package_id"))
    handoff[LEADPACK_EVIDENCE_PACK_ID_INPUT_KEY] = str(package_payload.get("evidence_pack_id"))
    handoff[LEADPACK_PAGE_DRAFT_ID_INPUT_KEY] = str(package_payload.get("page_draft_id"))
    handoff[LEADPACK_ARTIFACT_MANIFEST_ID_INPUT_KEY] = str(package_payload.get("artifact_manifest_id"))
    resolution_trace = stage_inputs.get("stage7_resolution_trace")
    if isinstance(resolution_trace, Mapping):
        resolution_trace_payload = dict(resolution_trace)
        resolution_trace_payload[LEADPACK_DELIVERY_PACKAGE_INPUT_KEY] = {
            "package_id": package_payload.get("package_id"),
            "evidence_pack_id": package_payload.get("evidence_pack_id"),
            "page_draft_id": package_payload.get("page_draft_id"),
            "artifact_manifest_id": package_payload.get("artifact_manifest_id"),
            "package_state": package_payload.get("package_state"),
            "page_state": package_payload.get("page_state"),
            "delivery_state": package_payload.get("delivery_state"),
            "customer_visible_enabled": bool(package_payload.get("customer_visible_enabled", False)),
            "customer_visible_export_enabled": bool(
                package_payload.get("customer_visible_export_enabled", False)
            ),
            "page_publication_enabled": bool(package_payload.get("page_publication_enabled", False)),
            "export_artifact_generation_enabled": bool(
                package_payload.get("export_artifact_generation_enabled", False)
            ),
            "external_delivery_enabled": False,
            "approved_customer_visible_unlock_summary": dict(
                package_payload.get("approved_customer_visible_unlock_summary", {})
            ),
        }
        stage_inputs["stage7_resolution_trace"] = resolution_trace_payload


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
    workbench_payload, workbench_stale = _hydrate_stage7_crm_quote_workbench(
        stage_inputs=stage_inputs,
        persisted_refs=persisted_refs,
        opportunity_refs=opportunity.object_refs,
        work_item_refs=work_item.object_refs if work_item is not None else None,
    )
    if workbench_stale:
        return None
    leadpack_package_payload, leadpack_package_stale = _hydrate_stage7_leadpack_delivery_package(
        stage_inputs=stage_inputs,
        persisted_refs=persisted_refs,
        opportunity_refs=opportunity.object_refs,
        work_item_refs=work_item.object_refs if work_item is not None else None,
    )
    if leadpack_package_stale:
        return None
    trace_rules = list(stage_inputs.pop(_STAGE7_TRACE_RULES_SNAPSHOT_KEY, []))
    handoff_snapshot = stage_inputs.pop(_STAGE7_HANDOFF_SNAPSHOT_KEY, None)
    handoff = dict(handoff_snapshot) if isinstance(handoff_snapshot, Mapping) else {}
    _restore_stage7_crm_quote_workbench(
        stage_inputs=stage_inputs,
        handoff=handoff,
        workbench=workbench_payload,
    )
    _restore_stage7_leadpack_delivery_package(
        stage_inputs=stage_inputs,
        handoff=handoff,
        leadpack_package=leadpack_package_payload,
    )

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
        handoff=handoff,
        trace_rules=trace_rules,
        inputs=stage_inputs,
    )


def hydrate_stage6_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    project_fact_id = str(payload.get("project_fact_id", "")).strip()
    report_record_id = str(payload.get("report_record_id", "")).strip()
    review_queue_profile_id = str(payload.get("review_queue_profile_id", "")).strip()
    challenger_candidate_profile_id = str(payload.get("challenger_candidate_profile_id", "")).strip()
    action_id = str(payload.get("action_id", "")).strip()

    project_fact_from_payload = (
        ProjectFactRepository().get_by_id(project_fact_id) if project_fact_id else None
    )
    if project_fact_id and project_fact_from_payload is None:
        return None
    report_record_from_payload = (
        ReportRecordRepository().get_by_id(report_record_id) if report_record_id else None
    )
    if report_record_id and report_record_from_payload is None:
        return None
    review_queue_profile_from_payload = (
        ReviewQueueProfileRepository().get_by_id(review_queue_profile_id)
        if review_queue_profile_id
        else None
    )
    if review_queue_profile_id and review_queue_profile_from_payload is None:
        return None
    challenger_candidate_profile_from_payload = (
        ChallengerCandidateProfileRepository().get_by_id(challenger_candidate_profile_id)
        if challenger_candidate_profile_id
        else None
    )
    if challenger_candidate_profile_id and challenger_candidate_profile_from_payload is None:
        return None
    legal_action_recommendation_from_payload = (
        LegalActionRecommendationRepository().get_by_id(action_id) if action_id else None
    )
    if action_id and legal_action_recommendation_from_payload is None:
        return None

    stage_state = _stage6_stage_state_from_payload(
        payload,
        project_fact_project_id=str(project_fact_from_payload.project_id or "") if project_fact_from_payload else "",
        report_project_id=str(report_record_from_payload.project_id or "") if report_record_from_payload else "",
        review_queue_project_id=str(review_queue_profile_from_payload.project_id or "")
        if review_queue_profile_from_payload
        else "",
        challenger_project_id=str(challenger_candidate_profile_from_payload.project_id or "")
        if challenger_candidate_profile_from_payload
        else "",
        action_project_id=str(legal_action_recommendation_from_payload.project_id or "")
        if legal_action_recommendation_from_payload
        else "",
    )
    if stage_state is None:
        return None

    payload_typed_refs = _payload_stage6_typed_refs(payload)
    if any(
        stage_state.typed_object_refs.get(key) not in (None, "", value)
        for key, value in payload_typed_refs.items()
    ):
        return None

    persisted_refs = stage_state.typed_object_refs
    stage_inputs = dict(stage_state.inputs)
    private_supplement, private_supplement_stale = _hydrate_stage6_private_supplement(
        stage_inputs=stage_inputs,
        persisted_refs=persisted_refs,
    )
    if private_supplement_stale:
        return None
    project_id = str(stage_state.project_id or "").strip()
    project_fact = _record_from_persisted_refs(
        ProjectFactRepository(),
        ref_sources=(persisted_refs,),
        ref_keys=("project_fact_id",),
        fallback_field="project_id",
        fallback_value=project_id,
    )
    report_record = _record_from_persisted_refs(
        ReportRecordRepository(),
        ref_sources=(persisted_refs,),
        ref_keys=("report_record_id",),
        fallback_field="project_id",
        fallback_value=project_id,
    )
    review_queue_profile = _record_from_persisted_refs(
        ReviewQueueProfileRepository(),
        ref_sources=(persisted_refs,),
        ref_keys=("review_queue_profile_id",),
        fallback_field="project_id",
        fallback_value=project_id,
    )
    challenger_candidate_profile = _record_from_persisted_refs(
        ChallengerCandidateProfileRepository(),
        ref_sources=(persisted_refs,),
        ref_keys=("challenger_candidate_profile_id",),
        fallback_field="project_id",
        fallback_value=project_id,
    )
    legal_action_recommendation = _record_from_persisted_refs(
        LegalActionRecommendationRepository(),
        ref_sources=(persisted_refs,),
        ref_keys=("action_id",),
        fallback_field="project_id",
        fallback_value=project_id,
    )
    if not all(
        (
            project_fact,
            report_record,
            review_queue_profile,
            challenger_candidate_profile,
            legal_action_recommendation,
        )
    ):
        return None

    trace_rules = list(stage_inputs.pop(_STAGE6_TRACE_RULES_SNAPSHOT_KEY, []))
    handoff_snapshot = stage_inputs.pop(_STAGE6_HANDOFF_SNAPSHOT_KEY, None)
    records = {
        "project_fact": ContractRecord("project_fact", project_fact.as_payload()),
        "report_record": ContractRecord("report_record", report_record.as_payload()),
        "review_queue_profile": ContractRecord(
            "review_queue_profile",
            review_queue_profile.as_payload(),
        ),
        "challenger_candidate_profile": ContractRecord(
            "challenger_candidate_profile",
            challenger_candidate_profile.as_payload(),
        ),
        "legal_action_recommendation": ContractRecord(
            "legal_action_recommendation",
            legal_action_recommendation.as_payload(),
        ),
    }
    handoff = (
        dict(handoff_snapshot)
        if isinstance(handoff_snapshot, Mapping)
        else _build_stage6_handoff(
            project_fact=records["project_fact"],
            report_record=records["report_record"],
            review_queue_profile=records["review_queue_profile"],
            challenger_candidate_profile=records["challenger_candidate_profile"],
            legal_action_recommendation=records["legal_action_recommendation"],
            inputs=stage_inputs,
        )
    )
    _restore_stage6_private_supplement_carrier(
        stage_inputs=stage_inputs,
        handoff=handoff,
        supplement=private_supplement,
    )
    _restore_stage6_product_package_readiness(
        stage_inputs=stage_inputs,
        handoff=handoff,
    )
    return StageBundle(
        stage=6,
        records=records,
        handoff=handoff,
        trace_rules=trace_rules,
        inputs=stage_inputs,
    )


def _stage8_repo_record(
    repository: Any,
    *,
    stage_inputs: Mapping[str, Any],
    persisted_refs: Mapping[str, Any],
    ref_keys: tuple[str, ...],
) -> tuple[dict[str, Any] | None, bool]:
    record_id = _resolve_typed_ref(persisted_refs, stage_inputs, keys=ref_keys)
    if not record_id:
        return None, False
    record = repository.get_by_id(record_id)
    if record is None:
        return None, True
    return record.as_payload(), False


def _hydrate_stage8_carriers(
    *,
    stage_inputs: Mapping[str, Any],
    persisted_refs: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None] | None:
    contact_candidate_collection, collection_stale = _stage8_repo_record(
        ContactCandidateCollectionRepository(),
        stage_inputs=stage_inputs,
        persisted_refs=persisted_refs,
        ref_keys=("contact_candidate_collection_id", "contact_candidate_collection_id_optional"),
    )
    if collection_stale:
        return None
    contact_selection_trace, selection_stale = _stage8_repo_record(
        ContactSelectionTraceRepository(),
        stage_inputs=stage_inputs,
        persisted_refs=persisted_refs,
        ref_keys=("contact_selection_trace_id", "contact_selection_trace_id_optional"),
    )
    if selection_stale:
        return None

    if contact_candidate_collection is not None and contact_selection_trace is None:
        selection_trace_id = str(contact_candidate_collection.get("selection_trace_id", "")).strip()
        if selection_trace_id:
            selection_record = ContactSelectionTraceRepository().get_by_id(selection_trace_id)
            if selection_record is None:
                return None
            contact_selection_trace = selection_record.as_payload()

    if contact_candidate_collection is None:
        snapshot = stage_inputs.get("contact_candidate_collection_snapshot")
        contact_candidate_collection = dict(snapshot) if isinstance(snapshot, Mapping) else None
    if contact_selection_trace is None:
        snapshot = stage_inputs.get("contact_selection_trace_snapshot")
        contact_selection_trace = dict(snapshot) if isinstance(snapshot, Mapping) else None
    return contact_candidate_collection, contact_selection_trace


def _hydrate_stage8_outbox(
    *,
    stage_inputs: Mapping[str, Any],
    persisted_refs: Mapping[str, Any],
) -> dict[str, Any] | None:
    outbox, outbox_stale = _stage8_repo_record(
        OutreachExecutionOutboxRepository(),
        stage_inputs=stage_inputs,
        persisted_refs=persisted_refs,
        ref_keys=("outbox_id", OUTBOX_ID_INPUT_KEY, "outreach_execution_outbox_id_optional"),
    )
    if outbox_stale:
        return None
    if outbox is not None:
        return outbox
    snapshot = stage_inputs.get(OUTBOX_SNAPSHOT_INPUT_KEY)
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _restore_stage8_carrier_inputs(
    *,
    stage_inputs: dict[str, Any],
    contact_candidate_collection: Mapping[str, Any] | None,
    contact_selection_trace: Mapping[str, Any] | None,
) -> None:
    if contact_candidate_collection is not None:
        stage_inputs["contact_candidate_collection_snapshot"] = dict(contact_candidate_collection)
        collection_id = contact_candidate_collection.get("contact_candidate_collection_id")
        if collection_id not in (None, "", "UNKNOWN"):
            stage_inputs["contact_candidate_collection_id_optional"] = str(collection_id)
        winning_contact_candidate_id = contact_candidate_collection.get("winning_contact_candidate_id")
        if winning_contact_candidate_id not in (None, "", "UNKNOWN"):
            stage_inputs["winning_contact_candidate_id_optional"] = str(winning_contact_candidate_id)
        if contact_candidate_collection.get("reselect_reason_optional") not in (None, ""):
            stage_inputs["reselect_reason_optional"] = contact_candidate_collection.get(
                "reselect_reason_optional"
            )
    if contact_selection_trace is not None:
        stage_inputs["contact_selection_trace_snapshot"] = dict(contact_selection_trace)
        selection_trace_id = contact_selection_trace.get("contact_selection_trace_id")
        if selection_trace_id not in (None, "", "UNKNOWN"):
            stage_inputs["contact_selection_trace_id_optional"] = str(selection_trace_id)
        if stage_inputs.get("contact_candidate_collection_id_optional") in (None, ""):
            collection_id = contact_selection_trace.get("contact_candidate_collection_id")
            if collection_id not in (None, "", "UNKNOWN"):
                stage_inputs["contact_candidate_collection_id_optional"] = str(collection_id)
        if stage_inputs.get("winning_contact_candidate_id_optional") in (None, ""):
            winning_contact_candidate_id = contact_selection_trace.get("winning_contact_candidate_id")
            if winning_contact_candidate_id not in (None, "", "UNKNOWN"):
                stage_inputs["winning_contact_candidate_id_optional"] = str(winning_contact_candidate_id)
        if stage_inputs.get("reselect_reason_optional") in (None, ""):
            reselect_reason = contact_selection_trace.get("reselect_reason_optional")
            if reselect_reason not in (None, ""):
                stage_inputs["reselect_reason_optional"] = reselect_reason

    resolution_trace = stage_inputs.get("stage8_resolution_trace")
    resolution_trace = dict(resolution_trace) if isinstance(resolution_trace, Mapping) else {}
    if contact_candidate_collection is not None:
        resolution_trace["contact_candidate_collection_id"] = contact_candidate_collection.get(
            "contact_candidate_collection_id"
        )
        resolution_trace["winning_contact_candidate_id"] = contact_candidate_collection.get(
            "winning_contact_candidate_id"
        )
    if contact_selection_trace is not None:
        resolution_trace["contact_selection_trace_id"] = contact_selection_trace.get(
            "contact_selection_trace_id"
        )
        resolution_trace["contact_selection_trace"] = {
            "winning_selection_reason": contact_selection_trace.get("winning_selection_reason"),
            "conflict_flag": contact_selection_trace.get("conflict_flag"),
            "conflict_reason_optional": contact_selection_trace.get("conflict_reason_optional"),
            "source_conflict_candidate_count": contact_selection_trace.get(
                "source_conflict_candidate_count",
                0,
            ),
            "source_merge_review_required_count": contact_selection_trace.get(
                "source_merge_review_required_count",
                0,
            ),
            "reselect_reason_optional": contact_selection_trace.get("reselect_reason_optional"),
            "reselect_history": contact_selection_trace.get("reselect_history"),
        }
    if resolution_trace:
        stage_inputs["stage8_resolution_trace"] = resolution_trace


def _restore_stage8_outbox_inputs(
    *,
    stage_inputs: dict[str, Any],
    handoff: dict[str, Any],
    outreach_execution_outbox: Mapping[str, Any],
) -> None:
    if not outreach_execution_outbox:
        return
    outbox_payload = dict(outreach_execution_outbox)
    outbox_summary = build_outbox_readiness_summary(outbox_payload)
    stage_inputs[OUTBOX_SNAPSHOT_INPUT_KEY] = outbox_payload
    stage_inputs[OUTBOX_ID_INPUT_KEY] = str(outbox_payload.get("outbox_id"))
    stage_inputs["outreach_execution_outbox_id_optional"] = str(outbox_payload.get("outbox_id"))
    stage_inputs[OUTBOX_READINESS_INPUT_KEY] = outbox_summary
    handoff[OUTBOX_ID_INPUT_KEY] = str(outbox_payload.get("outbox_id"))
    handoff["outreach_execution_outbox_id_optional"] = str(outbox_payload.get("outbox_id"))
    handoff[OUTBOX_READINESS_INPUT_KEY] = outbox_summary


def _hydrate_stage9_execution_ledger(
    *,
    stage_inputs: Mapping[str, Any],
    persisted_refs: Mapping[str, Any] | None,
    order_refs: Mapping[str, Any] | None,
    work_item_refs: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    execution_ledger_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        order_refs,
        work_item_refs,
        keys=("execution_ledger_id", STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY),
    )
    order_execution_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        order_refs,
        work_item_refs,
        keys=("order_execution_id",),
    )
    payment_execution_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        order_refs,
        work_item_refs,
        keys=("payment_execution_id",),
    )
    delivery_execution_id = _resolve_typed_ref(
        persisted_refs,
        stage_inputs,
        order_refs,
        work_item_refs,
        keys=("delivery_execution_id",),
    )
    repository = Stage9ExecutionLedgerRepository()
    record = repository.get_by_id(execution_ledger_id) if execution_ledger_id else None
    if record is None and order_execution_id:
        record = repository.get_by_order_execution_id(order_execution_id)
    if record is None and payment_execution_id:
        record = repository.get_by_payment_execution_id(payment_execution_id)
    if record is None and delivery_execution_id:
        record = repository.get_by_delivery_execution_id(delivery_execution_id)
    if record is None:
        if execution_ledger_id or order_execution_id or payment_execution_id or delivery_execution_id:
            return None, True
        snapshot = stage_inputs.get(STAGE9_EXECUTION_LEDGER_INPUT_KEY)
        return (dict(snapshot), False) if isinstance(snapshot, Mapping) else (None, False)

    payload = record.as_payload()
    expected_ids = {
        "execution_ledger_id": execution_ledger_id,
        "order_execution_id": order_execution_id,
        "payment_execution_id": payment_execution_id,
        "delivery_execution_id": delivery_execution_id,
    }
    if any(
        expected and str(payload.get(field_name, "")).strip() != expected
        for field_name, expected in expected_ids.items()
    ):
        return None, True
    return payload, False


def _restore_stage9_execution_ledger_inputs(
    *,
    stage_inputs: dict[str, Any],
    handoff: dict[str, Any],
    execution_ledger: Mapping[str, Any] | None,
) -> None:
    if not execution_ledger:
        return
    ledger_payload = dict(execution_ledger)
    readiness = build_stage9_execution_ledger_readiness_summary(ledger_payload)
    stage_inputs[STAGE9_EXECUTION_LEDGER_INPUT_KEY] = ledger_payload
    stage_inputs[STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY] = str(ledger_payload.get("execution_ledger_id"))
    stage_inputs[STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY] = readiness
    live_pilot_carrier = ledger_payload.get(PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY)
    if isinstance(live_pilot_carrier, Mapping):
        stage_inputs[PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY] = dict(live_pilot_carrier)
        handoff[PAYMENT_DELIVERY_LIVE_PILOT_INPUT_KEY] = dict(live_pilot_carrier)
    for field_name in ("order_execution_id", "payment_execution_id", "delivery_execution_id"):
        if ledger_payload.get(field_name) not in (None, "", "UNKNOWN"):
            stage_inputs[field_name] = str(ledger_payload[field_name])
            handoff[field_name] = str(ledger_payload[field_name])
    handoff[STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY] = str(ledger_payload.get("execution_ledger_id"))
    handoff[STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY] = readiness


def _build_stage8_handoff_readback(
    *,
    handoff_snapshot: Mapping[str, Any] | None,
    contact_target: Mapping[str, Any],
    outreach_plan: Mapping[str, Any],
    touch_record: Mapping[str, Any],
    stage_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    handoff = dict(handoff_snapshot) if isinstance(handoff_snapshot, Mapping) else {}
    handoff.setdefault("opportunity_id", contact_target.get("opportunity_id"))
    handoff.setdefault("touch_record_id", touch_record.get("touch_record_id"))
    handoff.setdefault("response_status", touch_record.get("response_status"))
    handoff.setdefault("saleability_status", touch_record.get("saleability_status"))
    handoff.setdefault("crm_owner_state", stage_inputs.get("crm_owner_state"))
    handoff.setdefault("contact_target_status", contact_target.get("contact_target_status"))
    handoff.setdefault("plan_status", outreach_plan.get("plan_status"))
    handoff.setdefault("touch_record_state", touch_record.get("touch_record_state"))
    handoff.setdefault("feedback_reason", touch_record.get("feedback_reason"))
    handoff.setdefault("written_back_at_optional", touch_record.get("written_back_at_optional"))
    for field_name in (
        "contact_candidate_collection_id_optional",
        "contact_selection_trace_id_optional",
        "winning_contact_candidate_id_optional",
        "reselect_reason_optional",
    ):
        if stage_inputs.get(field_name) not in (None, ""):
            handoff[field_name] = stage_inputs[field_name]
    if stage_inputs.get("contact_candidate_collection_id_optional") not in (None, ""):
        handoff["contact_candidate_collection_id"] = stage_inputs[
            "contact_candidate_collection_id_optional"
        ]
    if stage_inputs.get("contact_selection_trace_id_optional") not in (None, ""):
        handoff["contact_selection_trace_id"] = stage_inputs["contact_selection_trace_id_optional"]
    return handoff


def hydrate_stage8_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    contact_target, outreach_plan, touch_record, stage_state = _find_stage8_records(payload)
    if not all((contact_target, outreach_plan, touch_record, stage_state)):
        return None
    if stage_state.root_record_id != touch_record.record_id:
        stage_state = _get_stage_state(8, STAGE_SURFACE_IDS[8], touch_record.record_id)
    if not stage_state:
        return None
    stage_inputs = dict(stage_state.inputs)
    trace_rules = list(stage_inputs.pop(_STAGE8_TRACE_RULES_SNAPSHOT_KEY, []))
    handoff_snapshot = stage_inputs.pop(_STAGE8_HANDOFF_SNAPSHOT_KEY, None)
    carrier_resolution = _hydrate_stage8_carriers(
        stage_inputs=stage_inputs,
        persisted_refs=stage_state.typed_object_refs,
    )
    if carrier_resolution is None:
        return None
    outreach_execution_outbox = _hydrate_stage8_outbox(
        stage_inputs=stage_inputs,
        persisted_refs=stage_state.typed_object_refs,
    )
    if outreach_execution_outbox is None:
        return None
    contact_candidate_collection, contact_selection_trace = carrier_resolution
    _restore_stage8_carrier_inputs(
        stage_inputs=stage_inputs,
        contact_candidate_collection=contact_candidate_collection,
        contact_selection_trace=contact_selection_trace,
    )
    handoff = _build_stage8_handoff_readback(
        handoff_snapshot=handoff_snapshot,
        contact_target=contact_target.as_payload(),
        outreach_plan=outreach_plan.as_payload(),
        touch_record=touch_record.as_payload(),
        stage_inputs=stage_inputs,
    )
    _restore_stage8_outbox_inputs(
        stage_inputs=stage_inputs,
        handoff=handoff,
        outreach_execution_outbox=outreach_execution_outbox,
    )

    return StageBundle(
        stage=8,
        records={
            "contact_target": ContractRecord("contact_target", contact_target.as_payload()),
            "outreach_plan": ContractRecord("outreach_plan", outreach_plan.as_payload()),
            "touch_record": ContractRecord("touch_record", touch_record.as_payload()),
        },
        handoff=handoff,
        trace_rules=trace_rules,
        inputs=stage_inputs,
    )


def hydrate_stage9_bundle(payload: Mapping[str, Any]) -> StageBundle | None:
    stage_state = _resolve_stage9_stage_state(payload)
    order_id = str(payload.get("order_id", "")).strip() or (
        stage_state.root_record_id if stage_state is not None else ""
    )
    order = OrderRecordRepository().get_by_id(order_id) if order_id else None
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
        fallback_field="outcome_event_id",
        fallback_value="",
    )
    governance = _record_from_persisted_refs(
        GovernanceFeedbackEventRepository(),
        ref_sources=(persisted_refs, order.object_refs, work_item_refs),
        ref_keys=("governance_feedback_event_id",),
        fallback_field="governance_feedback_event_id",
        fallback_value="",
    )
    if not all((payment, delivery, outcome, governance, stage_state)):
        return None
    stage_inputs = dict(stage_state.inputs)
    trace_rules = list(stage_inputs.pop(_STAGE9_TRACE_RULES_SNAPSHOT_KEY, []))
    handoff_snapshot = stage_inputs.pop(_STAGE9_HANDOFF_SNAPSHOT_KEY, None)
    handoff = dict(handoff_snapshot) if isinstance(handoff_snapshot, Mapping) else {}
    execution_ledger, execution_ledger_stale = _hydrate_stage9_execution_ledger(
        stage_inputs=stage_inputs,
        persisted_refs=persisted_refs,
        order_refs=order.object_refs,
        work_item_refs=work_item_refs,
    )
    if execution_ledger_stale:
        return None
    _restore_stage9_execution_ledger_inputs(
        stage_inputs=stage_inputs,
        handoff=handoff,
        execution_ledger=execution_ledger,
    )

    return StageBundle(
        stage=9,
        records={
            "order_record": ContractRecord("order_record", order.as_payload()),
            "payment_record": ContractRecord("payment_record", payment.as_payload()),
            "delivery_record": ContractRecord("delivery_record", delivery.as_payload()),
            "opportunity_outcome_event": ContractRecord("opportunity_outcome_event", outcome.as_payload()),
            "governance_feedback_event": ContractRecord("governance_feedback_event", governance.as_payload()),
        },
        handoff=handoff,
        trace_rules=trace_rules,
        inputs=stage_inputs,
    )
