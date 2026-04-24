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
            self.assertEqual(
                response["package_page_delivery_summary"]["package"]["package_id"],
                response["leadpack_delivery_package"]["package_id"],
            )
            self.assertFalse(response["leadpack_delivery_readiness_summary"]["delivery_ready"])
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
