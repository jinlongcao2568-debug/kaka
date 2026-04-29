from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_yaml(relative_path: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


class TestControlledRealWorldE2ECloseout(unittest.TestCase):
    def setUp(self) -> None:
        self.report = read_yaml("control/controlled_real_world_e2e_pilot_report.yaml")
        self.gap_matrix = read_yaml("control/product_operability_gap_matrix.yaml")
        self.checklist = read_yaml("control/product_acceptance_checklist.yaml")
        self.task_library = read_yaml("control/product_task_library.yaml")
        self.current_task = read_yaml("control/current_task.yaml")

    def test_closeout_report_records_owner_operable_controlled_e2e(self) -> None:
        self.assertEqual(
            self.report["packet_ref"],
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
        )
        self.assertEqual(self.report["acceptance_result"], "CONTROLLED_REAL_WORLD_E2E_ACCEPTED")
        self.assertEqual(self.report["product_closure_result"], "CONTROLLED_REAL_WORLD_CLOSED")
        self.assertTrue(self.report["owner_can_complete_e2e_business_flow"])
        self.assertEqual(
            self.report["closeout_recommendation"],
            "PRODUCTION_CLOSEOUT_READY_FOR_OWNER_OPERATED_CONTROLLED_USE",
        )

    def test_report_covers_full_business_flow_and_twelve_acceptance_dimensions(self) -> None:
        step_ids = {step["step_id"] for step in self.report["e2e_flow"]}
        self.assertEqual(
            step_ids,
            {
                "source_capture",
                "parse",
                "public_verification",
                "rules",
                "product_package",
                "real_challenger",
                "crm_quote",
                "customer_artifact",
                "outreach",
                "payment_delivery",
                "writeback_audit",
                "slo_incident_rollback",
            },
        )
        for step in self.report["e2e_flow"]:
            with self.subTest(step=step["step_id"]):
                self.assertEqual(step["state"], "PRODUCTION_READY")
                self.assertTrue((ROOT / step["evidence_ref"]).exists(), step["evidence_ref"])

        dimensions = {entry["dimension"]: entry for entry in self.report["twelve_dimension_acceptance"]}
        self.assertEqual(len(dimensions), 12)
        self.assertEqual(dimensions["real_source_adapter_practicality"]["result"], "PASS_WITH_BOUNDARY")
        self.assertEqual(dimensions["wecom_and_model_assist"]["result"], "PASS_WITH_BOUNDARY")
        self.assertEqual(dimensions["controlled_opening_requirement_review"]["result"], "PASS")

    def test_controlled_opening_requirements_remain_closed_after_product_closeout(self) -> None:
        boundary = self.report["scope_boundary"]
        self.assertFalse(boundary["public_software_release_enabled"])
        self.assertFalse(boundary["unapproved_live_provider_call_enabled"])
        self.assertFalse(boundary["unapproved_live_capture_enabled"])
        self.assertFalse(boundary["real_refund_execution_enabled"])
        self.assertFalse(boundary["automated_refund_execution_enabled"])
        self.assertIn("no automated refund execution", boundary["refund_boundary"])

    def test_gap_matrix_and_checklist_mark_131_as_final_closeout(self) -> None:
        final_118r = self.gap_matrix["final_118R_operational_reacceptance"]
        final_131 = self.gap_matrix["final_131_controlled_real_world_e2e_closeout"]
        checklist_131 = self.checklist["tasks"][
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout"
        ]["current_131_closeout_result"]

        self.assertEqual(final_118r["real_world_gaps"], [])
        self.assertEqual(final_118r["product_closure_result"], "CONTROLLED_REAL_WORLD_CLOSED")
        self.assertTrue(final_118r["owner_end_to_end_real_world_sales_delivery_operable"])
        self.assertEqual(final_131["remaining_product_blockers"], [])
        self.assertEqual(checklist_131["remaining_product_blockers"], [])
        self.assertEqual(
            checklist_131["report_ref"],
            "control/controlled_real_world_e2e_pilot_report.yaml",
        )

        resolved = {row["gap_id"]: row for row in final_118r["resolved_real_world_gaps"]}
        self.assertEqual(
            resolved["B118R_REAL_WORLD_E2E_PILOT_NOT_DONE"]["resolved_by_task_id"],
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
        )

    def test_task_pool_marks_127_through_132_completed_and_post_132_real_source_packets_progress(self) -> None:
        tasks = {entry["task_id"]: entry for entry in self.task_library["tasks"]}
        for task_id in (
            "PTL-I100-127-owner-operator-frontend-and-customer-portal",
            "PTL-I100-128-real-public-source-field-validation-and-coverage",
            "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
            "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
            "PTL-I100-132-owner-operator-frontend-productization-workbench",
        ):
            with self.subTest(task=task_id):
                self.assertEqual(tasks[task_id]["status"], "COMPLETED")
                self.assertEqual(tasks[task_id]["planning_state"], "COMPLETED")
                self.assertFalse(tasks[task_id]["is_current_mainline_next_candidate"])

        candidate = self.task_library["current_mainline_next_candidate"]
        self.assertEqual(candidate["planning_state"], "ACTIVE")
        self.assertNotIn(
            candidate["task_id"],
            {
                "PTL-I100-127-owner-operator-frontend-and-customer-portal",
                "PTL-I100-128-real-public-source-field-validation-and-coverage",
                "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
                "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
                "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
                "PTL-I100-132-owner-operator-frontend-productization-workbench",
            },
        )
        self.assertEqual(candidate["task_id"], self.current_task["currentTask"]["task_id"])
        self.assertRegex(candidate["runtime_notes"], r"public|verification|entry")
        self.assertEqual(tasks[candidate["task_id"]]["status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
