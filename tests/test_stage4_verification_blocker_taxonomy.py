from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class Stage4VerificationBlockerTaxonomyTests(unittest.TestCase):
    def test_not_found_probe_is_review_required_not_clearance(self) -> None:
        from stage4_verification.blocker_taxonomy import classify_stage4_probe_result

        outcome = classify_stage4_probe_result(
            {
                "probe_status": "NOT_FOUND",
                "source_url": "https://example.test/public-source",
                "source_snapshot_id": "SNAP-NOT-FOUND",
                "query_terms": {"company_name": "测试公司"},
            }
        )

        self.assertEqual(outcome["verification_state"], "NOT_FOUND")
        self.assertEqual(outcome["run_state"], "REVIEW_REQUIRED")
        self.assertIn("source_not_found_not_clearance", outcome["blocker_ids"])
        self.assertTrue(outcome["query_miss_is_not_clearance"])
        self.assertFalse(outcome["clearance_allowed"])
        self.assertTrue(outcome["readback_required"])
        self.assertNotIn("NO_RISK", str(outcome))

    def test_needs_browser_is_distinct_from_not_found(self) -> None:
        from stage4_verification.blocker_taxonomy import classify_stage4_probe_result

        outcome = classify_stage4_probe_result(
            {
                "probe_status": "NEEDS_BROWSER",
                "source_url": "https://example.test/browser-only",
                "blocking_reason": "dynamic_render_required",
            }
        )

        self.assertEqual(outcome["verification_state"], "NEEDS_BROWSER")
        self.assertEqual(outcome["run_state"], "BLOCKED")
        self.assertIn("needs_browser", outcome["blocker_ids"])
        self.assertNotIn("source_not_found_not_clearance", outcome["blocker_ids"])
        self.assertEqual(outcome["operator_next_action"], "RUN_BROWSER_WORKER_OR_OPERATOR_CAPTURE")

    def test_login_or_sso_gap_uses_blocked_authorization_state_not_new_needs_auth_enum(self) -> None:
        from stage4_verification.blocker_taxonomy import classify_stage4_probe_result

        outcome = classify_stage4_probe_result(
            {
                "probe_status": "LOGIN_OR_SSO_REQUIRED",
                "source_url": "https://example.test/login-required",
            }
        )

        self.assertEqual(outcome["verification_state"], "BLOCKED")
        self.assertEqual(outcome["run_state"], "BLOCKED")
        self.assertEqual(outcome["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
        self.assertIn("login_or_sso_required", outcome["blocker_ids"])
        self.assertNotIn("NEEDS_AUTH", str(outcome))
        self.assertEqual(outcome["operator_next_action"], "OPERATOR_LOGIN_OR_SSO_CAPTURE_REQUIRED")

    def test_matched_probe_still_stays_internal_and_non_legal(self) -> None:
        from stage4_verification.blocker_taxonomy import classify_stage4_probe_result

        outcome = classify_stage4_probe_result(
            {
                "probe_status": "MATCHED",
                "verification_target_type": "personnel_public_record",
                "source_url": "https://example.test/public-record",
                "source_snapshot_id": "SNAP-MATCHED",
                "snapshot_hash": "abc123",
                "readback_refs": ["READBACK-1"],
                "field_match_state": "MATCHED",
            }
        )

        self.assertEqual(outcome["verification_state"], "MATCHED")
        self.assertEqual(outcome["run_state"], "READY")
        self.assertEqual(outcome["blocker_ids"], [])
        self.assertFalse(outcome["customer_visible_allowed"])
        self.assertTrue(outcome["no_legal_conclusion"])
        self.assertFalse(outcome["clearance_allowed"])

    def test_blocked_probe_records_blocker_without_converting_to_not_found(self) -> None:
        from stage4_verification.blocker_taxonomy import classify_stage4_probe_result

        outcome = classify_stage4_probe_result(
            {
                "probe_status": "BLOCKED",
                "source_url": "https://example.test/blocked",
                "blocking_reason": "rate_limited_or_captcha",
            }
        )

        self.assertEqual(outcome["verification_state"], "BLOCKED")
        self.assertEqual(outcome["run_state"], "BLOCKED")
        self.assertIn("source_blocked", outcome["blocker_ids"])
        self.assertIn("rate_limited_or_captcha", outcome["blocking_reasons"])
        self.assertNotIn("source_not_found_not_clearance", outcome["blocker_ids"])


if __name__ == "__main__":
    unittest.main()
