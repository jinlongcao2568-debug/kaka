from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class Stage5RuleBundleExecutorTests(unittest.TestCase):
    def test_rule_bundle_records_executed_skipped_and_missing_readbacks(self) -> None:
        from stage4_verification.public_evidence_readback import build_public_evidence_readback
        from stage5_rules_evidence.rule_bundle_executor import RuleBundleExecutor

        credit_readback = build_public_evidence_readback(
            readback_id="RB-CREDIT-1",
            verification_target_type="credit_penalty_blacklist",
            source_family="credit_china",
            source_url="https://example.test/credit",
            source_snapshot_id="SNAP-CREDIT-1",
            snapshot_hash="hash-credit",
            subject_identifier="COMPANY-1",
            field_extracts={"source_slice_sha256": "slice-credit"},
            validity_or_status="ACTIVE",
            repair_or_release_state="UNREPAIRED",
            data_grade_or_audit_state="AUDITED",
        )

        result = RuleBundleExecutor(
            rule_codes=["CREDIT-001", "REL-001", "UNKNOWN-001"],
        ).execute(
            bundle_id="BUNDLE-STAGE5-1",
            readbacks=[credit_readback],
        )

        self.assertEqual(result["executor_id"], "stage5-rule-bundle-executor-v1")
        self.assertEqual(result["bundle_id"], "BUNDLE-STAGE5-1")
        self.assertEqual(result["executed_rule_codes"], ["CREDIT-001"])
        self.assertEqual(result["skipped_rule_codes"], ["REL-001", "UNKNOWN-001"])
        self.assertEqual(result["rule_results"]["CREDIT-001"]["gate_status"], "PASS")
        self.assertIn("REL-001", result["missing_readback_reasons"])
        self.assertIn("UNKNOWN-001", result["missing_readback_reasons"])
        calibration = result["stage5_abcd_calibration"]
        self.assertEqual(
            calibration["calibration_bucket_counts"],
            {
                "A_OFFICIAL_PUBLIC_READBACK_PASS": 1,
                "C_MISSING_RELEVANT_PUBLIC_READBACK": 1,
                "D_UNSUPPORTED_RULE_OR_RUNTIME_BLOCKED": 1,
            },
        )
        self.assertEqual(calibration["truth_label_required_count"], 2)
        self.assertEqual(calibration["non_clearance_rule_count"], 2)
        self.assertEqual(
            calibration["calibration_evidence_strength_counts"],
            {
                "OFFICIAL_PUBLIC_READBACK_PASS": 1,
                "PUBLIC_READBACK_MISSING_OR_INSUFFICIENT": 1,
                "BLOCKED_OR_UNSUPPORTED": 1,
            },
        )
        self.assertEqual(
            calibration["calibration_review_family_counts"],
            {
                "baseline_pass": 1,
                "missing_relevant_public_readback": 1,
                "unsupported_rule_or_runtime_blocked": 1,
            },
        )
        self.assertEqual(
            result["summary"]["stage5_abcd_calibration_counts"],
            calibration["calibration_bucket_counts"],
        )
        self.assertFalse(result["customer_visible_allowed"])
        self.assertTrue(result["no_legal_conclusion"])

    def test_relevant_but_incomplete_readback_is_executed_with_review_reasons(self) -> None:
        from stage5_rules_evidence.rule_bundle_executor import RuleBundleExecutor

        incomplete_relation_readback = {
            "readback_id": "RB-REL-1",
            "verification_target_type": "enterprise_relation_public_record",
            "source_family": "national_enterprise_credit_publicity_system",
            "source_url": "https://example.test/gsxt",
            "source_snapshot_id": "SNAP-REL-1",
            "snapshot_hash": "hash-rel",
            "official_source": True,
            "subject_identifier": "COMPANY-1",
            "field_extracts": {},
            "validity_or_status": "ACTIVE",
            "repair_or_release_state": "UNREPAIRED",
            "data_grade_or_audit_state": "AUDITED",
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
        }

        result = RuleBundleExecutor(rule_codes=["REL-001"]).execute(
            bundle_id="BUNDLE-STAGE5-REL",
            readbacks=[incomplete_relation_readback],
        )

        self.assertEqual(result["executed_rule_codes"], ["REL-001"])
        self.assertEqual(result["skipped_rule_codes"], [])
        self.assertEqual(result["rule_results"]["REL-001"]["gate_status"], "REVIEW")
        self.assertEqual(result["missing_readback_reasons"], {})
        self.assertTrue(result["rule_results"]["REL-001"]["reasons"])
        calibration_row = result["stage5_abcd_calibration"]["calibration_rows"][0]
        self.assertEqual(calibration_row["calibration_bucket"], "B_PUBLIC_READBACK_REVIEW_REQUIRED")
        self.assertEqual(calibration_row["calibration_evidence_strength"], "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED")
        self.assertEqual(calibration_row["calibration_review_family"], "manual_public_readback_review")
        self.assertTrue(calibration_row["truth_label_required"])
        self.assertTrue(calibration_row["query_miss_is_not_clearance"])
        self.assertTrue(calibration_row["no_clearance_without_public_readback"])

    def test_blocked_or_not_found_readback_calibration_never_becomes_clearance(self) -> None:
        from stage5_rules_evidence.rule_bundle_executor import RuleBundleExecutor

        blocked_readback = {
            "readback_id": "RB-ENG-BLOCKED",
            "verification_target_type": "construction_permit",
            "source_family": "local_housing_construction_permit",
            "source_url": "https://example.test/permit",
            "source_snapshot_id": "SNAP-ENG-BLOCKED",
            "snapshot_hash": "hash-eng-blocked",
            "official_source": True,
            "subject_identifier": "COMPANY-1",
            "field_extracts": {"project_code": "P-1", "candidate_company_match": True},
            "validity_or_status": "NOT_FOUND",
            "repair_or_release_state": "UNKNOWN",
            "data_grade_or_audit_state": "D",
            "review_required": True,
            "failure_reasons": ["LOGIN_OR_SSO_REQUIRED"],
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
        }

        result = RuleBundleExecutor(rule_codes=["ENG-001"]).execute(
            bundle_id="BUNDLE-STAGE5-BLOCKED",
            readbacks=[blocked_readback],
        )

        calibration_row = result["stage5_abcd_calibration"]["calibration_rows"][0]
        self.assertEqual(calibration_row["calibration_bucket"], "D_BLOCKED_OR_AUTHORIZATION_REQUIRED")
        self.assertEqual(calibration_row["calibration_evidence_strength"], "BLOCKED_OR_UNSUPPORTED")
        self.assertEqual(calibration_row["calibration_review_family"], "authorization_or_source_blocked")
        self.assertEqual(result["summary"]["truth_label_required_count"], 1)
        self.assertEqual(result["summary"]["non_clearance_rule_count"], 1)
        self.assertTrue(calibration_row["query_miss_is_not_clearance"])
        self.assertTrue(calibration_row["no_clearance_without_public_readback"])
        self.assertNotIn("无风险", str(result))


if __name__ == "__main__":
    unittest.main()
