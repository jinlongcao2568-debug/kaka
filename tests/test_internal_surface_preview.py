from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from helpers import load_fixture, run_internal_chain_to_stage7
from api.projections import get_surface_runtime_defaults
from shared.pipeline import run_internal_chain
from api.routes.stage6 import (
    list_stage6_work_items,
    preview_stage6_review_report_workbench,
    register_stage6_routes,
)
from api.routes.stage7 import (
    list_saleable_opportunities,
    list_stage7_work_items,
    preview_leadpack_activation_design_implementation_prep_packet,
    preview_leadpack_activation_prep_packet,
    preview_leadpack_external_delivery_candidate,
    preview_leadpack_implementation_decision_readiness_packet,
    register_stage7_routes,
    request_leadpack_activation_design_implementation_prep_review,
    request_leadpack_activation_prep_review,
    request_leadpack_external_delivery_candidate_review,
    submit_stage7_operator_action,
    simulate_leadpack_external_delivery_export,
)
from api.routes.stage8 import (
    create_outreach_plan,
    create_touch_record,
    list_contact_targets,
    list_stage8_work_items,
    register_stage8_routes,
    submit_stage8_operator_action,
)
from api.routes.stage9 import (
    create_delivery_record,
    create_order,
    list_orders,
    list_stage9_work_items,
    register_stage9_routes,
    submit_stage9_operator_action,
)
from storage import persist_stage_bundle, reset_default_storage


def read_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class TestInternalSurfacePreview(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

    def test_stage6_preview_surface_consumes_repository_backed_formal_objects(self) -> None:
        stage6 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage6"]
        persist_stage_bundle(stage6)

        response = preview_stage6_review_report_workbench(
            {"project_id": stage6.record("project_fact").get("project_id")}
        )

        self.assertEqual(response["surface_id"], "review_report_workbench")
        self.assertEqual(response["surface_mode"], "preview-only")
        self.assertTrue(response["internal_only"])
        self.assertFalse(response["live_execution_enabled"])
        self.assertFalse(response["blocked_by_default"])
        self.assertEqual(response["surface_state"], "preview-ready")
        self.assertEqual(response["surface_state"], response["semantic_envelope"]["surface_state"])
        self.assertEqual(response["surface_access"], response["semantic_envelope"]["surface_access"])
        self.assertEqual(response["decision_states"], response["governance_envelope"]["decision_states"])
        self.assertEqual(response["capability_envelope"]["surface_capability_mode"], "INTERNAL_ONLY")
        self.assertIn("previewStage6ReviewReportWorkbench", response["governance_envelope"]["action_availability"])
        self.assertEqual(
            response["formal_object_refs"]["project_fact"]["object_id"],
            stage6.record("project_fact").get("project_fact_id"),
        )
        self.assertEqual(
            response["formal_object_refs"]["report_record"]["object_id"],
            stage6.record("report_record").get("report_id"),
        )
        self.assertEqual(
            response["formal_object_refs"]["review_queue_profile"]["object_id"],
            stage6.record("review_queue_profile").get("queue_profile_id"),
        )
        self.assertEqual(
            response["formal_object_refs"]["challenger_candidate_profile"]["object_id"],
            stage6.record("challenger_candidate_profile").get("challenger_profile_id"),
        )
        self.assertEqual(
            response["formal_object_refs"]["legal_action_recommendation"]["object_id"],
            stage6.record("legal_action_recommendation").get("action_id"),
        )
        self.assertEqual(
            response["preview_projection"]["project_fact_summary"]["sale_gate_status"],
            stage6.record("project_fact").get("sale_gate_status"),
        )
        self.assertEqual(
            response["preview_projection"]["report_status_summary"]["report_status"],
            stage6.record("report_record").get("report_status"),
        )
        self.assertEqual(
            response["preview_projection"]["review_queue_summary"]["review_lane"],
            stage6.record("review_queue_profile").get("review_lane"),
        )
        self.assertEqual(
            response["preview_projection"]["challenger_summary"]["challenge_actionability_score"],
            stage6.record("challenger_candidate_profile").get("challenge_actionability_score"),
        )
        self.assertEqual(
            response["preview_projection"]["legal_action_summary"]["action_family"],
            stage6.record("legal_action_recommendation").get("action_family"),
        )
        self.assertTrue(response["operational_loop_persisted"])
        self.assertEqual(response["operational_context_status"], "persisted")
        self.assertEqual(response["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(response["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(
            response["persisted_operational_context"]["object_refs"]["report_record_id"],
            stage6.record("report_record").get("report_id"),
        )

    def test_stage6_preview_surface_marks_readback_failure_as_review_or_blocked(self) -> None:
        stage6 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage6"]
        persist_stage_bundle(stage6)
        project_id = stage6.record("project_fact").get("project_id")

        blocked_response = preview_stage6_review_report_workbench(
            {
                "project_id": project_id,
                "project_fact_id": "FACT-STALE-TYPED-REF-001",
            }
        )
        review_response = preview_stage6_review_report_workbench({"project_id": "PROJ-NOT-PERSISTED"})

        self.assertEqual(blocked_response["surface_id"], "review_report_workbench")
        self.assertEqual(blocked_response["surface_state"], "blocked")
        self.assertEqual(blocked_response["semantic_envelope"]["surface_state"], "blocked")
        self.assertIn(
            "stage6_repository_readback_failed:typed_refs_unresolved",
            blocked_response["semantic_envelope"]["state_reasons"],
        )
        self.assertEqual(
            blocked_response["preview_projection"]["project_fact_summary"]["repository_readback_status"],
            "unavailable",
        )
        self.assertEqual(blocked_response["decision_states"]["semantic_decision_state"], "BLOCK")
        self.assertFalse(blocked_response["blocked_by_default"])

        self.assertEqual(review_response["surface_id"], "review_report_workbench")
        self.assertEqual(review_response["surface_state"], "review-required")
        self.assertEqual(review_response["semantic_envelope"]["surface_state"], "review-required")
        self.assertIn(
            "stage6_repository_readback_failed:project_not_persisted",
            review_response["semantic_envelope"]["state_reasons"],
        )
        self.assertEqual(review_response["decision_states"]["semantic_decision_state"], "REVIEW")
        self.assertTrue(review_response["internal_only"])
        self.assertFalse(review_response["live_execution_enabled"])

    def test_stage6_route_registration_exposes_internal_queue_without_live_execution(self) -> None:
        routes = register_stage6_routes()
        defaults = get_surface_runtime_defaults("review_report_workbench")

        self.assertEqual(len(routes), 3)
        route = next(route for route in routes if route["operationId"] == "previewStage6ReviewReportWorkbench")
        self.assertEqual(route["operationId"], "previewStage6ReviewReportWorkbench")
        self.assertEqual(route["method"], "GET")
        self.assertEqual(route["surface_mode"], defaults["surface_mode"])
        self.assertEqual(route["internal_only"], defaults["internal_only"])
        self.assertEqual(route["live_execution_enabled"], defaults["live_execution_enabled"])
        self.assertEqual(route["blocked_by_default"], defaults["blocked_by_default"])
        list_route = next(route for route in routes if route["operationId"] == "listStage6WorkItems")
        action_route = next(route for route in routes if route["operationId"] == "submitStage6OperatorAction")
        self.assertEqual(list_route["method"], "GET")
        self.assertEqual(action_route["method"], "POST")
        self.assertTrue(list_route["internal_only"])
        self.assertFalse(action_route["live_execution_enabled"])

    def test_stage6_work_item_route_uses_canonical_surface_defaults(self) -> None:
        stage6 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage6"]
        persist_stage_bundle(stage6)

        response = list_stage6_work_items({"project_id": stage6.record("project_fact").get("project_id")})
        defaults = get_surface_runtime_defaults("review_report_workbench")

        self.assertEqual(len(response["work_items"]), 1)
        self.assertEqual(response["internal_only"], defaults["internal_only"])
        self.assertEqual(response["live_execution_enabled"], defaults["live_execution_enabled"])
        self.assertEqual(response["blocked_by_default"], defaults["blocked_by_default"])

    def test_stage7_preview_surface_consumes_formal_objects(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        response = list_saleable_opportunities(stage7)

        self.assertEqual(response["surface_id"], "opportunity_pool")
        self.assertEqual(response["surface_mode"], "preview-only")
        self.assertTrue(response["internal_only"])
        self.assertFalse(response["live_execution_enabled"])
        self.assertIn("saleable_opportunity", response["formal_object_refs"])
        self.assertIn("offer_summary", response["preview_projection"])
        self.assertIn("actor_preview", response["preview_projection"])
        self.assertIn(response["surface_state"], {"preview-ready", "review-required", "governed-hold"})
        self.assertEqual(response["surface_state"], response["semantic_envelope"]["surface_state"])
        self.assertEqual(response["surface_access"], response["semantic_envelope"]["surface_access"])
        self.assertEqual(response["decision_states"], response["governance_envelope"]["decision_states"])
        self.assertEqual(response["capability_envelope"]["surface_capability_mode"], "INTERNAL_ONLY")
        capability_families = {
            entry["capability_family"]: entry["projected_current_mode"]
            for entry in response["capability_envelope"]["capability_family_refs"]
        }
        self.assertEqual(capability_families["delivery_export_variants"], "INTERNAL_GOVERNED")
        self.assertTrue(response["governance_envelope"]["action_availability"]["refreshSaleableOpportunity"]["allowed"])
        self.assertFalse(response["operational_loop_persisted"])
        self.assertEqual(response["operational_context_status"], "transient_preview")
        self.assertIn("transient_preview_context", response)
        self.assertNotIn("pending_actions", response["transient_preview_context"])
        self.assertNotIn("pending_button_flows", response["transient_preview_context"])
        self.assertNotIn("action_history", response["transient_preview_context"])
        self.assertNotIn("last_action", response["transient_preview_context"])
        self.assertEqual(response["operator_loop_projection"]["context_key"], "transient_preview_context")
        self.assertEqual(response["operator_loop_projection"]["workbench_replay_source"], "projection_only")
        self.assertFalse(response["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(response["operator_loop_projection"]["action_history_count"], 0)
        self.assertEqual(response["operator_loop_projection"]["pending_action_count"], 0)
        self.assertEqual(response["operator_loop_projection"]["pending_button_flow_count"], 0)
        self.assertEqual(
            response["operator_loop_projection"]["action_controls_source"],
            "governance_envelope.action_availability",
        )
        self.assertFalse(response["operator_loop_projection"]["display_contract"]["action_history_visible"])
        self.assertFalse(response["operator_loop_projection"]["display_contract"]["pending_button_flows_visible"])
        self.assertEqual(response["workbench_replay"]["context_key"], "transient_preview_context")
        self.assertEqual(response["workbench_replay"]["replay_source"], "projection_only")
        self.assertEqual(
            response["workbench_replay"]["work_item_key"],
            response["transient_preview_context"]["work_item_key"],
        )
        self.assertIn(
            response["transient_preview_context"]["current_operational_state"],
            {"ready_for_internal_operator_action", "review_required", "governed_hold"},
        )
        self.assertEqual(
            response["transient_preview_context"]["object_refs"]["offer_recommendation_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertEqual(
            response["transient_preview_context"]["object_refs"]["buyer_fit_id"],
            stage7.record("buyer_fit").get("buyer_fit_id"),
        )

    def test_stage8_preview_surface_keeps_governed_and_blocked_boundaries(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        list_response = list_contact_targets(stage8)
        draft_response = create_outreach_plan(stage8)

        self.assertEqual(list_response["surface_id"], "outreach_workbench")
        self.assertEqual(draft_response["surface_mode"], "draft-only")
        self.assertTrue(list_response["blocked_by_default"])
        self.assertFalse(list_response["live_execution_enabled"])
        self.assertIn("outreach_plan", list_response["formal_object_refs"])
        self.assertIn("touch_record_preview", list_response["preview_projection"])
        self.assertTrue(list_response["trace_refs"]["policy_trace_present"])
        self.assertEqual(list_response["surface_state"], list_response["semantic_envelope"]["surface_state"])
        self.assertEqual(list_response["decision_states"], list_response["governance_envelope"]["decision_states"])
        self.assertEqual(list_response["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        capability_families = {
            entry["capability_family"]: entry["projected_current_mode"]
            for entry in list_response["capability_envelope"]["capability_family_refs"]
        }
        self.assertEqual(capability_families["stage8_execution"], "DRY_RUN")
        self.assertEqual(capability_families["contact_enrichment"], "APPROVAL_REQUIRED")
        self.assertEqual(
            draft_response["draft_created"],
            draft_response["governance_envelope"]["action_availability"]["createOutreachPlan"]["allowed"],
        )
        self.assertFalse(list_response["operational_loop_persisted"])
        self.assertEqual(list_response["operational_context_status"], "transient_preview")
        self.assertIn("transient_preview_context", list_response)
        self.assertNotIn("pending_actions", list_response["transient_preview_context"])
        self.assertNotIn("pending_button_flows", list_response["transient_preview_context"])
        self.assertNotIn("action_history", list_response["transient_preview_context"])
        self.assertEqual(list_response["operator_loop_projection"]["context_key"], "transient_preview_context")
        self.assertEqual(list_response["workbench_replay"]["replay_source"], "projection_only")
        self.assertIn(
            list_response["transient_preview_context"]["surface_operational_state"],
            {"draft_only", "review_required", "governed_hold"},
        )
        self.assertTrue(draft_response["operational_loop_persisted"])
        self.assertEqual(draft_response["operational_context_status"], "persisted")
        self.assertIn("persisted_operational_context", draft_response)
        self.assertIn("pending_actions", draft_response["persisted_operational_context"])
        self.assertIn("pending_button_flows", draft_response["persisted_operational_context"])
        self.assertIn("action_history", draft_response["persisted_operational_context"])
        self.assertEqual(draft_response["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(draft_response["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(draft_response["operator_loop_projection"]["queue_materialized"])
        self.assertTrue(draft_response["operator_loop_projection"]["display_contract"]["action_history_visible"])
        self.assertTrue(draft_response["operator_loop_projection"]["display_contract"]["pending_button_flows_visible"])
        self.assertEqual(
            draft_response["operator_loop_projection"]["pending_action_count"],
            len(draft_response["persisted_operational_context"]["pending_actions"]),
        )
        self.assertEqual(
            draft_response["operator_loop_projection"]["pending_button_flow_count"],
            len(draft_response["persisted_operational_context"]["pending_button_flows"]),
        )
        self.assertEqual(
            draft_response["operator_loop_projection"]["action_history_count"],
            len(draft_response["persisted_operational_context"]["action_history"]),
        )
        self.assertEqual(draft_response["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(
            draft_response["workbench_replay"]["work_item_id"],
            draft_response["persisted_operational_context"]["work_item_id"],
        )
        self.assertEqual(
            draft_response["persisted_operational_context"]["object_refs"]["contact_target_id"],
            stage8.record("contact_target").get("contact_target_id"),
        )
        self.assertEqual(
            draft_response["persisted_operational_context"]["object_refs"]["outreach_plan_id"],
            stage8.record("outreach_plan").get("outreach_plan_id"),
        )
        self.assertEqual(
            draft_response["persisted_operational_context"]["object_refs"]["touch_record_id"],
            stage8.record("touch_record").get("touch_record_id"),
        )

    def test_stage8_persisted_surface_replays_writeback_and_human_handoff_without_unblocking(self) -> None:
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
        governed = replay["persisted_operational_context"]["governed_context"]

        for response in (created, replay):
            self.assertEqual(response["surface_id"], "outreach_workbench")
            self.assertEqual(response["surface_mode"], "draft-only")
            self.assertTrue(response["internal_only"])
            self.assertTrue(response["blocked_by_default"])
            self.assertFalse(response["live_execution_enabled"])
            self.assertEqual(response["formalization_scope"], "INTERNAL_GOVERNED")
            self.assertTrue(response["operational_loop_persisted"])
            self.assertEqual(response["operational_context_status"], "persisted")
            self.assertIn("persisted_operational_context", response)
            self.assertEqual(response["operator_loop_projection"]["context_key"], "persisted_operational_context")
            self.assertEqual(response["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
            self.assertTrue(response["operator_loop_projection"]["queue_materialized"])
            self.assertEqual(
                response["operator_loop_projection"]["action_controls_source"],
                "persisted_operational_context.pending_actions",
            )
            self.assertEqual(response["workbench_replay"]["replay_source"], "repository_readback")

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
        self.assertEqual(created["persisted_operational_context"]["governed_context"], governed)
        self.assertEqual(
            created["persisted_operational_context"]["work_item_key"],
            replay["persisted_operational_context"]["work_item_key"],
        )
        self.assertEqual(
            created["workbench_replay"]["work_item_id"],
            replay["workbench_replay"]["work_item_id"],
        )
        self.assertEqual(created["surface_state"], replay["surface_state"])
        self.assertEqual(
            created["governance_envelope"]["action_availability"],
            replay["governance_envelope"]["action_availability"],
        )

    def test_stage9_preview_surface_is_draft_only_and_not_live(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        list_response = list_orders(stage9)
        create_response = create_order(stage9)
        delivery_response = create_delivery_record(stage9)

        self.assertEqual(list_response["surface_id"], "order_delivery_workbench")
        self.assertEqual(list_response["surface_mode"], "draft-only")
        self.assertTrue(list_response["blocked_by_default"])
        self.assertFalse(list_response["live_execution_enabled"])
        self.assertEqual(list_response["formalization_scope"], "INTERNAL_GOVERNED")
        self.assertIn("order_record", list_response["formal_object_refs"])
        self.assertIn("payment_draft_preview", list_response["preview_projection"])
        self.assertEqual(list_response["surface_state"], list_response["semantic_envelope"]["surface_state"])
        self.assertEqual(list_response["decision_states"], list_response["governance_envelope"]["decision_states"])
        self.assertEqual(list_response["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        capability_families = {
            entry["capability_family"]: entry["projected_current_mode"]
            for entry in list_response["capability_envelope"]["capability_family_refs"]
        }
        self.assertEqual(capability_families["stage9_execution"], "SHADOW_MODE")
        self.assertEqual(capability_families["delivery_export_variants"], "INTERNAL_GOVERNED")
        self.assertEqual(
            create_response["draft_created"],
            create_response["governance_envelope"]["action_availability"]["createOrder"]["allowed"],
        )
        self.assertEqual(
            delivery_response["preview_generated"],
            delivery_response["governance_envelope"]["action_availability"]["createDeliveryRecord"]["allowed"],
        )
        self.assertFalse(list_response["operational_loop_persisted"])
        self.assertEqual(list_response["operational_context_status"], "transient_preview")
        self.assertIn("transient_preview_context", list_response)
        self.assertNotIn("pending_actions", list_response["transient_preview_context"])
        self.assertNotIn("pending_button_flows", list_response["transient_preview_context"])
        self.assertNotIn("action_history", list_response["transient_preview_context"])
        self.assertEqual(list_response["operator_loop_projection"]["context_key"], "transient_preview_context")
        self.assertEqual(list_response["workbench_replay"]["replay_source"], "projection_only")
        self.assertIn(
            list_response["transient_preview_context"]["surface_operational_state"],
            {"draft_only", "preview_ready", "review_required", "governed_hold"},
        )
        self.assertTrue(create_response["operational_loop_persisted"])
        self.assertEqual(create_response["operational_context_status"], "persisted")
        self.assertIn("persisted_operational_context", create_response)
        self.assertIn("pending_actions", create_response["persisted_operational_context"])
        self.assertIn("pending_button_flows", create_response["persisted_operational_context"])
        self.assertIn("action_history", create_response["persisted_operational_context"])
        self.assertEqual(create_response["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(create_response["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(create_response["operator_loop_projection"]["queue_materialized"])
        self.assertTrue(create_response["operator_loop_projection"]["display_contract"]["action_history_visible"])
        self.assertEqual(
            create_response["operator_loop_projection"]["pending_action_count"],
            len(create_response["persisted_operational_context"]["pending_actions"]),
        )
        self.assertEqual(
            create_response["operator_loop_projection"]["pending_button_flow_count"],
            len(create_response["persisted_operational_context"]["pending_button_flows"]),
        )
        self.assertEqual(
            create_response["operator_loop_projection"]["action_history_count"],
            len(create_response["persisted_operational_context"]["action_history"]),
        )
        self.assertEqual(create_response["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(
            create_response["persisted_operational_context"]["object_refs"]["payment_id"],
            stage9.record("payment_record").get("payment_id"),
        )
        self.assertEqual(
            create_response["persisted_operational_context"]["object_refs"]["delivery_id"],
            stage9.record("delivery_record").get("delivery_id"),
        )
        self.assertEqual(
            create_response["persisted_operational_context"]["object_refs"]["outcome_event_id"],
            stage9.record("opportunity_outcome_event").get("outcome_event_id"),
        )
        self.assertEqual(
            create_response["persisted_operational_context"]["object_refs"]["governance_feedback_event_id"],
            stage9.record("governance_feedback_event").get("governance_feedback_event_id"),
        )

    def test_stage9_preview_surface_uses_canonical_pending_approval_mapping(self) -> None:
        stage9 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage9"]
        stage9.record("order_record").data["order_status"] = "PENDING_APPROVAL"

        response = list_orders(stage9)

        self.assertEqual(response["surface_state"], "governed-hold")
        self.assertEqual(response["semantic_envelope"]["surface_state"], "governed-hold")
        self.assertEqual(
            response["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertIn("formal_status:order_record=PENDING_APPROVAL", response["semantic_envelope"]["state_reasons"])

    def test_stage7_to_stage9_work_item_routes_use_canonical_surface_defaults(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        stage9 = result["stage9"]

        responses = (
            (list_stage7_work_items(stage7), "opportunity_pool"),
            (list_stage8_work_items(stage8), "outreach_workbench"),
            (list_stage9_work_items(stage9), "order_delivery_workbench"),
        )

        for response, surface_id in responses:
            defaults = get_surface_runtime_defaults(surface_id)
            self.assertEqual(response["internal_only"], defaults["internal_only"])
            self.assertEqual(response["live_execution_enabled"], defaults["live_execution_enabled"])
            self.assertEqual(response["blocked_by_default"], defaults["blocked_by_default"])

    def test_leadpack_candidate_surface_is_internal_only_and_candidate_only(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        preview_response = preview_leadpack_external_delivery_candidate(result)
        review_response = request_leadpack_external_delivery_candidate_review(result)
        simulation_response = simulate_leadpack_external_delivery_export(result)

        self.assertEqual(preview_response["surface_id"], "review_report_workbench")
        self.assertTrue(preview_response["internal_only"])
        self.assertTrue(preview_response["candidate_only"])
        self.assertFalse(preview_response["external_delivery_enabled"])
        self.assertTrue(preview_response["requires_review"])
        self.assertFalse(preview_response["approval_prerequisites_met"])
        self.assertIn("leadpack_candidate_review_gate", preview_response["required_review_gates"])
        self.assertIn("leadpack_candidate_review_gate", preview_response["missing_review_gates"])
        self.assertIn("stage7.opportunity_summary", preview_response["candidate_projection"]["allowed_projection"])
        self.assertIn("stage8.contact_activity_digest", preview_response["candidate_projection"]["masked_projection"])
        self.assertIn("stage9.fulfillment_summary", preview_response["candidate_projection"]["summary_only"])
        self.assertTrue(review_response["review_requested"])
        self.assertTrue(review_response["review_gate_prerequisites_met"])
        self.assertNotIn("leadpack_candidate_review_gate", review_response["missing_approvals"])
        self.assertTrue(simulation_response["export_simulation_requested"])
        self.assertTrue(simulation_response["export_simulation_allowed"])
        self.assertEqual(simulation_response["export_simulation_mode"], "simulation_only")
        self.assertFalse(simulation_response["direct_export_enabled"])
        self.assertFalse(simulation_response["external_ready_direct_export"])
        self.assertFalse(simulation_response["external_delivery_enabled"])
        self.assertIn("approval_prerequisites_not_met", simulation_response["blocked_reasons"])

    def test_leadpack_activation_prep_surface_is_review_only_and_can_fail_formally(self) -> None:
        happy = run_internal_chain(load_fixture("internal_chain_happy.json"))
        blocked = run_internal_chain(load_fixture("internal_chain_block.json"))

        packet = preview_leadpack_activation_prep_packet(happy)
        review = request_leadpack_activation_prep_review(happy)
        blocked_review = request_leadpack_activation_prep_review(blocked)

        self.assertTrue(packet["internal_only"])
        self.assertTrue(packet["candidate_only"])
        self.assertFalse(packet["external_delivery_enabled"])
        self.assertEqual(packet["evidence_pack"]["evidence_pack_status"], "ACTIVATION_PREP_READY_FOR_REVIEW")
        self.assertEqual(review["readiness_transition"]["current_prep_status"], "ACTIVATION_PREP_READY_FOR_REVIEW")
        self.assertTrue(review["activation_prep_review_requested"])
        self.assertEqual(review["signoff_packet"]["packet_status"], "PACKET_READY_FOR_REVIEW")
        self.assertEqual(review["simulation_replay"]["replay_status"], "REPLAY_READY")
        self.assertIn("manual prep review still required", review["evidence_pack"]["activation_blockers_remaining"])
        self.assertIn("actual activation remains out of scope", review["evidence_pack"]["activation_blockers_remaining"])

        self.assertFalse(blocked_review["activation_prep_review_requested"])
        self.assertEqual(blocked_review["error"]["error_code"], "LEADPACK-409-ACTIVATION_PREP_NOT_READY")
        self.assertEqual(blocked_review["readiness_transition"]["current_prep_status"], "ACTIVATION_PREP_HELD")
        self.assertTrue(blocked_review["error"]["meta"]["missing_evidence_items"])
        self.assertIn("candidate_source_status_blocked", blocked_review["error"]["meta"]["activation_blockers_remaining"])

    def test_leadpack_activation_design_prep_surface_is_design_only_and_can_fail_formally(self) -> None:
        happy = run_internal_chain(load_fixture("internal_chain_happy.json"))
        blocked = run_internal_chain(load_fixture("internal_chain_block.json"))

        packet = preview_leadpack_activation_design_implementation_prep_packet(happy)
        review = request_leadpack_activation_design_implementation_prep_review(happy)
        blocked_review = request_leadpack_activation_design_implementation_prep_review(blocked)

        self.assertTrue(packet["internal_only"])
        self.assertTrue(packet["candidate_only"])
        self.assertFalse(packet["external_delivery_enabled"])
        self.assertFalse(packet["actual_activation_enabled"])
        self.assertFalse(packet["implementation_approved"])
        self.assertEqual(packet["activation_design_prep_status"], "ACTIVATION_DESIGN_PREP_READY_FOR_REVIEW")
        self.assertEqual(
            {entry["status"] for entry in packet["owner_signoff_execution"]["required_owner_signoffs"]},
            {"REQUESTED"},
        )
        self.assertTrue(review["activation_design_prep_review_requested"])
        self.assertEqual(review["implementation_decision_readiness"]["state"], "IMPLEMENTATION_DECISION_HELD")
        self.assertFalse(review["implementation_decision_readiness"]["ready"])
        hold_source_types = {entry["source_type"] for entry in review["implementation_decision_readiness"]["hold_sources"]}
        self.assertTrue({"owner_signoff", "approval_chain", "audit_ref"}.issubset(hold_source_types))
        self.assertIn(
            "owner_signoff_not_approved:release_approver",
            review["implementation_decision_readiness"]["blockers"],
        )
        self.assertIn(
            "approval_missing_or_pending:client_report_release",
            review["implementation_decision_readiness"]["blockers"],
        )

        self.assertFalse(blocked_review["activation_design_prep_review_requested"])
        self.assertEqual(blocked_review["error"]["error_code"], "LEADPACK-410-ACTIVATION_DESIGN_PREP_NOT_READY")
        self.assertEqual(blocked_review["activation_design_prep_status"], "ACTIVATION_DESIGN_PREP_HELD")

    def test_leadpack_implementation_decision_readiness_packet_is_review_only_and_held(self) -> None:
        happy = run_internal_chain(load_fixture("internal_chain_happy.json"))

        packet = preview_leadpack_implementation_decision_readiness_packet(happy)

        self.assertTrue(packet["internal_only"])
        self.assertTrue(packet["candidate_only"])
        self.assertEqual(packet["implementation_decision_packet_status"], "PACKET_HELD")
        self.assertFalse(packet["implementation_decision_ready"])
        self.assertEqual(packet["readiness_state"], "IMPLEMENTATION_DECISION_HELD")
        self.assertFalse(packet["implementation_decision_executed"])
        self.assertFalse(packet["implementation_approved"])
        self.assertTrue(packet["implementation_not_approved"])
        self.assertTrue(packet["actual_activation_not_approved"])
        self.assertTrue(packet["external_delivery_not_approved"])
        self.assertEqual(
            {entry["source_type"] for entry in packet["hold_sources"]},
            {"owner_signoff", "approval_chain", "review_gate", "audit_ref"},
        )
        self.assertEqual(packet["owner_signoff_summary"]["missing_or_pending"], ["governance_owner", "release_approver", "testing_owner"])
        self.assertIn("client_report_release", packet["approval_readiness_summary"]["missing_or_pending"])
        self.assertIn("leadpack_candidate_review_gate", packet["review_gate_readiness_summary"]["missing_or_pending"])
        self.assertIn("activation_design_decision_audit_ref", packet["audit_readiness_summary"]["missing_or_pending"])

    def test_route_registration_aligns_with_stage7_8_9_contracts(self) -> None:
        api_catalog = read_json("contracts/api/api_catalog.json")
        contract_ops = {
            op["operationId"]
            for group in api_catalog["groups"]
            if group["groupId"] in {"sales_surfaces", "outreach_surfaces", "orders_and_delivery", "leadpack_candidate_surfaces", "governance"}
            for op in group["operations"]
        }
        route_ops = {
            route["operationId"]
            for route in register_stage7_routes()
            + register_stage8_routes()
            + register_stage9_routes()
        }
        expected = {
            "listSaleableOpportunities",
            "refreshSaleableOpportunity",
            "listStage7WorkItems",
            "submitStage7OperatorAction",
            "previewLeadpackExternalDeliveryCandidate",
            "requestLeadpackExternalDeliveryCandidateReview",
            "simulateLeadpackExternalDeliveryExport",
            "previewLeadpackActivationPrepPacket",
            "requestLeadpackActivationPrepReview",
            "previewLeadpackActivationDesignImplementationPrepPacket",
            "previewLeadpackImplementationDecisionReadinessPacket",
            "requestLeadpackActivationDesignImplementationPrepReview",
            "listContactTargets",
            "checkContactCompliance",
            "createOutreachPlan",
            "createTouchRecord",
            "listStage8WorkItems",
            "submitStage8OperatorAction",
            "listOrders",
            "createOrder",
            "createPaymentRecord",
            "createDeliveryRecord",
            "listOpportunityOutcomes",
            "createOpportunityOutcomeEvent",
            "listGovernanceFeedbackEvents",
            "createGovernanceFeedbackEvent",
            "listStage9WorkItems",
            "submitStage9OperatorAction",
        }
        self.assertEqual(route_ops, expected)
        self.assertTrue(expected.issubset(contract_ops))

    def test_ui_contracts_define_surface_state_and_review_boundaries(self) -> None:
        surface_states = read_json("contracts/ui/page_surface_states.json")
        review_actions = read_json("contracts/ui/review_action_catalog.json")
        workbenches = read_json("contracts/ui/workbench_catalog.json")
        button_flows = read_json("contracts/ui/button_flow_catalog.json")
        export_templates = read_json("contracts/ui/export_template_catalog.json")

        profile_ids = {profile["profileId"] for profile in surface_states["profiles"]}
        operational_states = {state["stateId"] for state in surface_states["operationalStates"]}
        action_ids = {action["actionId"] for action in review_actions["actions"]}
        workbench_ids = {entry["workbenchId"] for entry in workbenches["workbenches"]}
        template_ids = {entry["templateId"] for entry in export_templates["templates"]}
        flow_ids = {entry["flowId"] for entry in button_flows["flows"]}

        for profile_id in (
            "stage7_internal_preview_surface",
            "leadpack_external_delivery_candidate_surface",
            "leadpack_activation_design_prep_surface",
            "leadpack_implementation_decision_readiness_packet_surface",
            "stage8_governed_preview_surface",
            "stage9_internal_governed_surface",
        ):
            self.assertIn(profile_id, profile_ids)
        for action_id in (
            "stage7_open_internal_preview",
            "stage7_mark_reviewed",
            "stage7_return_for_revision",
            "leadpack_candidate_open_preview",
            "leadpack_candidate_request_review",
            "leadpack_candidate_request_export_simulation",
            "leadpack_candidate_mark_hold",
            "leadpack_candidate_mark_denied",
            "leadpack_activation_prep_open_packet",
            "leadpack_activation_prep_request_review",
            "leadpack_activation_prep_mark_hold",
            "leadpack_activation_prep_mark_denied",
            "leadpack_activation_prep_return_for_revision",
            "leadpack_activation_prep_cancel",
            "leadpack_activation_design_prep_open_packet",
            "leadpack_implementation_decision_readiness_open_packet",
            "leadpack_activation_design_prep_request_review",
            "leadpack_activation_design_prep_mark_hold",
            "leadpack_activation_design_prep_mark_denied",
            "leadpack_activation_design_prep_emergency_off",
            "stage8_request_governed_review",
            "stage8_approve_draft_progression",
            "stage8_deny_draft_progression",
            "stage8_put_governed_hold",
            "stage8_return_for_revision",
            "stage9_submit_draft_writeback",
            "stage9_mark_reviewed",
            "stage9_deny_draft_writeback",
            "stage9_put_governed_hold",
            "stage9_return_for_revision",
        ):
            self.assertIn(action_id, action_ids)
        for state_id in (
            "preview_ready",
            "draft_only",
            "review_required",
            "governed_hold",
            "ready_for_internal_operator_action",
            "action_submitted",
            "action_completed",
            "action_denied",
            "action_returned_for_revision",
        ):
            self.assertIn(state_id, operational_states)
        for workbench_id in ("opportunity_pool", "outreach_workbench", "order_delivery_workbench", "review_report_workbench"):
            self.assertIn(workbench_id, workbench_ids)
        for template_id in (
            "leadpack_external_delivery_candidate_simulation",
            "stage7_internal_preview_summary",
            "stage8_governed_preview_summary",
            "stage9_internal_governed_preview_summary",
        ):
            self.assertIn(template_id, template_ids)
        for flow_id in (
            "open_leadpack_candidate_preview",
            "request_leadpack_candidate_review",
            "request_leadpack_candidate_export_simulation",
            "leadpack_candidate_hold_notice",
            "leadpack_candidate_denied_notice",
            "open_leadpack_activation_prep_packet",
            "request_leadpack_activation_prep_review",
            "leadpack_activation_prep_hold_notice",
            "leadpack_activation_prep_denied_notice",
            "leadpack_activation_prep_return_notice",
            "leadpack_activation_prep_cancel_notice",
            "open_leadpack_activation_design_prep_packet",
            "request_leadpack_activation_design_prep_review",
            "open_leadpack_implementation_decision_readiness_packet",
            "leadpack_activation_design_prep_hold_notice",
            "leadpack_activation_design_prep_denied_notice",
            "leadpack_activation_design_prep_emergency_off_notice",
            "open_stage7_internal_preview",
            "list_stage7_work_items",
            "submit_stage7_mark_reviewed",
            "submit_stage7_return_for_revision",
            "submit_stage8_governed_review",
            "list_stage8_work_items",
            "approve_stage8_draft_progression",
            "deny_stage8_draft_progression",
            "hold_stage8_draft_progression",
            "return_stage8_for_revision",
            "open_stage9_order_draft",
            "list_stage9_work_items",
            "open_stage9_delivery_preview",
            "submit_stage9_governance_feedback",
            "mark_stage9_reviewed",
            "deny_stage9_draft_writeback",
            "hold_stage9_draft_writeback",
            "return_stage9_for_revision",
        ):
            self.assertIn(flow_id, flow_ids)

    def test_api_permission_and_error_catalog_cover_internal_preview_surfaces(self) -> None:
        permission_matrix = read_json("contracts/api/permission_matrix.json")
        error_catalog = read_json("contracts/api/error_code_catalog.json")

        resources = {resource["resourceId"] for resource in permission_matrix["resources"]}
        self.assertTrue(
            {
                "stage7_internal_preview",
                "stage7_internal_work_items",
                "stage7_operator_action",
                "leadpack_external_delivery_candidate",
                "leadpack_activation_prep_packet",
                "leadpack_activation_design_implementation_prep_packet",
                "leadpack_implementation_decision_readiness_packet",
                "stage8_governed_preview",
                "stage8_internal_work_items",
                "stage8_operator_action",
                "stage9_internal_governed_preview",
                "stage9_internal_work_items",
                "stage9_operator_action",
                "governance_feedback_preview",
            }.issubset(resources)
        )
        error_codes = {
            item["code"]
            for category in error_catalog["categories"]
            for item in category["items"]
        }
        self.assertTrue(
            {
                "SURFACE-409-DRAFT_ONLY",
                "SURFACE-409-PREVIEW_ONLY",
                "SURFACE-423-GOVERNED_HOLD",
                "SURFACE-423-INTERNAL_ONLY",
                "LIVE-423-EXECUTION_BLOCKED",
                "LEADPACK-409-ACTIVATION_PREP_NOT_READY",
                "LEADPACK-410-ACTIVATION_DESIGN_PREP_NOT_READY",
                "WORKITEM-404-NOT_FOUND",
                "ACTION-409-NOT_PENDING",
                "ACTION-409-AUDIT_REQUIRED",
            }.issubset(error_codes)
        )


if __name__ == "__main__":
    unittest.main()
