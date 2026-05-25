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

from storage.stage1_6_scoreboard_comparison import build_stage1_6_scoreboard_comparison


class StageOneSixScoreboardComparisonTests(unittest.TestCase):
    def test_comparison_summarizes_sellable_stage4_stage5_and_long_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_a = root / "stage1-6-sellable-rate-regression-live12"
            run_b = root / "stage1-6-sellable-rate-regression-live15"
            out = root / "out"
            _write_scoreboard(
                run_a / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=12,
                limited_count=3,
                rate=0.25,
                stage4={"MATCHED": 9, "NEEDS_BROWSER": 39, "NOT_FOUND": 5},
                stage5={"RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 6},
                stage5_family={},
                stage5_primary={"responsible_person_certificate_gap": 6},
                stage5_priority={"P2_INPUT_REPAIR_AND_DISAMBIGUATION": 6},
                stage5_safety={"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 6},
                long_tail={"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 6},
                public_source_chain={"LOCAL_AUTHORITY_PUBLIC_API_READBACK": 4},
                public_readback_outcomes={"NOT_FOUND": 3, "READBACK_READY": 2},
                public_readback_channel_outcomes={
                    "LOCAL_AUTHORITY:NOT_FOUND": 3,
                    "YGP:YGP_READBACK_READY": 2,
                },
                design_registry_status={},
                code_backfill={"MISSING_PROJECT_CODE_BACKFILL_INPUT": 10},
                code_backfill_gap_detail={
                    "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 4,
                    "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 6,
                },
                route_policy={
                    "BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING": 10,
                },
            )
            _write_scoreboard(
                run_b / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=15,
                limited_count=4,
                rate=0.2667,
                stage4={"MATCHED": 11, "NEEDS_BROWSER": 45, "NOT_FOUND": 11},
                stage5={"RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 9},
                stage5_family={"responsible_person_certificate_gap": 9, "evidence_insufficient": 2},
                stage5_primary={"responsible_person_certificate_gap": 9, "evidence_insufficient": 2},
                stage5_priority={
                    "P2_INPUT_REPAIR_AND_DISAMBIGUATION": 9,
                    "P3_EVIDENCE_INSUFFICIENT_PARK_OR_SAMPLE": 2,
                },
                stage5_safety={"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 11},
                long_tail={"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 9},
                public_source_chain={
                    "LOCAL_AUTHORITY_PUBLIC_API_READBACK": 4,
                    "YGP_ORIGINAL_READBACK_BACKFILL": 7,
                },
                public_readback_outcomes={"NOT_FOUND": 3, "READBACK_READY": 3},
                public_readback_channel_outcomes={
                    "DESIGN_SURVEY_PUBLIC_REGISTRY:NOT_FOUND": 1,
                    "LOCAL_AUTHORITY:NOT_FOUND": 3,
                    "YGP:YGP_READBACK_READY": 3,
                },
                design_registry_status={
                    "artifact_state": "BUILT",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "readback_state_counts": {"NOT_FOUND": 1},
                    "verification_result_counts": {"REVIEW_REQUIRED": 1},
                    "projected_stage5_queue_counts": {
                        "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW": 1,
                    },
                },
                code_backfill={
                    "MISSING_PROJECT_CODE_BACKFILL_INPUT": 12,
                    "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 3,
                },
                code_backfill_gap_detail={
                    "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 3,
                    "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 9,
                },
                route_policy={
                    "BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING": 12,
                    "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE": 3,
                },
            )

            result = build_stage1_6_scoreboard_comparison(
                run_roots=[run_a, run_b],
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )
            self.assertEqual(result["summary"]["run_count"], 2)
            self.assertEqual(result["summary"]["total_candidate_count"], 27)
            self.assertEqual(result["summary"]["total_limited_sellable_review_candidate_count"], 7)
            self.assertEqual(result["summary"]["best_rate_run_label"], "stage1-6-sellable-rate-regression-live15")
            self.assertEqual(result["comparison_rows"][0]["stage2_success_rate"], 1.0)
            self.assertEqual(result["comparison_rows"][1]["stage4_adapter_result_state_counts"]["MATCHED"], 11)
            self.assertEqual(
                result["comparison_rows"][1]["stage5_operational_review_queue_counts"],
                {"RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 9},
            )
            self.assertEqual(
                result["comparison_rows"][1]["stage5_operational_review_family_counts"],
                {"responsible_person_certificate_gap": 9, "evidence_insufficient": 2},
            )
            self.assertEqual(
                result["delta_from_first_row"][1]["stage5_operational_review_family_count_deltas"],
                {"evidence_insufficient": 2, "responsible_person_certificate_gap": 3},
            )
            self.assertEqual(
                result["delta_from_first_row"][1]["stage5_operational_primary_track_count_deltas"],
                {"evidence_insufficient": 2, "responsible_person_certificate_gap": 3},
            )
            self.assertEqual(
                result["delta_from_first_row"][1]["stage5_operational_priority_bucket_count_deltas"],
                {
                    "P2_INPUT_REPAIR_AND_DISAMBIGUATION": 3,
                    "P3_EVIDENCE_INSUFFICIENT_PARK_OR_SAMPLE": 2,
                },
            )
            self.assertEqual(
                result["comparison_rows"][1]["stage1_3_long_tail_bucket_counts"],
                {"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 9},
            )
            self.assertEqual(
                result["comparison_rows"][1]["stage6_limited_sellable_review_public_source_chain_counts"],
                {
                    "LOCAL_AUTHORITY_PUBLIC_API_READBACK": 4,
                    "YGP_ORIGINAL_READBACK_BACKFILL": 7,
                },
            )
            self.assertEqual(
                result["comparison_rows"][1]["stage4_public_readback_outcome_counts"],
                {"NOT_FOUND": 3, "READBACK_READY": 3},
            )
            self.assertEqual(
                result["comparison_rows"][1]["stage4_public_readback_channel_outcome_counts"],
                {
                    "DESIGN_SURVEY_PUBLIC_REGISTRY:NOT_FOUND": 1,
                    "LOCAL_AUTHORITY:NOT_FOUND": 3,
                    "YGP:YGP_READBACK_READY": 3,
                },
            )
            self.assertEqual(
                result["comparison_rows"][1]["design_survey_public_registry_readback_state_counts"],
                {"NOT_FOUND": 1},
            )
            self.assertEqual(
                result["comparison_rows"][1]["design_survey_public_registry_verification_result_counts"],
                {"REVIEW_REQUIRED": 1},
            )
            self.assertEqual(result["delta_from_first_row"][1]["stage4_matched_delta"], 2)
            self.assertEqual(result["delta_from_first_row"][1]["stage4_public_readback_ready_delta"], 1)
            self.assertEqual(
                result["delta_from_first_row"][1]["stage4_public_readback_channel_outcome_count_deltas"],
                {
                    "DESIGN_SURVEY_PUBLIC_REGISTRY:NOT_FOUND": 1,
                    "LOCAL_AUTHORITY:NOT_FOUND": 0,
                    "YGP:YGP_READBACK_READY": 1,
                },
            )
            self.assertEqual(result["delta_from_first_row"][1]["design_survey_public_registry_not_found_delta"], 1)
            self.assertEqual(
                result["delta_from_first_row"][1]["design_survey_public_registry_readback_state_count_deltas"],
                {"NOT_FOUND": 1},
            )
            self.assertEqual(result["delta_from_first_row"][1]["stage4_public_identifier_backfilled_delta"], 3)
            self.assertEqual(result["delta_from_first_row"][1]["stage4_project_code_missing_backfill_input_delta"], 2)
            self.assertEqual(
                result["comparison_rows"][1]["stage4_project_code_backfill_gap_detail_counts"],
                {
                    "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 3,
                    "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 9,
                },
            )
            self.assertEqual(result["delta_from_previous_row"][1]["previous_run_label"], "stage1-6-sellable-rate-regression-live12")
            self.assertEqual(result["delta_from_previous_row"][1]["stage6_ygp_original_readback_backfill_delta"], 7)
            self.assertEqual(
                result["delta_from_previous_row"][1]["public_source_deepening_effect_state"],
                "NOT_COMPARABLE_CANDIDATE_COUNT_CHANGED",
            )
            self.assertEqual(result["delta_from_previous_row"][1]["regression_flags"], [])
            self.assertEqual(result["summary"]["latest_run_label"], "stage1-6-sellable-rate-regression-live15")
            self.assertEqual(
                result["summary"]["latest_stage5_operational_review_family_counts"],
                {"responsible_person_certificate_gap": 9, "evidence_insufficient": 2},
            )
            self.assertEqual(
                result["summary"]["latest_stage5_operational_priority_bucket_counts"],
                {
                    "P2_INPUT_REPAIR_AND_DISAMBIGUATION": 9,
                    "P3_EVIDENCE_INSUFFICIENT_PARK_OR_SAMPLE": 2,
                },
            )
            self.assertEqual(
                result["summary"]["latest_stage4_public_readback_channel_outcome_counts"],
                {
                    "DESIGN_SURVEY_PUBLIC_REGISTRY:NOT_FOUND": 1,
                    "LOCAL_AUTHORITY:NOT_FOUND": 3,
                    "YGP:YGP_READBACK_READY": 3,
                },
            )
            self.assertEqual(
                result["summary"]["latest_design_survey_public_registry_readback_state_counts"],
                {"NOT_FOUND": 1},
            )
            self.assertFalse(result["safety"]["customer_visible_allowed"])
            self.assertTrue((out / "stage1-6-scoreboard-comparison-v1.json").exists())
            markdown = (out / "stage1-6-scoreboard-comparison-v1.md").read_text(encoding="utf-8")
            self.assertIn("stage6 public source chain", markdown)
            self.assertIn("public readback outcomes", markdown)
            self.assertIn("channel outcomes", markdown)
            self.assertIn("design registry", markdown)
            self.assertIn("DESIGN_SURVEY_PUBLIC_REGISTRY:NOT_FOUND", markdown)
            self.assertIn("code route policy", markdown)
            self.assertIn("gap_detail", markdown)
            self.assertIn("stage5 family", markdown)
            self.assertIn("stage5 priority", markdown)
            self.assertIn("P2_INPUT_REPAIR_AND_DISAMBIGUATION", markdown)
            self.assertIn("YGP_ORIGINAL_READBACK_BACKFILL", markdown)
            self.assertIn("Public Source Deepening Recommendations", markdown)

    def test_same_candidate_public_source_deepening_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_a = root / "stage1-6-sellable-rate-regression-live20-r1"
            run_b = root / "stage1-6-sellable-rate-regression-live20-r2"
            out = root / "out"
            _write_scoreboard(
                run_a / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=20,
                limited_count=5,
                rate=0.25,
                stage4={"MATCHED": 10, "NEEDS_BROWSER": 8, "NOT_FOUND": 2},
                stage5={"PUBLIC_SOURCE_BLOCKED_REVIEW": 8},
                stage5_family={"public_source_blocked": 8},
                stage5_primary={"public_source_blocked": 8},
                stage5_priority={"P1_BLOCKER_RETRY_OR_ALTERNATE_SOURCE": 8},
                stage5_safety={"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 8},
                long_tail={"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 4},
                public_source_chain={"YGP_ORIGINAL_READBACK_BACKFILL": 6},
                public_readback_outcomes={"READBACK_READY": 4, "BLOCKED": 8, "NOT_FOUND": 2},
                public_readback_channel_outcomes={
                    "LOCAL_AUTHORITY:BLOCKED": 8,
                    "LOCAL_AUTHORITY:NOT_FOUND": 2,
                    "YGP:YGP_READBACK_READY": 4,
                },
                design_registry_status={},
                code_backfill={"MISSING_PROJECT_CODE_BACKFILL_INPUT": 8},
                code_backfill_gap_detail={
                    "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 2,
                    "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 6,
                },
                route_policy={
                    "BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING": 8,
                },
            )
            _write_scoreboard(
                run_b / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=20,
                limited_count=9,
                rate=0.45,
                stage4={"MATCHED": 18, "NEEDS_BROWSER": 6, "NOT_FOUND": 2},
                stage5={"PUBLIC_SOURCE_BLOCKED_REVIEW": 6, "LIMITED_SELLABLE_OFFICIAL_READBACK_REVIEW": 9},
                stage5_family={"public_source_blocked": 6, "strong_lead": 9},
                stage5_primary={"public_source_blocked": 6, "strong_lead": 9},
                stage5_priority={
                    "P0_LIMITED_SELLABLE_REVIEW": 9,
                    "P1_BLOCKER_RETRY_OR_ALTERNATE_SOURCE": 6,
                },
                stage5_safety={
                    "INTERNAL_LIMITED_SELLABLE_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE": 9,
                    "INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 6,
                },
                long_tail={"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 4},
                public_source_chain={"YGP_ORIGINAL_READBACK_BACKFILL": 14},
                public_readback_outcomes={"READBACK_READY": 8, "BLOCKED": 6, "NOT_FOUND": 2},
                public_readback_channel_outcomes={
                    "DESIGN_SURVEY_PUBLIC_REGISTRY:MATCHED": 2,
                    "LOCAL_AUTHORITY:BLOCKED": 6,
                    "LOCAL_AUTHORITY:NOT_FOUND": 2,
                    "YGP:YGP_READBACK_READY": 8,
                },
                design_registry_status={
                    "artifact_state": "BUILT",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "readback_state_counts": {"MATCHED": 2},
                    "verification_result_counts": {"REVIEW_REQUIRED": 2},
                    "projected_stage5_queue_counts": {
                        "DESIGN_SURVEY_PUBLIC_REGISTRY_MATCHED_REVIEW": 2,
                    },
                },
                code_backfill={
                    "MISSING_PROJECT_CODE_BACKFILL_INPUT": 4,
                    "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 14,
                },
                code_backfill_gap_detail={
                    "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 1,
                    "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 3,
                },
                route_policy={
                    "BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING": 4,
                    "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE": 14,
                },
            )

            result = build_stage1_6_scoreboard_comparison(
                run_roots=[run_a, run_b],
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

            delta = result["delta_from_previous_row"][1]
            self.assertEqual(delta["candidate_count_delta"], 0)
            self.assertGreater(delta["real_public_sellable_pack_rate_delta"], 0)
            self.assertGreater(delta["limited_sellable_review_candidate_count_delta"], 0)
            self.assertGreater(delta["stage4_matched_delta"], 0)
            self.assertGreater(delta["stage4_public_readback_ready_delta"], 0)
            self.assertLess(delta["stage4_public_readback_blocked_delta"], 0)
            self.assertEqual(delta["stage6_ygp_original_readback_backfill_delta"], 8)
            self.assertEqual(delta["design_survey_public_registry_matched_delta"], 2)
            self.assertEqual(delta["public_source_deepening_effect_state"], "PUBLIC_SOURCE_DEEPENING_EFFECTIVE")

            recommendations = result["public_source_deepening_recommendations"]
            self.assertEqual(len(recommendations), 1)
            self.assertEqual(recommendations[0]["decision"], "CONTINUE_PUBLIC_SOURCE_DEEPENING")
            self.assertIn(
                "increase_p13b_prior_award_and_candidate_overlap_budget",
                recommendations[0]["recommended_budget_focus"],
            )
            self.assertIn(
                "continue_remaining_stage4_backfill_followup_queue_before_gdcic_project_code_guessing",
                recommendations[0]["recommended_budget_focus"],
            )
            self.assertFalse(recommendations[0]["safety_invariants"]["customer_visible_allowed"])
            self.assertFalse(recommendations[0]["safety_invariants"]["gdcic_project_code_digit_guessing_allowed"])
            markdown = (out / "stage1-6-scoreboard-comparison-v1.md").read_text(encoding="utf-8")
            self.assertIn("CONTINUE_PUBLIC_SOURCE_DEEPENING", markdown)

    def test_same_candidate_public_source_followup_classified_non_terminal_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_a = root / "stage1-6-sellable-rate-regression-live15-r1"
            run_b = root / "stage1-6-sellable-rate-regression-live15-r2"
            out = root / "out"
            _write_scoreboard(
                run_a / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=15,
                limited_count=0,
                rate=0.0,
                stage4={},
                stage5={"PROJECT_CODE_BACKFILL_GAP_REVIEW": 15},
                stage5_family={"project_code_backfill_gap": 15},
                stage5_primary={"project_code_backfill_gap": 15},
                stage5_priority={"P2_INPUT_REPAIR_AND_DISAMBIGUATION": 15},
                stage5_safety={"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 15},
                long_tail={},
                public_source_chain={},
                public_readback_outcomes={},
                public_readback_channel_outcomes={},
                design_registry_status={},
                code_backfill={"MISSING_PROJECT_CODE_BACKFILL_INPUT": 15},
                code_backfill_gap_detail={"NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 15},
                route_policy={"BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING": 15},
            )
            _write_scoreboard(
                run_b / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=15,
                limited_count=0,
                rate=0.0,
                stage4={},
                stage5={"LOCAL_AUTHORITY_BLOCKED_REVIEW": 5, "LOCAL_AUTHORITY_NOT_FOUND_REVIEW": 10},
                stage5_family={"public_source_blocked": 5, "source_not_found": 10},
                stage5_primary={"public_source_blocked": 5, "source_not_found": 10},
                stage5_priority={
                    "P1_BLOCKER_RETRY_OR_ALTERNATE_SOURCE": 5,
                    "P2_NOT_FOUND_NON_CLEARANCE_DEEPENING": 10,
                },
                stage5_safety={"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 15},
                long_tail={},
                public_source_chain={},
                public_readback_outcomes={"BLOCKED": 5, "NOT_FOUND": 10},
                public_readback_channel_outcomes={
                    "LOCAL_AUTHORITY:BLOCKED": 5,
                    "LOCAL_AUTHORITY:NOT_FOUND": 10,
                },
                design_registry_status={},
                code_backfill={"MISSING_PROJECT_CODE_BACKFILL_INPUT": 15},
                code_backfill_gap_detail={"NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 15},
                route_policy={"BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING": 15},
            )

            result = build_stage1_6_scoreboard_comparison(
                run_roots=[run_a, run_b],
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        delta = result["delta_from_previous_row"][1]
        self.assertEqual(delta["candidate_count_delta"], 0)
        self.assertEqual(delta["limited_sellable_review_candidate_count_delta"], 0)
        self.assertEqual(delta["stage4_public_readback_blocked_delta"], 5)
        self.assertEqual(delta["stage4_public_readback_not_found_delta"], 10)
        self.assertEqual(
            delta["public_source_deepening_effect_state"],
            "PUBLIC_SOURCE_FOLLOWUP_CLASSIFIED_NON_TERMINAL",
        )
        recommendations = result["public_source_deepening_recommendations"]
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["decision"], "CONTINUE_PUBLIC_SOURCE_DEEPENING")
        self.assertEqual(
            recommendations[0]["effect_state"],
            "PUBLIC_SOURCE_FOLLOWUP_CLASSIFIED_NON_TERMINAL",
        )
        self.assertIn(
            "keep_not_found_blocked_as_internal_review_not_clearance",
            recommendations[0]["recommended_budget_focus"],
        )
        self.assertFalse(recommendations[0]["safety_invariants"]["customer_visible_allowed"])

    def test_same_candidate_public_identifier_backfill_effective_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_a = root / "stage1-6-sellable-rate-regression-live15-r2"
            run_b = root / "stage1-6-sellable-rate-regression-live15-r3"
            out = root / "out"
            _write_scoreboard(
                run_a / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=15,
                limited_count=0,
                rate=0.0,
                stage4={},
                stage5={"LOCAL_AUTHORITY_BLOCKED_REVIEW": 5, "LOCAL_AUTHORITY_NOT_FOUND_REVIEW": 10},
                stage5_family={"public_source_blocked": 5, "source_not_found": 10},
                stage5_primary={"public_source_blocked": 5, "source_not_found": 10},
                stage5_priority={
                    "P1_BLOCKER_RETRY_OR_ALTERNATE_SOURCE": 5,
                    "P2_NOT_FOUND_NON_CLEARANCE_DEEPENING": 10,
                },
                stage5_safety={"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 15},
                long_tail={},
                public_source_chain={},
                public_readback_outcomes={"BLOCKED": 5, "NOT_FOUND": 10},
                public_readback_channel_outcomes={
                    "LOCAL_AUTHORITY:BLOCKED": 5,
                    "LOCAL_AUTHORITY:NOT_FOUND": 10,
                },
                design_registry_status={},
                code_backfill={"MISSING_PROJECT_CODE_BACKFILL_INPUT": 15},
                code_backfill_gap_detail={"NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 15},
                route_policy={"BACKFILL_NOTICE_DATA_GGZY_BID_SHOW_OR_LOCAL_SOURCE_WITHOUT_DIGIT_GUESSING": 15},
            )
            _write_scoreboard(
                run_b / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=15,
                limited_count=0,
                rate=0.0,
                stage4={},
                stage5={"YGP_STAGE4_BACKFILL_READY_REVIEW": 7, "LOCAL_AUTHORITY_NOT_FOUND_REVIEW": 5},
                stage5_family={"official_readback_ready": 7, "source_not_found": 5},
                stage5_primary={"official_readback_ready": 7, "source_not_found": 5},
                stage5_priority={
                    "P1_OFFICIAL_READBACK_DEEPENING": 7,
                    "P2_NOT_FOUND_NON_CLEARANCE_DEEPENING": 5,
                },
                stage5_safety={"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 15},
                long_tail={},
                public_source_chain={},
                public_readback_outcomes={"READBACK_READY": 10, "BLOCKED": 3, "NOT_FOUND": 5},
                public_readback_channel_outcomes={
                    "YGP:YGP_READBACK_READY": 10,
                    "ORIGINAL_NOTICE:BLOCKED": 1,
                    "ORIGINAL_NOTICE:NOT_FOUND": 5,
                },
                design_registry_status={},
                code_backfill={
                    "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 5,
                    "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 10,
                },
                code_backfill_gap_detail={},
                route_policy={
                    "DATA_GGZY_BID_SHOW_ORIGINAL_URL_NOT_SENT_TO_GDCIC_PROJECT_CODE": 5,
                    "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE": 10,
                },
            )

            result = build_stage1_6_scoreboard_comparison(
                run_roots=[run_a, run_b],
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        delta = result["delta_from_previous_row"][1]
        self.assertEqual(delta["candidate_count_delta"], 0)
        self.assertEqual(delta["limited_sellable_review_candidate_count_delta"], 0)
        self.assertEqual(delta["stage4_public_identifier_backfilled_delta"], 10)
        self.assertEqual(delta["stage4_project_code_missing_backfill_input_delta"], -15)
        self.assertEqual(delta["stage4_public_readback_ready_delta"], 10)
        self.assertEqual(
            delta["public_source_deepening_effect_state"],
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILL_EFFECTIVE",
        )
        recommendations = result["public_source_deepening_recommendations"]
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["effect_state"], "PUBLIC_SOURCE_IDENTIFIER_BACKFILL_EFFECTIVE")
        self.assertIn(
            "promote_only_b_or_c_official_release_readback_to_limited_sellable_review",
            recommendations[0]["recommended_budget_focus"],
        )
        self.assertFalse(recommendations[0]["safety_invariants"]["customer_visible_allowed"])


def _write_scoreboard(
    path: Path,
    *,
    candidate_count: int,
    limited_count: int,
    rate: float,
    stage4: dict[str, int],
    stage5: dict[str, int],
    stage5_family: dict[str, int],
    stage5_primary: dict[str, int],
    stage5_priority: dict[str, int],
    stage5_safety: dict[str, int],
    long_tail: dict[str, int],
    public_source_chain: dict[str, int],
    public_readback_outcomes: dict[str, int],
    public_readback_channel_outcomes: dict[str, int],
    design_registry_status: dict[str, object],
    code_backfill: dict[str, int],
    code_backfill_gap_detail: dict[str, int],
    route_policy: dict[str, int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scoreboard": {
            "candidate_count": candidate_count,
            "stage2_success_count": candidate_count,
            "stage3_success_count": candidate_count,
            "limited_sellable_review_candidate_count": limited_count,
            "strong_lead_review_candidate_count": limited_count,
            "real_public_sellable_pack_rate": rate,
            "stage4_adapter_result_state_counts": stage4,
            "stage5_operational_review_family_counts": stage5_family,
            "stage5_operational_review_queue_counts": stage5,
            "stage5_operational_primary_track_counts": stage5_primary,
            "stage5_operational_priority_bucket_counts": stage5_priority,
            "stage5_operational_safety_boundary_counts": stage5_safety,
            "stage1_3_long_tail_bucket_counts": long_tail,
            "stage6_limited_sellable_review_public_source_chain_counts": public_source_chain,
            "stage4_public_readback_outcome_counts": public_readback_outcomes,
            "stage4_public_readback_channel_outcome_counts": public_readback_channel_outcomes,
            "design_survey_public_registry_readback_status": design_registry_status,
            "stage4_project_code_backfill_state_counts": code_backfill,
            "stage4_project_code_backfill_gap_detail_counts": code_backfill_gap_detail,
            "stage4_gdcic_project_code_route_policy_counts": route_policy,
            "gdcic_authorized_readback_status": {
                "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
            },
        },
        "blocker_summary": {"active_fail_closed_reason_counts": {}},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
