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

from helpers import load_fixture
from api.routes.stage7 import (
    preview_formal_client_export_page_layer_readiness,
    preview_leadpack_external_delivery_candidate,
    request_leadpack_external_delivery_candidate_review,
    simulate_leadpack_external_delivery_export,
)
from shared.pipeline import run_internal_chain

def read_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class TestLeadpackCandidateSurface(unittest.TestCase):
    def _approved_customer_visible_payload(self) -> dict:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "approved_customer_visible_unlock_requested": True,
                "approved_customer_artifact_access_requested": True,
                "approved_customer_page_publication_requested": True,
                "approved_export_artifact_generation_requested": True,
                "approved_customer_download_requested": True,
                "customer_download_requested": True,
                "approval_state": "APPROVED",
                "project_fact_audit_ref": "AUD-PROJECT-FACT-001",
                "candidate_projection_audit_ref": "AUD-CANDIDATE-001",
                "approval_chain_audit_ref": "AUD-APPROVAL-001",
                "customer_account_access_state": "APPROVED",
                "customer_artifact_access_approval_state": "APPROVED",
                "customer_download_auth_state": "AUTHORIZED",
                "download_auth_audit_ref": "AUD-DOWNLOAD-AUTH-001",
                "customer_access_audit_ref": "AUD-CUSTOMER-ACCESS-001",
                "external_visibility_state": "CUSTOMER_VISIBLE_APPROVED",
                "leadpack_candidate_review_gate": "APPROVED",
                "leadpack_activation_prep_review_gate": "APPROVED",
                "implementation_decision_state": "APPROVED",
            }
        )
        return payload

    def test_candidate_matrix_freezes_projection_and_denial_contract(self) -> None:
        matrix = read_json("contracts/release/leadpack_external_delivery_candidate_matrix.json")

        self.assertEqual(matrix["candidate_domain_id"], "leadpack_external_delivery")
        self.assertEqual(matrix["candidate_status"], "INTERNAL_ONLY_CANDIDATE_DEFINED")
        self.assertTrue(matrix["projection_only"])
        self.assertFalse(matrix["direct_object_export_allowed"])
        self.assertTrue(matrix["candidate_scope"]["internal_only"])
        self.assertTrue(matrix["candidate_scope"]["candidate_only"])
        self.assertFalse(matrix["candidate_scope"]["external_delivery_enabled"])
        self.assertTrue(matrix["candidate_scope"]["requires_review"])

        boundary = {entry["object"]: entry["classification"] for entry in matrix["projection_boundary_rules"]}
        self.assertEqual(boundary["saleable_opportunity"], "allowed_projection")
        self.assertEqual(boundary["contact_target"], "masked_projection")
        self.assertEqual(boundary["touch_record"], "summary_only")
        self.assertEqual(boundary["outreach_plan"], "forbidden")
        self.assertEqual(boundary["order_record"], "forbidden")
        self.assertEqual(boundary["governance_feedback_event"], "forbidden")
        self.assertTrue(matrix["denial_conditions"])

    def test_candidate_preview_review_and_export_simulation_stay_internal_only(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))

        preview = preview_leadpack_external_delivery_candidate(result)
        review = request_leadpack_external_delivery_candidate_review(result)
        simulation = simulate_leadpack_external_delivery_export(result)

        for response in (preview, review, simulation):
            self.assertTrue(response["internal_only"])
            self.assertTrue(response["candidate_only"])
            self.assertFalse(response["external_delivery_enabled"])
            self.assertFalse(response["leadpack_delivery_package"]["customer_visible_enabled"])
            self.assertFalse(response["leadpack_delivery_package"]["external_delivery_enabled"])
            self.assertEqual(response["leadpack_delivery_package"]["masking_state"], "MASKING_REQUIRED")
            artifact_candidate = response["leadpack_delivery_package"]["customer_visible_artifact_candidate"]
            page_export_candidate = response["leadpack_delivery_package"]["page_export_candidate"]
            field_policy = artifact_candidate["field_policy"]
            self.assertEqual(artifact_candidate["candidate_state"], "SANDBOX_CANDIDATE_READY")
            self.assertFalse(artifact_candidate["customer_visible_enabled"])
            self.assertFalse(artifact_candidate["external_delivery_enabled"])
            self.assertIn("opportunity_id", field_policy["field_allowlist"])
            self.assertIn("payment_record", field_policy["field_blacklist"])
            self.assertTrue(field_policy["allowlist_enforced"])
            self.assertTrue(field_policy["blacklist_enforced"])
            self.assertEqual(artifact_candidate["watermark"]["watermark_state"], "APPLIED_TO_DRAFT")
            self.assertTrue(
                artifact_candidate["artifact_version_hash"].startswith("sha256:"),
                artifact_candidate["artifact_version_hash"],
            )
            self.assertFalse(artifact_candidate["download_audit"]["customer_download_enabled"])
            self.assertEqual(artifact_candidate["export_page_replay"]["replay_state"], "REPLAY_READY")
            self.assertEqual(
                page_export_candidate["artifact_version_hash"],
                artifact_candidate["artifact_version_hash"],
            )
            self.assertFalse(page_export_candidate["page_publication_enabled"])
            self.assertEqual(
                response["package_page_delivery_summary"]["package"]["package_id"],
                response["leadpack_delivery_package"]["package_id"],
            )
            self.assertEqual(
                response["package_page_delivery_summary"]["page_export_candidate"]["export_candidate_id"],
                page_export_candidate["export_candidate_id"],
            )
            self.assertFalse(response["leadpack_delivery_readiness_summary"]["delivery_ready"])
            self.assertEqual(
                response["leadpack_delivery_readiness_summary"]["artifact_version_hash"],
                artifact_candidate["artifact_version_hash"],
            )
            self.assertEqual(
                response["candidate_readback_summary"]["export_page_replay_id"],
                artifact_candidate["export_page_replay"]["replay_id"],
            )
            self.assertFalse(response["package_page_delivery_summary"]["page_publication_enabled"])
            self.assertTrue(response["requires_review"])
            self.assertIn(response["surface_state"], {"preview-ready", "review-required", "governed-hold", "blocked"})
            self.assertIn("approval_prerequisites_not_met", response["blocked_reasons"])
            self.assertIn("stage8_governed_preview_not_external_ready", response["hold_reasons"])
            self.assertIn("stage9_internal_governed_preview_not_external_ready", response["hold_reasons"])

        self.assertFalse(preview["review_requested"])
        self.assertTrue(review["review_requested"])
        self.assertTrue(simulation["export_simulation_requested"])
        self.assertIn("stage9.delivery_record_direct_export", {item["component_id"] for item in preview["candidate_projection"]["forbidden"]})

    def test_approved_customer_visible_leadpack_unlock_requires_all_gates(self) -> None:
        result = run_internal_chain(self._approved_customer_visible_payload())

        package = result["stage7"].inputs["leadpack_delivery_package"]
        unlock = package["approved_customer_visible_unlock_summary"]

        self.assertTrue(unlock["approved_customer_visible_unlock_enabled"])
        self.assertEqual(unlock["unlock_state"], "APPROVED_CUSTOMER_VISIBLE_READBACK")
        self.assertEqual(unlock["download_auth_state"], "AUTHORIZED")
        self.assertEqual(unlock["external_visibility_state"], "CUSTOMER_VISIBLE_APPROVED")
        self.assertTrue(package["customer_visible_enabled"])
        self.assertTrue(package["customer_visible_export_enabled"])
        self.assertTrue(package["export_artifact_generation_enabled"])
        self.assertTrue(package["page_publication_enabled"])
        self.assertTrue(package["download_audit"]["download_enabled"])
        self.assertTrue(package["download_audit"]["customer_download_enabled"])
        self.assertFalse(package["download_audit"]["real_customer_download_executed"])
        self.assertFalse(package["external_delivery_enabled"])
        self.assertFalse(package["external_release_enabled"])
        self.assertFalse(package["real_provider_call_enabled"])
        self.assertIn("opportunity_id", package["field_policy"]["field_allowlist"])
        self.assertIn("internal_score_raw", package["field_policy"]["field_blacklist"])
        self.assertEqual(package["watermark"]["watermark_state"], "APPLIED_TO_APPROVED_ARTIFACT")
        self.assertTrue(package["artifact_version_hash"].startswith("sha256:"))
        self.assertIn("external_software_release_controlled_opening_required", package["blocked_reasons"])
        self.assertNotIn("customer_visible_request_blocked", package["blocked_reasons"])

        readiness = preview_formal_client_export_page_layer_readiness(result)
        self.assertEqual(readiness["readiness_state"], "APPROVED_CUSTOMER_VISIBLE_READBACK")
        self.assertFalse(readiness["release_blocked"])
        self.assertFalse(readiness["readiness_only"])
        self.assertTrue(readiness["customer_visible_export_enabled"])
        self.assertTrue(readiness["client_page_release_enabled"])
        self.assertTrue(readiness["export_artifact_generation_enabled"])
        self.assertTrue(readiness["page_publication_enabled"])
        self.assertFalse(readiness["external_release_enabled"])
        self.assertTrue(readiness["download_audit"]["customer_download_enabled"])
        self.assertTrue(
            readiness["operator_readback_summary"]["operator_can_enable_customer_visible_export"]
        )

    def test_customer_visible_unlock_fails_closed_on_blackbox_or_unreviewed_inputs(self) -> None:
        payload = self._approved_customer_visible_payload()
        payload.update(
            {
                "internal_blackbox_score_export_requested": True,
                "unreviewed_inference_customer_visible_requested": True,
                "formal_legal_document_auto_send_requested": True,
            }
        )

        result = run_internal_chain(payload)
        package = result["stage7"].inputs["leadpack_delivery_package"]
        unlock = package["approved_customer_visible_unlock_summary"]

        self.assertFalse(unlock["approved_customer_visible_unlock_enabled"])
        self.assertFalse(package["customer_visible_enabled"])
        self.assertFalse(package["download_audit"]["customer_download_enabled"])
        for reason in (
            "internal_blackbox_score_exposure_blocked",
            "unreviewed_inference_customer_visible_blocked",
            "legal_document_auto_send_blocked",
        ):
            self.assertIn(reason, unlock["blocking_reasons"])
            self.assertIn(reason, package["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
