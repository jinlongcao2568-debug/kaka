from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from shared.pipeline import run_internal_chain
from shared.settings import Settings


ACCEPTANCE_FIXTURE = ROOT / "fixtures" / "internal_acceptance_full_product_operational.json"
REACCEPTANCE_FIXTURE = ROOT / "fixtures" / "internal_acceptance_full_product_operational_reacceptance.json"


def read_json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def read_yaml(relative_path: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


class TestFullProductOperationalAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.acceptance = json.loads(ACCEPTANCE_FIXTURE.read_text(encoding="utf-8"))
        self.reacceptance = json.loads(REACCEPTANCE_FIXTURE.read_text(encoding="utf-8"))
        self.gap_matrix = read_yaml("control/product_operability_gap_matrix.yaml")
        self.checklist = read_yaml("control/product_acceptance_checklist.yaml")
        self.task_library = read_yaml("control/product_task_library.yaml")

    def test_118_acceptance_result_is_blocked_not_closeout(self) -> None:
        metadata = self.acceptance["metadata"]
        product_closure = self.acceptance["three_layer_acceptance"]["product_closure"]
        final_gap = self.gap_matrix["final_118_operational_acceptance"]
        checklist_result = self.checklist["tasks"][
            "PTL-I100-118-full-product-operational-acceptance"
        ]["current_118_acceptance_result"]

        self.assertEqual(metadata["packet_id"], "PTL-I100-118-full-product-operational-acceptance")
        self.assertEqual(metadata["acceptance_result"], "BLOCKED_BY_PRODUCT_OPERATIONAL_GAPS")
        self.assertEqual(final_gap["acceptance_result"], metadata["acceptance_result"])
        self.assertEqual(checklist_result["acceptance_result"], metadata["acceptance_result"])
        self.assertEqual(product_closure["status"], "NOT_CLOSED")
        self.assertTrue(product_closure["owner_internal_loop_operable"])
        self.assertFalse(product_closure["owner_end_to_end_sales_delivery_operable"])
        self.assertEqual(product_closure["closeout_recommendation"], "DO_NOT_CLOSEOUT")
        self.assertEqual(final_gap["closeout_recommendation"], "DO_NOT_CLOSEOUT")
        self.assertEqual(checklist_result["closeout_recommendation"], "DO_NOT_CLOSEOUT")

    def test_capability_states_are_verified_without_promoting_readback_to_live(self) -> None:
        policy_states = set(self.gap_matrix["product_model"]["open_capability_policy"]["state_order"])
        capabilities = self.acceptance["three_layer_acceptance"]["capability_state"]["capabilities"]
        by_id = {entry["capability_id"]: entry for entry in capabilities}

        for entry in capabilities:
            with self.subTest(capability=entry["capability_id"]):
                if entry["state"] != "EXCLUDED":
                    self.assertIn(entry["state"], policy_states)
                self.assertFalse(entry["default_live_execution_enabled"])

        self.assertEqual(by_id["sales_outreach_live_pilot"]["state"], "LIVE_READY")
        self.assertEqual(
            by_id["sales_outreach_live_pilot"]["owner_operability"],
            "approved_live_pilot_readback_only",
        )
        self.assertEqual(by_id["payment_delivery_live_pilot_no_auto_refund"]["state"], "LIVE_READY")
        self.assertEqual(by_id["production_slo_monitoring_incident"]["state"], "PRODUCTION_READY")
        self.assertEqual(by_id["automated_refund_execution"]["state"], "EXCLUDED")

    def test_internal_runtime_chain_reaches_sales_package_order_and_audit_readback(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))

        for stage_name in (
            "stage1",
            "stage2",
            "stage3",
            "stage4",
            "stage5",
            "stage6",
            "stage7",
            "stage8",
            "stage9",
        ):
            with self.subTest(stage=stage_name):
                self.assertIn(stage_name, result)
                self.assertTrue(result[stage_name].records)

        stage7 = result["stage7"]
        stage8 = result["stage8"]
        stage9 = result["stage9"]

        package = stage7.inputs["stage6_product_package_readiness"]
        self.assertEqual(package["product_package_readiness"], "INTERNAL_READY")
        self.assertEqual(package["sales_readiness"], "INTERNAL_READY_NO_EXECUTION_TRIGGERED")
        self.assertTrue(package["audit_readback_summary"]["replayable"])
        self.assertTrue(package["audit_readback_summary"]["no_external_release_enabled"])

        challenger = stage7.inputs["real_challenger_readback"]
        self.assertEqual(challenger["readiness_state"], "INTERNAL_READY")
        self.assertEqual(challenger["real_challenger_decision_state"], "ALLOW")
        self.assertTrue(challenger["winning_candidate"]["internal_sales_judgment_only"])
        self.assertFalse(challenger["winning_candidate"]["customer_visible"])

        crm_workbench = stage7.inputs["crm_quote_workbench"]
        self.assertEqual(crm_workbench["quote_surface_state"], "DRAFT")
        self.assertFalse(crm_workbench["real_external_quote_sent"])
        self.assertFalse(crm_workbench["real_crm_receipt_generated"])
        self.assertEqual(
            crm_workbench["quote_sandbox_record"]["quote_sandbox_state"],
            "SANDBOX_READBACK_READY",
        )

        leadpack = stage7.inputs["leadpack_delivery_package"]
        candidate = leadpack["customer_visible_artifact_candidate"]
        self.assertTrue(candidate["field_policy"]["allowlist_enforced"])
        self.assertTrue(candidate["field_policy"]["blacklist_enforced"])
        self.assertTrue(candidate["masking"]["masking_required"])
        self.assertEqual(leadpack["watermark"]["watermark_state"], "APPLIED_TO_DRAFT")
        self.assertTrue(leadpack["artifact_version_hash"].startswith("sha256:"))
        self.assertTrue(leadpack["download_audit"]["audit_replayable"])
        self.assertFalse(candidate["customer_visible_enabled"])
        self.assertFalse(candidate["external_delivery_enabled"])
        self.assertFalse(leadpack["download_audit"]["customer_download_enabled"])

        outbox = stage8.inputs["outreach_execution_outbox_snapshot"]
        self.assertEqual(outbox["sandbox_execution_state"], "SANDBOX_RECORDED")
        self.assertTrue(outbox["replay_state"]["sandbox_record_replayable"])
        self.assertFalse(outbox["real_send_attempted"])
        self.assertFalse(outbox["provider_result_readback"]["provider_call_executed"])

        ledger = stage9.inputs["stage9_execution_ledger"]
        self.assertTrue(stage9.inputs["stage9_execution_ledger_readiness"]["owner_operable"])
        self.assertIn(ledger["refund_execution_state"], {"MANUAL_EXCEPTION_ONLY", "MANUAL_EXCEPTION_REVIEW"})
        self.assertFalse(ledger["automated_refund_enabled"])
        self.assertFalse(ledger["real_charge_attempted"])
        self.assertFalse(ledger["real_delivery_attempted"])
        self.assertTrue(stage9.inputs["manual_refund_exception_record"]["audit_record"]["audit_required"])
        self.assertEqual(stage9.record("order_record").get("governed_execution_mode"), "INTERNAL_GOVERNED")

    def test_approved_live_pilot_carriers_are_ready_but_do_not_execute_providers(self) -> None:
        stage8_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        stage8_payload.update(
            {
                "live_execution_requested": True,
                "approval_state": "APPROVED",
                "template_approval_state": "APPROVED",
                "operator_approval_state": "APPROVED",
                "operator_action_audit_refs": ["AUD-STAGE8-LIVE-PILOT-001"],
                "approved_sample_size": 1,
                "requested_sample_size": 1,
            }
        )
        stage8 = run_internal_chain(stage8_payload)["stage8"]
        outbox = stage8.inputs["outreach_execution_outbox_snapshot"]
        outbox_summary = stage8.inputs["outbox_readiness_summary"]

        self.assertEqual(outbox["live_pilot_readiness_state"], "LIVE_READY")
        self.assertTrue(outbox["live_execution_enabled"])
        self.assertTrue(outbox_summary["live_pilot_execution_ready"])
        self.assertFalse(outbox_summary["ready_for_real_send"])
        self.assertFalse(outbox["real_send_attempted"])
        self.assertFalse(outbox["provider_result_readback"]["provider_call_executed"])
        self.assertFalse(outbox["live_execution_record"]["real_provider_call_enabled"])

        stage9_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        stage9_payload.update(
            {
                "payment_status": "PAID",
                "payment_proof_state": "PROVIDED",
                "paid_at_optional": "2026-04-24T10:00:00Z",
                "delivery_status": "READY",
                "manual_settlement_note_optional": "owner marked bank transfer as received",
                "payment_delivery_live_pilot_requested": True,
                "approved_sample_size": 1,
                "requested_sample_size": 1,
                "payment_approval_state": "APPROVED",
                "delivery_approval_state": "APPROVED",
                "finance_review_state": "APPROVED",
                "operator_action_audit_refs": ["AUDIT-S9-PILOT-001"],
                "download_auth_state": "AUTHORIZED",
            }
        )
        stage9 = run_internal_chain(stage9_payload)["stage9"]
        carrier = stage9.inputs["payment_delivery_live_pilot"]
        ledger = stage9.inputs["stage9_execution_ledger"]

        self.assertEqual(carrier["payment_live_pilot_readiness_state"], "LIVE_READY")
        self.assertEqual(carrier["delivery_live_pilot_readiness_state"], "LIVE_READY")
        self.assertTrue(carrier["live_payment_enabled"])
        self.assertTrue(carrier["live_delivery_enabled"])
        self.assertFalse(carrier["payment_provider_result_readback"]["provider_call_executed"])
        self.assertFalse(carrier["delivery_provider_result_readback"]["provider_call_executed"])
        self.assertFalse(carrier["real_payment_capture_attempted"])
        self.assertFalse(carrier["real_charge_attempted"])
        self.assertFalse(carrier["real_delivery_fulfillment_attempted"])
        self.assertFalse(carrier["real_customer_download_attempted"])
        self.assertFalse(carrier["real_refund_attempted"])
        self.assertFalse(carrier["automated_refund_program"]["present"])
        self.assertFalse(carrier["automated_refund_program"]["enabled"])
        self.assertTrue(ledger["live_payment_enabled"])
        self.assertTrue(ledger["live_delivery_enabled"])
        self.assertFalse(ledger["real_charge_attempted"])
        self.assertFalse(ledger["real_delivery_attempted"])

    def test_remaining_blockers_map_to_minimum_followup_tasks(self) -> None:
        blockers = self.acceptance["remaining_blockers"]
        final_gap_blockers = self.gap_matrix["final_118_operational_acceptance"]["remaining_blockers"]
        fixture_blocker_ids = {blocker["blocker_id"] for blocker in blockers}
        final_gap_blocker_ids = {blocker["blocker_id"] for blocker in final_gap_blockers}

        self.assertEqual(fixture_blocker_ids, final_gap_blocker_ids)
        self.assertEqual(len(blockers), 5)
        registered_task_ids = {row["task_id"] for row in self.task_library["tasks"]}
        for blocker in blockers:
            with self.subTest(blocker=blocker["blocker_id"]):
                self.assertTrue(blocker["minimum_followup_task_id"].startswith("PTL-I100-12"))
                self.assertIn(blocker["minimum_followup_task_id"], registered_task_ids)

        self.assertEqual(
            self.checklist["tasks"]["PTL-I100-118-full-product-operational-acceptance"][
                "current_118_acceptance_result"
            ]["minimum_followup_task_refs"],
            [blocker["minimum_followup_task_id"] for blocker in blockers],
        )

    def test_production_resilience_is_readback_ready_without_live_side_effects(self) -> None:
        readiness = Settings(
            storage_backend="sqlalchemy",
            storage_database_url_optional="sqlite:///:memory:",
        ).platform_infra_readiness()
        production = readiness["production_slo_incident_readiness"]
        controlled_opening_requirements = production["controlled_opening_requirements"]

        self.assertEqual(production["target_capability_state"], "PRODUCTION_READY")
        self.assertTrue(production["repository_backed_readback"])
        self.assertTrue(production["validation"]["valid"])
        self.assertTrue(
            all(
                evaluation["alert_fired"]
                for evaluation in production["simulated_alert_evaluation_readback"]
            )
        )
        self.assertEqual(
            production["suspended_state_operation_readback"]["suspension_state"],
            "SUSPENDED",
        )
        self.assertFalse(controlled_opening_requirements["real_alert_dispatch_enabled"])
        self.assertFalse(controlled_opening_requirements["incident_automation_enabled"])
        self.assertFalse(controlled_opening_requirements["destructive_restore_enabled"])
        self.assertFalse(controlled_opening_requirements["rollback_execution_enabled"])
        self.assertFalse(readiness["controlled_opening_requirements"]["real_provider_execution_enabled"])

    def test_118r_reacceptance_records_post_122_126_real_world_gaps(self) -> None:
        metadata = self.reacceptance["metadata"]
        product_closure = self.reacceptance["four_layer_acceptance"]["product_closure"]
        real_world = self.reacceptance["four_layer_acceptance"]["real_world_operability"]
        final = self.gap_matrix["final_118R_operational_reacceptance"]
        checklist = self.checklist["tasks"]["PTL-I100-118R-final-product-operational-reacceptance"]

        self.assertEqual(metadata["packet_id"], "PTL-I100-118R-final-product-operational-reacceptance")
        self.assertEqual(metadata["acceptance_result"], "BLOCKED_BY_REAL_WORLD_OPERATIONAL_GAPS")
        self.assertEqual(final["acceptance_result"], "CONTROLLED_REAL_WORLD_E2E_ACCEPTED")
        self.assertEqual(final["closeout_report_ref"], "control/controlled_real_world_e2e_pilot_report.yaml")
        self.assertEqual(product_closure["status"], "NOT_REAL_WORLD_CLOSED")
        self.assertEqual(final["product_closure_result"], "CONTROLLED_REAL_WORLD_CLOSED")
        self.assertTrue(product_closure["owner_internal_loop_operable"])
        self.assertTrue(product_closure["owner_controlled_execution_loop_operable"])
        self.assertFalse(product_closure["owner_end_to_end_real_world_sales_delivery_operable"])
        self.assertTrue(final["owner_end_to_end_real_world_sales_delivery_operable"])
        self.assertEqual(product_closure["closeout_recommendation"], "DO_NOT_PRODUCTION_CLOSEOUT")
        self.assertTrue(checklist["final_reacceptance_gate"])
        self.assertEqual(real_world["frontend_page_state"], "API_ONLY_NO_PRODUCTIZED_FRONTEND_DETECTED")
        self.assertEqual(real_world["source_adapter_field_validation_state"], "SANDBOX_ALLOWLISTED_NOT_REAL_SITE_VALIDATED")
        self.assertEqual(real_world["wecom_robot_integration_state"], "TARGET_TASK_REGISTERED_NOT_BOUND_TO_REAL_PROVIDER")
        self.assertEqual(real_world["llm_assist_state"], "TARGET_TASK_REGISTERED_NOT_PRODUCTIZED")

    def test_118r_capability_states_do_not_treat_fake_provider_as_real_provider(self) -> None:
        capabilities = self.reacceptance["four_layer_acceptance"]["capability_state"]["capabilities"]
        by_id = {entry["capability_id"]: entry for entry in capabilities}

        for capability_id in (
            "approved_sales_outreach_provider_execution",
            "approved_crm_quote_provider_execution",
            "approved_payment_delivery_provider_execution_no_auto_refund",
        ):
            with self.subTest(capability=capability_id):
                entry = by_id[capability_id]
                self.assertEqual(entry["execution_surface"], "LOCAL_CONTROLLED_FAKE_PROVIDER")
                self.assertTrue(entry["controlled_execution_recorded"])
                self.assertFalse(entry["real_provider_call_executed"])

        self.assertFalse(by_id["approved_payment_delivery_provider_execution_no_auto_refund"]["automated_refund_execution"])
        self.assertFalse(
            by_id["approved_production_live_dependency_drill"]["real_external_dependency_execution"]
        )

    def test_118r_followup_tasks_are_registered_for_remaining_real_world_gaps(self) -> None:
        gaps = self.reacceptance["remaining_real_world_gaps"]
        matrix_gaps = self.gap_matrix["final_118R_operational_reacceptance"]["real_world_gaps"]
        original_118r_task_ids = {
            "PTL-I100-127-owner-operator-frontend-and-customer-portal",
            "PTL-I100-128-real-public-source-field-validation-and-coverage",
            "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
            "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
        }
        unresolved_after_129_task_ids: set[str] = set()
        registered_task_ids = {row["task_id"] for row in self.task_library["tasks"]}

        self.assertEqual({gap["minimum_followup_task_id"] for gap in gaps}, original_118r_task_ids)
        self.assertEqual(
            {gap["minimum_followup_task_id"] for gap in matrix_gaps},
            unresolved_after_129_task_ids,
        )
        self.assertTrue(original_118r_task_ids.issubset(registered_task_ids))

    def test_runtime_probe_confirms_controlled_provider_paths_are_not_real_calls(self) -> None:
        stage8_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        stage8_payload.update(
            {
                "approved_provider_execution_requested": True,
                "live_execution_requested": True,
                "approval_state": "APPROVED",
                "template_approval_state": "APPROVED",
                "operator_approval_state": "APPROVED",
                "operator_action_audit_refs": ["AUD-STAGE8-APPROVED-001"],
                "approved_sample_size": 1,
                "requested_sample_size": 1,
            }
        )
        stage8 = run_internal_chain(stage8_payload)["stage8"]
        outbox = stage8.inputs["outreach_execution_outbox_snapshot"]

        self.assertEqual(outbox["controlled_provider_adapter_scope"], "LOCAL_CONTROLLED_FAKE_PROVIDER")
        self.assertTrue(outbox["controlled_provider_execution_executed"])
        self.assertFalse(outbox["real_send_attempted"])
        self.assertFalse(outbox["provider_result_readback"]["provider_call_executed"])

        stage9_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        stage9_payload.update(
            {
                "approved_payment_delivery_execution_requested": True,
                "payment_delivery_live_pilot_requested": True,
                "payment_status": "PAID",
                "payment_proof_state": "PROVIDED",
                "paid_at_optional": "2026-04-24T10:00:00Z",
                "delivery_status": "READY",
                "sandbox_payment_pass_state": "PASS",
                "payment_approval_state": "APPROVED",
                "delivery_approval_state": "APPROVED",
                "finance_review_state": "APPROVED",
                "operator_action_audit_refs": ["AUDIT-S9-APPROVED-001"],
                "download_auth_state": "AUTHORIZED",
                "approved_sample_size": 1,
                "requested_sample_size": 1,
            }
        )
        stage9 = run_internal_chain(stage9_payload)["stage9"]
        carrier = stage9.inputs["approved_payment_delivery_execution"]

        self.assertEqual(carrier["controlled_provider_adapter_scope"], "LOCAL_CONTROLLED_FAKE_PROVIDER")
        self.assertTrue(carrier["controlled_provider_execution_executed"])
        self.assertTrue(carrier["approved_payment_delivery_execution_enabled"])
        self.assertFalse(carrier["provider_call_executed"])
        self.assertFalse(carrier["real_payment_capture_attempted"])
        self.assertFalse(carrier["real_charge_attempted"])
        self.assertFalse(carrier["real_delivery_fulfillment_attempted"])
        self.assertFalse(carrier["real_customer_download_attempted"])
        self.assertFalse(carrier["automated_refund_program"]["present"])

    def test_127_adds_productized_internal_frontend_without_public_release_stack(self) -> None:
        frontend_route = ROOT / "src/api/routes/operator_frontend.py"
        self.assertTrue(frontend_route.exists())
        route_text = frontend_route.read_text(encoding="utf-8")

        self.assertIn("render_operator_console", route_text)
        self.assertIn("render_customer_artifact_portal", route_text)
        self.assertIn("external_release_enabled\": False", route_text)
        self.assertIn("automated_refund_enabled\": False", route_text)

        frontend_markers = [
            "package.json",
            "vite.config.ts",
            "vite.config.js",
            "next.config.js",
            "next.config.ts",
        ]
        frontend_extensions = {".tsx", ".jsx", ".vue", ".svelte"}
        self.assertFalse(any((ROOT / marker).exists() for marker in frontend_markers))
        self.assertFalse(
            any(
                path.suffix in frontend_extensions
                for path in ROOT.rglob("*")
                if ".git" not in path.parts
            )
        )


if __name__ == "__main__":
    unittest.main()
