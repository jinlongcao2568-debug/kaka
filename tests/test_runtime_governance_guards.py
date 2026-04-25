from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from api.routes.stage7 import (
    preview_formal_client_export_page_layer_readiness,
    preview_leadpack_external_delivery_candidate,
    simulate_leadpack_external_delivery_export,
)
from shared.settings import Settings
from shared.provider_adapter_config import PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY
from shared.pipeline import run_internal_chain


class TestRuntimeGovernanceGuards(unittest.TestCase):
    def test_platform_infra_readiness_keeps_external_live_redlines_locked(self) -> None:
        settings = Settings(
            storage_backend="sqlalchemy",
            storage_database_url_optional="sqlite:///:memory:",
        )

        readiness = settings.platform_infra_readiness()
        redlines = readiness["redlines"]

        self.assertTrue(redlines["no_live_provider_call"])
        self.assertTrue(redlines["no_real_sales_outreach"])
        self.assertTrue(redlines["no_real_payment"])
        self.assertTrue(redlines["no_real_charge"])
        self.assertTrue(redlines["no_real_delivery"])
        self.assertTrue(redlines["no_real_refund"])
        self.assertTrue(redlines["no_automated_refund"])
        self.assertFalse(redlines["external_software_release_enabled"])
        self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
        self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
        self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
        self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])

    def test_stage8_high_restriction_field_requires_runtime_review(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "person_name_optional": "张三",
                "approval_state": "PENDING",
            }
        )

        result = run_internal_chain(payload)
        stage8 = result["stage8"]

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "REVIEW_REQUIRED")
        self.assertTrue(stage8.record("contact_target").get("requires_manual_review"))
        self.assertEqual(stage8.inputs.get("governance_decision_state"), "REVIEW")
        self.assertIn(
            "contact_target.person_name",
            stage8.inputs.get("governance_additions", {}).get("contact_target", {}).get("field_policy", {}).get("review_fields", []),
        )

    def test_stage8_delivery_matrix_blocks_outreach_plan_on_leadpack_surface(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["requested_delivery_surface"] = "LEADPACK_DELIVERABLE"

        result = run_internal_chain(payload)
        stage8 = result["stage8"]

        self.assertEqual(stage8.record("outreach_plan").get("plan_status"), "BLOCKED")
        self.assertEqual(stage8.inputs.get("governance_decision_state"), "BLOCK")
        self.assertEqual(
            stage8.inputs.get("governance_additions", {}).get("outreach_plan", {}).get("delivery_matrix", {}).get("projection_policies", {}).get("LEADPACK_DELIVERABLE"),
            "BLOCK",
        )

    def test_stage9_delivery_matrix_blocks_direct_leadpack_objects(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["requested_delivery_surface"] = "LEADPACK_DELIVERABLE"

        result = run_internal_chain(payload)
        stage9 = result["stage9"]

        self.assertEqual(stage9.record("order_record").get("order_status"), "ON_HOLD")
        self.assertEqual(stage9.record("delivery_record").get("delivery_status"), "RELEASE_BLOCKED")
        self.assertEqual(stage9.inputs.get("governance_decision_state"), "BLOCK")
        self.assertEqual(
            stage9.inputs.get("governance_additions", {}).get("order_record", {}).get("delivery_matrix", {}).get("projection_policies", {}).get("LEADPACK_DELIVERABLE"),
            "BLOCK",
        )

    def test_stage9_release_gate_is_runtime_consumed(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["release_level"] = "DEV_ALLOWED"

        result = run_internal_chain(payload)
        stage9 = result["stage9"]

        self.assertEqual(stage9.inputs.get("governance_decision_state"), "REVIEW")
        gate_results = stage9.inputs.get("governance_additions", {}).get("order_record", {}).get("release_gates", {}).get("gate_results", [])
        self.assertTrue(any(item.get("gate_id") == "internal_review_release" and item.get("decision_state") == "REVIEW" for item in gate_results))

    def test_stage9_governance_trace_covers_all_runtime_assets(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        governance_trace = stage9.inputs.get("governance_trace", [])
        guarded_objects = {entry.get("object_type") for entry in governance_trace}

        self.assertEqual(
            guarded_objects,
            {
                "order_record",
                "payment_record",
                "delivery_record",
                "opportunity_outcome_event",
                "governance_feedback_event",
            },
        )
        for entry in governance_trace:
            self.assertIn("field_policy", entry)
            self.assertIn("delivery_matrix", entry)
            self.assertIn("release_gates", entry)

    def test_stage9_payment_delivery_refund_live_execution_remains_blocked(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "refund_state": "REQUESTED",
                "real_payment_gateway_enabled": True,
                "real_charge_requested": True,
                "automated_refund_requested": True,
                "real_refund_requested": True,
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]

        for record_name in (
            "order_record",
            "payment_record",
            "delivery_record",
            "opportunity_outcome_event",
            "governance_feedback_event",
        ):
            metadata = stage9.record(record_name).get("governed_metadata", {})
            self.assertEqual(stage9.record(record_name).get("governed_execution_mode"), "INTERNAL_GOVERNED")
            self.assertFalse(metadata.get("live_execution_enabled"))
            self.assertTrue(metadata.get("projection_only"))

        self.assertEqual(stage9.record("payment_record").get("paid_at_optional"), "NOT_PAID")
        self.assertEqual(stage9.record("payment_record").get("refund_state"), "REQUESTED")
        self.assertNotEqual(stage9.record("payment_record").get("refund_state"), "COMPLETED")
        self.assertEqual(stage9.record("delivery_record").get("delivered_at_optional"), "NOT_DELIVERED")
        self.assertNotEqual(stage9.record("delivery_record").get("delivery_status"), "DELIVERED")
        ledger = stage9.inputs["stage9_execution_ledger"]
        provider_summary = stage9.inputs[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]
        self.assertFalse(provider_summary["real_provider_call_enabled"])
        self.assertFalse(provider_summary["automated_refund_program"]["enabled"])
        self.assertEqual(ledger["refund_execution_state"], "MANUAL_EXCEPTION_REVIEW")
        self.assertFalse(ledger["real_payment_gateway_enabled"])
        self.assertFalse(ledger["real_charge_attempted"])
        self.assertFalse(ledger["real_refund_attempted"])
        self.assertFalse(ledger["automated_refund_enabled"])
        self.assertIn("real_payment_gateway_requested_but_blocked", ledger["blocked_reasons"])
        self.assertIn("real_charge_requested_but_blocked", ledger["blocked_reasons"])
        self.assertIn("real_refund_requested_but_blocked", ledger["blocked_reasons"])
        self.assertIn("automated_refund_requested_but_blocked", ledger["blocked_reasons"])
        self.assertFalse(ledger["provider_adapter_readiness"]["real_provider_call_enabled"])

    def test_stage7_crm_and_external_quote_live_requests_remain_blocked(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "crm_runtime_enabled": True,
                "external_quote_enabled": True,
                "external_delivery_enabled": True,
                "live_execution_enabled": True,
            }
        )

        stage7 = run_internal_chain(payload)["stage7"]
        carrier = stage7.inputs["crm_quote_prerequisite_readiness"]
        workbench = stage7.inputs["crm_quote_workbench"]
        provider_summary = stage7.inputs[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]

        self.assertEqual(carrier["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertFalse(provider_summary["real_provider_call_enabled"])
        self.assertFalse(workbench["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertEqual(carrier["crm_prerequisite_state"], "RESERVED_NOT_LIVE")
        self.assertEqual(carrier["quote_prerequisite_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(carrier["crm_runtime_enabled"])
        self.assertFalse(carrier["external_quote_enabled"])
        self.assertFalse(carrier["external_delivery_enabled"])
        self.assertIn("crm_runtime_enabled=false", carrier["blocked_reasons"])
        self.assertIn("external_quote_enabled=false", carrier["blocked_reasons"])
        self.assertIn("external_delivery_enabled=false", carrier["blocked_reasons"])
        self.assertIn("customer_facing_quote_not_generated", carrier["blocked_reasons"])
        self.assertFalse(carrier["operator_readback_summary"]["operator_can_enable_crm_runtime"])
        self.assertFalse(carrier["operator_readback_summary"]["operator_can_generate_external_quote"])
        self.assertFalse(carrier["operator_readback_summary"]["operator_can_deliver_external"])
        self.assertEqual(workbench["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertEqual(workbench["owner_action_state"], "BLOCKED")
        self.assertEqual(workbench["quote_surface_state"], "BLOCKED")
        self.assertFalse(workbench["live_execution_enabled"])
        self.assertFalse(workbench["real_external_quote_sent"])
        self.assertFalse(workbench["real_crm_receipt_generated"])
        self.assertIn("live_crm_request_blocked", workbench["blocked_reasons"])
        self.assertIn("external_quote_request_blocked", workbench["blocked_reasons"])
        self.assertIn("live_execution_requested_but_blocked", workbench["blocked_reasons"])

    def test_leadpack_candidate_external_delivery_requests_remain_readback_only(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "external_delivery_enabled": True,
                "direct_export_enabled": True,
                "live_execution_enabled": True,
            }
        )

        result = run_internal_chain(payload)
        preview = preview_leadpack_external_delivery_candidate(result)
        simulation = simulate_leadpack_external_delivery_export(result)

        for response in (preview, simulation):
            self.assertTrue(response["readiness_only"])
            self.assertTrue(response["review_only"])
            self.assertTrue(response["candidate_only"])
            self.assertFalse(response["external_delivery_enabled"])
            self.assertFalse(response["direct_export_enabled"])
            self.assertFalse(response["external_ready_direct_export"])
            self.assertFalse(response["candidate_readback_summary"]["customer_visible_export_enabled"])
            self.assertFalse(response["operator_readback_summary"]["operator_can_deliver_external"])
            self.assertFalse(response["operator_readback_summary"]["operator_can_direct_export"])
            self.assertIn("external_delivery_enabled=false", response["blocked_reasons"])
            self.assertIn("direct_export_enabled=false", response["why_not_live"])

        self.assertTrue(simulation["export_simulation_requested"])

    def test_formal_client_export_page_layer_live_flags_remain_readiness_only(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "customer_visible_export_enabled": True,
                "client_page_release_enabled": True,
                "external_release_enabled": True,
                "external_delivery_enabled": True,
                "direct_export_enabled": True,
                "export_artifact_generation_enabled": True,
                "page_publication_enabled": True,
                "live_execution_enabled": True,
            }
        )

        result = run_internal_chain(payload)
        readiness = preview_formal_client_export_page_layer_readiness(result)

        self.assertTrue(readiness["internal_only"])
        self.assertTrue(readiness["readiness_only"])
        self.assertTrue(readiness["projection_only"])
        self.assertTrue(readiness["release_blocked"])
        self.assertFalse(readiness["customer_visible_export_enabled"])
        self.assertFalse(readiness["client_page_release_enabled"])
        self.assertFalse(readiness["external_release_enabled"])
        self.assertFalse(readiness["external_delivery_enabled"])
        self.assertFalse(readiness["direct_export_enabled"])
        self.assertFalse(readiness["export_artifact_generation_enabled"])
        self.assertFalse(readiness["page_publication_enabled"])
        for reason in (
            "customer_visible_export_enabled=false",
            "client_page_release_enabled=false",
            "external_release_enabled=false",
            "external_delivery_enabled=false",
            "direct_export_enabled=false",
            "export_artifact_generation_enabled=false",
            "page_publication_enabled=false",
        ):
            self.assertIn(reason, readiness["blocked_reasons"])
            self.assertIn(reason, readiness["why_not_live"])
        operator_summary = readiness["operator_readback_summary"]
        package = readiness["leadpack_delivery_package"]
        self.assertFalse(package["customer_visible_enabled"])
        self.assertFalse(package["external_delivery_enabled"])
        self.assertFalse(package["page_publication_enabled"])
        self.assertFalse(readiness["delivery_readiness_summary"]["delivery_ready"])
        self.assertIn("customer_visible_request_blocked", package["blocked_reasons"])
        self.assertIn("external_delivery_or_direct_export_request_blocked", package["blocked_reasons"])
        self.assertIn("page_publication_request_blocked", package["blocked_reasons"])
        self.assertIn("external_or_live_request_blocked", package["blocked_reasons"])
        self.assertFalse(operator_summary["operator_can_enable_external_release"])
        self.assertFalse(operator_summary["operator_can_enable_customer_visible_export"])
        self.assertFalse(operator_summary["operator_can_generate_export_artifact"])
        self.assertFalse(operator_summary["operator_can_publish_customer_page"])


if __name__ == "__main__":
    unittest.main()
