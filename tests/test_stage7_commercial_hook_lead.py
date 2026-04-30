from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture, run_internal_chain_to_stage7
from stage7_sales.commercial_hook import (
    COMMERCIAL_HOOK_LEAD_INPUT_KEY,
    COMMERCIAL_HOOK_READINESS_INPUT_KEY,
)


class Stage7CommercialHookLeadTests(unittest.TestCase):
    def test_commercial_hook_lead_summarizes_value_without_presale_evidence_leakage(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        hook = stage7.inputs[COMMERCIAL_HOOK_LEAD_INPUT_KEY]
        summary = stage7.inputs[COMMERCIAL_HOOK_READINESS_INPUT_KEY]

        self.assertTrue(hook["hook_lead_id"].startswith("HOOK-"))
        self.assertEqual(hook["contract_id"], "COMMERCIAL_HOOK_LEAD_V1")
        self.assertEqual(hook["disclosure_level"], "L1_HOOK")
        self.assertEqual(hook["hook_eligibility_state"], "ELIGIBLE_FOR_INTERNAL_HOOK_REVIEW")
        self.assertTrue(hook["hook_eligible_for_presale_touch"])
        self.assertFalse(hook["customer_visible_enabled"])
        self.assertFalse(hook["external_send_enabled"])
        self.assertFalse(hook["real_outreach_send_enabled"])
        self.assertTrue(hook["forbidden_claims_filter_passed"])
        self.assertTrue(hook["no_full_evidence_leakage"])
        self.assertEqual(summary["hook_lead_id"], hook["hook_lead_id"])
        self.assertEqual(summary["disclosure_level"], "L1_HOOK")
        self.assertTrue(summary["leakage_risk_classified"])

        for field in (
            "source_url",
            "complete_verification_path",
            "raw_snapshot_or_attachment",
            "internal_scores",
        ):
            self.assertIn(field, hook["withheld_fields"])
        for claim in (
            "concrete_source_url_that_reveals_full_evidence_path",
            "full_public_verification_route",
            "internal_score_model_or_buyer_ranking_logic",
        ):
            self.assertIn(claim, hook["forbidden_sales_claims"])

        allowed_surface = " ".join(
            [
                hook["teaser_copy"],
                hook["redacted_claim_summary"],
                hook["buyer_benefit_summary"],
                *hook["allowed_sales_talking_points"],
            ]
        ).lower()
        for forbidden_token in (
            "http://",
            "https://",
            "source_url",
            "raw_snapshot",
            "complete_verification_path",
            "full_public_verification_route",
            "internal_score_model",
        ):
            self.assertNotIn(forbidden_token, allowed_surface)

        self.assertEqual(stage7.handoff["commercial_hook_lead_optional"], hook)
        self.assertEqual(
            stage7.inputs["stage7_resolution_trace"][COMMERCIAL_HOOK_LEAD_INPUT_KEY],
            hook,
        )
        self.assertEqual(
            stage7.inputs["crm_quote_workbench"][COMMERCIAL_HOOK_READINESS_INPUT_KEY],
            summary,
        )
        self.assertEqual(
            stage7.inputs["leadpack_delivery_package"][COMMERCIAL_HOOK_LEAD_INPUT_KEY],
            hook,
        )
        self.assertEqual(
            hook["business_value_summary"]["objection_value_score"],
            summary["objection_value_score"],
        )
        self.assertEqual(
            hook["buyer_fit_summary"]["buyer_fit_score"],
            stage7.record("buyer_fit").get("fit_score"),
        )

    def test_commercial_hook_fails_closed_when_stage7_sales_state_is_review(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_block.json"))["stage7"]
        hook = stage7.inputs[COMMERCIAL_HOOK_LEAD_INPUT_KEY]
        summary = stage7.inputs[COMMERCIAL_HOOK_READINESS_INPUT_KEY]

        self.assertEqual(hook["disclosure_level"], "INTERNAL_REVIEW_ONLY")
        self.assertEqual(hook["hook_eligibility_state"], "REVIEW_REQUIRED")
        self.assertFalse(hook["hook_eligible_for_presale_touch"])
        self.assertFalse(hook["customer_visible_enabled"])
        self.assertFalse(hook["external_send_enabled"])
        self.assertTrue(hook["requires_manual_review"])
        self.assertIn(summary["leakage_risk_level"], {"MEDIUM", "HIGH"})
        self.assertTrue(hook["forbidden_claims_filter_passed"])
        self.assertTrue(hook["no_full_evidence_leakage"])


if __name__ == "__main__":
    unittest.main()
