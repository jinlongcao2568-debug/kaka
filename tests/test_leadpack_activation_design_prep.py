from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class TestLeadpackActivationDesignPrep(unittest.TestCase):
    def test_activation_design_prep_matrix_formalizes_pre_implementation_gates(self) -> None:
        matrix = read_json("contracts/release/leadpack_activation_design_implementation_prep_matrix.json")
        signoff = read_json("contracts/release/leadpack_activation_prep_signoff_packet.json")
        readiness_packet = read_json("contracts/release/leadpack_implementation_decision_readiness_packet.json")
        transition = read_json("contracts/release/leadpack_activation_prep_transition_matrix.json")
        release_gates = read_json("contracts/release/release_gates.json")

        self.assertEqual(matrix["candidate_domain_id"], "leadpack_external_delivery")
        self.assertTrue(matrix["scope"]["design_prep_only"])
        self.assertFalse(matrix["scope"]["actual_activation_enabled"])
        self.assertFalse(matrix["scope"]["external_delivery_enabled"])
        self.assertFalse(matrix["scope"]["implementation_approved"])

        self.assertIn("GO", matrix["state_layering"]["activation_go_no_go_decision_states"])
        self.assertIn(
            "ACTIVATION_DESIGN_PREP_READY_FOR_REVIEW",
            matrix["state_layering"]["activation_design_prep_states"],
        )
        self.assertIn(
            "IMPLEMENTATION_DECISION_READY_FOR_REVIEW",
            matrix["state_layering"]["implementation_decision_states"],
        )
        self.assertTrue(matrix["state_layering"]["canonical_repo_readiness_must_not_change"])

        required_roles = {entry["owner_role"] for entry in matrix["owner_signoff_execution"]["required_owner_signoffs"]}
        self.assertEqual(required_roles, {"release_approver", "governance_owner", "testing_owner"})
        self.assertIn("APPROVED", matrix["owner_signoff_execution"]["owner_status_vocabulary"])
        self.assertEqual(
            matrix["owner_signoff_execution"]["decision_mapping"]["any_mandatory_owner_denied"],
            "IMPLEMENTATION_DECISION_DENIED",
        )
        self.assertEqual(signoff["execution_policy_ref"], "contracts/release/leadpack_activation_design_implementation_prep_matrix.json#owner_signoff_execution")

        candidate_matrix = read_json("contracts/release/leadpack_external_delivery_candidate_matrix.json")
        self.assertNotIn("leadpack_candidate_review_gate", candidate_matrix["required_approvals"])
        self.assertIn("leadpack_candidate_review_gate", candidate_matrix["required_review_gates"])

        self.assertIn("internal_review_release", matrix["approval_audit_prerequisites"]["required_approval_chains_before_implementation_decision"])
        self.assertNotIn("leadpack_candidate_review_gate", matrix["approval_audit_prerequisites"]["required_approval_chains_before_implementation_decision"])
        self.assertIn("leadpack_candidate_review_gate", matrix["approval_audit_prerequisites"]["required_review_gates_before_implementation_decision"])
        self.assertIn("activation_design_decision_audit_ref", matrix["approval_audit_prerequisites"]["required_audit_refs_before_implementation_decision"])
        self.assertIn("layering_rule", matrix["approval_audit_prerequisites"])
        self.assertIn("actual_owner_signoff_states", matrix["owner_signoff_execution"])
        self.assertTrue(matrix["owner_signoff_execution"]["actual_state_required"])
        self.assertEqual(
            {entry["current_status"] for entry in matrix["owner_signoff_execution"]["actual_owner_signoff_states"]},
            {"REQUESTED"},
        )
        self.assertIn("actual_owner_signoff_states", signoff)

        control_ids = {entry["control_id"] for entry in matrix["rollback_cancel_emergency_off"]["controls"]}
        self.assertEqual(
            control_ids,
            {
                "CANCEL_ACTIVATION_DESIGN_PREP",
                "ROLLBACK_ACTIVATION_DESIGN_PREP",
                "EMERGENCY_OFF_ACTIVATION_PREP",
            },
        )

        gate = matrix["implementation_prep_readiness_gate"]
        self.assertEqual(gate["gate_id"], "leadpack_activation_implementation_prep_readiness_gate")
        self.assertTrue(gate["manual_review_required"])
        self.assertIn("REL-184", gate["required_release_checks"])
        self.assertIn("REG-LEADPACK-ACTIVATION-DESIGN-PREP", gate["required_regression_suites"])
        self.assertIn("leadpack_candidate_review_gate", gate["required_review_gates"])
        self.assertNotIn("leadpack_candidate_review_gate", gate["required_approval_chains"])
        hold_source_types = {entry["source_type"] for entry in gate["formal_hold_sources"]}
        self.assertEqual(hold_source_types, {"owner_signoff", "approval_chain", "review_gate", "audit_ref"})
        self.assertEqual(readiness_packet["implementation_decision_packet_status"], "PACKET_HELD")
        self.assertFalse(readiness_packet["implementation_decision_ready"])
        self.assertTrue(readiness_packet["decision_scope"]["decision_not_equal_to_implementation_approval"])
        self.assertFalse(readiness_packet["decision_scope"]["implementation_approved"])
        self.assertEqual(
            {entry["source_type"] for entry in readiness_packet["hold_sources"]},
            {"owner_signoff", "approval_chain", "review_gate", "audit_ref"},
        )
        self.assertIn("direct object export attempted", gate["no_go_conditions"])
        self.assertIn("activation design / implementation prep ready for review still does not authorize implementation", read_json("contracts/release/external_unlock_prerequisite_matrix.json")["capability_domains"][1]["never_default_open_conditions"])

        gate_ids = {entry["gateId"] for entry in release_gates["future_unlock_prerequisite_gates"]}
        self.assertIn("leadpack_activation_implementation_prep_ready", gate_ids)
        self.assertEqual(transition["activation_design_prep_entry"]["source_decision"], "GO")


if __name__ == "__main__":
    unittest.main()
