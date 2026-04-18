from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class TestLeadpackActivationPrep(unittest.TestCase):
    def test_activation_prep_release_assets_exist_and_align(self) -> None:
        evidence_pack = read_json("contracts/release/leadpack_activation_prep_evidence_pack.json")
        replay = read_json("contracts/release/leadpack_activation_prep_simulation_replay.json")
        runbook = read_json("contracts/release/leadpack_activation_prep_runbook.json")
        signoff = read_json("contracts/release/leadpack_activation_prep_signoff_packet.json")
        transition = read_json("contracts/release/leadpack_activation_prep_transition_matrix.json")

        self.assertEqual(evidence_pack["candidate_domain_id"], "leadpack_external_delivery")
        self.assertIn("ACTIVATION_PREP_READY_FOR_REVIEW", evidence_pack["evidence_pack_status_vocabulary"])
        self.assertTrue(evidence_pack["simulation_replay_required"])
        self.assertTrue(evidence_pack["approval_trace_required"])
        self.assertTrue(evidence_pack["audit_trace_required"])
        self.assertTrue(evidence_pack["projection_boundary_check_required"])
        self.assertTrue(evidence_pack["coverage_boundary_check_required"])
        self.assertTrue(evidence_pack["delivery_matrix_check_required"])
        self.assertTrue(evidence_pack["required_evidence_items"])
        self.assertIn("export_simulation_replay_artifact", evidence_pack["evidence_item_sources"])

        self.assertEqual(replay["source_operation_id"], "simulateLeadpackExternalDeliveryExport")
        self.assertIn("REPLAY_READY", replay["replay_status_vocabulary"])
        self.assertIn("candidate_matrix_ref", replay["artifact_fields"])

        action_ids = {entry["runbook_action_id"] for entry in runbook["runbook_actions"]}
        self.assertEqual(
            action_ids,
            {
                "OPEN_PREP_PACKET",
                "REQUEST_PREP_REVIEW",
                "HOLD_PREP",
                "DENY_PREP",
                "RETURN_FOR_REVISION",
                "ROLLBACK_OR_CANCEL_PREP",
            },
        )

        required_roles = {entry["owner_role"] for entry in signoff["required_owner_signoffs"]}
        self.assertEqual(required_roles, {"release_approver", "governance_owner", "testing_owner"})
        self.assertTrue(signoff["draft_packet_allowed"])
        self.assertTrue(signoff["draft_packet_is_not_activation_ready"])

        self.assertEqual(transition["review_gate"]["gate_id"], "leadpack_activation_prep_review_gate")
        self.assertTrue(transition["review_gate"]["manual_review_required"])
        self.assertTrue(transition["review_gate"]["activation_ready_claim_forbidden"])
        self.assertTrue(transition["review_gate"]["external_ready_claim_forbidden"])


if __name__ == "__main__":
    unittest.main()
