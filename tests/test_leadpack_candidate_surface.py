from __future__ import annotations

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
    preview_leadpack_external_delivery_candidate,
    request_leadpack_external_delivery_candidate_review,
    simulate_leadpack_external_delivery_export,
)
from shared.pipeline import run_internal_chain

def read_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class TestLeadpackCandidateSurface(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
