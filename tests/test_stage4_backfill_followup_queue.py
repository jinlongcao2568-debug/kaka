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
                        {
                            "project_id": "PROJ-SOURCE-BLOCKED-NO-CODE-GAP",
                            "project_name": "source blocked after project code backfill",
                            "stage4_project_code_backfill_state": "NOT_FLAGGED_FOR_PROJECT_CODE_BACKFILL",
                            "stage4_project_code_backfill_gap_detail": "",
                            "stage5_operational_review_bucket": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_public_source_readback_state": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_overlap_triage_state": "SOURCE_LIMIT_DEFERRED",
                        },
                        {
                            "project_id": "PROJ-GDCIC-UNRESOLVED",
                            "project_name": "GDCIC unresolved after public backfill",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "GDCIC_IDENTIFIER_UNRESOLVED_AFTER_PUBLIC_BACKFILL_REQUIRED",
                            "stage5_operational_review_bucket": "AUTHORIZATION_BLOCKED_REVIEW",
                            "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_overlap_triage_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_bid_show_original_notice_url_count": 1,
                        },
                        {
                            "project_id": "PROJ-STRONG-ORIGINAL-BLOCKED",
                            "project_name": "Strong signal but original notice blocked",
                            "stage4_project_code_backfill_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                            "stage4_project_code_backfill_gap_detail": "",
                            "stage5_operational_review_bucket": "STRONG_LEAD_INTERNAL_REVIEW",
                            "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_original_notice_readback_state": "BLOCKED",
                            "p13b_ygp_original_readback_state": "YGP_READBACK_READY",
                            "p13b_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                        },
                        {
                            "project_id": "PROJ-YGP-BLOCKED",
                            "project_name": "YGP blocked after bid show backfill",
                            "stage4_project_code_backfill_state": "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                            "stage4_project_code_backfill_gap_detail": "",
                            "stage5_operational_review_bucket": "YGP_READBACK_BLOCKED_REVIEW",
                            "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_original_notice_readback_state": "PENDING_OR_NOT_RUN",
                            "p13b_ygp_original_readback_state": "YGP_BLOCKED",
                            "p13b_overlap_triage_state": "SOURCE_LIMIT_DEFERRED",
                        },
                    ]
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        self.assertEqual(result["summary"]["followup_record_count"], 6)
        self.assertEqual(
            result["summary"]["gap_detail_counts"],
            {
                "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 1,
                "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 2,
                "GDCIC_IDENTIFIER_UNRESOLVED_AFTER_PUBLIC_BACKFILL_REQUIRED": 1,
                "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED": 1,
                "YGP_READBACK_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 1,
            },
        )
        routes = {record["project_id"]: record["followup_route"] for record in result["records"]}
        self.assertEqual(routes["PROJ-NO-SIGNAL"], "local_authority_fallback_source_planning")
        self.assertEqual(routes["PROJ-BLOCKED"], "public_source_retry_then_local_authority_fallback")
        self.assertEqual(
            routes["PROJ-SOURCE-BLOCKED-NO-CODE-GAP"],
            "public_source_retry_then_local_authority_fallback",
        )
        self.assertEqual(routes["PROJ-GDCIC-UNRESOLVED"], "local_authority_fallback_source_planning")
        self.assertEqual(
            routes["PROJ-STRONG-ORIGINAL-BLOCKED"],
            "original_notice_retry_then_local_authority_fallback",
        )
        self.assertEqual(routes["PROJ-YGP-BLOCKED"], "ygp_retry_then_local_authority_fallback")
        unresolved = next(record for record in result["records"] if record["project_id"] == "PROJ-GDCIC-UNRESOLVED")
        self.assertEqual(
            [step["source_kind"] for step in unresolved["public_source_fallback_sequence"]],
            [
                "data_ggzy_company_history_search",
                "data_ggzy_bid_list_pagination",
                "data_ggzy_bid_show_readback",
                "ygp_original_notice_readback",
                "project_local_authority_public_source",
            ],
        )
        self.assertEqual(
            unresolved["public_source_fallback_sequence"][2]["input_state"],
            "BID_SHOW_ORIGINAL_NOTICE_URL_PRESENT",
        )
        self.assertIn("data_ggzy_bid_show_or_ygp_backfill_input", unresolved["required_input"])
        self.assertEqual(
            result["next_regression_execution_plan"]["target_project_ids"],
            [
                "PROJ-NO-SIGNAL",
                "PROJ-BLOCKED",
                "PROJ-SOURCE-BLOCKED-NO-CODE-GAP",
                "PROJ-GDCIC-UNRESOLVED",
                "PROJ-STRONG-ORIGINAL-BLOCKED",
                "PROJ-YGP-BLOCKED",
            ],
        )
        self.assertEqual(
            result["next_regression_execution_plan"]["public_source_fallback_sequence"],
            [
                "data_ggzy_company_history_search",
                "data_ggzy_bid_list_pagination",
                "data_ggzy_bid_show_readback",
                "ygp_original_notice_readback",
                "project_local_authority_public_source",
            ],
        )
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
        execution_plan = result["next_regression_execution_plan"]
        self.assertEqual(execution_plan["plan_state"], "PUBLIC_SOURCE_DEEPENING_RUN_RECOMMENDED")
        self.assertEqual(
            execution_plan["recommended_switches"],
            ["RunP13BPublicSourceChain", "RunYgpBackfillFieldQuery", "RunStage6MergedProjection"],
        )
        self.assertEqual(execution_plan["recommended_parameter_overrides"]["MaxLiveP13BCompanies"], 8)
        self.assertEqual(execution_plan["recommended_parameter_overrides"]["MaxLiveOriginalNotices"], 12)
        self.assertEqual(execution_plan["recommended_parameter_overrides"]["MaxLiveYgpOriginalNotices"], 8)
        self.assertEqual(execution_plan["recommended_parameter_overrides"]["MaxLiveYgpBackfillTasks"], 8)
        self.assertEqual(
            execution_plan["target_project_ids"],
            ["PROJ-PUBLIC-RETRY", "PROJ-LOCAL-FALLBACK"],
        )
        self.assertEqual(
            execution_plan["public_source_fallback_sequence"],
            [
                "data_ggzy_company_history_search",
                "data_ggzy_bid_list_pagination",
                "data_ggzy_bid_show_readback",
                "ygp_original_notice_readback",
                "project_local_authority_public_source",
            ],
        )
        self.assertTrue(execution_plan["operator_live_public_query_decision_required"])
        self.assertFalse(execution_plan["live_execution_enabled_by_default"])
        self.assertFalse(execution_plan["safety_invariants"]["gdcic_project_code_digit_guessing_allowed"])
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
        self.assertIn("next_regression_execution_plan", markdown)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
