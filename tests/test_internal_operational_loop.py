from __future__ import annotations

from dataclasses import replace
import unittest

from api.routes.stage7 import list_stage7_work_items, refresh_saleable_opportunity, submit_stage7_operator_action
from api.routes.stage8 import create_touch_record, list_stage8_work_items, submit_stage8_operator_action
from api.routes.stage9 import create_governance_feedback_event, list_stage9_work_items, submit_stage9_operator_action
import copy
from helpers import load_fixture, run_internal_chain_to_stage7
from shared.pipeline import run_internal_chain
from storage import reset_default_storage
from storage.repositories import WorkItemRepository


class TestInternalOperationalLoop(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

    def test_stage7_operator_loop_and_work_item_queue(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        refresh_saleable_opportunity(stage7)

        queue = list_stage7_work_items({"opportunity_id": stage7.record("saleable_opportunity").get("opportunity_id")})
        self.assertEqual(len(queue["work_items"]), 1)
        work_item = queue["work_items"][0]
        self.assertIn(work_item["surface_operational_state"], {"preview_ready", "review_required"})
        self.assertIn(work_item["current_operational_state"], {"ready_for_internal_operator_action", "review_required"})
        self.assertIn("stage7_mark_reviewed", work_item["pending_actions"])
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=7)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE7-READY"}))

        reviewed = submit_stage7_operator_action(
            {
                "opportunity_id": stage7.record("saleable_opportunity").get("opportunity_id"),
                "action_id": "stage7_mark_reviewed",
                "button_flow_id": "submit_stage7_mark_reviewed",
                "reason": "internal preview verified",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )
        self.assertEqual(reviewed["action_result"]["action_state"], "action_completed")
        self.assertEqual(reviewed["persisted_operational_context"]["current_operational_state"], "action_completed")
        self.assertEqual(reviewed["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "completed")
        self.assertEqual(reviewed["persisted_operational_context"]["pending_actions"], [])

    def test_stage8_operator_loop_progression_and_return(self) -> None:
        stage8 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage8"]
        create_touch_record(stage8)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=8)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE8-READY"}))

        requested = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "action_id": "stage8_request_governed_review",
                "button_flow_id": "submit_stage8_governed_review",
                "reason": "submit draft for governed review",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )
        self.assertEqual(requested["action_result"]["action_state"], "action_submitted")
        self.assertEqual(requested["persisted_operational_context"]["current_operational_state"], "action_submitted")
        self.assertEqual(requested["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "in_review")
        self.assertIn("stage8_approve_draft_progression", requested["persisted_operational_context"]["pending_actions"])

        returned = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "action_id": "stage8_return_for_revision",
                "button_flow_id": "return_stage8_for_revision",
                "reason": "need revised draft notes",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )
        self.assertEqual(returned["action_result"]["action_state"], "action_returned_for_revision")
        self.assertEqual(returned["persisted_operational_context"]["current_operational_state"], "action_returned_for_revision")
        self.assertEqual(returned["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "returned")

        queue = list_stage8_work_items({"opportunity_id": stage8.record("contact_target").get("opportunity_id")})
        self.assertEqual(len(queue["work_items"]), 1)
        self.assertEqual(queue["work_items"][0]["last_action"]["action_id"], "stage8_return_for_revision")

    def test_stage8_approve_progression_completes_when_approval_chain_is_available(self) -> None:
        stage8 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage8"]
        create_touch_record(stage8)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=8)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE8-READY"}))

        submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_request_governed_review",
                "button_flow_id": "submit_stage8_governed_review",
                "reason": "submit draft for governed review",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )
        approved = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_approve_draft_progression",
                "button_flow_id": "approve_stage8_draft_progression",
                "reason": "governed review approved",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(approved["action_result"]["action_state"], "action_completed")
        self.assertEqual(approved["persisted_operational_context"]["current_operational_state"], "action_completed")
        self.assertEqual(approved["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "completed")

    def test_stage8_hold_progression_reopens_governed_review_lane(self) -> None:
        stage8 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage8"]
        create_touch_record(stage8)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=8)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE8-READY"}))

        submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_request_governed_review",
                "button_flow_id": "submit_stage8_governed_review",
                "reason": "submit draft for governed review",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )
        held = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_put_governed_hold",
                "button_flow_id": "hold_stage8_draft_progression",
                "reason": "await governed clarification",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(held["action_result"]["action_state"], "governed_hold")
        self.assertEqual(held["persisted_operational_context"]["current_operational_state"], "governed_hold")
        self.assertEqual(held["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "in_review")
        self.assertEqual(held["persisted_operational_context"]["pending_actions"], ["stage8_request_governed_review"])

        queue = list_stage8_work_items({"opportunity_id": stage8.record("contact_target").get("opportunity_id")})
        self.assertEqual(len(queue["work_items"]), 1)
        self.assertEqual(queue["work_items"][0]["current_operational_state"], "governed_hold")
        self.assertEqual(queue["work_items"][0]["last_action"]["action_id"], "stage8_put_governed_hold")
        self.assertEqual(queue["work_items"][0]["pending_actions"], ["stage8_request_governed_review"])

    def test_stage8_deny_progression_persists_denied_queue_state(self) -> None:
        stage8 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage8"]
        create_touch_record(stage8)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=8)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE8-READY"}))

        submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_request_governed_review",
                "button_flow_id": "submit_stage8_governed_review",
                "reason": "submit draft for governed review",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )
        denied = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_deny_draft_progression",
                "button_flow_id": "deny_stage8_draft_progression",
                "reason": "draft denied by governance review",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(denied["action_result"]["action_state"], "action_denied")
        self.assertEqual(denied["persisted_operational_context"]["current_operational_state"], "action_denied")
        self.assertEqual(denied["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "denied")
        self.assertEqual(denied["persisted_operational_context"]["pending_actions"], [])

        queue = list_stage8_work_items({"opportunity_id": stage8.record("contact_target").get("opportunity_id")})
        self.assertEqual(len(queue["work_items"]), 1)
        self.assertEqual(queue["work_items"][0]["current_operational_state"], "action_denied")
        self.assertEqual(queue["work_items"][0]["assignment"]["assignment_lifecycle_state"], "denied")
        self.assertEqual(queue["work_items"][0]["last_action"]["action_id"], "stage8_deny_draft_progression")
        self.assertEqual(queue["work_items"][0]["pending_actions"], [])

    def test_stage8_work_item_exposes_persisted_writeback_and_handoff_context(self) -> None:
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
        queue = list_stage8_work_items({"opportunity_id": stage8.record("contact_target").get("opportunity_id")})

        governed = created["persisted_operational_context"]["governed_context"]
        queue_governed = queue["work_items"][0]["governed_context"]

        self.assertEqual(created["operational_context_status"], "persisted")
        self.assertEqual(governed["feedback_reason"], stage8.record("touch_record").get("feedback_reason"))
        self.assertEqual(governed["next_step_optional"], stage8.record("touch_record").get("next_step_optional"))
        self.assertEqual(governed["writeback_targets"], stage8.record("touch_record").get("writeback_targets"))
        self.assertEqual(
            governed["writeback_target_optional"],
            stage8.record("touch_record").get("writeback_target_optional"),
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
        self.assertEqual(queue_governed, governed)

    def test_stage9_writeback_loop_and_governed_hold(self) -> None:
        stage9 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage9"]
        create_governance_feedback_event(stage9)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=9)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE9-READY"}))

        submitted = submit_stage9_operator_action(
            {
                "opportunity_id": stage9.record("order_record").get("opportunity_id"),
                "order_id": stage9.record("order_record").get("order_id"),
                "action_id": "stage9_submit_draft_writeback",
                "button_flow_id": "open_stage9_order_draft",
                "reason": "submit typed writeback draft",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )
        self.assertEqual(submitted["action_result"]["action_state"], "action_submitted")
        self.assertEqual(submitted["persisted_operational_context"]["current_operational_state"], "action_submitted")
        self.assertEqual(submitted["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "in_review")
        self.assertIn("stage9_mark_reviewed", submitted["persisted_operational_context"]["pending_actions"])

        held = submit_stage9_operator_action(
            {
                "opportunity_id": stage9.record("order_record").get("opportunity_id"),
                "order_id": stage9.record("order_record").get("order_id"),
                "action_id": "stage9_put_governed_hold",
                "button_flow_id": "hold_stage9_draft_writeback",
                "reason": "await governed confirmation",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )
        self.assertEqual(held["action_result"]["action_state"], "governed_hold")
        self.assertEqual(held["persisted_operational_context"]["current_operational_state"], "governed_hold")

        queue = list_stage9_work_items({"opportunity_id": stage9.record("order_record").get("opportunity_id")})
        self.assertEqual(len(queue["work_items"]), 1)
        item = queue["work_items"][0]
        self.assertTrue(item["audit_refs"])
        self.assertTrue(item["trace_refs"])
        self.assertEqual(item["last_action"]["action_id"], "stage9_put_governed_hold")

    def test_stage9_mark_reviewed_completes_when_approval_chain_is_available(self) -> None:
        stage9 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage9"]
        create_governance_feedback_event(stage9)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=9)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE9-READY"}))

        submit_stage9_operator_action(
            {
                "opportunity_id": stage9.record("order_record").get("opportunity_id"),
                "order_id": stage9.record("order_record").get("order_id"),
                "action_id": "stage9_submit_draft_writeback",
                "button_flow_id": "open_stage9_order_draft",
                "reason": "submit typed writeback draft",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )
        reviewed = submit_stage9_operator_action(
            {
                "opportunity_id": stage9.record("order_record").get("opportunity_id"),
                "order_id": stage9.record("order_record").get("order_id"),
                "action_id": "stage9_mark_reviewed",
                "button_flow_id": "mark_stage9_reviewed",
                "reason": "governed writeback reviewed",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(reviewed["action_result"]["action_state"], "action_completed")
        self.assertEqual(reviewed["persisted_operational_context"]["current_operational_state"], "action_completed")
        self.assertEqual(reviewed["persisted_operational_context"]["assignment"]["assignment_lifecycle_state"], "completed")


if __name__ == "__main__":
    unittest.main()
