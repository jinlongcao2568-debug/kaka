from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.stage4_backfill_followup_queue import build_stage4_backfill_followup_queue


class Stage4BackfillFollowupQueueTests(unittest.TestCase):
    def test_builds_controller_consumable_followups_from_scoreboard_gap_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scoreboard = root / "scoreboard.json"
            out = root / "out"
            _write_json(
                scoreboard,
                {
                    "project_rows": [
                        {
                            "project_id": "PROJ-NO-SIGNAL",
                            "project_name": "No signal project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW",
                            "p13b_public_source_readback_state": "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW",
                            "p13b_overlap_triage_state": "NO_OVERLAP_SIGNAL_REVIEW",
                        },
                        {
                            "project_id": "PROJ-BLOCKED",
                            "project_name": "Blocked project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_public_source_readback_state": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_overlap_triage_state": "SOURCE_LIMIT_DEFERRED",
                        },
                        {
                            "project_id": "PROJ-READY",
                            "stage4_project_code_backfill_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                            "stage4_project_code_backfill_gap_detail": "",
                        },
                    ]
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        self.assertEqual(result["summary"]["followup_record_count"], 2)
        self.assertEqual(
            result["summary"]["gap_detail_counts"],
            {
                "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 1,
                "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 1,
            },
        )
        routes = {record["project_id"]: record["followup_route"] for record in result["records"]}
        self.assertEqual(routes["PROJ-NO-SIGNAL"], "local_authority_fallback_source_planning")
        self.assertEqual(routes["PROJ-BLOCKED"], "public_source_retry_then_local_authority_fallback")
        for record in result["records"]:
            self.assertTrue(record["controller_consumable"])
            self.assertFalse(record["customer_visible_allowed"])
            self.assertFalse(record["live_execution_enabled"])
            self.assertTrue(record["query_miss_is_not_clearance"])
            self.assertEqual(record["execution_priority"], "NORMAL")
            self.assertFalse(record["public_source_deepening_recommended"])

    def test_applies_public_source_deepening_policy_from_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_root = root / "stage1-6-sellable-rate-regression-live20-r2"
            scoreboard = run_root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            comparison = root / "comparison.json"
            out = root / "out"
            _write_json(
                scoreboard,
                {
                    "project_rows": [
                        {
                            "project_id": "PROJ-PUBLIC-RETRY",
                            "project_name": "Public retry project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_public_source_readback_state": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_overlap_triage_state": "SOURCE_LIMIT_DEFERRED",
                        },
                        {
                            "project_id": "PROJ-LOCAL-FALLBACK",
                            "project_name": "Local fallback project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW",
                            "p13b_public_source_readback_state": "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW",
                            "p13b_overlap_triage_state": "NO_OVERLAP_SIGNAL_REVIEW",
                        },
                    ]
                },
            )
            _write_json(
                comparison,
                {
                    "public_source_deepening_recommendations": [
                        {
                            "run_label": "stage1-6-sellable-rate-regression-live20-r2",
                            "previous_run_label": "stage1-6-sellable-rate-regression-live20-r1",
                            "decision": "CONTINUE_PUBLIC_SOURCE_DEEPENING",
                            "reason": "same_candidate_count_improved_rate_limited_stage4_matched_readback_ready_and_ygp_backfill",
                            "recommended_budget_focus": [
                                "increase_p13b_prior_award_and_candidate_overlap_budget",
                                "increase_original_notice_readback_budget",
                                "increase_ygp_original_readback_backfill_budget",
                                "continue_remaining_stage4_backfill_followup_queue_before_gdcic_project_code_guessing",
                            ],
                        }
                    ]
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                scoreboard_comparison_json=comparison,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )
            markdown = (out / "stage4-backfill-followup-queue-v1.md").read_text(encoding="utf-8")

        self.assertTrue(result["public_source_deepening_policy"]["public_source_deepening_recommended"])
        self.assertEqual(result["public_source_deepening_policy"]["decision"], "CONTINUE_PUBLIC_SOURCE_DEEPENING")
        self.assertFalse(result["public_source_deepening_policy"]["customer_visible_allowed"])
        self.assertFalse(result["public_source_deepening_policy"]["gdcic_project_code_digit_guessing_allowed"])
        self.assertEqual(
            result["summary"]["execution_priority_counts"],
            {
                "HIGH_PUBLIC_SOURCE_DEEPENING": 1,
                "MEDIUM_LOCAL_AUTHORITY_FALLBACK": 1,
            },
        )
        records = {record["project_id"]: record for record in result["records"]}
        self.assertEqual(records["PROJ-PUBLIC-RETRY"]["execution_priority"], "HIGH_PUBLIC_SOURCE_DEEPENING")
        self.assertEqual(records["PROJ-LOCAL-FALLBACK"]["execution_priority"], "MEDIUM_LOCAL_AUTHORITY_FALLBACK")
        for record in result["records"]:
            self.assertTrue(record["public_source_deepening_recommended"])
            self.assertEqual(record["public_source_deepening_decision"], "CONTINUE_PUBLIC_SOURCE_DEEPENING")
            self.assertIn(
                "continue_remaining_stage4_backfill_followup_queue_before_gdcic_project_code_guessing",
                record["recommended_budget_focus"],
            )
            self.assertFalse(record["customer_visible_allowed"])
            self.assertFalse(record["live_execution_enabled"])
            self.assertTrue(record["query_miss_is_not_clearance"])
        self.assertIn("public_source_deepening_policy", markdown)
        self.assertIn("CONTINUE_PUBLIC_SOURCE_DEEPENING", markdown)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
