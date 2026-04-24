from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from helpers import load_fixture
from shared.pipeline import run_internal_chain
from api.routes.stage7 import list_saleable_opportunities, refresh_saleable_opportunity
from api.routes.stage8 import create_touch_record, list_contact_targets
from api.routes.stage9 import create_governance_feedback_event, list_orders
from stage7_sales.service import Stage7Service
from storage.db import DatabaseSession, PersistedStageState, PersistedWorkItem
from storage import persist_stage_bundle, reset_default_storage
from storage.repository_boundary import hydrate_stage_bundle
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
    TouchRecordRepository,
    WorkItemRepository,
)


class TestInternalRepositoryBoundary(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()
        self.result = run_internal_chain(load_fixture("internal_chain_happy.json"))

    def test_repository_boundary_readback_works_with_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "sqlite",
                    "KAKA_STORAGE_PATH": str(Path(tmp_dir) / "repository-boundary.json"),
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in ("KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
                    os.environ.pop(key, None)
                reset_default_storage()
                try:
                    result = run_internal_chain(load_fixture("internal_chain_happy.json"))
                    stage8 = result["stage8"]
                    original_contact = dict(stage8.record("contact_target").data)
                    original_plan = dict(stage8.record("outreach_plan").data)
                    original_touch = dict(stage8.record("touch_record").data)

                    create_touch_record(stage8)
                    DatabaseSession.default(reload_from_disk=True)

                    replay = list_contact_targets({"opportunity_id": original_touch["opportunity_id"]})
                    hydrated = hydrate_stage_bundle("stage8", {"opportunity_id": original_touch["opportunity_id"]})
                    self.assertEqual(DatabaseSession.default().storage_backend, "sqlite")
                    self.assertEqual(
                        replay["preview_projection"]["touch_record_preview"]["touch_record_id"],
                        original_touch["touch_record_id"],
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
                finally:
                    DatabaseSession.default().close()

    def test_stage6_repository_boundary_persists_formal_objects_and_rehydrates_stage7_inputs(self) -> None:
        stage6 = self.result["stage6"]
        stage7 = self.result["stage7"]
        persist_stage_bundle(stage6)

        project_fact = stage6.record("project_fact")
        report_record = stage6.record("report_record")
        review_queue_profile = stage6.record("review_queue_profile")
        challenger_candidate_profile = stage6.record("challenger_candidate_profile")
        legal_action_recommendation = stage6.record("legal_action_recommendation")

        project_fact_entry = ProjectFactRepository().get_by_id(project_fact.get("project_fact_id"))
        report_record_entry = ReportRecordRepository().get_by_id(report_record.get("report_id"))
        review_queue_profile_entry = ReviewQueueProfileRepository().get_by_id(
            review_queue_profile.get("queue_profile_id")
        )
        challenger_candidate_profile_entry = ChallengerCandidateProfileRepository().get_by_id(
            challenger_candidate_profile.get("challenger_profile_id")
        )
        legal_action_recommendation_entry = LegalActionRecommendationRepository().get_by_id(
            legal_action_recommendation.get("action_id")
        )

        self.assertIsNotNone(project_fact_entry)
        self.assertIsNotNone(report_record_entry)
        self.assertIsNotNone(review_queue_profile_entry)
        self.assertIsNotNone(challenger_candidate_profile_entry)
        self.assertIsNotNone(legal_action_recommendation_entry)
        self.assertEqual(project_fact_entry.stage_scope, 6)
        self.assertEqual(project_fact_entry.payload["sale_gate_status"], project_fact.get("sale_gate_status"))
        self.assertEqual(report_record_entry.payload["report_status"], report_record.get("report_status"))
        self.assertEqual(
            review_queue_profile_entry.payload["review_lane"],
            review_queue_profile.get("review_lane"),
        )
        self.assertEqual(
            challenger_candidate_profile_entry.payload["challenge_actionability_score"],
            challenger_candidate_profile.get("challenge_actionability_score"),
        )
        self.assertEqual(
            legal_action_recommendation_entry.payload["action_family"],
            legal_action_recommendation.get("action_family"),
        )
        stage6_work_items = WorkItemRepository().list(stage_scope=6)
        self.assertEqual(len(stage6_work_items), 1)
        self.assertEqual(stage6_work_items[0].surface_id, "review_report_workbench")
        self.assertEqual(stage6_work_items[0].primary_object_type, "project_fact")
        self.assertEqual(stage6_work_items[0].primary_record_id, project_fact.get("project_fact_id"))
        self.assertEqual(
            stage6_work_items[0].work_item_key,
            f"6:review_report_workbench:project_fact:{project_fact.get('project_fact_id')}",
        )
        self.assertEqual(stage6_work_items[0].object_refs["project_fact_id"], project_fact.get("project_fact_id"))
        self.assertEqual(stage6_work_items[0].object_refs["report_record_id"], report_record.get("report_id"))
        self.assertEqual(
            stage6_work_items[0].object_refs["review_queue_profile_id"],
            review_queue_profile.get("queue_profile_id"),
        )
        self.assertEqual(
            stage6_work_items[0].object_refs["challenger_candidate_profile_id"],
            challenger_candidate_profile.get("challenger_profile_id"),
        )
        self.assertEqual(stage6_work_items[0].object_refs["action_id"], legal_action_recommendation.get("action_id"))
        self.assertEqual(
            set(stage6_work_items[0].pending_actions),
            {"stage6_mark_reviewed", "stage6_return_for_revision"},
        )

        hydrated = hydrate_stage_bundle("stage6", {"project_id": project_fact.get("project_id")})

        self.assertIsNotNone(hydrated)
        self.assertEqual(hydrated.handoff, stage6.handoff)
        self.assertEqual(
            hydrated.inputs.get("stage6_review_report_trace"),
            stage6.inputs.get("stage6_review_report_trace"),
        )
        self.assertEqual(
            hydrated.inputs.get("stage6_h06_formal_carrier_trace"),
            stage6.inputs.get("stage6_h06_formal_carrier_trace"),
        )

        replayed_stage7 = Stage7Service().run(hydrated)
        self.assertEqual(
            replayed_stage7.record("saleable_opportunity").get("saleability_status"),
            stage7.record("saleable_opportunity").get("saleability_status"),
        )
        self.assertEqual(
            replayed_stage7.handoff.get("project_fact_id_optional"),
            stage7.handoff.get("project_fact_id_optional"),
        )
        self.assertEqual(
            replayed_stage7.handoff.get("challenger_candidate_profile_id_optional"),
            stage7.handoff.get("challenger_candidate_profile_id_optional"),
        )

    def test_stage6_repository_readback_prefers_persisted_formal_refs_over_project_lookup(self) -> None:
        stage6 = self.result["stage6"]
        persist_stage_bundle(stage6)

        project_fact = dict(stage6.record("project_fact").data)
        report_record = dict(stage6.record("report_record").data)
        review_queue_profile = dict(stage6.record("review_queue_profile").data)
        challenger_candidate_profile = dict(stage6.record("challenger_candidate_profile").data)
        legal_action_recommendation = dict(stage6.record("legal_action_recommendation").data)

        conflicting_project_fact = dict(project_fact)
        conflicting_project_fact["project_fact_id"] = "FACT-CONFLICT-PROJ-001"
        conflicting_project_fact["sale_gate_status"] = "BLOCK"
        conflicting_report_record = dict(report_record)
        conflicting_report_record["report_id"] = "REPORT-CONFLICT-PROJ-001"
        conflicting_report_record["report_status"] = "REVOKED"
        conflicting_review_queue_profile = dict(review_queue_profile)
        conflicting_review_queue_profile["queue_profile_id"] = "QUEUE-CONFLICT-PROJ-001"
        conflicting_review_queue_profile["review_lane"] = "FAST_WINDOW"
        conflicting_challenger_candidate_profile = dict(challenger_candidate_profile)
        conflicting_challenger_candidate_profile["challenger_profile_id"] = "CH-CONFLICT-PROJ-001"
        conflicting_challenger_candidate_profile["challenge_actionability_score"] = 9
        conflicting_legal_action_recommendation = dict(legal_action_recommendation)
        conflicting_legal_action_recommendation["action_id"] = "LAR-CONFLICT-PROJ-001"
        conflicting_legal_action_recommendation["action_family"] = "REVIEW_ONLY"

        ProjectFactRepository().save(conflicting_project_fact)
        ReportRecordRepository().save(conflicting_report_record)
        ReviewQueueProfileRepository().save(conflicting_review_queue_profile)
        ChallengerCandidateProfileRepository().save(conflicting_challenger_candidate_profile)
        LegalActionRecommendationRepository().save(conflicting_legal_action_recommendation)

        hydrated = hydrate_stage_bundle("stage6", {"project_id": project_fact["project_id"]})

        self.assertIsNotNone(hydrated)
        self.assertEqual(
            hydrated.record("project_fact").get("project_fact_id"),
            project_fact["project_fact_id"],
        )
        self.assertEqual(
            hydrated.record("report_record").get("report_id"),
            report_record["report_id"],
        )
        self.assertEqual(
            hydrated.record("review_queue_profile").get("queue_profile_id"),
            review_queue_profile["queue_profile_id"],
        )
        self.assertEqual(
            hydrated.record("challenger_candidate_profile").get("challenger_profile_id"),
            challenger_candidate_profile["challenger_profile_id"],
        )
        self.assertEqual(
            hydrated.record("legal_action_recommendation").get("action_id"),
            legal_action_recommendation["action_id"],
        )
        self.assertEqual(
            hydrated.record("project_fact").get("sale_gate_status"),
            project_fact["sale_gate_status"],
        )
        self.assertNotEqual(
            hydrated.record("project_fact").get("sale_gate_status"),
            conflicting_project_fact["sale_gate_status"],
        )

    def test_stage6_repository_readback_does_not_broad_fallback_when_typed_refs_are_stale(self) -> None:
        stage6 = self.result["stage6"]
        persist_stage_bundle(stage6)

        project_fact_id = stage6.record("project_fact").get("project_fact_id")
        project_id = stage6.record("project_fact").get("project_id")

        self.assertIsNone(
            hydrate_stage_bundle(
                "stage6",
                {
                    "project_id": project_id,
                    "project_fact_id": "FACT-STALE-TYPED-REF-001",
                },
            )
        )

        stage_state = DatabaseSession.default().get_stage_state(6, "stage6_fact_review", project_fact_id)
        self.assertIsNotNone(stage_state)

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs.update(
            {
                "project_fact_id": "FACT-STALE-TYPED-REF-001",
                "report_record_id": "REPORT-STALE-TYPED-REF-001",
                "review_queue_profile_id": "QUEUE-STALE-TYPED-REF-001",
                "challenger_candidate_profile_id": "CH-STALE-TYPED-REF-001",
                "action_id": "LAR-STALE-TYPED-REF-001",
            }
        )
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        self.assertIsNone(hydrate_stage_bundle("stage6", {"project_id": project_id}))

    def test_stage6_private_supplement_carrier_persists_and_hydrates(self) -> None:
        reset_default_storage()
        payload = copy.deepcopy(load_fixture("internal_chain_block.json"))
        payload.update(
            {
                "supplement_material_family": "MISSING_ATTACHMENT_BACKFILL",
                "supplement_source_owner": "MANUAL_REVIEW",
                "supplement_lawful_basis": "REVIEW_CHAIN_AUTHORIZED",
                "supplement_visible_roles": "review_user,governance_owner",
                "supplement_written_back_policy": "GOVERNANCE_SINK_ONLY",
            }
        )
        payload["flags"] = {
            **dict(payload.get("flags", {})),
            "supplement_ready_for_impact": True,
        }
        result = run_internal_chain(payload)
        stage6 = result["stage6"]
        supplement = stage6.inputs["private_supplement_record_optional"]
        supplement_summary = stage6.inputs["private_supplement_carrier_summary"]

        persist_stage_bundle(stage6)

        supplement_entry = DatabaseSession.default().get_record(
            "private_supplement_record",
            supplement["supplement_id"],
        )
        self.assertIsNotNone(supplement_entry)
        self.assertEqual(supplement_entry.stage_scope, 6)
        self.assertEqual(supplement_entry.payload, supplement)
        self.assertEqual(
            supplement_entry.object_refs["linked_review_request_id"],
            supplement["linked_review_request_id"],
        )

        stage_state = DatabaseSession.default().get_stage_state(
            6,
            "stage6_fact_review",
            stage6.record("project_fact").get("project_fact_id"),
        )
        self.assertIsNotNone(stage_state)
        self.assertEqual(
            stage_state.typed_object_refs["private_supplement_record_id_optional"],
            supplement["supplement_id"],
        )
        stage6_work_items = WorkItemRepository().list(stage_scope=6)
        self.assertEqual(len(stage6_work_items), 1)
        self.assertEqual(
            stage6_work_items[0].object_refs["private_supplement_record_id_optional"],
            supplement["supplement_id"],
        )
        self.assertEqual(
            stage6_work_items[0].governed_context["private_supplement_carrier_summary"],
            supplement_summary,
        )

        hydrated = hydrate_stage_bundle("stage6", {"project_id": supplement["project_id"]})

        self.assertIsNotNone(hydrated)
        self.assertEqual(hydrated.inputs["private_supplement_record_optional"], supplement)
        self.assertEqual(hydrated.inputs["private_supplement_carrier_summary"], supplement_summary)
        self.assertEqual(
            hydrated.handoff["private_supplement_carrier_summary"],
            supplement_summary,
        )
        self.assertEqual(
            hydrated.inputs["stage6_review_report_trace"]["supplement_trace"][
                "private_supplement_carrier_summary"
            ],
            supplement_summary,
        )

        replayed_stage7 = Stage7Service().run(hydrated)
        for field_name in (
            "private_supplement_record",
            "private_supplement_record_id_optional",
            "private_supplement_release_state_optional",
            "private_supplement_usable_scope_optional",
            "private_supplement_written_back_policy_optional",
            "private_supplement_carrier_summary",
        ):
            self.assertNotIn(field_name, replayed_stage7.records)
            self.assertNotIn(field_name, replayed_stage7.handoff)

    def test_stage6_private_supplement_readback_does_not_broad_fallback_when_typed_ref_is_stale(self) -> None:
        reset_default_storage()
        payload = copy.deepcopy(load_fixture("internal_chain_block.json"))
        payload.update(
            {
                "supplement_material_family": "MISSING_ATTACHMENT_BACKFILL",
                "supplement_source_owner": "MANUAL_REVIEW",
            }
        )
        stage6 = run_internal_chain(payload)["stage6"]
        persist_stage_bundle(stage6)

        project_fact_id = stage6.record("project_fact").get("project_fact_id")
        project_id = stage6.record("project_fact").get("project_id")
        stage_state = DatabaseSession.default().get_stage_state(6, "stage6_fact_review", project_fact_id)
        self.assertIsNotNone(stage_state)
        self.assertIsNotNone(
            DatabaseSession.default().get_record(
                "private_supplement_record",
                stage6.inputs["private_supplement_record_optional"]["supplement_id"]
            )
        )

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs["private_supplement_record_id_optional"] = "SUP-STALE-TYPED-REF-001"
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        self.assertIsNone(hydrate_stage_bundle("stage6", {"project_id": project_id}))

    def test_stage7_repository_boundary_persists_formal_objects_without_rejudging(self) -> None:
        stage7 = self.result["stage7"]
        refresh_saleable_opportunity(stage7)

        opportunity = stage7.record("saleable_opportunity")
        workbench = stage7.inputs["crm_quote_workbench"]
        opportunity_entry = SaleableOpportunityRepository().get_by_id(opportunity.get("opportunity_id"))
        offer_entry = OfferRecommendationRepository().find_one_by_field("project_id", opportunity.get("project_id"))
        buyer_entry = BuyerFitRepository().get_by_id(opportunity.get("buyer_fit_id"))
        workbench_entry = CRMQuoteWorkbenchRepository().get_by_id(workbench["crm_action_id"])

        self.assertIsNotNone(opportunity_entry)
        self.assertIsNotNone(offer_entry)
        self.assertIsNotNone(buyer_entry)
        self.assertIsNotNone(workbench_entry)
        self.assertEqual(opportunity_entry.stage_scope, 7)
        self.assertEqual(workbench_entry.stage_scope, 7)
        self.assertEqual(opportunity_entry.payload["saleability_status"], opportunity.get("saleability_status"))
        self.assertEqual(offer_entry.payload["offer_recommendation_state"], stage7.record("offer_recommendation").get("offer_recommendation_state"))
        self.assertEqual(buyer_entry.payload["fit_score"], stage7.record("buyer_fit").get("fit_score"))
        self.assertEqual(workbench_entry.payload["quote_draft_id"], workbench["quote_draft_id"])
        self.assertFalse(workbench_entry.payload["live_execution_enabled"])
        self.assertFalse(workbench_entry.payload["real_external_quote_sent"])

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
        self.assertEqual(
            replay["crm_quote_workbench"]["crm_action_id"],
            workbench["crm_action_id"],
        )
        self.assertEqual(
            replay["crm_quote_workbench_readiness_summary"]["quote_draft_id"],
            workbench["quote_draft_id"],
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
        self.assertEqual(
            hydrated.inputs["crm_quote_workbench"]["quote_draft_id"],
            workbench["quote_draft_id"],
        )

    def test_stage8_repository_boundary_keeps_governed_writeback_state(self) -> None:
        stage8 = self.result["stage8"]
        create_touch_record(stage8)

        touch = stage8.record("touch_record")
        collection = stage8.inputs["contact_candidate_collection_snapshot"]
        selection_trace = stage8.inputs["contact_selection_trace_snapshot"]
        outbox = stage8.inputs["outreach_execution_outbox_snapshot"]
        touch_entry = TouchRecordRepository().get_by_id(touch.get("touch_record_id"))
        contact_entry = ContactTargetRepository().get_by_id(stage8.record("contact_target").get("contact_target_id"))
        plan_entry = OutreachPlanRepository().get_by_id(stage8.record("outreach_plan").get("outreach_plan_id"))
        outbox_entry = OutreachExecutionOutboxRepository().get_by_id(outbox.get("outbox_id"))
        collection_entry = ContactCandidateCollectionRepository().get_by_id(
            collection.get("contact_candidate_collection_id")
        )
        selection_trace_entry = ContactSelectionTraceRepository().get_by_id(
            selection_trace.get("contact_selection_trace_id")
        )

        self.assertIsNotNone(touch_entry)
        self.assertIsNotNone(contact_entry)
        self.assertIsNotNone(plan_entry)
        self.assertIsNotNone(outbox_entry)
        self.assertIsNotNone(collection_entry)
        self.assertIsNotNone(selection_trace_entry)
        self.assertEqual(touch_entry.stage_scope, 8)
        self.assertEqual(outbox_entry.stage_scope, 8)
        self.assertEqual(collection_entry.stage_scope, 8)
        self.assertEqual(selection_trace_entry.stage_scope, 8)
        self.assertEqual(
            collection_entry.payload["winning_contact_candidate_id"],
            collection.get("winning_contact_candidate_id"),
        )
        self.assertEqual(
            selection_trace_entry.payload["contact_candidate_collection_id"],
            collection.get("contact_candidate_collection_id"),
        )
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
        self.assertEqual(outbox_entry.payload["outbox_id"], outbox["outbox_id"])
        self.assertEqual(outbox_entry.object_refs["outreach_plan_id"], stage8.record("outreach_plan").get("outreach_plan_id"))
        self.assertEqual(outbox_entry.governed_state["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertFalse(outbox_entry.governed_state["live_execution_enabled"])
        self.assertFalse(outbox_entry.governed_state["real_send_attempted"])

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
        self.assertEqual(
            replay["persisted_operational_context"]["object_refs"]["contact_candidate_collection_id"],
            collection.get("contact_candidate_collection_id"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["object_refs"]["contact_selection_trace_id"],
            selection_trace.get("contact_selection_trace_id"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["object_refs"]["outbox_id"],
            outbox.get("outbox_id"),
        )
        self.assertEqual(
            replay["preview_projection"]["outreach_execution_outbox_preview"]["outbox_id"],
            outbox.get("outbox_id"),
        )
        self.assertEqual(
            replay["outbox_readiness_summary"]["outbox_id"],
            outbox.get("outbox_id"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["governed_context"][
                "contact_candidate_collection_summary"
            ]["winning_contact_candidate_id"],
            collection.get("winning_contact_candidate_id"),
        )
        self.assertEqual(
            replay["persisted_operational_context"]["governed_context"][
                "contact_selection_trace_summary"
            ]["source_merge_review_required_count"],
            selection_trace.get("source_merge_review_required_count"),
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
        self.assertEqual(
            hydrated.inputs["contact_candidate_collection_snapshot"],
            collection_entry.payload,
        )
        self.assertEqual(
            hydrated.inputs["contact_selection_trace_snapshot"],
            selection_trace_entry.payload,
        )
        self.assertEqual(
            hydrated.inputs["outreach_execution_outbox_snapshot"],
            outbox_entry.payload,
        )
        self.assertEqual(
            hydrated.handoff["outbox_id_optional"],
            outbox.get("outbox_id"),
        )
        self.assertEqual(
            hydrated.inputs["winning_contact_candidate_id_optional"],
            collection.get("winning_contact_candidate_id"),
        )
        self.assertEqual(
            hydrated.handoff["contact_candidate_collection_id"],
            collection.get("contact_candidate_collection_id"),
        )
        self.assertEqual(
            hydrated.handoff["contact_selection_trace_id"],
            selection_trace.get("contact_selection_trace_id"),
        )

    def test_stage8_repository_replays_connected_handoff_governed_metadata(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "run_mode": "APPROVAL_RUN",
                "approval_state": "APPROVED",
                "response_status": "CONNECTED",
                "commercial_urgency_level": "HIGH",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        created = create_touch_record(stage8)
        replay = list_contact_targets(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
            }
        )
        hydrated = hydrate_stage_bundle(
            "stage8",
            {"opportunity_id": stage8.record("contact_target").get("opportunity_id")},
        )
        governed = replay["persisted_operational_context"]["governed_context"]

        self.assertTrue(replay["operational_loop_persisted"])
        self.assertEqual(replay["operational_context_status"], "persisted")
        self.assertTrue(replay["blocked_by_default"])
        self.assertFalse(replay["live_execution_enabled"])
        self.assertEqual(replay["formalization_scope"], "INTERNAL_GOVERNED")
        self.assertEqual(created["persisted_operational_context"]["governed_context"], governed)
        self.assertEqual(governed["writeback_targets"], stage8.record("touch_record").get("writeback_targets"))
        self.assertEqual(
            governed["written_back_at_optional"],
            stage8.record("touch_record").get("written_back_at_optional"),
        )
        self.assertEqual(
            governed["human_handoff_next_owner_role_optional"],
            stage8.handoff.get("human_handoff_next_owner_role_optional"),
        )
        self.assertEqual(
            governed["human_handoff_sla_hours_optional"],
            stage8.handoff.get("human_handoff_sla_hours_optional"),
        )
        self.assertEqual(
            governed["human_handoff_reason_optional"],
            stage8.handoff.get("human_handoff_reason_optional"),
        )
        self.assertIsNotNone(hydrated)
        self.assertEqual(
            hydrated.inputs["writeback_targets"],
            stage8.record("touch_record").get("writeback_targets"),
        )
        self.assertEqual(
            hydrated.inputs["written_back_at_optional"],
            stage8.record("touch_record").get("written_back_at_optional"),
        )
        self.assertEqual(
            hydrated.inputs["human_handoff_next_owner_role_optional"],
            stage8.handoff.get("human_handoff_next_owner_role_optional"),
        )
        self.assertEqual(
            hydrated.inputs["human_handoff_sla_hours_optional"],
            stage8.handoff.get("human_handoff_sla_hours_optional"),
        )
        self.assertEqual(
            hydrated.inputs["human_handoff_reason_optional"],
            stage8.handoff.get("human_handoff_reason_optional"),
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
            outcome_entry.writeback_state["written_back_at_optional"],
            outcome.get("written_back_at_optional"),
        )
        self.assertEqual(
            governance_entry.writeback_state["written_back_at_optional"],
            governance.get("written_back_at_optional"),
        )
        self.assertEqual(
            governance_entry.writeback_state["writeback_targets"],
            governance.get("writeback_targets"),
        )
        self.assertEqual(
            governance_entry.governed_state["governed_execution_mode"],
            governance.get("governed_execution_mode"),
        )
        self.assertEqual(
            outcome_entry.payload["governed_metadata"]["writeback_contract_summary"],
            stage9.inputs["writeback_contract_summary"],
        )
        self.assertEqual(
            governance_entry.payload["governed_metadata"]["writeback_contract_summary"],
            stage9.inputs["writeback_contract_summary"],
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
        self.assertEqual(
            replay["formal_object_refs"]["opportunity_outcome_event"]["governed_metadata"][
                "writeback_contract_summary"
            ],
            stage9.inputs["writeback_contract_summary"],
        )
        self.assertEqual(
            replay["formal_object_refs"]["governance_feedback_event"]["governed_metadata"][
                "writeback_contract_summary"
            ],
            stage9.inputs["writeback_contract_summary"],
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

    def test_stage7_repository_readback_does_not_broad_fallback_when_typed_refs_are_stale(self) -> None:
        stage7 = self.result["stage7"]
        refresh_saleable_opportunity(stage7)

        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")
        stage_state = DatabaseSession.default().get_stage_state(7, "opportunity_pool", opportunity_id)
        self.assertIsNotNone(stage_state)

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs.update(
            {
                "buyer_fit_id": "BUYER-FIT-STALE-TYPED-REF-001",
                "offer_recommendation_id": "OFFER-STALE-TYPED-REF-001",
                "legal_action_actor_id": "LEGAL-ACTOR-STALE-TYPED-REF-001",
                "procurement_decision_actor_id": "PROC-ACTOR-STALE-TYPED-REF-001",
            }
        )
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        hydrated = hydrate_stage_bundle("stage7", {"opportunity_id": opportunity_id})

        self.assertIsNone(hydrated)
        with self.assertRaises(TypeError):
            list_saleable_opportunities({"opportunity_id": opportunity_id})

    def test_stage7_crm_quote_workbench_readback_does_not_fallback_when_typed_ref_is_stale(self) -> None:
        stage7 = self.result["stage7"]
        refresh_saleable_opportunity(stage7)

        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")
        stage_state = DatabaseSession.default().get_stage_state(7, "opportunity_pool", opportunity_id)
        self.assertIsNotNone(stage_state)

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs.update(
            {
                "crm_action_id": "CRMACT-STALE-TYPED-REF-001",
                "quote_draft_id": "QDRAFT-STALE-TYPED-REF-001",
            }
        )
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        hydrated = hydrate_stage_bundle("stage7", {"opportunity_id": opportunity_id})

        self.assertIsNone(hydrated)
        with self.assertRaises(TypeError):
            list_saleable_opportunities({"opportunity_id": opportunity_id})

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
        original_work_item = WorkItemRepository().get(
            stage_scope=8,
            surface_id="outreach_workbench",
            primary_object_type="touch_record",
            primary_record_id=original_touch["touch_record_id"],
        )
        self.assertIsNotNone(original_work_item)
        conflicting_work_item_payload = original_work_item.as_payload()
        conflicting_work_item_payload.update(
            {
                "work_item_id": "WI-S8-CONFLICT-PROJ-001",
                "work_item_key": "stage8:outreach_workbench:touch_record:TOUCH-CONFLICT-PROJ-001",
                "primary_record_id": conflicting_touch["touch_record_id"],
                "object_refs": {
                    **conflicting_work_item_payload["object_refs"],
                    "contact_target_id": conflicting_contact["contact_target_id"],
                    "outreach_plan_id": conflicting_plan["outreach_plan_id"],
                    "touch_record_id": conflicting_touch["touch_record_id"],
                },
                "created_at": "2099-01-01T00:00:00Z",
                "updated_at": "2099-01-01T00:00:00Z",
            }
        )
        WorkItemRepository().save(PersistedWorkItem(**conflicting_work_item_payload))

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

    def test_stage8_repository_readback_does_not_broad_fallback_when_typed_refs_are_stale(self) -> None:
        stage8 = self.result["stage8"]
        create_touch_record(stage8)

        touch_id = stage8.record("touch_record").get("touch_record_id")
        opportunity_id = stage8.record("contact_target").get("opportunity_id")
        stage_state = DatabaseSession.default().get_stage_state(8, "outreach_workbench", touch_id)
        self.assertIsNotNone(stage_state)

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs.update(
            {
                "contact_target_id": "CT-STALE-TYPED-REF-001",
                "outreach_plan_id": "PLAN-STALE-TYPED-REF-001",
            }
        )
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        hydrated = hydrate_stage_bundle("stage8", {"opportunity_id": opportunity_id})

        self.assertIsNone(hydrated)
        with self.assertRaises(TypeError):
            list_contact_targets({"opportunity_id": opportunity_id})

    def test_stage8_carrier_readback_does_not_broad_fallback_when_typed_refs_are_stale(self) -> None:
        stage8 = self.result["stage8"]
        create_touch_record(stage8)

        touch_id = stage8.record("touch_record").get("touch_record_id")
        opportunity_id = stage8.record("contact_target").get("opportunity_id")
        stage_state = DatabaseSession.default().get_stage_state(8, "outreach_workbench", touch_id)
        self.assertIsNotNone(stage_state)

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs.update(
            {
                "contact_candidate_collection_id": "CCOLL-STALE-TYPED-REF-001",
                "contact_selection_trace_id": "CTRACE-STALE-TYPED-REF-001",
            }
        )
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        hydrated = hydrate_stage_bundle("stage8", {"opportunity_id": opportunity_id})

        self.assertIsNone(hydrated)
        with self.assertRaises(TypeError):
            list_contact_targets({"opportunity_id": opportunity_id})

    def test_stage8_outbox_readback_does_not_broad_fallback_when_typed_ref_is_stale(self) -> None:
        stage8 = self.result["stage8"]
        create_touch_record(stage8)

        touch_id = stage8.record("touch_record").get("touch_record_id")
        opportunity_id = stage8.record("contact_target").get("opportunity_id")
        stage_state = DatabaseSession.default().get_stage_state(8, "outreach_workbench", touch_id)
        self.assertIsNotNone(stage_state)

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs["outbox_id"] = "OUTBOX-STALE-TYPED-REF-001"
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        hydrated = hydrate_stage_bundle("stage8", {"opportunity_id": opportunity_id})

        self.assertIsNone(hydrated)
        with self.assertRaises(TypeError):
            list_contact_targets({"opportunity_id": opportunity_id})

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
        original_work_item = WorkItemRepository().get(
            stage_scope=9,
            surface_id="order_delivery_workbench",
            primary_object_type="order_record",
            primary_record_id=stage9.record("order_record").get("order_id"),
        )
        self.assertIsNotNone(original_work_item)
        conflicting_work_item_payload = original_work_item.as_payload()
        conflicting_work_item_payload["object_refs"] = {
            **conflicting_work_item_payload["object_refs"],
            "payment_id": conflicting_payment["payment_id"],
            "delivery_id": conflicting_delivery["delivery_id"],
            "outcome_event_id": conflicting_outcome["outcome_event_id"],
            "governance_feedback_event_id": conflicting_governance["governance_feedback_event_id"],
        }
        conflicting_work_item_payload["updated_at"] = "2099-01-01T00:00:00Z"
        WorkItemRepository().save(PersistedWorkItem(**conflicting_work_item_payload))

        replay = list_orders({"opportunity_id": stage9.record("order_record").get("opportunity_id")})
        hydrated = hydrate_stage_bundle("stage9", {"opportunity_id": stage9.record("order_record").get("opportunity_id")})
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
        self.assertIsNotNone(hydrated)
        self.assertEqual(
            hydrated.record("payment_record").get("payment_id"),
            payment["payment_id"],
        )
        self.assertEqual(
            hydrated.record("delivery_record").get("delivery_id"),
            delivery["delivery_id"],
        )
        self.assertEqual(
            hydrated.record("opportunity_outcome_event").get("outcome_event_id"),
            outcome["outcome_event_id"],
        )
        self.assertEqual(
            hydrated.record("governance_feedback_event").get("governance_feedback_event_id"),
            governance["governance_feedback_event_id"],
        )

    def test_stage9_repository_readback_does_not_broad_fallback_when_persisted_refs_exist(self) -> None:
        stage9 = self.result["stage9"]
        create_governance_feedback_event(stage9)

        order_id = stage9.record("order_record").get("order_id")
        opportunity_id = stage9.record("order_record").get("opportunity_id")
        stage_state = DatabaseSession.default().get_stage_state(9, "order_delivery_workbench", order_id)

        self.assertIsNotNone(stage_state)

        stale_typed_refs = dict(stage_state.typed_object_refs)
        stale_typed_refs.update(
            {
                "payment_id": "PAY-STALE-TYPED-REF-001",
                "delivery_id": "DELIVERY-STALE-TYPED-REF-001",
                "outcome_event_id": "OUTCOME-STALE-TYPED-REF-001",
                "governance_feedback_event_id": "GOV-STALE-TYPED-REF-001",
            }
        )
        DatabaseSession.default().upsert_stage_state(
            PersistedStageState(
                stage_scope=stage_state.stage_scope,
                project_id=stage_state.project_id,
                surface_id=stage_state.surface_id,
                root_object_type=stage_state.root_object_type,
                root_record_id=stage_state.root_record_id,
                inputs=dict(stage_state.inputs),
                persisted_at=stage_state.persisted_at,
                typed_object_refs=stale_typed_refs,
            )
        )

        hydrated = hydrate_stage_bundle("stage9", {"opportunity_id": opportunity_id})

        self.assertIsNone(hydrated)
        with self.assertRaises(TypeError):
            list_orders({"opportunity_id": opportunity_id})

        self.assertIsNone(
            hydrate_stage_bundle(
                "stage9",
                {
                    "order_id": "ORDER-STALE-TYPED-REF-001",
                    "opportunity_id": opportunity_id,
                },
            )
        )


if __name__ == "__main__":
    unittest.main()
