from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


class ProductOperabilityGapMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = read_yaml("control/product_doc_runtime_coverage_ledger.yaml")
        self.matrix = read_yaml("control/product_operability_gap_matrix.yaml")
        self.task_library = read_yaml("control/product_task_library.yaml")

    def test_matrix_covers_every_product_doc_capability_once(self) -> None:
        ledger_ids = {row["capability_id"] for row in self.ledger["capabilities"]}
        matrix_ids = [row["capability_id"] for row in self.matrix["capability_assessments"]]

        self.assertEqual(len(matrix_ids), len(set(matrix_ids)))
        self.assertEqual(set(matrix_ids), ledger_ids)
        self.assertEqual(self.matrix["source_ledger"], "control/product_doc_runtime_coverage_ledger.yaml")

    def test_rollup_counts_match_assessment_rows(self) -> None:
        counts = Counter(row["operability_state"] for row in self.matrix["capability_assessments"])
        rollup = self.matrix["rollup_counts"]

        for state in self.matrix["operability_state_vocabulary"]:
            self.assertEqual(rollup[state], counts[state], state)
        self.assertEqual(rollup["TOTAL_CAPABILITIES"], len(self.matrix["capability_assessments"]))

    def test_next_packet_refs_are_registered_or_explicit_none(self) -> None:
        task_ids = {row["task_id"] for row in self.task_library["tasks"]}
        suggested_packet_refs = {
            packet_ref
            for row in self.task_library["tasks"]
            for packet_ref in row.get("suggested_packet_refs", [])
        }
        registered_refs = task_ids | suggested_packet_refs
        none_refs = {"NONE_CURRENTLY_REQUIRED", "NONE_PRODUCT_GOAL"}

        for row in self.matrix["capability_assessments"]:
            next_packet_ref = row["next_packet_ref"]
            if next_packet_ref in none_refs:
                continue
            self.assertIn(next_packet_ref, registered_refs, row["capability_id"])

    def test_missing_runtime_rows_are_product_implementation_gaps(self) -> None:
        ledger_by_id = {row["capability_id"]: row for row in self.ledger["capabilities"]}
        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}

        missing_runtime_ids = {
            capability_id
            for capability_id, row in ledger_by_id.items()
            if "MISSING_RUNTIME" in row["classification"]
        }

        self.assertEqual(missing_runtime_ids, {"POSTGRES_REDIS_OBJECT_STORAGE_DOCKER_BACKENDS"})
        for capability_id in missing_runtime_ids:
            row = matrix_by_id[capability_id]
            self.assertEqual(row["operability_state"], "NEEDS_PRODUCT_IMPLEMENTATION")
            self.assertEqual(row["next_packet_ref"], "PTL-I100-110A-platform-backend-operability-foundation")

    def test_external_or_live_readiness_is_not_misclassified_as_operable(self) -> None:
        ledger_by_id = {row["capability_id"]: row for row in self.ledger["capabilities"]}

        for row in self.matrix["capability_assessments"]:
            ledger_row = ledger_by_id[row["capability_id"]]
            if ledger_row["external_or_live_capability"]:
                self.assertNotEqual(row["operability_state"], "OPERABLE_NOW_INTERNAL", row["capability_id"])
                self.assertFalse(row["ready_for_live_execution"], row["capability_id"])

    def test_sales_touch_delivery_and_payment_gaps_have_implementation_packets(self) -> None:
        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}

        expected_packets = {
            "STAGE8_REAL_OUTREACH_EXECUTION": "PTL-I100-110B-stage8-sales-outreach-governed-execution",
            "STAGE7_FULL_CRM_ORCHESTRATION_AND_EXTERNAL_QUOTE": "PTL-I100-110C-stage7-crm-quote-sales-workbench",
            "FORMAL_CLIENT_EXPORT_AND_PAGE_LAYER": "PTL-I100-110D-leadpack-export-page-delivery",
            "STAGE9_LIVE_PAYMENT_DELIVERY_REFUND_EXECUTION": (
                "PTL-I100-111-live-provider-adapters-no-auto-refund"
            ),
        }
        for capability_id, packet_ref in expected_packets.items():
            self.assertEqual(matrix_by_id[capability_id]["operability_state"], "NEEDS_PRODUCT_IMPLEMENTATION")
            self.assertEqual(matrix_by_id[capability_id]["next_packet_ref"], packet_ref)

    def test_stage9_internal_order_payment_delivery_ledger_is_owner_operable(self) -> None:
        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}

        h08_row = matrix_by_id["STAGE9_H08_ORDER_PAYMENT_DELIVERY_TYPED_LIFECYCLE"]
        self.assertEqual(h08_row["operability_state"], "OPERABLE_NOW_INTERNAL")
        self.assertTrue(h08_row["owner_usable_now"])
        self.assertEqual(h08_row["next_packet_ref"], "NONE_CURRENTLY_REQUIRED")
        self.assertFalse(h08_row["ready_for_live_execution"])

        live_row = matrix_by_id["STAGE9_LIVE_PAYMENT_DELIVERY_REFUND_EXECUTION"]
        self.assertEqual(live_row["operability_state"], "NEEDS_PRODUCT_IMPLEMENTATION")
        self.assertFalse(live_row["owner_usable_now"])
        self.assertFalse(live_row["ready_for_live_execution"])
        self.assertEqual(live_row["refund_boundary"], "do_not_implement_automated_refund_program")

    def test_business_model_separates_internal_software_from_sold_evidence_pack(self) -> None:
        product_model = self.matrix["product_model"]
        self.assertEqual(product_model["sold_product"], "evidence_pack_and_leadpack")
        self.assertEqual(product_model["not_sold_product"], "external_software_platform")
        self.assertIn("sales_outreach_execution", product_model["required_business_capabilities"])
        self.assertIn("leadpack_export_and_delivery", product_model["required_business_capabilities"])

        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}
        self.assertEqual(
            matrix_by_id["EXTERNAL_SOFTWARE_RELEASE"]["operability_state"],
            "NOT_REQUIRED_FOR_EVIDENCE_PACK_BUSINESS",
        )

    def test_refund_policy_remains_manual_exception_only(self) -> None:
        refund_policy = self.matrix["product_model"]["refund_policy"]
        self.assertFalse(refund_policy["automated_refund_program"])
        self.assertEqual(refund_policy["allowed_refund_handling"], "manual_exception_record_and_governed_review_only")

        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}
        self.assertEqual(
            matrix_by_id["STAGE9_LIVE_PAYMENT_DELIVERY_REFUND_EXECUTION"]["refund_boundary"],
            "do_not_implement_automated_refund_program",
        )

    def test_next_sequence_starts_with_backend_then_sales_execution(self) -> None:
        sequence = self.matrix["next_implementation_sequence"]
        self.assertEqual(sequence[0]["packet_ref"], "PTL-I100-110A-platform-backend-operability-foundation")
        self.assertEqual(sequence[1]["packet_ref"], "PTL-I100-110B-stage8-sales-outreach-governed-execution")
        self.assertEqual(sequence[-1]["packet_ref"], "PTL-I100-110E-order-payment-delivery-no-auto-refund")


if __name__ == "__main__":
    unittest.main()
