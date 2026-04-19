from __future__ import annotations

import copy
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

from helpers import load_fixture
from shared.contract_loader import load_contract
from shared.pipeline import run_internal_chain
from stage9_delivery.impact_executor import ImpactExecutor


class TestStage9ImpactExecutor(unittest.TestCase):
    def _run_stage9(self, overrides: dict[str, object]) -> object:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(overrides)
        return run_internal_chain(payload)["stage9"]

    def test_m6_contact_failed_projects_only_formal_targets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"response_status": "WRONG_ROLE"})

        stage9 = run_internal_chain(payload)["stage9"]
        impact = stage9.inputs["impact_mutations"]
        contract_only = stage9.inputs["impact_projected_contracts"]

        self.assertEqual(stage9.inputs["impact_executor_state"], "INTERNAL_V0_ACTIVE")
        self.assertEqual(set(stage9.inputs["impact_formal_targets"]), {"project_fact", "saleable_opportunity", "contact_target", "review_queue_profile"})
        self.assertEqual(set(stage9.inputs["impact_targets_projected"]), {"contact_target", "saleable_opportunity"})
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})
        self.assertEqual(impact["contact_target"]["field_patches"]["contact_target_status"], "INVALID")
        self.assertTrue(impact["contact_target"]["field_patches"]["contact_conflict_flag"])
        self.assertEqual(impact["saleable_opportunity"]["field_patches"]["saleability_status"], "RESTRICTED")
        self.assertEqual(contract_only["sales_lead"]["field_patches"]["lead_status"], "REVIEW")
        self.assertEqual(contract_only["report_record"]["field_patches"]["report_status"], "REVIEW_REQUIRED")

    def test_m6_window_missed_reprioritizes_review_queue(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "CONNECTED",
                "outcome_family": "WINDOW_MISSED",
                "outcome_reason_tags": ["WINDOW_EXPIRED"],
                "window_missed_state": "MISSED",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        impact = stage9.inputs["impact_mutations"]

        self.assertIn("project_fact", impact)
        self.assertIn("review_queue_profile", impact)
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})
        self.assertEqual(stage9.inputs["impact_targets_advisory"], ["buyer_fit"])
        self.assertEqual(impact["review_queue_profile"]["field_patches"]["review_queue_bucket"], "CRITICAL_WINDOW")
        self.assertEqual(impact["review_queue_profile"]["field_patches"]["window_risk_level"], "CRITICAL")
        self.assertEqual(impact["project_fact"]["field_patches"]["sale_gate_status"], "HOLD")
        self.assertEqual(
            stage9.inputs["impact_projected_contracts"]["sales_lead"]["field_patches"]["lead_status"],
            "REVIEW",
        )
        self.assertEqual(
            stage9.inputs["impact_advisories"]["buyer_fit"]["field_patches"]["fit_refresh_reason"],
            "WINDOW_MISSED",
        )

    def test_m6_governance_targets_remain_additive(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"response_status": "NO_RESPONSE", "crm_owner_state": "UNASSIGNED"})

        stage9 = run_internal_chain(payload)["stage9"]
        projected = stage9.inputs["impact_targets_projected"]
        impact = stage9.inputs["impact_mutations"]

        self.assertEqual(set(projected), {"contact_target", "saleable_opportunity"})
        self.assertEqual(impact["contact_target"]["field_patches"]["contact_target_status"], "REVIEW_REQUIRED")
        self.assertEqual(impact["saleable_opportunity"]["field_patches"]["saleability_status"], "RESTRICTED")
        self.assertIn("IMPACT-CONTACT-FAILED-OPPORTUNITY-001", impact["saleable_opportunity"]["applied_rule_ids"])
        self.assertIn("IMPACT-APPROVAL-MISSING-OPPORTUNITY-001", impact["saleable_opportunity"]["applied_rule_ids"])
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})

    def test_writeback_contract_formalizes_target_semantics(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "refund_state": "COMPLETED",
                "outcome_family": "DELIVERY_ABANDONED",
                "outcome_reason_tags": ["REFUND_COMPLETED"],
                "trigger_type": "EXCEPTION_TRIGGERED",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        contracts = stage9.inputs["writeback_target_contracts"]
        semantics = stage9.inputs["writeback_contract_semantics"]

        self.assertEqual(stage9.inputs["writeback_contract_state"], "FORMAL_CONTRACT_ACTIVE")
        self.assertTrue(semantics["outcome_targets_authoritative"])
        self.assertTrue(semantics["governance_targets_additive_only"])
        self.assertTrue(semantics["payment_exception_targets_additive_only"])
        self.assertTrue(semantics["delivery_exception_targets_additive_only"])
        self.assertTrue(semantics["silent_override_outcome_targets_forbidden"])
        self.assertEqual(
            stage9.inputs["writeback_persistence_targets"],
            [
                "delivery_record",
                "opportunity_outcome_event",
                "governance_feedback_event",
                "payment_record",
            ],
        )
        self.assertEqual(
            stage9.inputs["writeback_projected_targets"],
            ["project_fact", "sales_lead", "report_record", "saleable_opportunity"],
        )
        self.assertEqual(
            stage9.inputs["resolved_effective_writeback_targets"],
            [
                "delivery_record",
                "project_fact",
                "opportunity_outcome_event",
                "sales_lead",
                "report_record",
                "controlled_exception_record",
                "release_gates",
                "governance_feedback_event",
                "saleable_opportunity",
                "payment_record",
            ],
        )
        self.assertEqual(
            stage9.inputs["writeback_advisory_targets"],
            [],
        )
        self.assertEqual(
            stage9.inputs["writeback_trace_only_targets"],
            ["controlled_exception_record", "release_gates"],
        )
        self.assertEqual(
            contracts["delivery_record"]["mutation_semantics"],
            "PERSISTED_STAGE9_RECORD",
        )
        self.assertEqual(
            contracts["project_fact"]["mutation_semantics"],
            "PROJECTED_MUTATION_ONLY",
        )
        self.assertEqual(
            contracts["controlled_exception_record"]["mutation_semantics"],
            "TRACE_ONLY_CONTRACT",
        )
        self.assertEqual(
            contracts["sales_lead"]["mutation_semantics"],
            "PROJECTED_MUTATION_ONLY",
        )
        self.assertEqual(
            contracts["report_record"]["persistence_semantics"],
            "NOT_PERSISTED_IN_STAGE9_RUNTIME",
        )
        self.assertEqual(
            contracts["governance_feedback_event"]["resolved_from_sources"],
            ["governance_taxonomy"],
        )
        self.assertEqual(
            contracts["opportunity_outcome_event"]["resolved_from_sources"],
            ["outcome_taxonomy"],
        )

    def test_writeback_source_contracts_and_target_sources_are_exposed(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "refund_state": "COMPLETED",
                "outcome_family": "DELIVERY_ABANDONED",
                "outcome_reason_tags": ["REFUND_COMPLETED"],
                "trigger_type": "EXCEPTION_TRIGGERED",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        source_contracts = stage9.inputs["writeback_source_contracts"]
        target_sources = stage9.inputs["writeback_target_sources"]
        contracts = stage9.inputs["writeback_target_contracts"]

        self.assertEqual(
            source_contracts["outcome_taxonomy"]["merge_semantics"],
            "AUTHORITATIVE_BASE",
        )
        self.assertEqual(
            source_contracts["governance_taxonomy"]["merge_semantics"],
            "ADDITIVE_ONLY",
        )
        self.assertEqual(
            source_contracts["payment_exception"]["persisted_stage9_record_target"],
            "payment_record",
        )
        self.assertEqual(
            source_contracts["delivery_exception"]["persisted_stage9_record_target"],
            "delivery_record",
        )
        self.assertEqual(
            source_contracts["upstream_feedback_loop"]["merge_semantics"],
            "PROJECTED_FEEDBACK_ONLY",
        )
        self.assertEqual(
            source_contracts["upstream_feedback_loop"]["target_semantics"],
            "PROJECTED_CONTRACT_ONLY + TRACE_ONLY_ADVISORY",
        )
        self.assertEqual(
            target_sources["project_fact"],
            ["outcome_taxonomy", "payment_exception"],
        )
        self.assertEqual(
            target_sources["sales_lead"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            target_sources["report_record"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            target_sources["delivery_record"],
            ["outcome_taxonomy", "delivery_exception"],
        )
        self.assertEqual(
            contracts["delivery_record"]["resolved_from_sources"],
            ["outcome_taxonomy", "delivery_exception"],
        )
        self.assertEqual(
            contracts["saleable_opportunity"]["resolved_from_sources"],
            ["payment_exception"],
        )
        self.assertEqual(
            target_sources["governance_feedback_event"],
            ["governance_taxonomy"],
        )
        self.assertEqual(
            target_sources["opportunity_outcome_event"],
            ["outcome_taxonomy"],
        )
        self.assertEqual(
            target_sources["payment_record"],
            ["payment_exception"],
        )
        self.assertEqual(
            source_contracts["outcome_taxonomy"]["authoritative_feedback_contract_ref"],
            "contracts/sales/opportunity_policy_catalog.json#policies.opportunity_outcome_writeback_v1",
        )

    def test_false_positive_forms_projected_and_advisory_feedback_targets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "outcome_family": "FALSE_POSITIVE",
                "outcome_reason_tags": ["FACT_CONFLICT"],
                "is_false_positive": True,
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        self.assertEqual(
            stage9.inputs["upstream_feedback_projected_targets"],
            ["sales_lead", "report_record"],
        )
        self.assertEqual(
            set(stage9.inputs["upstream_feedback_advisory_targets"]),
            {"buyer_fit", "challenger_candidate_profile"},
        )
        self.assertEqual(set(stage9.inputs["impact_targets_projected_contract_only"]), {"sales_lead", "report_record"})
        self.assertEqual(set(stage9.inputs["impact_targets_advisory"]), {"buyer_fit", "challenger_candidate_profile"})
        self.assertEqual(
            stage9.inputs["impact_projected_contracts"]["sales_lead"]["field_patches"]["lead_status"],
            "DISQUALIFIED",
        )
        self.assertEqual(
            stage9.inputs["impact_advisories"]["challenger_candidate_profile"]["field_patches"]["profile_refresh_reason"],
            "FALSE_POSITIVE",
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["challenger_candidate_profile"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            stage9.inputs["outcome_writeback_targets"],
            ["project_fact"],
        )

    def test_false_positive_advisory_targets_stay_out_of_effective_sets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "outcome_family": "FALSE_POSITIVE",
                "outcome_reason_tags": ["FACT_CONFLICT"],
                "is_false_positive": True,
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(stage9.inputs["writeback_trace_only_targets"], ["buyer_fit", "challenger_candidate_profile"])
        self.assertNotIn("buyer_fit", stage9.inputs["effective_writeback_targets"])
        self.assertNotIn("challenger_candidate_profile", stage9.inputs["effective_writeback_targets"])
        self.assertIn("buyer_fit", stage9.inputs["resolved_effective_writeback_targets"])
        self.assertIn("challenger_candidate_profile", stage9.inputs["resolved_effective_writeback_targets"])
        self.assertEqual(stage9.inputs["writeback_target_sources"]["buyer_fit"], ["upstream_feedback_loop"])
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["challenger_candidate_profile"],
            ["upstream_feedback_loop"],
        )

    def test_partial_payment_keeps_precise_exception_family_and_additive_targets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"payment_status": "PARTIALLY_PAID"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "PARTIAL_PAYMENT",
        )
        self.assertEqual(stage9.record("opportunity_outcome_event").get("outcome_family"), "LOST")
        self.assertEqual(
            stage9.record("opportunity_outcome_event").get("outcome_reason_tags"),
            ["PAYMENT_FAILED"],
        )
        self.assertEqual(
            stage9.inputs["payment_exception_writeback_targets_optional"],
            ["saleable_opportunity", "project_fact"],
        )
        self.assertEqual(
            stage9.inputs["governance_writeback_targets_optional"],
            ["delivery_record", "release_gates"],
        )
        self.assertEqual(
            stage9.inputs["effective_writeback_targets"],
            [
                "project_fact",
                "saleable_opportunity",
                "delivery_record",
                "release_gates",
            ],
        )
        self.assertNotIn("buyer_fit", stage9.inputs["effective_writeback_targets"])
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["project_fact"],
            ["outcome_taxonomy", "payment_exception"],
        )

    def test_refund_requested_keeps_precise_family_and_coarse_signed_reason(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"refund_state": "REQUESTED"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "REFUND_REQUESTED",
        )
        self.assertEqual(
            stage9.record("opportunity_outcome_event").get("outcome_family"),
            "DELIVERY_ABANDONED",
        )
        self.assertEqual(
            stage9.record("opportunity_outcome_event").get("outcome_reason_tags"),
            ["SIGNED"],
        )
        self.assertEqual(
            stage9.inputs["payment_exception_writeback_targets_optional"],
            ["delivery_record", "saleable_opportunity"],
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["sales_lead"],
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["governance_feedback_event"],
            ["governance_taxonomy"],
        )

    def test_payer_mismatch_keeps_outcome_and_governance_semantics_separate(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"payer_mismatch_state": "CONFIRMED"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.inputs["outcome_writeback_targets"],
            ["order_record", "payment_record"],
        )
        self.assertEqual(
            stage9.inputs["governance_writeback_targets_optional"],
            ["delivery_record", "release_gates"],
        )
        self.assertEqual(
            stage9.inputs["payment_exception_writeback_targets_optional"],
            ["order_record", "delivery_record"],
        )
        self.assertEqual(
            stage9.inputs["writeback_target_sources"]["payment_record"],
            ["outcome_taxonomy", "payment_exception"],
        )
        self.assertEqual(
            set(stage9.inputs["impact_targets_projected_contract_only"]),
            {"sales_lead", "report_record"},
        )

    def test_policy_executor_exposes_canonical_source_contract_outputs(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "refund_state": "REQUESTED",
                "outcome_family": "DELIVERY_ABANDONED",
                "outcome_reason_tags": ["SIGNED"],
                "trigger_type": "EXCEPTION_TRIGGERED",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        trace = {
            entry["policy_key"]: entry["outputs"]
            for entry in stage9.inputs["policy_trace"]
            if "outputs" in entry
        }
        outcome_outputs = trace["outcome_taxonomy"]
        governance_outputs = trace["governance_taxonomy"]

        self.assertEqual(
            outcome_outputs["writeback_targets"],
            ["delivery_record", "project_fact", "governance_feedback_event"],
        )
        self.assertEqual(
            outcome_outputs["authoritative_base_targets"],
            ["delivery_record", "project_fact"],
        )
        self.assertEqual(
            outcome_outputs["projected_feedback_only_targets"],
            ["sales_lead", "report_record"],
        )
        self.assertEqual(governance_outputs["governance_owned_self_target"], "governance_feedback_event")
        self.assertEqual(
            governance_outputs["additive_writeback_targets"],
            ["controlled_exception_record", "release_gates"],
        )

    def test_payment_exception_family_matrix_is_contract_driven(self) -> None:
        cases = [
            (
                "PARTIAL_PAYMENT",
                {"payment_exception_family_optional": "PARTIAL_PAYMENT"},
                {
                    "outcome_family": "LOST",
                    "outcome_reason_tags": ["PAYMENT_FAILED"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "payment_status": "PARTIALLY_PAID",
                    "writeback_targets": ["saleable_opportunity", "project_fact"],
                },
            ),
            (
                "PAYMENT_FAILURE",
                {"payment_exception_family_optional": "PAYMENT_FAILURE"},
                {
                    "outcome_family": "LOST",
                    "outcome_reason_tags": ["PAYMENT_FAILED"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "payment_status": "PAYMENT_EXCEPTION",
                    "delivery_status": "RELEASE_BLOCKED",
                    "writeback_targets": ["order_record", "saleable_opportunity"],
                },
            ),
            (
                "AMOUNT_MISMATCH",
                {"payment_exception_family_optional": "AMOUNT_MISMATCH"},
                {
                    "outcome_family": "LOST",
                    "outcome_reason_tags": ["AMOUNT_MISMATCH"],
                    "trigger_type": "APPROVAL_MISSING",
                    "payment_status": "PAYMENT_EXCEPTION",
                    "delivery_status": "RELEASE_BLOCKED",
                    "writeback_targets": ["order_record", "saleable_opportunity"],
                    "amount_match_state": "MISMATCHED",
                    "amount_mismatch_state_optional": "CONFIRMED",
                },
            ),
            (
                "PAYER_MISMATCH",
                {"payment_exception_family_optional": "PAYER_MISMATCH"},
                {
                    "outcome_family": "PAYER_MISMATCH",
                    "outcome_reason_tags": ["PAYER_CONFIRMED_MISMATCH"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "payment_status": "PAYMENT_EXCEPTION",
                    "delivery_status": "RELEASE_BLOCKED",
                    "writeback_targets": ["order_record", "delivery_record"],
                    "payer_match_state": "MISMATCHED",
                },
            ),
            (
                "REFUND_REQUESTED",
                {"payment_exception_family_optional": "REFUND_REQUESTED"},
                {
                    "outcome_family": "DELIVERY_ABANDONED",
                    "outcome_reason_tags": ["SIGNED"],
                    "trigger_type": "EXCEPTION_TRIGGERED",
                    "payment_status": "REFUND_PENDING",
                    "refund_state": "REQUESTED",
                    "writeback_targets": ["delivery_record", "saleable_opportunity"],
                },
            ),
            (
                "REFUND_APPROVED",
                {"payment_exception_family_optional": "REFUND_APPROVED"},
                {
                    "outcome_family": "DELIVERY_ABANDONED",
                    "outcome_reason_tags": ["SIGNED"],
                    "trigger_type": "EXCEPTION_TRIGGERED",
                    "payment_status": "REFUND_PENDING",
                    "refund_state": "APPROVED",
                    "writeback_targets": ["delivery_record", "saleable_opportunity"],
                },
            ),
            (
                "REFUND_COMPLETED",
                {"payment_exception_family_optional": "REFUND_COMPLETED"},
                {
                    "outcome_family": "DELIVERY_ABANDONED",
                    "outcome_reason_tags": ["REFUND_COMPLETED"],
                    "trigger_type": "EXCEPTION_TRIGGERED",
                    "payment_status": "REFUNDED",
                    "refund_state": "COMPLETED",
                    "delivery_status": "RELEASE_BLOCKED",
                    "archival_status": "ARCHIVE_EXCEPTION",
                    "writeback_targets": ["saleable_opportunity", "project_fact"],
                },
            ),
        ]

        for family, overrides, expected in cases:
            with self.subTest(exception_family=family):
                stage9 = self._run_stage9(overrides)
                payment_record = stage9.record("payment_record")
                delivery_record = stage9.record("delivery_record")
                governance_feedback_event = stage9.record("governance_feedback_event")
                opportunity_outcome_event = stage9.record("opportunity_outcome_event")

                self.assertEqual(payment_record.get("payment_exception_family_optional"), family)
                self.assertEqual(
                    stage9.inputs["payment_exception_writeback_targets_optional"],
                    expected["writeback_targets"],
                )
                self.assertEqual(
                    opportunity_outcome_event.get("outcome_family"),
                    expected["outcome_family"],
                )
                self.assertEqual(
                    opportunity_outcome_event.get("outcome_reason_tags"),
                    expected["outcome_reason_tags"],
                )
                self.assertEqual(
                    governance_feedback_event.get("trigger_type"),
                    expected["trigger_type"],
                )
                self.assertEqual(payment_record.get("payment_status"), expected["payment_status"])
                if "refund_state" in expected:
                    self.assertEqual(payment_record.get("refund_state"), expected["refund_state"])
                    self.assertEqual(
                        payment_record.get("refund_amount_band_optional"),
                        payment_record.get("amount_band"),
                    )
                if "amount_match_state" in expected:
                    self.assertEqual(
                        payment_record.get("amount_match_state"),
                        expected["amount_match_state"],
                    )
                    self.assertEqual(
                        payment_record.get("amount_mismatch_state_optional"),
                        expected["amount_mismatch_state_optional"],
                    )
                if "payer_match_state" in expected:
                    self.assertEqual(
                        payment_record.get("payer_match_state"),
                        expected["payer_match_state"],
                    )
                if "delivery_status" in expected:
                    self.assertEqual(
                        delivery_record.get("delivery_status"),
                        expected["delivery_status"],
                    )
                if "archival_status" in expected:
                    self.assertEqual(
                        delivery_record.get("archival_status"),
                        expected["archival_status"],
                    )
                self.assertIn("POLICY:emit_decision:payment_exception", stage9.trace_rules)

    def test_delivery_exception_family_matrix_is_contract_driven(self) -> None:
        cases = [
            (
                "DELIVERY_REJECTED",
                {"delivery_exception_family_optional": "DELIVERY_REJECTED"},
                {
                    "outcome_reason_tags": ["DELIVERY_REJECTED"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "writeback_targets": ["saleable_opportunity", "project_fact"],
                    "delivery_status": "RELEASE_BLOCKED",
                    "customer_ack_state_optional": "REJECTED",
                },
            ),
            (
                "PARTIAL_DELIVERY",
                {"delivery_exception_family_optional": "PARTIAL_DELIVERY"},
                {
                    "outcome_reason_tags": ["PARTIAL_DELIVERY"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "writeback_targets": ["saleable_opportunity"],
                    "customer_ack_state_optional": "PENDING",
                    "partial_delivery_state_optional": "PARTIAL",
                },
            ),
            (
                "REDELIVERY_REQUIRED",
                {"delivery_exception_family_optional": "REDELIVERY_REQUIRED"},
                {
                    "outcome_reason_tags": ["REDELIVERY_FAILED"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "writeback_targets": ["delivery_record"],
                    "delivery_status": "REDELIVERY_REQUIRED",
                    "customer_ack_state_optional": "PENDING",
                    "redeliver_required_optional": True,
                },
            ),
            (
                "REWORK_REQUIRED",
                {"delivery_exception_family_optional": "REWORK_REQUIRED"},
                {
                    "outcome_reason_tags": ["DELIVERY_REJECTED"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "writeback_targets": ["delivery_record", "project_fact"],
                    "delivery_status": "REWORK_REQUIRED",
                    "customer_ack_state_optional": "REJECTED",
                    "resend_required_optional": True,
                },
            ),
            (
                "ACK_TIMEOUT",
                {"delivery_exception_family_optional": "ACK_TIMEOUT"},
                {
                    "outcome_reason_tags": ["ACK_TIMEOUT"],
                    "trigger_type": "DELIVERY_BLOCK",
                    "writeback_targets": ["delivery_record"],
                    "delivery_status": "ACK_PENDING",
                    "customer_ack_state_optional": "TIMEOUT",
                },
            ),
            (
                "ARCHIVE_FAILURE",
                {"delivery_exception_family_optional": "ARCHIVE_FAILURE"},
                {
                    "outcome_reason_tags": ["ARCHIVE_FAILURE"],
                    "trigger_type": "ARCHIVE_FAILURE",
                    "writeback_targets": ["delivery_record"],
                    "delivery_status": "RELEASE_BLOCKED",
                    "archival_status": "ARCHIVE_EXCEPTION",
                },
            ),
            (
                "RETRIEVAL_FAILED",
                {"delivery_exception_family_optional": "RETRIEVAL_FAILED"},
                {
                    "outcome_reason_tags": ["ARCHIVE_FAILURE"],
                    "trigger_type": "ARCHIVE_FAILURE",
                    "writeback_targets": ["delivery_record"],
                    "delivery_status": "RELEASE_BLOCKED",
                    "retrieval_status": "FAILED",
                },
            ),
        ]

        for family, overrides, expected in cases:
            with self.subTest(exception_family=family):
                stage9 = self._run_stage9(overrides)
                delivery_record = stage9.record("delivery_record")
                governance_feedback_event = stage9.record("governance_feedback_event")
                opportunity_outcome_event = stage9.record("opportunity_outcome_event")

                self.assertEqual(
                    delivery_record.get("delivery_exception_family_optional"),
                    family,
                )
                self.assertEqual(
                    stage9.inputs["delivery_exception_writeback_targets_optional"],
                    expected["writeback_targets"],
                )
                self.assertEqual(
                    opportunity_outcome_event.get("outcome_family"),
                    "DELIVERY_ABANDONED",
                )
                self.assertEqual(
                    opportunity_outcome_event.get("outcome_reason_tags"),
                    expected["outcome_reason_tags"],
                )
                self.assertEqual(
                    governance_feedback_event.get("trigger_type"),
                    expected["trigger_type"],
                )
                if "customer_ack_state_optional" in expected:
                    self.assertEqual(
                        delivery_record.get("customer_ack_state_optional"),
                        expected["customer_ack_state_optional"],
                    )
                if "delivery_status" in expected:
                    self.assertEqual(
                        delivery_record.get("delivery_status"),
                        expected["delivery_status"],
                    )
                if "partial_delivery_state_optional" in expected:
                    self.assertEqual(
                        delivery_record.get("partial_delivery_state_optional"),
                        expected["partial_delivery_state_optional"],
                    )
                if "redeliver_required_optional" in expected:
                    self.assertEqual(
                        delivery_record.get("redeliver_required_optional"),
                        expected["redeliver_required_optional"],
                    )
                if "resend_required_optional" in expected:
                    self.assertEqual(
                        delivery_record.get("resend_required_optional"),
                        expected["resend_required_optional"],
                    )
                if "archival_status" in expected:
                    self.assertEqual(
                        delivery_record.get("archival_status"),
                        expected["archival_status"],
                    )
                if "retrieval_status" in expected:
                    self.assertEqual(
                        delivery_record.get("retrieval_status"),
                        expected["retrieval_status"],
                    )
                self.assertIn("POLICY:emit_decision:delivery_exception", stage9.trace_rules)

    def test_writeback_contract_rejects_disallowed_additive_source(self) -> None:
        executor = ImpactExecutor()

        with self.assertRaisesRegex(
            ValueError,
            "does not allow additive source governance_taxonomy",
        ):
            executor.resolve_effective_targets(
                outcome_targets=["contact_target"],
                upstream_feedback_targets=[],
                governance_targets=["saleable_opportunity"],
                payment_exception_targets=[],
                delivery_exception_targets=[],
            )

    def test_runtime_facing_contract_fields_remain_authoritative(self) -> None:
        impact_policy = load_contract("contracts/governance/writeback_impact_policy.json")
        opportunity_catalog = load_contract("contracts/sales/opportunity_policy_catalog.json")
        outcome_policy = next(
            policy
            for policy in opportunity_catalog["policies"]
            if policy["policyId"] == "opportunity_outcome_writeback_v1"
        )

        self.assertEqual(impact_policy["current_state"], "INTERNAL_V0_ACTIVE")
        self.assertEqual(
            impact_policy["target_source_resolution_order"],
            [
                "outcome_taxonomy",
                "upstream_feedback_loop",
                "governance_taxonomy",
                "payment_exception",
                "delivery_exception",
            ],
        )
        self.assertEqual(
            set(impact_policy["target_semantic_groups"]["projected_only_targets"]),
            {
                "project_fact",
                "saleable_opportunity",
                "contact_target",
                "review_queue_profile",
                "sales_lead",
                "report_record",
            },
        )
        self.assertEqual(
            set(impact_policy["target_semantic_groups"]["persisted_targets"]),
            {
                "order_record",
                "payment_record",
                "delivery_record",
                "opportunity_outcome_event",
                "governance_feedback_event",
            },
        )
        self.assertEqual(
            set(impact_policy["target_semantic_groups"]["advisory_targets"]),
            {"buyer_fit", "challenger_candidate_profile", "outreach_plan"},
        )
        self.assertEqual(
            impact_policy["source_ownership_layers"]["upstream_feedback_loop"][
                "projected_target_field"
            ],
            "mustWriteBackTo",
        )
        self.assertEqual(
            outcome_policy["runtimeVisibilityFields"],
            [
                "upstream_feedback_projected_targets",
                "upstream_feedback_advisory_targets",
                "writeback_target_contracts",
            ],
        )
        self.assertEqual(
            outcome_policy["writebackRoleFields"]["resolvedRuntimeFields"],
            [
                "upstream_feedback_projected_targets",
                "upstream_feedback_advisory_targets",
                "resolved_effective_writeback_targets",
            ],
        )
        self.assertEqual(
            outcome_policy["upstreamFeedbackLoopContracts"]["false_positive"][
                "advisoryTargets"
            ]["challenger_candidate_profile"]["fieldPatches"][
                "profile_refresh_reason"
            ],
            "FALSE_POSITIVE",
        )

    def test_target_semantic_groups_drive_runtime_contract_buckets(self) -> None:
        executor = ImpactExecutor()
        summary = executor.describe_targets(
            [
                "project_fact",
                "order_record",
                "buyer_fit",
                "controlled_exception_record",
            ],
            target_sources={
                "project_fact": ["outcome_taxonomy"],
                "order_record": ["payment_exception"],
                "buyer_fit": ["upstream_feedback_loop"],
                "controlled_exception_record": ["governance_taxonomy"],
            },
        )

        self.assertEqual(summary["writeback_projected_targets"], ["project_fact"])
        self.assertEqual(summary["writeback_persistence_targets"], ["order_record"])
        self.assertEqual(summary["writeback_advisory_targets"], ["buyer_fit"])
        self.assertEqual(
            summary["writeback_trace_only_targets"],
            ["buyer_fit", "controlled_exception_record"],
        )

    def test_target_source_resolution_order_follows_policy(self) -> None:
        executor = ImpactExecutor()
        executor.policy = copy.deepcopy(executor.policy)
        executor.policy["target_source_resolution_order"] = [
            "outcome_taxonomy",
            "upstream_feedback_loop",
            "governance_taxonomy",
            "delivery_exception",
            "payment_exception",
        ]

        resolution = executor.resolve_effective_targets(
            outcome_targets=[],
            upstream_feedback_targets=[],
            governance_targets=[],
            payment_exception_targets=["saleable_opportunity"],
            delivery_exception_targets=["saleable_opportunity"],
        )

        self.assertEqual(
            resolution["writeback_target_sources"]["saleable_opportunity"],
            ["delivery_exception", "payment_exception"],
        )
        self.assertEqual(
            resolution["legacy_effective_writeback_targets"],
            ["saleable_opportunity"],
        )


if __name__ == "__main__":
    unittest.main()
