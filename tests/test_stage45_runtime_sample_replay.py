from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class Stage45RuntimeSampleReplayTests(unittest.TestCase):
    def test_stage4_miss_browser_login_and_blocked_enter_ledger_and_operator_actions(self) -> None:
        from runtime.stage45_replay import build_stage45_runtime_sample_replay

        result = build_stage45_runtime_sample_replay(
            {
                "bundle_id": "BUNDLE-STAGE45-REPLAY",
                "stage5_rule_codes": ["CREDIT-001", "REL-001"],
                "stage4_probe_results": [
                    {
                        "project_id": "PROJ-NOT-FOUND",
                        "probe_status": "NOT_FOUND",
                        "source_url": "https://example.test/not-found",
                    },
                    {
                        "project_id": "PROJ-BROWSER",
                        "probe_status": "NEEDS_BROWSER",
                        "source_url": "https://example.test/browser",
                    },
                    {
                        "project_id": "PROJ-LOGIN",
                        "probe_status": "LOGIN_OR_SSO_REQUIRED",
                        "source_url": "https://example.test/login",
                    },
                    {
                        "project_id": "PROJ-BLOCKED",
                        "probe_status": "BLOCKED",
                        "blocking_reason": "rate_limited_or_captcha",
                    },
                    {
                        "project_id": "PROJ-MATCHED",
                        "probe_status": "MATCHED",
                        "field_match_state": "MATCHED",
                        "source_url": "https://example.test/matched",
                        "source_snapshot_id": "SNAP-MATCHED",
                        "snapshot_hash": "hash-matched",
                    },
                ],
                "stage4_public_evidence_readbacks": [
                    {
                        "readback_id": "RB-CREDIT",
                        "verification_target_type": "credit_penalty_blacklist",
                        "source_family": "credit_china",
                        "source_url": "https://example.test/credit",
                        "source_snapshot_id": "SNAP-CREDIT",
                        "snapshot_hash": "hash-credit",
                        "official_source": True,
                        "subject_identifier": "COMPANY-1",
                        "field_extracts": {"source_slice_sha256": "slice-credit"},
                        "validity_or_status": "ACTIVE",
                        "repair_or_release_state": "UNREPAIRED",
                        "data_grade_or_audit_state": "AUDITED",
                        "public_only": True,
                        "customer_visible": False,
                        "no_legal_conclusion": True,
                    }
                ],
            },
            created_at="2026-05-24T00:00:00+08:00",
        )

        self.assertTrue(result["safe_to_execute"])
        summary = result["summary"]
        self.assertEqual(summary["stage4_probe_replay_count"], 5)
        self.assertEqual(
            summary["stage4_verification_state_counts"],
            {"BLOCKED": 2, "MATCHED": 1, "NEEDS_BROWSER": 1, "NOT_FOUND": 1},
        )
        self.assertEqual(summary["stage4_blocker_ledger_count"], 4)
        self.assertEqual(summary["operator_action_count"], 4)
        self.assertEqual(summary["authorization_readiness_state_counts"], {"LOGIN_OR_SSO_REQUIRED": 1})
        self.assertEqual(summary["stage5_executed_rule_codes"], ["CREDIT-001"])
        self.assertEqual(summary["stage5_skipped_rule_codes"], ["REL-001"])
        self.assertEqual(summary["stage5_missing_readback_count"], 1)
        self.assertEqual(summary["stage5_calibration_sample_count"], 2)
        self.assertEqual(summary["stage5_calibration_truth_label_required_count"], 1)
        self.assertEqual(
            summary["stage5_abcd_calibration_counts"],
            {
                "A_OFFICIAL_PUBLIC_READBACK_PASS": 1,
                "C_MISSING_RELEVANT_PUBLIC_READBACK": 1,
            },
        )
        self.assertEqual(
            summary["stage5_calibration_review_family_counts"]["missing_relevant_public_readback"],
            1,
        )
        calibration_samples = result["manifest"]["stage5_calibration_sample_records"]
        self.assertEqual(len(calibration_samples), 2)
        missing_sample = next(
            item for item in calibration_samples if item["stage5_abcd_calibration_bucket"] == "C_MISSING_RELEVANT_PUBLIC_READBACK"
        )
        self.assertTrue(missing_sample["calibration_truth_label_required"])
        self.assertTrue(missing_sample["query_miss_is_not_clearance"])
        self.assertEqual(
            missing_sample["suggested_calibration_action"],
            "collect_targeted_public_readback_before_any_clearance_claim",
        )
        route_counts = summary["runtime_blocker_subqueue_route_counts"]
        self.assertEqual(route_counts["browser_worker"], 2)
        self.assertEqual(route_counts["fallback_source"], 1)
        self.assertEqual(route_counts["retry"], 1)
        self.assertEqual(route_counts["suspend_dead_letter"], 1)
        self.assertEqual(route_counts["operator_action"], 4)
        self.assertTrue(summary["query_miss_is_not_clearance"])
        self.assertFalse(result["customer_visible_allowed"])
        self.assertNotIn("NO_RISK", str(result))
        self.assertNotIn("无风险", str(result))

    def test_stage45_replay_writes_machine_readable_artifact(self) -> None:
        from runtime.stage45_replay import build_stage45_runtime_sample_replay

        with self.subTest("write artifact"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                result = build_stage45_runtime_sample_replay(
                    {
                        "stage4_probe_results": [
                            {
                                "project_id": "PROJ-NOT-FOUND",
                                "probe_status": "NOT_FOUND",
                            }
                        ],
                        "stage5_rule_codes": ["CREDIT-001"],
                    },
                    created_at="2026-05-24T00:00:00+08:00",
                    output_root=root,
                )

                self.assertTrue(result["safe_to_execute"])
                self.assertTrue((root / "stage45-runtime-sample-replay-v1.json").exists())


if __name__ == "__main__":
    unittest.main()
