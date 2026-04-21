from __future__ import annotations

from dataclasses import replace
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

from api.routes.stage7 import list_saleable_opportunities, list_stage7_work_items, refresh_saleable_opportunity, submit_stage7_operator_action
from api.routes.stage8 import create_touch_record, list_stage8_work_items, submit_stage8_operator_action
from api.routes.stage9 import create_governance_feedback_event, list_stage9_work_items, submit_stage9_operator_action
from helpers import load_fixture, run_internal_chain_to_stage7
from shared.pipeline import run_internal_chain
from storage import reopen_default_storage, reset_default_storage
from storage.repositories import WorkItemRepository


class TestInternalOperationalHardening(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

    def test_preview_context_does_not_masquerade_as_persisted_work_item(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]

        response = list_saleable_opportunities(stage7)
        queue = list_stage7_work_items({"opportunity_id": stage7.record("saleable_opportunity").get("opportunity_id")})

        self.assertFalse(response["operational_loop_persisted"])
        self.assertEqual(response["operational_context_status"], "transient_preview")
        self.assertNotIn("persisted_operational_context", response)
        self.assertIn("transient_preview_context", response)
        self.assertEqual(queue["work_items"], [])

    def test_missing_work_item_returns_structured_error(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]

        response = submit_stage7_operator_action(
            {
                "opportunity_id": stage7.record("saleable_opportunity").get("opportunity_id"),
                "action_id": "stage7_mark_reviewed",
                "button_flow_id": "submit_stage7_mark_reviewed",
                "reason": "attempt before persistence",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(response["error"]["error_code"], "WORKITEM-404-NOT_FOUND")

    def test_invalid_transition_returns_structured_not_pending_error(self) -> None:
        stage8 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage8"]
        create_touch_record(stage8)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=8)[0]
        repo.save(replace(persisted, audit_refs={"operator_action_audit_ref": "AUD-STAGE8-READY"}))

        first = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_request_governed_review",
                "button_flow_id": "submit_stage8_governed_review",
                "reason": "submit draft",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )
        second = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_request_governed_review",
                "button_flow_id": "submit_stage8_governed_review",
                "reason": "duplicate submit",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(first["action_result"]["action_state"], "action_submitted")
        self.assertEqual(second["error"]["error_code"], "ACTION-409-NOT_PENDING")

    def test_audit_required_error_does_not_backfill_synthetic_audit(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        refresh_saleable_opportunity(stage7)

        repo = WorkItemRepository()
        item = repo.list(stage_scope=7)[0]
        repo.save(replace(item, audit_refs={}))

        response = submit_stage7_operator_action(
            {
                "opportunity_id": stage7.record("saleable_opportunity").get("opportunity_id"),
                "action_id": "stage7_mark_reviewed",
                "button_flow_id": "submit_stage7_mark_reviewed",
                "reason": "audit should be required",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(response["error"]["error_code"], "ACTION-409-AUDIT_REQUIRED")
        self.assertEqual(repo.list(stage_scope=7)[0].audit_refs, {})

    def test_stage8_requires_resolved_approval_chain_before_progression(self) -> None:
        stage8 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage8"]
        create_touch_record(stage8)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=8)[0]
        repo.save(
            replace(
                persisted,
                audit_refs={"operator_action_audit_ref": "AUD-STAGE8-READY"},
                reviewer_role="",
                reviewer="",
                assignment_resolved_from="unassigned",
            )
        )

        queue = list_stage8_work_items({"opportunity_id": stage8.record("contact_target").get("opportunity_id")})
        self.assertEqual(queue["work_items"][0]["pending_actions"], [])

        response = submit_stage8_operator_action(
            {
                "opportunity_id": stage8.record("contact_target").get("opportunity_id"),
                "touch_record_id": stage8.record("touch_record").get("touch_record_id"),
                "action_id": "stage8_request_governed_review",
                "button_flow_id": "submit_stage8_governed_review",
                "reason": "approval chain should be required",
                "requested_by_role": "sales_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(response["error"]["error_code"], "ACTION-409-APPROVAL_REQUIRED")
        self.assertEqual(response["error"]["meta"]["approval_requirement_mode"], "resolved_reviewer_chain")
        self.assertIn("reviewer_role", response["error"]["meta"]["missing_approval_fields"])
        self.assertIn("reviewer", response["error"]["meta"]["missing_approval_fields"])
        self.assertIn("assignment_resolution", response["error"]["meta"]["missing_approval_fields"])
        self.assertEqual(repo.list(stage_scope=8)[0].current_operational_state, persisted.current_operational_state)

    def test_stage9_audit_and_approval_gates_stay_distinct(self) -> None:
        stage9 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage9"]
        create_governance_feedback_event(stage9)
        repo = WorkItemRepository()
        persisted = repo.list(stage_scope=9)[0]
        repo.save(replace(persisted, audit_refs={}))

        response = submit_stage9_operator_action(
            {
                "opportunity_id": stage9.record("order_record").get("opportunity_id"),
                "order_id": stage9.record("order_record").get("order_id"),
                "action_id": "stage9_submit_draft_writeback",
                "button_flow_id": "open_stage9_order_draft",
                "reason": "audit should still be required",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )

        self.assertEqual(response["error"]["error_code"], "ACTION-409-AUDIT_REQUIRED")
        self.assertNotEqual(response["error"]["error_code"], "ACTION-409-APPROVAL_REQUIRED")

    def test_file_backed_work_items_survive_default_session_reopen(self) -> None:
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
                "reason": "persist before reopen",
                "requested_by_role": "delivery_governance_user",
                "requested_by": "卡卡罗特",
            }
        )
        before = list_stage9_work_items({"opportunity_id": stage9.record("order_record").get("opportunity_id")})

        reopen_default_storage()
        after = list_stage9_work_items(
            {
                "opportunity_id": stage9.record("order_record").get("opportunity_id"),
                "order_id": stage9.record("order_record").get("order_id"),
            }
        )

        self.assertEqual(len(before["work_items"]), 1)
        self.assertEqual(after["work_items"][0]["work_item_id"], before["work_items"][0]["work_item_id"])
        self.assertEqual(
            after["work_items"][0]["current_operational_state"],
            before["work_items"][0]["current_operational_state"],
        )
        self.assertEqual(after["work_items"][0]["pending_actions"], before["work_items"][0]["pending_actions"])


if __name__ == "__main__":
    unittest.main()
